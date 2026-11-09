from datetime import UTC, datetime, time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.db import get_db
from app.models import Garment, JobStatus, KioskSession, TryOnJob
from app.schemas.admin import StatsOut
from app.services.queue import queue_depth

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)):
    start_of_day = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)

    garments_active = db.scalar(select(func.count()).select_from(Garment).where(Garment.is_active.is_(True)))
    sessions_today = db.scalar(
        select(func.count()).select_from(KioskSession).where(KioskSession.started_at >= start_of_day)
    )
    jobs_today = db.scalar(
        select(func.count()).select_from(TryOnJob).where(TryOnJob.created_at >= start_of_day)
    )
    jobs_failed_today = db.scalar(
        select(func.count())
        .select_from(TryOnJob)
        .where(TryOnJob.created_at >= start_of_day, TryOnJob.status == JobStatus.failed)
    )

    try:
        depth = queue_depth()
    except Exception:
        depth = -1

    return StatsOut(
        garments_active=garments_active or 0,
        sessions_today=sessions_today or 0,
        jobs_today=jobs_today or 0,
        jobs_failed_today=jobs_failed_today or 0,
        queue_depth=depth,
    )
