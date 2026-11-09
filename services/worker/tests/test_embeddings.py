import io
import math
import uuid

import pytest
from PIL import Image
from sqlalchemy import text

from tests.helpers import add_product, garment_png
from worker import db, embeddings
from worker import embed_products as cli
from worker.embeddings import EMBEDDING_DIM, embed_products, normalise, prepare_image


class ColourEncoder:
    """A stand-in for FashionCLIP: the mean RGB of the image in the first three dimensions."""

    def __init__(self):
        self.calls: list[int] = []

    def encode(self, images):
        self.calls.append(len(images))
        out = []
        for img in images:
            r, g, b = (sum(band.getdata()) / (img.width * img.height) for band in img.split())
            out.append([r, g, b] + [0.0] * (EMBEDDING_DIM - 3))
        return out


def png(color, size=(40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def stored(pid):
    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT embedding::text AS v, embedding_updated_at AS at FROM products WHERE id = :id"),
            {"id": pid},
        ).one()
    return (None if row.v is None else [float(x) for x in row.v.strip("[]").split(",")]), row.at


def test_every_product_gets_a_unit_length_512_dimension_embedding(pg, s3):
    red = add_product("Red", image=png((200, 0, 0)))
    blue = add_product("Blue", image=png((0, 0, 200)))

    report = embed_products(encoder=ColourEncoder())

    assert sorted(report.updated) == sorted([red, blue]) and report.failed == {}
    for pid, axis in ((red, 0), (blue, 2)):
        vec, at = stored(pid)
        assert len(vec) == EMBEDDING_DIM and at is not None
        assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, abs_tol=1e-5)
        assert vec[axis] > 0.99  # red points along r, blue along b


def test_the_stored_vectors_can_be_ranked_by_pgvector_cosine_distance(pg, s3):
    red = add_product("Red", image=png((200, 0, 0)))
    pink = add_product("Pink", image=png((200, 40, 40)))
    blue = add_product("Blue", image=png((0, 0, 200)))
    embed_products(encoder=ColourEncoder())

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT p.name FROM products p, products r WHERE r.id = :red AND p.id <> r.id "
                "ORDER BY p.embedding <=> r.embedding"
            ),
            {"red": red},
        ).all()

    assert [r.name for r in rows] == ["Pink", "Blue"]
    assert pink and blue


def test_only_missing_leaves_existing_embeddings_alone(pg, s3):
    done = add_product("Done", image=png((10, 10, 10)))
    new = add_product("New", image=png((90, 90, 90)))
    embed_products([done], encoder=ColourEncoder())
    before = stored(done)

    encoder = ColourEncoder()
    report = embed_products(only_missing=True, encoder=encoder)

    assert report.updated == [new] and sum(encoder.calls) == 1
    assert stored(done) == before


def test_specific_ids_are_embedded_and_others_are_not(pg, s3):
    a = add_product("A", image=png((10, 10, 10)))
    b = add_product("B", image=png((90, 90, 90)))

    embed_products([b], encoder=ColourEncoder())

    assert stored(a)[0] is None and stored(b)[0] is not None


def test_one_unreadable_image_is_reported_and_the_rest_still_embed(pg, s3):
    good = add_product("Good", image=png((50, 50, 50)))
    not_an_image = add_product("Broken", image=b"this is not an image")
    gone = add_product("Gone", external_url="http://127.0.0.1:9/missing.png")

    report = embed_products(encoder=ColourEncoder(), load_image=lambda url: _load(url, gone))

    assert report.updated == [good]
    assert set(report.failed) == {not_an_image, gone}
    assert "could not be loaded" in report.failed[not_an_image]
    assert stored(not_an_image)[0] is None


def _load(url, gone_id):
    if "127.0.0.1:9" in url:
        raise ConnectionError("unreachable")
    from worker import storage

    return storage.load_image_from_url(url)


def test_a_bad_batch_is_retried_one_image_at_a_time(pg, s3):
    ids = [add_product(f"P{n}", image=png((n * 20, 0, 0))) for n in range(1, 4)]

    class Picky(ColourEncoder):
        def encode(self, images):
            if len(images) > 1:
                raise RuntimeError("out of memory")
            if images[0].getpixel((0, 0)) == (40, 0, 0):
                raise RuntimeError("bad image")
            return super().encode(images)

    report = embed_products(encoder=Picky(), batch_size=3)

    assert len(report.updated) == 2 and len(report.failed) == 1
    assert "bad image" in next(iter(report.failed.values()))
    assert ids


def test_a_wrong_sized_vector_is_rejected_not_stored(pg, s3):
    pid = add_product("Short", image=png((1, 2, 3)))

    class Wrong:
        def encode(self, images):
            return [[0.1] * 100 for _ in images]

    report = embed_products(encoder=Wrong())

    assert report.updated == [] and "expected 512" in report.failed[pid]
    assert stored(pid)[0] is None


def test_images_are_embedded_in_batches(pg, s3):
    for n in range(5):
        add_product(f"P{n}", image=png((n * 30, 0, 0)))
    encoder = ColourEncoder()

    embed_products(encoder=encoder, batch_size=2)

    assert encoder.calls == [2, 2, 1]


def test_progress_is_reported(pg, s3):
    for n in range(3):
        add_product(f"P{n}", image=png((n * 30, 0, 0)))
    seen = []

    embed_products(encoder=ColourEncoder(), progress=lambda done, total: seen.append((done, total)))

    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_a_product_deleted_during_the_run_is_reported(pg, s3):
    pid = add_product("Vanishing", image=png((1, 2, 3)))

    class Deleting(ColourEncoder):
        def encode(self, images):
            with db.engine.begin() as conn:
                conn.execute(text("DELETE FROM products WHERE id = :id"), {"id": pid})
            return super().encode(images)

    report = embed_products(encoder=Deleting())

    assert "no longer exists" in report.failed[pid]


def test_transparent_garments_are_embedded_on_white():
    img = prepare_image(garment_png((200, 30, 60)))  # an opaque patch on a transparent canvas
    assert img.mode == "RGB"
    assert img.getpixel((0, 0)) == (255, 255, 255)  # the transparent corner became white
    assert img.getpixel((150, 150)) == (200, 30, 60)


def test_paletted_and_greyscale_images_are_converted():
    for mode in ("P", "L", "CMYK"):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).convert(mode).save(buf, "PNG" if mode != "CMYK" else "TIFF")
        assert prepare_image(buf.getvalue()).mode == "RGB"


def test_normalise():
    assert normalise([3.0, 4.0]) == [0.6, 0.8]
    assert normalise([0.0, 0.0]) == [0.0, 0.0]  # a zero vector is left alone rather than dividing by zero


def test_the_command_line_embeds_everything_or_only_what_is_missing(pg, s3, monkeypatch, capsys):
    a = add_product("A", image=png((10, 10, 10)))
    b = add_product("B", image=png((90, 90, 90)))
    monkeypatch.setattr(embeddings, "FashionClipEncoder", ColourEncoder)
    monkeypatch.setattr(
        cli, "embed_products", lambda *a, **k: embed_products(*a, **{**k, "encoder": ColourEncoder()})
    )

    assert cli.main(["--ids", str(a)]) == 0
    assert stored(a)[0] is not None and stored(b)[0] is None
    assert cli.main(["--missing"]) == 0
    assert stored(b)[0] is not None
    assert "1 embedded, 0 failed" in capsys.readouterr().out


def test_the_command_line_exits_non_zero_when_something_failed(pg, s3, monkeypatch, capsys):
    bad = add_product("Bad", image=b"nope")
    monkeypatch.setattr(
        cli, "embed_products", lambda *a, **k: embed_products(*a, **{**k, "encoder": ColourEncoder()})
    )

    assert cli.main([]) == 1
    assert str(bad) in capsys.readouterr().err


def test_an_unknown_id_is_simply_ignored(pg, s3):
    assert embed_products([uuid.uuid4()], encoder=ColourEncoder()).updated == []


@pytest.mark.parametrize("bad", ["not-a-uuid"])
def test_the_command_line_rejects_malformed_ids(bad):
    with pytest.raises(SystemExit):
        cli.main(["--ids", bad])
