import uuid

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
