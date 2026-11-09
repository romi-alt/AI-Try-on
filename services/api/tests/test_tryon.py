import uuid

from botocore.exceptions import ClientError
from sqlalchemy import select

from app.core.config import settings
from app.models import JobStatus, TryOnJob
from app.services import queue as queue_module
from tests.helpers import ADMIN_HEADERS, make_product, make_session, put_capture_for


async def setup_job_inputs(api, adb, **product_kw):
    sid = await make_session(api)
    product = await make_product(adb, **product_kw)
    key = await put_capture_for(sid)
    return sid, product, key


def post(api, sid, key, product_ids):
    return api.post(
        "/tryon", json={"session_id": sid, "capture_key": key, "product_ids": [str(p) for p in product_ids]}
    )


async def test_tryon_inserts_a_queued_job_and_returns_its_id_immediately(api, adb, s3, rq_queue):
    sid, product, key = await setup_job_inputs(api, adb)

    r = await post(api, sid, key, [product.id])

    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["channel"] == f"session:{sid}:job"
    job = await adb.get(TryOnJob, uuid.UUID(body["job_id"]))
    assert job.status == JobStatus.queued and job.progress == 0
    assert job.session_id == uuid.UUID(sid)
    assert job.product_ids == [product.id]
    assert job.person_image_key == key
    assert job.result_url is None and job.error is None


async def test_tryon_pushes_the_job_onto_the_rq_queue(api, adb, s3, rq_queue):
    sid, product, key = await setup_job_inputs(api, adb)
    assert len(rq_queue) == 0

    job_id = (await post(api, sid, key, [product.id])).json()["job_id"]

    assert len(rq_queue) == 1
    queued = queue_module.get_queue().fetch_job(job_id)
    assert queued.id == job_id
    assert queued.func_name == "worker.tasks.run_tryon_job"
    assert list(queued.args) == [job_id]  # JSON-serialised, so a list
    assert queued.timeout == settings.tryon_job_timeout_seconds
    assert queued._failure_callback_name == "worker.tasks.handle_rq_failure"
    assert queued.origin == settings.tryon_queue_name


async def test_outfit_keeps_product_order_and_drops_duplicates(api, adb, s3, rq_queue):
    sid, first, key = await setup_job_inputs(api, adb)
    second, third = await make_product(adb), await make_product(adb)

    r = await post(api, sid, key, [second.id, first.id, second.id, third.id])

    job = await adb.get(TryOnJob, uuid.UUID(r.json()["job_id"]))
    assert job.product_ids == [second.id, first.id, third.id]


async def test_unknown_session_is_404(api, adb, s3, rq_queue):
    _, product, _ = await setup_job_inputs(api, adb)
    other = str(uuid.uuid4())
    r = await post(api, other, await put_capture_for(other), [product.id])
    assert r.status_code == 404 and "Session" in r.json()["detail"]
    assert len(rq_queue) == 0


async def test_unknown_product_is_404_and_names_it(api, adb, s3, rq_queue):
    sid, product, key = await setup_job_inputs(api, adb)
    ghost = uuid.uuid4()

    r = await post(api, sid, key, [product.id, ghost])

    assert r.status_code == 404 and str(ghost) in r.json()["detail"]
    assert len(rq_queue) == 0


async def test_capture_from_another_session_is_refused(api, adb, s3, rq_queue):
    sid, product, _ = await setup_job_inputs(api, adb)
    other_session = await make_session(api)
    someone_elses = await put_capture_for(other_session)

    r = await post(api, sid, someone_elses, [product.id])

    assert r.status_code == 422 and "does not belong" in r.json()["detail"]
    assert len(rq_queue) == 0


async def test_malformed_capture_keys_are_refused(api, adb, s3, rq_queue):
    sid, product, _ = await setup_job_inputs(api, adb)
    for bad in (
        f"captures/{sid}/not-a-uuid.webp",
        f"captures/{sid}/{uuid.uuid4()}.jpg",
        f"captures/{sid}/../{uuid.uuid4()}.webp",
        f"captures/{sid}/{uuid.uuid4()}.webp/extra",
        f"results/{sid}/{uuid.uuid4()}.webp",
        "garment/seed/x.png",
    ):
        r = await post(api, sid, bad, [product.id])
        assert r.status_code == 422, bad
    assert len(rq_queue) == 0


async def test_missing_or_expired_capture_is_404_with_guidance(api, adb, s3, rq_queue):
    sid, product, key = await setup_job_inputs(api, adb)
    s3.delete_object(Bucket=settings.s3_bucket, Key=key)  # what the 1-hour cleanup does

    r = await post(api, sid, key, [product.id])

    assert r.status_code == 404 and "expire" in r.json()["detail"]
    assert len(rq_queue) == 0


async def test_product_list_bounds(api, adb, s3, rq_queue):
    sid, product, key = await setup_job_inputs(api, adb)
    assert (await post(api, sid, key, [])).status_code == 422
    six = [(await make_product(adb)).id for _ in range(6)]
    assert (await post(api, sid, key, six)).status_code == 422
    five = six[:5]
    assert (await post(api, sid, key, five)).status_code == 202


async def test_malformed_body_is_422(api, rq_queue):
    assert (await api.post("/tryon", json={})).status_code == 422
    assert (
        await api.post("/tryon", json={"session_id": "x", "capture_key": "k", "product_ids": ["y"]})
    ).status_code == 422


async def test_redis_outage_marks_the_job_failed_and_returns_503(api, adb, s3, rq_queue, monkeypatch):
    sid, product, key = await setup_job_inputs(api, adb)

    def down(job_id):
        raise ConnectionError("redis is down")

    monkeypatch.setattr("app.api.tryon.enqueue_tryon", down)

    r = await post(api, sid, key, [product.id])

    assert r.status_code == 503
    job = (await adb.scalars(select(TryOnJob).where(TryOnJob.session_id == uuid.UUID(sid)))).one()
    assert job.status == JobStatus.failed
    assert job.error and "try again" in job.error.lower()
    assert len(rq_queue) == 0


async def test_storage_outage_is_a_503(api, adb, s3, rq_queue, monkeypatch):
    sid, product, key = await setup_job_inputs(api, adb)

    def down(_key):
        raise ClientError({"Error": {"Code": "500", "Message": "boom"}}, "HeadObject")

    monkeypatch.setattr("app.api.tryon.object_exists", down)

    r = await post(api, sid, key, [product.id])

    assert r.status_code == 503 and "Storage" in r.json()["detail"]
    assert len(rq_queue) == 0


async def test_get_job_returns_current_state(api, adb, s3, rq_queue):
    sid, product, key = await setup_job_inputs(api, adb)
    job_id = (await post(api, sid, key, [product.id])).json()["job_id"]

    r = await api.get(f"/tryon/{job_id}")

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == job_id and body["status"] == "queued" and body["progress"] == 0
    assert body["capture_key"] == key and "person_image_key" not in body
    assert body["product_ids"] == [str(product.id)] and body["result_url"] is None and body["error"] is None


async def test_get_job_reflects_worker_updates(api, adb, s3, rq_queue):
    sid, product, key = await setup_job_inputs(api, adb)
    job_id = (await post(api, sid, key, [product.id])).json()["job_id"]
    job = await adb.get(TryOnJob, uuid.UUID(job_id))
    job.status, job.progress, job.result_url = JobStatus.done, 100, "http://example.test/r.webp"
    await adb.flush()
    await adb.refresh(job)  # pick up the server-side updated_at, as a fresh request would

    body = (await api.get(f"/tryon/{job_id}")).json()

    assert (body["status"], body["progress"], body["result_url"]) == (
        "done",
        100,
        "http://example.test/r.webp",
    )


async def test_get_job_not_found_and_malformed(api):
    assert (await api.get(f"/tryon/{uuid.uuid4()}")).status_code == 404
    assert (await api.get("/tryon/nope")).status_code == 422


async def test_admin_job_list_needs_the_key(api, adb, s3, rq_queue):
    sid, product, key = await setup_job_inputs(api, adb)
    job_id = (await post(api, sid, key, [product.id])).json()["job_id"]

    assert (await api.get("/tryon")).status_code == 401
    listed = await api.get("/tryon", headers=ADMIN_HEADERS)

    assert listed.status_code == 200 and job_id in [j["id"] for j in listed.json()]
