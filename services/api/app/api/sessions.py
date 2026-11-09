import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.db import get_db
from app.models import KioskSession, TryOnJob
from app.schemas.session import SessionAdminOut, SessionCreate, SessionOut

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    session = KioskSession(kiosk_id=payload.kiosk_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/end", response_model=SessionOut)
def end_session(session_id: uuid.UUID, db: Session = Depends(get_db)):
    session = db.get(KioskSession, session_id)
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if session.ended_at is None:
        session.ended_at = datetime.now(UTC)
        db.commit()
        db.refresh(session)
    return session


@router.get("", response_model=list[SessionAdminOut], dependencies=[Depends(require_admin)])
def list_sessions(db: Session = Depends(get_db), limit: int = Query(50, le=500)):
    job_count = func.count(TryOnJob.id).label("job_count")
    stmt = (
        select(KioskSession, job_count)
        .outerjoin(TryOnJob, TryOnJob.session_id == KioskSession.id)
        .group_by(KioskSession.id)
        .order_by(KioskSession.started_at.desc())
        .limit(limit)
    )
    return [
        SessionAdminOut.model_validate({**SessionOut.model_validate(s).model_dump(), "job_count": int(c)})
        for s, c in db.execute(stmt).all()
    ]
