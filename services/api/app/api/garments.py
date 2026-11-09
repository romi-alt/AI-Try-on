import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.db import get_db
from app.models import Garment, GarmentCategory
from app.schemas.garment import GarmentCreate, GarmentOut, GarmentUpdate, SimilarGarmentOut

router = APIRouter(prefix="/garments", tags=["garments"])


@router.get("", response_model=list[GarmentOut])
def list_garments(
    db: Session = Depends(get_db),
    category: GarmentCategory | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=100, le=500),
):
    stmt = select(Garment).order_by(Garment.created_at.desc()).limit(limit)
    if category:
        stmt = stmt.where(Garment.category == category)
    if not include_inactive:
        stmt = stmt.where(Garment.is_active.is_(True))
    return db.scalars(stmt).all()


@router.get("/{garment_id}", response_model=GarmentOut)
def get_garment(garment_id: uuid.UUID, db: Session = Depends(get_db)):
    garment = db.get(Garment, garment_id)
    if not garment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Garment not found")
    return garment


@router.get("/{garment_id}/similar", response_model=list[SimilarGarmentOut])
def similar_garments(garment_id: uuid.UUID, db: Session = Depends(get_db), limit: int = Query(6, le=24)):
    """Nearest neighbours by cosine distance on the pgvector embedding."""
    garment = db.get(Garment, garment_id)
    if not garment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Garment not found")
    if garment.embedding is None:
        return []
    distance = Garment.embedding.cosine_distance(garment.embedding).label("distance")
    stmt = (
        select(Garment, distance)
        .where(Garment.id != garment_id, Garment.is_active.is_(True), Garment.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    return [
        SimilarGarmentOut.model_validate({**GarmentOut.model_validate(g).model_dump(), "distance": float(d)})
        for g, d in rows
    ]


@router.post(
    "", response_model=GarmentOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)]
)
def create_garment(payload: GarmentCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Garment).where(Garment.sku == payload.sku)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"SKU {payload.sku!r} already exists")
    garment = Garment(**payload.model_dump())
    db.add(garment)
    db.commit()
    db.refresh(garment)
    return garment


@router.patch("/{garment_id}", response_model=GarmentOut, dependencies=[Depends(require_admin)])
def update_garment(garment_id: uuid.UUID, payload: GarmentUpdate, db: Session = Depends(get_db)):
    garment = db.get(Garment, garment_id)
    if not garment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Garment not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(garment, field, value)
    db.commit()
    db.refresh(garment)
    return garment


@router.delete("/{garment_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_garment(garment_id: uuid.UUID, db: Session = Depends(get_db)):
    garment = db.get(Garment, garment_id)
    if not garment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Garment not found")
    db.delete(garment)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Garment has try-on history; deactivate it instead of deleting"
        ) from e
