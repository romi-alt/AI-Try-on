import logging

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import AsyncDb
from app.core.auth import require_admin
from app.core.ratelimit import check_ip
from app.models import KioskSession, TryOnJob
from app.schemas.session import SessionAdminOut, SessionCreate, SessionOut

router = APIRouter(prefix="/sessions", tags=["sessions"])
logger = logging.getLogger("app.sessions")


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, request: Request, db: AsyncDb):
    """Start a session. Rejected with 422 unless `consent_given` is true."""
    await check_ip("session_start_ip", request)
    session = KioskSession(consent_given=payload.consent_given)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    logger.info("session_started", extra={"session_id": str(session.id)})
    return session


@router.get("", response_model=list[SessionAdminOut], dependencies=[Depends(require_admin)])
async def list_sessions(db: AsyncDb, limit: int = Query(50, ge=1, le=500)):
    job_count = func.count(TryOnJob.id).label("job_count")
    stmt = (
        select(KioskSession, job_count)
        .outerjoin(TryOnJob, TryOnJob.session_id == KioskSession.id)
        .group_by(KioskSession.id)
        .order_by(KioskSession.started_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        SessionAdminOut.model_validate({**SessionOut.model_validate(s).model_dump(), "job_count": int(c)})
        for s, c in result.all()
    ]
