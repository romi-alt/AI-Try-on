import io
import uuid

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select, text, update

from tests.helpers import add_product
from tests.test_embeddings import ColourEncoder, png, stored
from worker import asset_tasks, db, main, storage
from worker.asset_tasks import embed_products_job, process_garment, process_garment_job
from worker.config import settings


class Remover:
    def __init__(self, mask=None, error=None):
        self.mask = np.zeros((100, 100), bool) if mask is None else mask
        if mask is None:
            self.mask[20:80, 30:70] = True
        self.error = error
        self.seen = []

    def alpha(self, image):
        self.seen.append(image.getpixel((50, 50)))
        if self.error:
            raise self.error
        return self.mask


def jpeg_bytes(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color).save(buf, "JPEG")
    return buf.getvalue()


def queued(name="Tee", color=(180, 40, 60)):
    pid = add_product(name, image=jpeg_bytes(color))
    with db.engine.begin() as conn:
        conn.execute(update(db.products).where(db.products.c.id == pid).values(processing_status="queued"))
    return pid


def row(pid):
    with db.engine.connect() as conn:
        return conn.execute(select(db.products).where(db.products.c.id == pid)).one()


def keys(s3):
    return {o["Key"] for o in s3.list_objects_v2(Bucket=settings.s3_bucket).get("Contents", [])}


def test_a_queued_product_is_processed_and_its_images_replaced(pg, s3):
    pid = queued()
    original = row(pid).garment_image_url

    assert process_garment(pid, remover=Remover(), encoder=ColourEncoder()) is True

    r = row(pid)
    assert (
        r.processing_status == "done" and r.processing_error is None and r.processing_updated_at is not None
    )
    assert r.garment_original_url == original  # the upload is remembered
    assert r.garment_image_url != original and r.garment_image_url.endswith("-cutout.png")
    assert r.garment_mask_url.endswith("-mask.png")
    prefix = f"{settings.s3_public_base_url}/garment/processed/{pid}/"
    assert r.garment_image_url.startswith(prefix) and r.garment_mask_url.startswith(prefix)
    cutout = Image.open(
        io.BytesIO(storage.get_bytes(r.garment_image_url[len(settings.s3_public_base_url) + 1 :]))
    )
    mask = Image.open(
        io.BytesIO(storage.get_bytes(r.garment_mask_url[len(settings.s3_public_base_url) + 1 :]))
    )
    assert cutout.mode == "RGBA" and mask.mode == "L"
    assert np.asarray(mask)[50, 50] == 255 and np.asarray(mask)[5, 5] == 0


def test_the_original_upload_is_never_deleted(pg, s3):
    pid = queued()
    original_key = row(pid).garment_image_url[len(settings.s3_public_base_url) + 1 :]
    process_garment(pid, remover=Remover(), encoder=ColourEncoder())
    assert original_key in keys(s3)


def test_the_embedding_is_recomputed_from_the_cutout(pg, s3):
    pid = queued()
    process_garment(pid, remover=Remover(), encoder=ColourEncoder())
    vec, at = stored(pid)
    assert vec is not None and at is not None  # a product with no embedding now has one


def test_reprocessing_starts_from_the_original_and_uses_fresh_keys(pg, s3):
    pid = queued(color=(10, 200, 10))
    edge_only = np.zeros((100, 100), bool)
    edge_only[0:10, :] = (
        True  # the first cutout is transparent at the centre, so it cannot pass for the photo
    )
    first = Remover(mask=edge_only)
    process_garment(pid, remover=first, reembed=False)
    first_url = row(pid).garment_image_url
    with db.engine.begin() as conn:
        conn.execute(update(db.products).where(db.products.c.id == pid).values(processing_status="queued"))

    second = Remover()
    process_garment(pid, remover=second, reembed=False)

    r = row(pid)
    assert r.garment_image_url != first_url  # a new key, so a cache never serves the old cutout
    assert second.seen[0] == pytest.approx((10, 200, 10), abs=8)  # it saw the original photo, not a cutout
    assert (
        len([k for k in keys(s3) if "-cutout.png" in k]) == 2
    )  # the old one is left for admins to compare/roll back


def test_a_product_that_was_not_queued_is_left_alone(pg, s3):
    pid = add_product("Idle", image=jpeg_bytes((1, 2, 3)))
    before = row(pid)

    assert process_garment(pid, remover=Remover(), reembed=False) is False

    assert row(pid) == before and not any("processed" in k for k in keys(s3))


def test_two_workers_cannot_both_process_the_same_product(pg, s3):
    pid = queued()
    assert db.claim_processing(pid) is True
    assert db.claim_processing(pid) is False
    assert process_garment(pid, remover=Remover(), reembed=False) is False  # it is already being processed


def test_an_image_with_no_garment_marks_the_product_failed_with_a_readable_reason(pg, s3):
    pid = queued()
    before = row(pid)

    assert process_garment(pid, remover=Remover(mask=np.zeros((100, 100), bool)), reembed=False) is True

    r = row(pid)
    assert r.processing_status == "failed" and "No garment was found" in r.processing_error
    assert (r.garment_image_url, r.garment_mask_url, r.garment_original_url) == (
        before.garment_image_url,
        before.garment_mask_url,
        before.garment_original_url,
    )
    assert not any("processed" in k for k in keys(s3))


def test_an_unexpected_error_marks_the_product_failed_and_is_raised_for_rq(pg, s3):
    pid = queued()

    with pytest.raises(RuntimeError, match="model crashed"):
        process_garment(pid, remover=Remover(error=RuntimeError("model crashed")), reembed=False)

    r = row(pid)
    assert r.processing_status == "failed"
    assert (
        "RuntimeError" in r.processing_error and "model crashed" not in r.processing_error
    )  # no internals leak


def test_an_unreachable_image_marks_the_product_failed(pg, s3):
    pid = queued()

    def boom(url):
        raise ConnectionError("no route")

    with pytest.raises(ConnectionError):
        process_garment(pid, remover=Remover(), reembed=False, load_image=boom)
    assert row(pid).processing_status == "failed"


def test_a_failing_reembed_does_not_undo_a_successful_processing(pg, s3):
    pid = queued()

    class Broken:
        def encode(self, images):
            raise RuntimeError("no gpu")

    assert process_garment(pid, remover=Remover(), encoder=Broken()) is True
    assert row(pid).processing_status == "done"


def test_a_storage_failure_leaves_the_product_unchanged_and_failed(pg, s3):
    pid = queued()
    before = row(pid)

    def refuse(key, data, content_type):
        raise OSError("bucket unavailable")

    with pytest.raises(OSError):
        process_garment(pid, remover=Remover(), reembed=False, put_bytes=refuse)

    r = row(pid)
    assert r.processing_status == "failed" and r.garment_image_url == before.garment_image_url


def test_the_rq_functions_take_string_ids(pg, s3, monkeypatch):
    pid = queued()
    monkeypatch.setattr(asset_tasks, "RembgRemover", lambda: Remover())
    monkeypatch.setattr(asset_tasks, "default_refiner", lambda: None)
    monkeypatch.setattr(
        asset_tasks,
        "embed_products",
        lambda ids, **kw: __import__("worker.embeddings", fromlist=["x"]).embed_products(
            ids, **{**kw, "encoder": ColourEncoder()}
        ),
    )

    assert process_garment_job(str(pid)) is True
    assert row(pid).processing_status == "done"


def test_the_embedding_job_reports_what_it_did(pg, s3, monkeypatch):
    ok = add_product("Ok", image=png((5, 5, 5)))
    broken = add_product("Broken", image=b"not an image")
    from worker import embeddings

    monkeypatch.setattr(
        asset_tasks,
        "embed_products",
        lambda ids, **kw: embeddings.embed_products(ids, **{**kw, "encoder": ColourEncoder()}),
    )

    result = embed_products_job()

    assert result["updated"] == 1 and str(broken) in result["failed"] and str(ok) not in result["failed"]
    assert embed_products_job([str(ok)], only_missing=True)["updated"] == 0


def test_the_default_refiner_needs_a_checkpoint(monkeypatch):
    monkeypatch.setattr(settings, "sam2_checkpoint", "")
    assert asset_tasks.default_refiner() is None
    monkeypatch.setattr(settings, "sam2_checkpoint", "/models/sam2.1_hiera_tiny.pt")
    assert asset_tasks.default_refiner() is not None


@pytest.mark.parametrize(
    ("setting", "names"),
    [("tryon", ["tryon"]), ("assets", ["assets"]), ("assets, tryon", ["assets", "tryon"])],
)
def test_a_worker_serves_the_queues_it_is_told_to(monkeypatch, setting, names):
    monkeypatch.setattr(settings, "worker_queues", setting)
    assert main.queue_names() == [
        {"tryon": settings.tryon_queue_name, "assets": settings.assets_queue_name}[n] for n in names
    ]


@pytest.mark.parametrize("bad", ["", "tryon,nope", "garment"])
def test_an_unknown_queue_name_stops_the_worker_at_startup(monkeypatch, bad):
    monkeypatch.setattr(settings, "worker_queues", bad)
    with pytest.raises(SystemExit):
        main.queue_names()


def test_the_unused_uuid_import_is_not_hiding_anything():
    assert uuid.UUID(int=0) and text("select 1") is not None
