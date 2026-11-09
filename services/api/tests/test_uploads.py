"""Garment image uploads: presign, the post-upload check, and the sweeper that backs it up."""

import asyncio
import uuid

import httpx
import pytest

from app.core import storage
from app.core.config import settings
from app.services import capture_cleanup
from tests.helpers import ADMIN_HEADERS

PNG = {"content_type": "image/png", "kind": "garment"}


def keys(s3) -> set[str]:
    return {o["Key"] for o in s3.list_objects_v2(Bucket=settings.s3_bucket).get("Contents", [])}


async def upload_via_presign(client: httpx.AsyncClient, data: bytes, content_type: str = "image/png") -> str:
    """The admin app's real flow: ask for a URL, then PUT the bytes straight to storage."""
    presign = await client.post(
        "/uploads/presign", json={"content_type": content_type, "kind": "garment"}, headers=ADMIN_HEADERS
    )
    assert presign.status_code == 200
    body = presign.json()
    async with httpx.AsyncClient() as raw:
        put = await raw.put(body["upload_url"], content=data, headers={"Content-Type": content_type})
    assert put.status_code == 200
    return body["key"]


def verify(client: httpx.AsyncClient, key: str, headers=ADMIN_HEADERS):
    return client.post("/uploads/verify", json={"key": key}, headers=headers)


async def test_a_normal_upload_passes_the_check(plain_api, s3):
    key = await upload_via_presign(plain_api, b"x" * 1234)

    r = await verify(plain_api, key)

    assert r.status_code == 200
    assert r.json() == {
        "key": key,
        "size_bytes": 1234,
        "content_type": "image/png",
        "public_url": storage.public_url(key),
    }
    assert key in keys(s3)


async def test_an_upload_exactly_at_the_limit_is_accepted(plain_api, s3, monkeypatch):
    monkeypatch.setattr(settings, "garment_max_bytes", 100)
    key = await upload_via_presign(plain_api, b"x" * 100)
    assert (await verify(plain_api, key)).status_code == 200


async def test_an_oversized_upload_is_refused_and_deleted(plain_api, s3, monkeypatch):
    monkeypatch.setattr(settings, "garment_max_bytes", 100)
    key = await upload_via_presign(plain_api, b"x" * 101)
    assert key in keys(s3)

    r = await verify(plain_api, key)

    assert r.status_code == 413
    assert r.json()["detail"] == "That image is larger than 1 KB"  # 100 bytes, shown as the smallest unit
    assert key not in keys(s3)


@pytest.mark.parametrize(
    ("limit", "shown"),
    [(10 * 1024 * 1024, "10 MB"), (1024 * 1024, "1 MB"), (1536 * 1024, "1.5 MB"), (30_000, "29 KB")],
)
async def test_the_limit_is_shown_in_a_readable_unit(plain_api, s3, monkeypatch, limit, shown):
    monkeypatch.setattr(settings, "garment_max_bytes", limit)
    key = await upload_via_presign(plain_api, b"x" * (limit + 1))
    assert (await verify(plain_api, key)).json()["detail"] == f"That image is larger than {shown}"


async def test_an_empty_upload_is_refused_and_deleted(plain_api, s3):
    key = await upload_via_presign(plain_api, b"")
    r = await verify(plain_api, key)
    assert r.status_code == 422 and "empty" in r.json()["detail"]
    assert key not in keys(s3)


async def test_an_object_with_the_wrong_content_type_is_refused_and_deleted(plain_api, s3):
    key = storage.build_key("garment", "image/png")
    s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=b"<html>", ContentType="text/html")

    r = await verify(plain_api, key)

    assert r.status_code == 422 and "content type" in r.json()["detail"]
    assert key not in keys(s3)


async def test_checking_a_key_that_was_never_uploaded_is_404(plain_api, s3):
    r = await verify(plain_api, storage.build_key("garment", "image/png"))
    assert r.status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        "captures/some-session/photo.webp",
        "garment/2026/01/01/short.png",
        "garment/../captures/x.webp",
        "garment/2026/01/01/" + "a" * 32 + ".exe",
        "garment/2026/01/01/" + "A" * 32 + ".png",
        "/garment/2026/01/01/" + "a" * 32 + ".png",
        "",
    ],
)
async def test_only_keys_that_presign_hands_out_can_be_checked(plain_api, s3, monkeypatch, bad):
    # Other objects must be neither inspected nor deleted by this endpoint, even ones over the size limit.
    s3.put_object(Bucket=settings.s3_bucket, Key="captures/some-session/photo.webp", Body=b"x" * 500)
    monkeypatch.setattr(settings, "garment_max_bytes", 1)

    r = await verify(plain_api, bad)

    assert r.status_code == 422
    assert "captures/some-session/photo.webp" in keys(s3)


async def test_verify_requires_the_admin_key(plain_api, s3):
    key = await upload_via_presign(plain_api, b"x")
    assert (await verify(plain_api, key, headers={})).status_code == 401
    assert (await verify(plain_api, key, headers={"X-Admin-Key": "nope"})).status_code == 401
    assert key in keys(s3)  # an unauthenticated caller cannot delete anything either


async def test_the_sweeper_deletes_oversized_garments_and_nothing_else(s3, monkeypatch):
    monkeypatch.setattr(settings, "garment_max_bytes", 100)
    big, ok = "garment/2026/01/01/big.png", "garment/2026/01/01/ok.png"
    s3.put_object(Bucket=settings.s3_bucket, Key=big, Body=b"x" * 101)
    s3.put_object(Bucket=settings.s3_bucket, Key=ok, Body=b"x" * 100)
    s3.put_object(Bucket=settings.s3_bucket, Key="results/s/j.webp", Body=b"x" * 500)
    s3.put_object(Bucket=settings.s3_bucket, Key="captures/s/c.webp", Body=b"x" * 500)

    assert await capture_cleanup.sweep_oversized_garments_once() == 1

    assert keys(s3) == {ok, "results/s/j.webp", "captures/s/c.webp"}
    assert await capture_cleanup.sweep_oversized_garments_once() == 0


async def test_the_background_loop_also_removes_oversized_garments(s3, monkeypatch):
    monkeypatch.setattr(settings, "garment_max_bytes", 10)
    s3.put_object(Bucket=settings.s3_bucket, Key="garment/2026/01/01/big.png", Body=b"x" * 11)
    task = asyncio.create_task(capture_cleanup.cleanup_loop(0.05))
    try:
        for _ in range(100):
            if not keys(s3):
                break
            await asyncio.sleep(0.05)
        assert keys(s3) == set()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_a_failing_garment_sweep_does_not_stop_the_capture_sweep(s3, monkeypatch, caplog):
    def broken(_):
        raise RuntimeError("storage down")

    monkeypatch.setattr(capture_cleanup, "delete_oversized_garments", broken)
    s3.put_object(Bucket=settings.s3_bucket, Key=f"captures/{uuid.uuid4()}/a.webp", Body=b"x")
    task = asyncio.create_task(capture_cleanup.cleanup_loop(0.05, ttl_seconds=0))
    try:
        for _ in range(100):
            if not keys(s3):
                break
            await asyncio.sleep(0.05)
        assert keys(s3) == set()
        assert any(r.message == "garment_sweep_failed" for r in caplog.records)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
