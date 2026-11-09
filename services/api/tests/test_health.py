from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_admin_requires_key():
    r = client.get("/admin/stats")
    assert r.status_code == 401


ADMIN = {"X-Admin-Key": settings.admin_api_key}
GARMENT = {"content_type": "image/png", "kind": "garment"}


def test_presign_rejects_unknown_content_type():
    r = client.post("/uploads/presign", json={"content_type": "text/plain", "kind": "capture"}, headers=ADMIN)
    assert r.status_code == 422


def test_presign_requires_the_admin_key():
    assert client.post("/uploads/presign", json=GARMENT).status_code == 401
    wrong = client.post("/uploads/presign", json=GARMENT, headers={"X-Admin-Key": "nope"})
    assert wrong.status_code == 401
    # The key is checked before the body, so a stranger learns nothing about the accepted types.
    assert client.post("/uploads/presign", json={"content_type": "text/plain"}).status_code == 401


def test_presign_with_the_admin_key_returns_an_upload_url():
    r = client.post("/uploads/presign", json=GARMENT, headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["key"].startswith("garment/") and body["key"].endswith(".png")
    assert "X-Amz-Signature" in body["upload_url"] or "Signature" in body["upload_url"]
