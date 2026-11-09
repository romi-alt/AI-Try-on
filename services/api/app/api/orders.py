"""Checkout: turn a session's cart into an order the shopper pays for at the counter.

There is no payment step. The order records what was bought and the price at the time, takes the items out of
stock, and gives the shopper a short pickup code to show staff.
"""

import logging
import secrets
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.api.cart import _require_session
from app.api.deps import AsyncDb
from app.core.auth import require_admin
from app.models import Cart, CartItem, Order, OrderItem, Product
from app.schemas.order import CheckoutIn, OrderOut

router = APIRouter(tags=["orders"])
logger = logging.getLogger("app.orders")

# No 0/O, 1/I/L or 5/S look-alikes: the code is read aloud and typed in by staff.
CODE_ALPHABET = "ABCDEFGHJKMNPQRTUVWXY346789"
CODE_LENGTH = 6


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _with_items():
    return selectinload(Order.items)


@router.post("/checkout", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def checkout(payload: CheckoutIn, response: Response, db: AsyncDb):
    """Place an order for everything in the session's cart, then empty the cart.

    Stock is checked and taken off in the same transaction (the products are locked, in a fixed order, so
    two checkouts cannot both take the last item and cannot deadlock). Prices are copied onto the order. If
    anything is short the whole checkout is refused (409) and nothing changes. Resending the same
    `idempotency_key` returns the order already placed (200) instead of placing another.
    """
    await _require_session(db, payload.session_id)
    # The same row lock as the cart routes: a checkout and a simultaneous add or removal happen one at a time.
    cart = (
        await db.execute(select(Cart).where(Cart.session_id == payload.session_id).with_for_update())
    ).scalar_one_or_none()

    if payload.idempotency_key is not None:
        existing = await db.scalar(
            select(Order)
            .options(_with_items())
            .where(Order.session_id == payload.session_id, Order.idempotency_key == payload.idempotency_key)
        )
        if existing:
            response.status_code = status.HTTP_200_OK
            return existing

    lines = []
    if cart:
        lines = (
            (
                await db.execute(
                    select(CartItem)
                    .where(CartItem.cart_id == cart.id)
                    .order_by(CartItem.created_at, CartItem.id)
                )
            )
            .scalars()
            .all()
        )
    if not lines:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your cart is empty")

    product_ids = sorted({line.product_id for line in lines})
    products = {
        p.id: p
        for p in (
            await db.execute(
                select(Product).where(Product.id.in_(product_ids)).order_by(Product.id).with_for_update()
            )
        ).scalars()
    }

    wanted: dict[uuid.UUID, int] = defaultdict(int)
    for line in lines:
        wanted[line.product_id] += line.quantity
    short = []
    for pid in product_ids:
        product = products[pid]
        if wanted[pid] > product.stock:
            short.append(
                f"{product.name}: sold out"
                if product.stock <= 0
                else f"{product.name}: only {product.stock} left"
            )
    if short:
        raise HTTPException(status.HTTP_409_CONFLICT, "Not enough stock. " + "; ".join(short))

    order = Order(
        session_id=payload.session_id,
        idempotency_key=payload.idempotency_key,
        pickup_code=await _unused_code(db),
        item_count=sum(line.quantity for line in lines),
        subtotal_pkr=0,
    )
    for position, line in enumerate(lines):
        product = products[line.product_id]
        unit = product.current_price_pkr
        order.items.append(
            OrderItem(
                position=position,
                product_id=product.id,
                product_name=product.name,
                garment_image_url=product.garment_image_url,
                size=line.size,
                color=line.color,
                quantity=line.quantity,
                unit_price_pkr=unit,
                line_total_pkr=unit * line.quantity,
            )
        )
        order.subtotal_pkr += unit * line.quantity
    for pid, qty in wanted.items():
        products[pid].stock -= qty

    db.add(order)
    await db.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
    order_id = order.id
    await db.commit()

    logger.info(
        "order_placed",
        extra={
            "order_id": str(order_id),
            "session_id": str(payload.session_id),
            "item_count": order.item_count,
            "subtotal_pkr": order.subtotal_pkr,
        },
    )
    return await db.scalar(select(Order).options(_with_items()).where(Order.id == order_id))


async def _unused_code(db) -> str:
    for _ in range(10):
        code = _new_code()
        if not await db.scalar(select(Order.id).where(Order.pickup_code == code)):
            return code
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not create an order code; try again")


@router.get("/orders", response_model=list[OrderOut], dependencies=[Depends(require_admin)])
async def list_orders(
    db: AsyncDb,
    code: str | None = Query(default=None, max_length=12, description="Find an order by its pickup code"),
    limit: int = Query(default=100, ge=1, le=200),
):
    """Recent orders, newest first. Admin only. `code` is matched ignoring case and surrounding spaces."""
    query = select(Order).options(_with_items()).order_by(Order.created_at.desc(), Order.id).limit(limit)
    if code is not None and code.strip():
        query = query.where(Order.pickup_code == code.strip().upper())
    return (await db.execute(query)).scalars().all()
