import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AsyncDb
from app.core.auth import require_admin
from app.models import Product
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate, SimilarProductOut

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: uuid.UUID, db: AsyncDb):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


@router.get("/{product_id}/similar", response_model=list[SimilarProductOut])
async def similar_products(product_id: uuid.UUID, db: AsyncDb, limit: int = Query(6, ge=1, le=24)):
    """Nearest neighbours by cosine distance on the pgvector embedding."""
    product = await db.get(Product, product_id)
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
    result = await db.execute(stmt)
    return [
        SimilarProductOut.model_validate({**ProductOut.model_validate(p).model_dump(), "distance": float(d)})
        for p, d in result.all()
    ]


@router.post(
    "", response_model=ProductOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)]
)
async def create_product(payload: ProductCreate, db: AsyncDb):
    product = Product(**payload.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductOut, dependencies=[Depends(require_admin)])
async def update_product(product_id: uuid.UUID, payload: ProductUpdate, db: AsyncDb):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    try:
        await db.commit()
    except IntegrityError as e:
        # e.g. a partial update leaving sale_price_pkr above price_pkr (enforced by the database).
        await db.rollback()
        raise HTTPException(422, "Update violates product constraints") from e
    await db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_product(product_id: uuid.UUID, db: AsyncDb):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    await db.delete(product)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Product is in a cart and cannot be deleted") from e
