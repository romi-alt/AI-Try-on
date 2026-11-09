from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import engine
from app.core.redis import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> dict:
    checks: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:  # pragma: no cover - env dependent
        checks["postgres"] = f"error: {e.__class__.__name__}"
    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:  # pragma: no cover
        checks["redis"] = f"error: {e.__class__.__name__}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
