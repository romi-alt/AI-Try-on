import uuid

import pytest

from app.models import ProductCategory
from tests.helpers import ADMIN_HEADERS, make_product, make_session


async def test_get_product(api, adb):
    p = await make_product(
        adb, price_pkr=2000, sale_price_pkr=1500, sizes=["M"], colors=[{"name": "Ivory", "hex": "#efe6d2"}]
    )

    r = await api.get(f"/products/{p.id}")

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(p.id)
    assert body["name"] == p.name
    assert body["sizes"] == ["M"]
    assert body["colors"] == [{"name": "Ivory", "hex": "#efe6d2"}]
    assert body["on_sale"] is True and body["current_price_pkr"] == 1500
    assert body["garment_mask_url"] is None


async def test_get_product_not_found(api):
    r = await api.get(f"/products/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_get_product_rejects_malformed_id(api):
    r = await api.get("/products/not-a-uuid")
    assert r.status_code == 422


async def test_similar_products_are_ordered_by_distance(api, adb):
    base = [1.0] + [0.0] * 511
    near = [0.9, 0.1] + [0.0] * 510
    far = [0.0, 1.0] + [0.0] * 510
    anchor = await make_product(adb, embedding=base)
    n = await make_product(adb, embedding=near)
    f = await make_product(adb, embedding=far)

    r = await api.get(f"/products/{anchor.id}/similar", params={"limit": 24})

    ids = [i["id"] for i in r.json()]
    assert str(anchor.id) not in ids
    assert ids.index(str(n.id)) < ids.index(str(f.id))
    assert all(isinstance(i["distance"], float) for i in r.json())


async def test_similar_products_without_embedding_is_empty(api, adb):
    p = await make_product(adb, embedding=None)
    r = await api.get(f"/products/{p.id}/similar")
    assert r.status_code == 200 and r.json() == []


NEW_PRODUCT = {
    "name": "Admin Created",
    "category": "bag",
    "price_pkr": 3000,
    "sale_price_pkr": 2500,
    "sizes": ["One Size"],
    "colors": [{"name": "Black", "hex": "#000000"}],
    "stock": 4,
    "garment_image_url": "http://example.test/a.png",
}


async def test_admin_routes_require_the_admin_key(api, adb):
    p = await make_product(adb)
    assert (await api.post("/products", json=NEW_PRODUCT)).status_code == 401
    assert (await api.patch(f"/products/{p.id}", json={"stock": 1})).status_code == 401
    assert (await api.delete(f"/products/{p.id}")).status_code == 401
    wrong = {"X-Admin-Key": "nope"}
    assert (await api.post("/products", json=NEW_PRODUCT, headers=wrong)).status_code == 401


async def test_admin_create_update_delete_roundtrip(api):
    created = await api.post("/products", json=NEW_PRODUCT, headers=ADMIN_HEADERS)
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json()["category"] == ProductCategory.bag

    patched = await api.patch(
        f"/products/{pid}", json={"stock": 9, "sale_price_pkr": 2000}, headers=ADMIN_HEADERS
    )
    assert patched.status_code == 200
    assert patched.json()["stock"] == 9 and patched.json()["current_price_pkr"] == 2000

    assert (await api.delete(f"/products/{pid}", headers=ADMIN_HEADERS)).status_code == 204
    assert (await api.get(f"/products/{pid}")).status_code == 404


async def test_admin_create_rejects_sale_price_above_price(api):
    bad = {**NEW_PRODUCT, "sale_price_pkr": 3001}
    r = await api.post("/products", json=bad, headers=ADMIN_HEADERS)
    assert r.status_code == 422


async def test_admin_patch_that_breaks_the_price_rule_is_rejected_by_the_database(api, adb):
    p = await make_product(adb, price_pkr=1000, sale_price_pkr=800)
    r = await api.patch(f"/products/{p.id}", json={"price_pkr": 500}, headers=ADMIN_HEADERS)
    assert r.status_code == 422


async def test_admin_delete_is_blocked_while_the_product_is_in_a_cart(api, adb):
    # Keep the id: the failed delete rolls back and expires ORM objects held by the test.
    pid = (await make_product(adb, sizes=["M"])).id
    session_id = await make_session(api)
    added = await api.post("/cart/add", json={"session_id": session_id, "product_id": str(pid)})
    assert added.status_code == 200

    r = await api.delete(f"/products/{pid}", headers=ADMIN_HEADERS)

    assert r.status_code == 409
    assert (await api.get(f"/products/{pid}")).status_code == 200


async def test_admin_unknown_product_is_404(api):
    missing = uuid.uuid4()
    assert (
        await api.patch(f"/products/{missing}", json={"stock": 1}, headers=ADMIN_HEADERS)
    ).status_code == 404
    assert (await api.delete(f"/products/{missing}", headers=ADMIN_HEADERS)).status_code == 404


# --- SKU ----------------------------------------------------------------------------------------


async def test_a_sku_must_be_unique_but_products_without_one_are_fine(api):
    one = await api.post("/products", json={**NEW_PRODUCT, "sku": "TEE-001"}, headers=ADMIN_HEADERS)
    assert one.status_code == 201 and one.json()["sku"] == "TEE-001"

    dup = await api.post("/products", json={**NEW_PRODUCT, "sku": "TEE-001"}, headers=ADMIN_HEADERS)
    assert dup.status_code == 409 and "SKU" in dup.json()["detail"]

    a = await api.post("/products", json=NEW_PRODUCT, headers=ADMIN_HEADERS)
    b = await api.post("/products", json=NEW_PRODUCT, headers=ADMIN_HEADERS)
    assert a.status_code == b.status_code == 201 and a.json()["sku"] is None


async def test_changing_a_sku_to_one_in_use_is_refused(api):
    a = (await api.post("/products", json={**NEW_PRODUCT, "sku": "A-1"}, headers=ADMIN_HEADERS)).json()
    b = (await api.post("/products", json={**NEW_PRODUCT, "sku": "B-1"}, headers=ADMIN_HEADERS)).json()

    clash = await api.patch(f"/products/{b['id']}", json={"sku": "A-1"}, headers=ADMIN_HEADERS)
    assert clash.status_code == 409
    fresh = await api.patch(f"/products/{b['id']}", json={"sku": "B-2"}, headers=ADMIN_HEADERS)
    assert fresh.status_code == 200 and fresh.json()["sku"] == "B-2" and a["id"]


# --- processing and embeddings (queued for the assets worker) ------------------------------------


async def test_a_product_reports_its_processing_and_embedding_state(api, adb):
    p = await make_product(adb)
    body = (await api.get(f"/products/{p.id}")).json()
    assert body["processing_status"] == "idle" and body["has_embedding"] is False
    assert body["garment_original_url"] is None and body["processing_error"] is None

    with_vec = await make_product(adb, embedding=[1.0] + [0.0] * 511)
    assert (await api.get(f"/products/{with_vec.id}")).json()["has_embedding"] is True
    assert "embedding" not in (await api.get(f"/products/{with_vec.id}")).json()  # 512 floats are never sent


async def test_processing_a_product_queues_it_for_the_assets_worker(api, adb, assets_queue):
    p = await make_product(adb)

    r = await api.post(f"/products/{p.id}/process", headers=ADMIN_HEADERS)

    assert r.status_code == 202 and r.json()["products"] == 1
    (job,) = assets_queue.jobs
    assert job.id == r.json()["job_id"]
    assert job.func_name == "worker.asset_tasks.process_garment_job" and job.args == [str(p.id), True]
    await adb.refresh(p)
    assert p.processing_status.value == "queued" and p.processing_error is None


async def test_processing_without_a_new_embedding_can_be_asked_for(api, adb, assets_queue):
    p = await make_product(adb)
    await api.post(f"/products/{p.id}/process", params={"reembed": "false"}, headers=ADMIN_HEADERS)
    assert assets_queue.jobs[0].args == [str(p.id), False]


async def test_a_product_already_being_processed_is_not_queued_twice(api, adb, assets_queue):
    p = await make_product(adb)
    assert (await api.post(f"/products/{p.id}/process", headers=ADMIN_HEADERS)).status_code == 202
    again = await api.post(f"/products/{p.id}/process", headers=ADMIN_HEADERS)

    assert again.status_code == 409 and "already being processed" in again.json()["detail"]
    assert len(assets_queue.jobs) == 1


@pytest.mark.parametrize("state", ["done", "failed", "idle"])
async def test_a_finished_or_failed_product_can_be_processed_again(api, adb, assets_queue, state):
    p = await make_product(
        adb, processing_status=state, processing_error="old problem" if state == "failed" else None
    )

    r = await api.post(f"/products/{p.id}/process", headers=ADMIN_HEADERS)

    assert r.status_code == 202
    await adb.refresh(p)
    assert p.processing_status.value == "queued" and p.processing_error is None  # the old error is cleared


async def test_processing_needs_the_admin_key_and_a_real_product(api, adb, assets_queue):
    p = await make_product(adb)
    assert (await api.post(f"/products/{p.id}/process")).status_code == 401
    assert (await api.post(f"/products/{uuid.uuid4()}/process", headers=ADMIN_HEADERS)).status_code == 404
    assert (await api.post("/products/nope/process", headers=ADMIN_HEADERS)).status_code == 422
    assert assets_queue.jobs == []


async def test_if_the_queue_is_down_the_product_goes_back_to_how_it_was(api, adb, monkeypatch):
    p = await make_product(adb, processing_status="failed", processing_error="earlier failure")

    def broken(*a, **k):
        raise ConnectionError("redis is down")

    monkeypatch.setattr("app.api.products.enqueue_process_garment", broken)
    r = await api.post(f"/products/{p.id}/process", headers=ADMIN_HEADERS)

    assert r.status_code == 503
    await adb.refresh(p)
    assert (p.processing_status.value, p.processing_error) == ("failed", "earlier failure")


async def test_embeddings_can_be_regenerated_for_chosen_products_or_everything(api, adb, assets_queue):
    a, b = await make_product(adb), await make_product(adb)

    some = await api.post(
        "/products/embeddings", json={"product_ids": [str(a.id), str(b.id)]}, headers=ADMIN_HEADERS
    )
    everything = await api.post("/products/embeddings", json={"only_missing": True}, headers=ADMIN_HEADERS)

    assert some.status_code == everything.status_code == 202
    assert some.json()["products"] == 2 and everything.json()["products"] == 0  # 0 means the whole catalog
    first, second = sorted(assets_queue.jobs, key=lambda j: j.created_at)
    assert first.func_name == "worker.asset_tasks.embed_products_job"
    assert first.args == [[str(a.id), str(b.id)], False]
    assert second.args == [None, True]


async def test_embeddings_need_the_admin_key_and_known_products(api, adb, assets_queue):
    p = await make_product(adb)
    stranger = uuid.uuid4()
    assert (await api.post("/products/embeddings", json={})).status_code == 401
    missing = await api.post(
        "/products/embeddings", json={"product_ids": [str(p.id), str(stranger)]}, headers=ADMIN_HEADERS
    )
    assert missing.status_code == 404 and str(stranger) in missing.json()["detail"]
    assert (
        await api.post("/products/embeddings", json={"product_ids": ["x"]}, headers=ADMIN_HEADERS)
    ).status_code == 422
    assert assets_queue.jobs == []
