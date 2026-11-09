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


# --- readiness
# ---------------------------------------------------------------------------------------------------

import pytest  # noqa: E402

from app.api import health as health_module  # noqa: E402


def test_liveness_does_not_touch_any_dependency(monkeypatch):
    for name in ("_postgres", "_redis", "_storage", "_worker"):
        monkeypatch.setattr(health_module, name, lambda: pytest.fail("liveness touched a dependency"))
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_reports_every_check_and_is_200_when_all_is_well(monkeypatch):
    for name in ("_postgres", "_redis", "_storage", "_worker"):
        monkeypatch.setattr(health_module, name, lambda: "ok")
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "checks": {"postgres": "ok", "redis": "ok", "storage": "ok", "worker": "ok"},
    }


@pytest.mark.parametrize("down", ["_postgres", "_redis"])
def test_a_dead_postgres_or_redis_is_503_so_a_proxy_stops_sending_traffic(monkeypatch, down):
    for name in ("_postgres", "_redis", "_storage", "_worker"):
        monkeypatch.setattr(health_module, name, lambda: "ok")

    def boom():
        raise ConnectionError("secret-host.internal:5432 refused")

    monkeypatch.setattr(health_module, down, boom)
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["status"] == "down"
    assert r.json()["checks"][down.lstrip("_")] == "error: ConnectionError"
    assert "secret-host" not in r.text  # only the error's class is shown, never its message


@pytest.mark.parametrize("flaky", ["_storage", "_worker"])
def test_storage_or_worker_trouble_is_degraded_but_still_200(monkeypatch, flaky):
    for name in ("_postgres", "_redis", "_storage", "_worker"):
        monkeypatch.setattr(health_module, name, lambda: "ok")
    monkeypatch.setattr(health_module, flaky, lambda: "error: down")
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "degraded"


def test_the_worker_check_sees_a_registered_worker_and_misses_a_stale_or_absent_one(monkeypatch):
    from datetime import UTC, datetime, timedelta

    class W:
        def __init__(self, beat):
            self.last_heartbeat = beat

    now = datetime.now(UTC)
    monkeypatch.setattr(
        health_module.Worker, "all", staticmethod(lambda **kw: [W(now - timedelta(seconds=10))])
    )
    assert health_module._worker() == "ok"
    monkeypatch.setattr(
        health_module.Worker, "all", staticmethod(lambda **kw: [W(now - timedelta(minutes=10))])
    )
    assert health_module._worker().startswith("error")
    monkeypatch.setattr(health_module.Worker, "all", staticmethod(lambda **kw: []))
    assert health_module._worker().startswith("error")
