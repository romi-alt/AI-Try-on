import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.db import get_db
from app.core.storage import object_exists
from app.models import KioskSession, Product, TryOnJob
from app.schemas.tryon import TryOnCreate, TryOnJobOut
from app.services.queue import enqueue_tryon

router = APIRouter(prefix="/tryon", tags=["tryon"])


@router.post("", response_model=TryOnJobOut, status_code=status.HTTP_202_ACCEPTED)
def create_tryon(payload: TryOnCreate, db: Session = Depends(get_db)):
    if not db.get(KioskSession, payload.session_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Session not found")

    # Same product twice in one outfit is meaningless; keep first occurrence, preserve order.
    product_ids = list(dict.fromkeys(payload.product_ids))
    found = db.scalar(select(func.count()).select_from(Product).where(Product.id.in_(product_ids)))
    if found != len(product_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "One or more products not found")

    if not payload.person_image_key.startswith("capture/") or not object_exists(payload.person_image_key):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Person image not found in storage")

    job = TryOnJob(
        session_id=payload.session_id, product_ids=product_ids, person_image_key=payload.person_image_key
    )
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
