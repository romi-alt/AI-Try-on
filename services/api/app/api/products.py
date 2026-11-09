import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.api.deps import AsyncDb
from app.core.auth import require_admin
from app.models import ProcessingStatus, Product
from app.schemas.product import (
    AssetJobAccepted,
    EmbeddingRequest,
    ImportReport,
    ImportRowResult,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    SimilarProductOut,
)
from app.services.csv_import import CsvError, parse_csv
from app.services.queue import enqueue_embeddings, enqueue_process_garment

router = APIRouter(prefix="/products", tags=["products"])
logger = logging.getLogger("app.products")

SKU_TAKEN = "That SKU is already used by another product"


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
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, SKU_TAKEN) from e
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
        if "uq_products_sku" in str(e.orig):
            raise HTTPException(status.HTTP_409_CONFLICT, SKU_TAKEN) from e
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


@router.post(
    "/{product_id}/process",
    response_model=AssetJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
async def process_product(product_id: uuid.UUID, db: AsyncDb, reembed: bool = True):
    """Queue background removal and mask generation for a product's image (and a fresh embedding by default).

    The worker replaces `garment_image_url` with a cutout and sets `garment_mask_url`, keeping the upload in
    `garment_original_url`. Progress shows in the product's `processing_status`.
    """
    product = await db.get(Product, product_id, with_for_update=True)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    if product.processing_status in (ProcessingStatus.queued, ProcessingStatus.processing):
        raise HTTPException(status.HTTP_409_CONFLICT, "This product is already being processed")
    previous = (product.processing_status, product.processing_error)
    product.processing_status = ProcessingStatus.queued
    product.processing_error = None
    await db.commit()  # committed before enqueueing so the worker always finds it queued
    try:
        job_id = await run_in_threadpool(enqueue_process_garment, product_id, reembed=reembed)
    except Exception as e:
        logger.exception("process_enqueue_failed", extra={"product_id": str(product_id)})
        product.processing_status, product.processing_error = previous
        await db.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The image service is busy. Try again."
        ) from e
    logger.info("process_queued", extra={"product_id": str(product_id), "job_id": job_id})
    return AssetJobAccepted(job_id=job_id, products=1)


@router.post(
    "/embeddings",
    response_model=AssetJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
async def regenerate_embeddings(payload: EmbeddingRequest, db: AsyncDb):
    """Queue recomputing FashionCLIP embeddings for the given products, or the whole catalog."""
    if payload.product_ids:
        found = set(await db.scalars(select(Product.id).where(Product.id.in_(payload.product_ids))))
        if missing := [str(p) for p in payload.product_ids if p not in found]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Products not found: {', '.join(missing)}")
    try:
        job_id = await run_in_threadpool(
            enqueue_embeddings, payload.product_ids, only_missing=payload.only_missing
        )
    except Exception as e:
        logger.exception("embedding_enqueue_failed")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The image service is busy. Try again."
        ) from e
    return AssetJobAccepted(job_id=job_id, products=len(payload.product_ids or []))


def _friendly(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        field = ".".join(str(p) for p in err["loc"] if not isinstance(p, int))
        msg = "is required" if err["type"] == "missing" else err["msg"].replace("Value error, ", "")
        out.append(
            f"{field} {msg}" if field and err["type"] == "missing" else (f"{field}: {msg}" if field else msg)
        )
    return out


# What a CSV row may change on an existing product: the columns of the file, under their `Product` names.
_BASE_FIELDS = (
    "sku",
    "name",
    "category",
    "price_pkr",
    "sale_price_pkr",
    "sizes",
    "colors",
    "stock",
    "garment_image_url",
    "garment_mask_url",
)


@router.post("/import", response_model=ImportReport, dependencies=[Depends(require_admin)])
async def import_products(
    request: Request,
    db: AsyncDb,
    dry_run: bool = Query(default=False, description="Check the file and report, without saving anything"),
    embed: bool = Query(default=True, description="Queue embeddings for new products and changed images"),
):
    """Create or update products from a CSV file sent as the request body (`text/csv`). Admin only.

    Rows are matched on `sku`: an existing SKU is updated (empty cells keep the current value), any other row
    creates a product. See `app/services/csv_import.py` for the columns. It is all or nothing: if any row has
    a problem nothing is saved, and every row is reported so the whole file can be fixed in one go. Use
    `dry_run=true` to check a file first.
    """
    try:
        rows = parse_csv(await request.body())
    except CsvError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    skus = sorted({r.sku for r in rows if r.sku})
    existing: dict[str, Product] = {}
    if skus:
        found = await db.execute(
            select(Product).where(Product.sku.in_(skus)).order_by(Product.id).with_for_update()
        )
        existing = {p.sku: p for p in found.scalars()}

    results: list[ImportRowResult] = []
    plan: list[tuple[str, Product | None, dict]] = []  # (action, product, validated fields)
    seen: set[str] = set()
    for row in rows:
        errors = list(row.errors)
        action, product, fields = "create", None, {}
        if row.sku and row.sku in seen:
            errors.append(f"sku {row.sku!r} appears more than once in this file")
        if row.sku:
            seen.add(row.sku)
        if not errors:
            product = existing.get(row.sku) if row.sku else None
            base = {f: getattr(product, f) for f in _BASE_FIELDS} if product else {"sku": row.sku}
            action = "update" if product else "create"
            try:
                fields = ProductCreate(**{**base, **row.values}).model_dump()
            except ValidationError as e:
                errors = _friendly(e)
        results.append(
            ImportRowResult(
                line=row.line,
                action="error" if errors else action,
                sku=row.sku,
                name=row.values.get("name") or (product.name if product else None),
                errors=errors,
            )
        )
        plan.append((action, product, fields))

    error_count = sum(1 for r in results if r.action == "error")
    created = sum(1 for r in results if r.action == "create")
    updated = sum(1 for r in results if r.action == "update")
    report = ImportReport(
        dry_run=dry_run,
        applied=False,
        created=created,
        updated=updated,
        error_count=error_count,
        rows=results,
    )
    if dry_run or error_count or not rows:
        await db.rollback()  # releases the row locks
        return report

    touched: list[Product] = []  # new products and ones whose picture changed: their embedding is stale
    for action, product, fields in plan:
        if action == "create":
            product = Product(**fields)
            db.add(product)
            touched.append(product)
        else:
            assert product is not None
            if fields["garment_image_url"] != product.garment_image_url:
                # A new picture: the old cutout, mask and embedding no longer describe it.
                product.garment_mask_url = None
                product.garment_original_url = None
                product.processing_status = ProcessingStatus.idle
                product.processing_error = None
                touched.append(product)
            for name, value in fields.items():
                if name != "garment_mask_url":  # the file has no mask column; it was reset above if needed
                    setattr(product, name, value)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"{SKU_TAKEN} (another change got there first)") from e
    to_embed = [p.id for p in touched]
    await db.commit()
    report.applied = True

    if embed and to_embed:
        try:
            report.embedding_job_id = await run_in_threadpool(
                enqueue_embeddings, to_embed, only_missing=False
            )
        except Exception:
            logger.exception("import_embed_enqueue_failed")  # the import itself succeeded
    logger.info("products_imported", extra={"rows_created": created, "rows_updated": updated})
    return report
