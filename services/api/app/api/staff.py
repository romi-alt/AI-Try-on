"""Staff requests ("Request Outfit"): a shopper at the mirror asks for an item, staff see it live and answer.

The kiosk creates a request (no key needed; the session is the credential, like the rest of the kiosk API).
The
staff page lists and updates requests with the staff key and hears about changes on `WS /ws/staff`.
"""

import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.cart import _require_session
from app.api.deps import AsyncDb
from app.api.ws import STAFF_CHANNEL
from app.core.auth import require_staff
from app.core.redis import get_redis
from app.models import Product, StaffRequest, StaffRequestStatus
from app.schemas.staff import StaffRequestCreate, StaffRequestOut, StaffRequestStatusIn
from app.services.notifier import get_notifier

router = APIRouter(prefix="/requests", tags=["staff"])
logger = logging.getLogger("app.staff")

OPEN_STATES = (StaffRequestStatus.open, StaffRequestStatus.bringing)


async def _publish(kind: str, request: StaffRequest) -> None:
    """Tell the staff page. Best effort: a Redis outage must not fail the request it is announcing."""
    event = json.dumps(
        {"type": kind, "request": json.loads(StaffRequestOut.model_validate(request).model_dump_json())}
    )
    try:
        await run_in_threadpool(get_redis().publish, STAFF_CHANNEL, event)
    except Exception:
        logger.warning("staff_publish_failed", exc_info=True)


async def _notify(request: StaffRequest) -> None:
    try:
        await get_notifier().notify(request)
    except Exception:
        logger.exception("staff_notify_failed", extra={"request_id": str(request.id)})


@router.post("", response_model=StaffRequestOut, status_code=status.HTTP_201_CREATED)
async def create_request(
    payload: StaffRequestCreate, response: Response, background: BackgroundTasks, db: AsyncDb
) -> StaffRequest:
    """Ask staff to bring an item (in a size). Asking again for the same open item returns that request
    (200)."""
    await _require_session(db, payload.session_id)
    product = await db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    if product.sizes and payload.size is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Choose a size: {', '.join(product.sizes)}"
        )
    if payload.size is not None and payload.size not in product.sizes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid size {payload.size!r}; available: {product.sizes}"
        )

    duplicate = await db.scalar(
        select(StaffRequest).where(
            StaffRequest.session_id == payload.session_id,
            StaffRequest.product_id == payload.product_id,
            StaffRequest.size.is_not_distinct_from(payload.size),
            StaffRequest.status.in_(OPEN_STATES),
        )
    )
    if duplicate:  # a double tap, or the shopper asking twice: staff are already coming
        response.status_code = status.HTTP_200_OK
        return duplicate

    request = StaffRequest(
        session_id=payload.session_id,
        product_id=product.id,
        product_name=product.name,
        size=payload.size,
        color=payload.color,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)
    logger.info(
        "staff_request_created", extra={"request_id": str(request.id), "session_id": str(payload.session_id)}
    )
    await _publish("request.created", request)
    background.add_task(_notify, request)
    return request


@router.get("", response_model=list[StaffRequestOut], dependencies=[Depends(require_staff)])
async def list_requests(
    db: AsyncDb,
    status_: StaffRequestStatus | None = Query(
        default=None, alias="status", description="Default: open and bringing"
    ),
    limit: int = Query(default=100, ge=1, le=200),
):
    """Requests staff still have to deal with (or one status), oldest first so the longest wait is on top."""
    query = select(StaffRequest).order_by(StaffRequest.created_at, StaffRequest.id).limit(limit)
    query = (
        query.where(StaffRequest.status == status_)
        if status_
        else query.where(StaffRequest.status.in_(OPEN_STATES))
    )
    return (await db.execute(query)).scalars().all()


@router.patch("/{request_id}", response_model=StaffRequestOut, dependencies=[Depends(require_staff)])
async def update_request(request_id: uuid.UUID, payload: StaffRequestStatusIn, db: AsyncDb) -> StaffRequest:
    """Mark a request `bringing` (on the way) or `done`. `done` is final; repeating a change is harmless."""
    request = (
        await db.execute(select(StaffRequest).where(StaffRequest.id == request_id).with_for_update())
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    target = StaffRequestStatus(payload.status)
    if request.status == target:
        return request
    if request.status == StaffRequestStatus.done:
        raise HTTPException(status.HTTP_409_CONFLICT, "This request is already done")
    request.status = target
    await db.commit()
    await db.refresh(request)
    logger.info("staff_request_updated", extra={"request_id": str(request_id), "status": target.value})
    await _publish("request.updated", request)
    return request
