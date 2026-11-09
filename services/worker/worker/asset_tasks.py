"""RQ jobs on the `assets` queue: processing a garment image and regenerating embeddings.

Both are started from the admin app through the API. They run in a separate worker (`WORKER_QUEUES=assets`) so
heavy model work never delays a shopper's try-on.
"""

import logging
import uuid
from collections.abc import Callable

from worker import db, storage
from worker.config import settings
from worker.embeddings import EmbedReport, ImageEncoder, embed_products, prepare_image
from worker.garment import (
    BackgroundRemover,
    MaskRefiner,
    ProcessingError,
    RembgRemover,
    Sam2Refiner,
    process_image,
)

logger = logging.getLogger("worker.assets")


def _public_url(key: str) -> str:
    return f"{settings.s3_public_base_url.rstrip('/')}/{key}"


def default_refiner() -> MaskRefiner | None:
    return Sam2Refiner() if settings.sam2_checkpoint else None


def process_garment(
    product_id: uuid.UUID,
    *,
    remover: BackgroundRemover | None = None,
    refiner: MaskRefiner | None = None,
    encoder: ImageEncoder | None = None,
    reembed: bool = True,
    load_image: Callable[[str], bytes] = storage.load_image_from_url,
    put_bytes: Callable[[str, bytes, str], None] = storage.put_bytes,
) -> bool:
    """Remove the background of a product's image and make its mask, then store both and re-embed.

    Reprocessing starts again from the original upload, not from an earlier cutout. Returns False when the
    product
    was not `queued` (another worker has it, or it was deleted). On failure the product is marked `failed`
    with a
    message the admin can read, and nothing about the product's images changes.
    """
    if not db.claim_processing(product_id):
        logger.info("garment_not_claimed", extra={"product_id": str(product_id)})
        return False
    try:
        row = next(iter(db.list_product_images([product_id])), None)
        if row is None:
            return False
        original = row.garment_original_url or row.garment_image_url
        result = process_image(
            load_image(original),
            remover or RembgRemover(),
            refiner if refiner is not None else default_refiner(),
        )
        run = uuid.uuid4().hex[:10]  # a new key per run, so a browser or CDN never serves the previous cutout
        base = f"garment/processed/{product_id}/{run}"
        put_bytes(f"{base}-cutout.png", result.cutout_png, "image/png")
        put_bytes(f"{base}-mask.png", result.mask_png, "image/png")
        db.finish_processing(
            product_id,
            image_url=_public_url(f"{base}-cutout.png"),
            mask_url=_public_url(f"{base}-mask.png"),
            original_url=original,
        )
        logger.info(
            "garment_processed",
            extra={
                "product_id": str(product_id),
                "coverage": round(result.coverage, 3),
                "sam2": result.used_sam2,
            },
        )
    except ProcessingError as e:
        db.fail_processing(product_id, str(e))
        logger.warning("garment_unprocessable", extra={"product_id": str(product_id), "reason": str(e)})
        return True
    except Exception as e:
        logger.exception("garment_processing_failed", extra={"product_id": str(product_id)})
        db.fail_processing(product_id, f"Processing failed: {type(e).__name__}. See the worker log.")
        raise

    if reembed:  # the cutout changes what the picture looks like, so the embedding is recomputed from it
        try:
            embed_products([product_id], encoder=encoder, load_image=lambda _url: result.cutout_png)
        except Exception:
            logger.warning(
                "reembed_after_processing_failed", extra={"product_id": str(product_id)}, exc_info=True
            )
    return True


# --- functions RQ calls by dotted path (arguments are JSON, so ids are strings) ---------------------------


def process_garment_job(product_id: str, reembed: bool = True) -> bool:
    return process_garment(uuid.UUID(product_id), reembed=reembed)


def embed_products_job(product_ids: list[str] | None = None, only_missing: bool = False) -> dict:
    report: EmbedReport = embed_products(
        [uuid.UUID(p) for p in product_ids] if product_ids else None, only_missing=only_missing
    )
    return {"updated": len(report.updated), "failed": {str(k): v for k, v in report.failed.items()}}


__all__ = ["embed_products_job", "prepare_image", "process_garment", "process_garment_job"]
