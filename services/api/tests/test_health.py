from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_admin_requires_key():
    r = client.get("/admin/stats")
    assert r.status_code == 401


def test_presign_rejects_unknown_content_type():
    r = client.post("/uploads/presign", json={"content_type": "text/plain", "kind": "capture"})
    assert r.status_code == 422
