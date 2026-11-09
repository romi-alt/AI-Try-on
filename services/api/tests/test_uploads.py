"""POST /uploads/presign is admin-only: it mints write access to the product-image prefix."""

import httpx
import pytest
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

from .helpers import ADMIN_HEADERS

BODY = {"content_type": "image/png", "kind": "garment"}


async def test_presign_requires_admin_key(plain_api: httpx.AsyncClient):
    r = await plain_api.post("/uploads/presign", json=BODY)
    assert r.status_code == 401


async def test_presign_rejects_wrong_admin_key(plain_api: httpx.AsyncClient):
    r = await plain_api.post(
        "/uploads/presign", json=BODY, headers={"X-Admin-Key": "wrong-" + settings.admin_api_key}
    )
    assert r.status_code == 401


async def test_presign_auth_is_checked_before_body_validation(plain_api: httpx.AsyncClient):
    r = await plain_api.post("/uploads/presign", json={"content_type": "text/plain"})
    assert r.status_code == 401


async def test_presign_with_admin_key(plain_api: httpx.AsyncClient):
    r = await plain_api.post("/uploads/presign", json=BODY, headers=ADMIN_HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["key"].startswith("garment/") and data["key"].endswith(".png")
    assert data["upload_url"].startswith("http")
    assert data["public_url"].endswith(data["key"])
    assert data["expires_in"] == settings.presign_expires_seconds


@pytest.mark.parametrize(
    "body",
    [
        {"content_type": "text/plain", "kind": "garment"},
        {"content_type": "image/png", "kind": "capture"},
    ],
)
async def test_presign_rejects_unsupported_input(plain_api: httpx.AsyncClient, body: dict):
    r = await plain_api.post("/uploads/presign", json=body, headers=ADMIN_HEADERS)
    assert r.status_code == 422


async def test_presigned_url_accepts_put(plain_api: httpx.AsyncClient, s3):
    """End to end against the moto server: the minted URL really takes an upload."""
    r = await plain_api.post("/uploads/presign", json=BODY, headers=ADMIN_HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    async with httpx.AsyncClient() as http:
        put = await http.put(data["upload_url"], content=b"png-bytes", headers={"Content-Type": "image/png"})
    assert put.status_code == 200
    obj = await run_in_threadpool(s3.get_object, Bucket=settings.s3_bucket, Key=data["key"])
    assert obj["Body"].read() == b"png-bytes"
