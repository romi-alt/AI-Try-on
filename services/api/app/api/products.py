import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.db import get_db
from app.models import Product, ProductCategory
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate, SimilarProductOut

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
def list_products(
    db: Session = Depends(get_db),
    category: ProductCategory | None = None,
    in_stock: bool = False,
    limit: int = Query(default=100, le=500),
):
    stmt = select(Product).order_by(Product.created_at.desc(), Product.name).limit(limit)
    if category:
        stmt = stmt.where(Product.category == category)
    if in_stock:
        stmt = stmt.where(Product.stock > 0)
    return db.scalars(stmt).all()


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: uuid.UUID, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


@router.get("/{product_id}/similar", response_model=list[SimilarProductOut])
def similar_products(product_id: uuid.UUID, db: Session = Depends(get_db), limit: int = Query(6, le=24)):
    """Nearest neighbours by cosine distance on the pgvector embedding."""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    if product.embedding is None:
        return []
    distance = Product.embedding.cosine_distance(product.embedding).label("distance")
    stmt = (
        select(Product, distance)
        .where(Product.id != product_id, Product.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    return [
        SimilarProductOut.model_validate({**ProductOut.model_validate(p).model_dump(), "distance": float(d)})
        for p, d in db.execute(stmt).all()
    ]


@router.post(
    "", response_model=ProductOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)]
)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductOut, dependencies=[Depends(require_admin)])
def update_product(product_id: uuid.UUID, payload: ProductUpdate, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    try:
        db.commit()
    except IntegrityError as e:
        # e.g. a partial update leaving sale_price_pkr above price_pkr (checked by the DB).
        db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Update violates product constraints"
        ) from e
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_product(product_id: uuid.UUID, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    db.delete(product)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Product is in a cart and cannot be deleted") from e
