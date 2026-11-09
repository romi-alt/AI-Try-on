"""Checkout: turn a session's cart into an order the shopper pays for at the counter.

There is no payment step. The order records what was bought and the price at the time, takes the items out of
stock, and gives the shopper a short pickup code to show staff.
"""

import logging
import secrets
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.api.cart import _require_session
from app.api.deps import AsyncDb
from app.core.auth import require_admin
from app.core.ratelimit import check_session
from app.models import Cart, CartItem, Order, OrderItem, OrderStatus, Product
from app.schemas.order import CheckoutIn, OrderOut, OrderStatusIn

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
    await check_session("checkout_session", payload.session_id)
    order, created = await place_order(db, payload.session_id, payload.idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    return order


async def place_order(
    db, session_id: uuid.UUID, idempotency_key: uuid.UUID | None = None
) -> tuple[Order, bool]:
    """Turn the session's cart into an order. Returns `(order, created)`; `created` is False for a replayed
    key.

    Shared by the kiosk checkout (pay at the counter) and the mobile page checkout (paid through a provider).
    Raises HTTP 404 (no such session) or 409 (empty cart, or not enough stock) without changing anything.
    """
    await _require_session(db, session_id)
    # The same row lock as the cart routes: a checkout and a simultaneous add or removal happen one at a time.
    cart = (
        await db.execute(select(Cart).where(Cart.session_id == session_id).with_for_update())
    ).scalar_one_or_none()

    if idempotency_key is not None:
        existing = await db.scalar(
            select(Order)
            .options(_with_items())
            .where(Order.session_id == session_id, Order.idempotency_key == idempotency_key)
        )
        if existing:
            return existing, False

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
        session_id=session_id,
        idempotency_key=idempotency_key,
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
            "session_id": str(session_id),
            "item_count": order.item_count,
            "subtotal_pkr": order.subtotal_pkr,
        },
    )
    return await db.scalar(select(Order).options(_with_items()).where(Order.id == order_id)), True


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
    status_: OrderStatus | None = Query(
        default=None, alias="status", description="Only orders in this state"
    ),
    limit: int = Query(default=100, ge=1, le=200),
):
    """Recent orders, newest first. Admin only. `code` is matched ignoring case and surrounding spaces."""
    query = select(Order).options(_with_items()).order_by(Order.created_at.desc(), Order.id).limit(limit)
    if code is not None and code.strip():
        query = query.where(Order.pickup_code == code.strip().upper())
    if status_ is not None:
        query = query.where(Order.status == status_)
    return (await db.execute(query)).scalars().all()


@router.patch("/orders/{order_id}", response_model=OrderOut, dependencies=[Depends(require_admin)])
async def set_order_status(order_id: uuid.UUID, payload: OrderStatusIn, db: AsyncDb):
    """Mark a waiting order `collected` or `cancelled`. Admin only.

    Cancelling puts every item back into stock, in the same transaction (a product that has since been deleted
    is skipped). Both are final: an order that is already closed cannot be changed to the other state (409).
    Asking for the state an order is already in is a harmless repeat and changes nothing, so a double click or
    a retry cannot return the stock twice.
    """
    # The order row is locked, so two staff members (or a retry) acting on one order happen one at a time.
    order = (
        await db.execute(
            select(Order).options(_with_items()).where(Order.id == order_id).with_for_update(of=Order)
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    target = OrderStatus(payload.status)
    if order.status == target:
        return order
    if order.status != OrderStatus.placed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This order is already {order.status.value} and cannot be marked {target.value}",
        )

    if target == OrderStatus.cancelled:
        await return_stock(db, order)

    order.status = target
    order.status_changed_at = func.now()
    await db.commit()

    logger.info("order_status_changed", extra={"order_id": str(order_id), "status": target.value})
    return await db.scalar(
        select(Order)
        .options(_with_items())
        .where(Order.id == order_id)
        .execution_options(populate_existing=True)
    )


async def return_stock(db, order: Order) -> None:
    """Put every item of `order` back into stock. A product that has since been deleted is skipped.

    The quantities are added to whatever the stock is now. Products are locked in id order, like checkout, so
    a cancel and a checkout cannot deadlock.
    """
    back: dict[uuid.UUID, int] = {}
    for item in order.items:
        back[item.product_id] = back.get(item.product_id, 0) + item.quantity
    products = (
        await db.execute(
            select(Product).where(Product.id.in_(sorted(back))).order_by(Product.id).with_for_update()
        )
    ).scalars()
    for product in products:
        product.stock += back[product.id]
