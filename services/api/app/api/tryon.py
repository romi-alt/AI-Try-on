import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.db import get_db
from app.core.storage import object_exists
from app.models import Garment, KioskSession, TryOnJob
from app.schemas.tryon import TryOnCreate, TryOnJobOut
from app.services.queue import enqueue_tryon

router = APIRouter(prefix="/tryon", tags=["tryon"])


@router.post("", response_model=TryOnJobOut, status_code=status.HTTP_202_ACCEPTED)
def create_tryon(payload: TryOnCreate, db: Session = Depends(get_db)):
    session = db.get(KioskSession, payload.session_id)
    if not session or session.ended_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Session not found or already ended")
    garment = db.get(Garment, payload.garment_id)
    if not garment or not garment.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Garment not available")
    if not payload.capture_key.startswith("capture/") or not object_exists(payload.capture_key):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Capture image not found in storage")

    job = TryOnJob(session_id=session.id, garment_id=garment.id, capture_key=payload.capture_key)
    db.add(job)
    db.commit()
    db.refresh(job)

    enqueue_tryon(job.id)
    return job


@router.get("/{job_id}", response_model=TryOnJobOut)
def get_tryon(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.get(TryOnJob, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.get("", response_model=list[TryOnJobOut], dependencies=[Depends(require_admin)])
def list_tryons(db: Session = Depends(get_db), limit: int = Query(50, le=500)):
    stmt = select(TryOnJob).order_by(TryOnJob.created_at.desc()).limit(limit)
    return db.scalars(stmt).all()
