"""Input validation at the edges: bounds, shapes and sizes of everything a client can send."""

import uuid

import pytest

from app.core.config import settings
from tests.helpers import ADMIN_HEADERS, make_product, make_session

GOOD = {
    "name": "Linen Shirt",
    "category": "top",
    "price_pkr": 3990,
    "sizes": ["S", "M"],
    "colors": [{"name": "Ivory", "hex": "#efe6d2"}],
    "stock": 5,
    "garment_image_url": "https://img.example.com/a.png",
}


async def create(api, **over):
    return await api.post("/products", json={**GOOD, **over}, headers=ADMIN_HEADERS)


# --- products ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "over",
    [
        {"sizes": [str(n) for n in range(21)]},  # too many
        {"sizes": ["S", "S"]},  # repeated
        {"sizes": [""]},
        {"sizes": ["x" * 21]},
        {"sizes": ["S\nM"]},  # control character
        {"colors": [{"name": f"c{n}", "hex": "#000000"} for n in range(13)]},
        {"colors": [{"name": "Red\n", "hex": "#ff0000"}]},
        {"colors": [{"name": "", "hex": "#ff0000"}]},
        {"name": "Shirt\x00"},
        {"name": "Line1\nLine2"},
        {"name": "x" * 201},
        {"price_pkr": 2_000_000_001},
        {"stock": 2_000_000_001},
        {"stock": -1},
        {"garment_image_url": "javascript:alert(1)"},
        {"garment_image_url": "ftp://example.com/a.png"},
        {"garment_image_url": "https://example.com/" + "a" * 2100},
        {"garment_image_url": "https://example.com/a\nb"},
        {"garment_mask_url": "file:///etc/passwd"},
        {"sale_price_pkr": 9999999},  # above the price
    ],
)
async def test_bad_product_fields_are_422(api, over):
    r = await create(api, **over)
    assert r.status_code == 422, (over, r.text)


async def test_a_normal_product_is_accepted(api):
    assert (await create(api)).status_code == 201


async def test_the_same_limits_apply_to_updates(api, adb):
    p = await make_product(adb)
    for patch in (
        {"sizes": ["x" * 30]},
        {"garment_image_url": "gopher://x"},
        {"stock": 2_000_000_001},
        {"name": "a\nb"},
    ):
        r = await api.patch(f"/products/{p.id}", json=patch, headers=ADMIN_HEADERS)
        assert r.status_code == 422, patch


# --- query parameters ----------------------------------------------------------------------------


async def test_catalog_rejects_absurd_query_values(api):
    assert (await api.get("/catalog", params={"page": 10**12})).status_code == 422
    assert (await api.get("/catalog", params={"page": 0})).status_code == 422
    assert (await api.get("/catalog", params={"page_size": 101})).status_code == 422
    assert (await api.get("/catalog", params={"search": "x" * 101})).status_code == 422
    many = [("category", "top")] * 50
    assert (await api.get("/catalog", params=many)).status_code == 422
    assert (await api.get("/catalog", params={"category": "nonsense"})).status_code == 422


async def test_recommend_refuses_oversized_or_malformed_id_lists(api):
    ids = ",".join(str(uuid.uuid4()) for _ in range(10))
    assert (await api.get("/recommend", params={"product_ids": ids})).status_code == 422
    assert (await api.get("/recommend", params={"product_ids": "a" * 5000})).status_code == 422
    assert (await api.get("/recommend", params={"product_ids": "not-a-uuid"})).status_code == 422
    assert (await api.get("/recommend", params={"product_ids": ""})).status_code == 422


@pytest.mark.parametrize("path", ["/sessions", "/tryon", "/orders", "/requests"])
async def test_list_limits_are_bounded(api, path):
    headers = ADMIN_HEADERS
    assert (await api.get(path, params={"limit": 0}, headers=headers)).status_code == 422
    assert (await api.get(path, params={"limit": 100000}, headers=headers)).status_code == 422


# --- bodies --------------------------------------------------------------------------------------


async def test_an_oversized_json_body_is_413_before_it_is_parsed(api):
    r = await api.post(
        "/cart/add",
        content=b"{" + b" " * (settings.default_body_limit_bytes + 10) + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


async def test_a_chunked_oversized_body_is_cut_off_too(api):
    async def chunks():
        for _ in range(40):
            yield b" " * 16384

    r = await api.post("/cart/add", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


@pytest.mark.parametrize("body", [b"", b"not json", b"[]", b'{"session_id": 5}', b'{"session_id": null}'])
async def test_malformed_json_is_422(api, body):
    r = await api.post("/cart/add", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "over",
    [
        {"quantity": 0},
        {"quantity": 11},
        {"quantity": "2; DROP TABLE"},
        {"size": "x" * 21},
        {"color": "c" * 41},
        {"session_id": "not-a-uuid"},
        {"product_id": 7},
    ],
)
async def test_cart_add_rejects_bad_fields(api, adb, over):
    p = await make_product(adb)
    sid = await make_session(api)
    body = {"session_id": sid, "product_id": str(p.id), "size": "S", "color": "Ivory", "quantity": 1, **over}
    assert (await api.post("/cart/add", json=body)).status_code == 422


async def test_an_option_that_the_product_does_not_have_is_refused(api, adb):
    p = await make_product(adb)
    sid = await make_session(api)
    for over in ({"size": "XXXL"}, {"color": "Chartreuse"}):
        body = {"session_id": sid, "product_id": str(p.id), "size": "S", "color": "Ivory", **over}
        assert (await api.post("/cart/add", json=body)).status_code in (400, 422)


# --- staff requests ------------------------------------------------------------------------------


async def test_a_staff_request_must_use_a_size_and_colour_the_product_has(api, adb):
    p = await make_product(adb)
    sid = await make_session(api)
    ok = await api.post(
        "/requests", json={"session_id": sid, "product_id": str(p.id), "size": "S", "color": "Ivory"}
    )
    assert ok.status_code == 201
    for over in (
        {"color": "Chartreuse"},
        {"color": "Ivory\nCall 555-0100"},
        {"size": "XXXL"},
        {"color": "c" * 41},
    ):
        body = {"session_id": sid, "product_id": str(p.id), "size": "M", "color": "Ivory", **over}
        assert (await api.post("/requests", json=body)).status_code == 422, over


async def test_a_staff_request_without_a_colour_is_still_fine(api, adb):
    p = await make_product(adb)
    sid = await make_session(api)
    r = await api.post("/requests", json={"session_id": sid, "product_id": str(p.id), "size": "S"})
    assert r.status_code == 201


# --- other public inputs -------------------------------------------------------------------------


async def test_uploads_verify_key_is_bounded(api):
    r = await api.post("/uploads/verify", json={"key": "k" * 600}, headers=ADMIN_HEADERS)
    assert r.status_code == 422


async def test_path_ids_must_be_uuids(api):
    for path in ("/cart/not-a-uuid", "/jobs/123", "/products/abc", "/tryon/xyz"):
        assert (await api.get(path)).status_code == 422, path


async def test_a_session_requires_an_explicit_true_consent(api):
    for body in (
        {},
        {"consent_given": False},
        {"consent_given": "yes"},
        {"consent_given": None},
        {"consent_given": 1},
    ):
        r = await api.post("/sessions", json=body)
        assert r.status_code == 422, body
