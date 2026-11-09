import uuid

from sqlalchemy import select

from app.models import KioskSession
from tests.helpers import ADMIN_HEADERS


async def test_session_starts_when_consent_is_given(api, adb):
    r = await api.post("/sessions", json={"consent_given": True})

    assert r.status_code == 201
    body = r.json()
    assert body["consent_given"] is True
    assert body["started_at"]
    stored = await adb.scalar(select(KioskSession).where(KioskSession.id == uuid.UUID(body["id"])))
    assert stored is not None and stored.consent_given is True


async def test_session_is_rejected_without_consent(api, adb):
    before = len((await adb.scalars(select(KioskSession.id))).all())

    refused = await api.post("/sessions", json={"consent_given": False})

    assert refused.status_code == 422
    assert "consent" in refused.text
    assert len((await adb.scalars(select(KioskSession.id))).all()) == before


async def test_session_requires_the_consent_field(api):
    assert (await api.post("/sessions", json={})).status_code == 422
    assert (await api.post("/sessions")).status_code == 422


async def test_session_rejects_non_boolean_consent(api):
    assert (await api.post("/sessions", json={"consent_given": "yes please"})).status_code == 422
    assert (await api.post("/sessions", json={"consent_given": None})).status_code == 422


async def test_each_session_gets_its_own_id(api):
    a = await api.post("/sessions", json={"consent_given": True})
    b = await api.post("/sessions", json={"consent_given": True})
    assert a.json()["id"] != b.json()["id"]


async def test_admin_session_list_requires_key_and_counts_jobs(api):
    created = await api.post("/sessions", json={"consent_given": True})

    assert (await api.get("/sessions")).status_code == 401
    r = await api.get("/sessions", headers=ADMIN_HEADERS)

    assert r.status_code == 200
    mine = next(s for s in r.json() if s["id"] == created.json()["id"])
    assert mine["job_count"] == 0 and mine["consent_given"] is True
