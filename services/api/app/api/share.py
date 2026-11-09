"""The mobile page: scan a QR code at the mirror, see the look and the cart on your phone, and pay.

`POST /share` (from the kiosk) makes a short code for a session. Everything under `/m/{code}` is public,
because
the code in the QR is the credential: it is random, it expires, and it only reaches that session's look and
cart.
"""

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.api.cart import _build_cart, _require_session
from app.api.deps import AsyncDb
from app.api.orders import place_order, return_stock
from app.core.config import settings
from app.core.ratelimit import (
    check,
    check_ip,
    check_session,
    raise_if_blocked,
    record_ip_failure,
)
from app.core.storage import object_exists, presigned_get
from app.models import (
    Cart,
    CartItem,
    JobStatus,
    Order,
    OrderStatus,
    PaymentStatus,
    Product,
    ShareLink,
    TryOnJob,
)
from app.schemas.share import (
    MobileCartOut,
    MobileCheckoutIn,
    MobileCheckoutOut,
    MobileLookOut,
    PaymentOut,
    ShareCreate,
    ShareOut,
)
from app.services.payments import get_payment_provider

router = APIRouter(tags=["share"])
# The codes this app makes are 8 letters and digits (a typed one may have stray spaces); anything else cannot
# exist, so it is refused before any lookup.
MobileCode = Annotated[str, Path(max_length=20, pattern=r"^ {0,2}[A-Za-z0-9]{4,16} {0,2}$")]
logger = logging.getLogger("app.share")

# No I, O, 0 or 1: the code is also typed by hand when a camera cannot read the QR.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
LOOK_IMAGE_TTL_SECONDS = 3600


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _result_key(session_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"results/{session_id}/{job_id}.webp"  # where the worker stores a finished look


@router.post("/share", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
async def create_share(payload: ShareCreate, response: Response, db: AsyncDb) -> ShareOut:
    """Make (or find) the mobile-page code for a session and, optionally, one of its finished looks."""
    await check_session("share_session", payload.session_id)
    await _require_session(db, payload.session_id)
    if payload.job_id is not None:
        job = await db.get(TryOnJob, payload.job_id)
        if job is None or job.session_id != payload.session_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Look not found for this session")
        if job.status != JobStatus.done:
            raise HTTPException(status.HTTP_409_CONFLICT, "That look is not finished yet")

    now = datetime.now(UTC)
    existing = await db.scalar(
        select(ShareLink).where(
            ShareLink.session_id == payload.session_id,
            ShareLink.job_id.is_not_distinct_from(payload.job_id),
            ShareLink.expires_at > now,
        )
    )
    link = existing
    if link is not None:
        response.status_code = status.HTTP_200_OK  # the same code again, not a new one
    else:
        for _ in range(10):
            code = _new_code()
            if not await db.scalar(select(ShareLink.id).where(ShareLink.short_code == code)):
                break
        else:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not make a code; try again")
        link = ShareLink(
            short_code=code,
            session_id=payload.session_id,
            job_id=payload.job_id,
            expires_at=now + timedelta(seconds=settings.share_link_ttl_seconds),
        )
        db.add(link)
        await db.commit()
        logger.info("share_created", extra={"session_id": str(payload.session_id)})
    return ShareOut(short_code=link.short_code, path=f"/m/{link.short_code}", expires_at=link.expires_at)


async def _live_link(db, code: str, request: Request) -> ShareLink:
    # Someone guessing codes gets locked out after a few misses (an unknown code is the only thing counted).
    await raise_if_blocked("mobile_bad_code_ip", request)
    link = await db.scalar(select(ShareLink).where(ShareLink.short_code == code.strip().upper()))
    if link is None:
        await record_ip_failure("mobile_bad_code_ip", request)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link was not found")
    if link.expires_at <= datetime.now(UTC):
        raise HTTPException(status.HTTP_410_GONE, "This link has expired. Ask staff for a new one.")
    return link


async def _look_image_url(link: ShareLink) -> str | None:
    if link.job_id is None:
        return None
    key = _result_key(link.session_id, link.job_id)
    try:
        if not await run_in_threadpool(object_exists, key):
            return None
        return await run_in_threadpool(presigned_get, key, LOOK_IMAGE_TTL_SECONDS)
    except (BotoCoreError, ClientError):
        logger.warning("look_image_unavailable", extra={"session_id": str(link.session_id)})
        return None


@router.get("/m/{code}", response_model=MobileLookOut)
async def mobile_page(code: MobileCode, request: Request, db: AsyncDb) -> MobileLookOut:
    """Everything the mobile page shows: the look image (a fresh signed URL), the cart, and any order
    placed since."""
    await check_ip("mobile_page_ip", request)
    link = await _live_link(db, code, request)
    cart = await _build_cart(db, link.session_id)
    order = await db.scalar(
        select(Order)
        .options(selectinload(Order.items))
        .where(
            Order.session_id == link.session_id,
            Order.created_at >= link.created_at,
            Order.status
            != OrderStatus.cancelled,  # a payment that failed leaves nothing for the page to show
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    return MobileLookOut(
        short_code=link.short_code,
        expires_at=link.expires_at,
        look_image_url=await _look_image_url(link),
        cart=MobileCartOut(items=cart.items, item_count=cart.item_count, subtotal_pkr=cart.subtotal_pkr),
        order=order,
    )


@router.post("/m/{code}/checkout", response_model=MobileCheckoutOut)
async def mobile_checkout(
    code: MobileCode, payload: MobileCheckoutIn, request: Request, db: AsyncDb
) -> MobileCheckoutOut:
    """Place the order for the cart and charge it through the payment provider.

    The order is placed first (stock is taken), then the provider is asked to collect the money. If it
    declines,
    the order is cancelled, its items go back into stock and the cart is put back as it was, so the shopper
    can try
    again. Repeating the same `idempotency_key` returns the same order and payment, charging once.
    """
    link = await _live_link(db, code, request)
    await check("mobile_checkout_code", link.short_code)
    await check_ip("mobile_checkout_ip", request)
    order, created = await place_order(db, link.session_id, payload.idempotency_key)
    provider = get_payment_provider()

    if not created:  # a retry: report what happened the first time instead of charging again
        return MobileCheckoutOut(order=order, payment=_payment_out(order))

    result = await provider.charge(
        order_id=order.id,
        amount_pkr=order.subtotal_pkr,
        description=f"Order {order.pickup_code}",
        idempotency_key=str(payload.idempotency_key or order.id),
    )
    order.payment_provider = provider.name
    order.payment_reference = result.reference
    order.payment_status = PaymentStatus(result.status)
    if result.status == "failed":
        await _undo_failed_order(db, order)
        await db.commit()
        logger.warning("mobile_payment_failed", extra={"order_id": str(order.id), "provider": provider.name})
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, result.message or "The payment did not go through"
        )
    await db.commit()
    logger.info(
        "mobile_checkout",
        extra={"order_id": str(order.id), "status": result.status, "provider": provider.name},
    )
    return MobileCheckoutOut(
        order=order,
        payment=PaymentOut(
            provider=provider.name,
            status=result.status,
            reference=result.reference,
            redirect_url=result.redirect_url,
        ),
    )


def _payment_out(order: Order) -> PaymentOut:
    return PaymentOut(
        provider=order.payment_provider or "none",
        status=order.payment_status.value,
        reference=order.payment_reference or "",
        redirect_url=None,
    )


async def _undo_failed_order(db, order: Order) -> None:
    """Cancel the order, return its stock and rebuild the cart from its items, so the shopper can try
    again."""
    await return_stock(db, order)
    order.status = OrderStatus.cancelled
    order.status_changed_at = datetime.now(UTC)
    cart = (await db.execute(select(Cart).where(Cart.session_id == order.session_id))).scalar_one()
    still_sold = set(
        await db.scalars(select(Product.id).where(Product.id.in_([i.product_id for i in order.items])))
    )
    for item in order.items:
        if item.product_id in still_sold:
            db.add(
                CartItem(
                    cart_id=cart.id,
                    product_id=item.product_id,
                    size=item.size,
                    color=item.color,
                    quantity=item.quantity,
                )
            )
