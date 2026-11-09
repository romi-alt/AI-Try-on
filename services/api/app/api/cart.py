import logging
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AsyncDb
from app.models import Cart, CartItem, KioskSession, Product
from app.schemas.cart import CartAddIn, CartItemOut, CartItemUpdateIn, CartOut, CartProductOut

router = APIRouter(prefix="/cart", tags=["cart"])
logger = logging.getLogger("app.cart")


def _resolve_option(label: str, value: str | None, options: list[str]) -> str | None:
    """Validate a size/color against what the product offers.

    Omitted: allowed only when there is nothing to choose (no options, or exactly one).
    """
    if value is None:
        if len(options) == 1:
            return options[0]
        if options:
            raise HTTPException(422, f"{label} is required; choose one of {options}")
        return None
    if value not in options:
        raise HTTPException(422, f"Invalid {label} {value!r}; available: {options}")
    return value


async def _require_session(db: AsyncSession, session_id: uuid.UUID) -> KioskSession:
    session = await db.get(KioskSession, session_id)
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return session


async def _build_cart(db: AsyncSession, session_id: uuid.UUID) -> CartOut:
    cart_id = await db.scalar(select(Cart.id).where(Cart.session_id == session_id))
    rows = []
    if cart_id:
        result = await db.execute(
            select(CartItem, Product)
            .join(Product, Product.id == CartItem.product_id)
            .where(CartItem.cart_id == cart_id)
            .order_by(CartItem.created_at, Product.name, CartItem.size, CartItem.id)
        )
        rows = result.all()

    items = [
        CartItemOut(
            id=item.id,
            product=CartProductOut.model_validate(product),
            size=item.size,
            color=item.color,
            quantity=item.quantity,
            unit_price_pkr=product.current_price_pkr,
            line_total_pkr=product.current_price_pkr * item.quantity,
        )
        for item, product in rows
    ]
    return CartOut(
        session_id=session_id,
        cart_id=cart_id,
        items=items,
        item_count=sum(i.quantity for i in items),
        subtotal_pkr=sum(i.line_total_pkr for i in items),
    )


@router.post("/add", response_model=CartOut)
async def add_to_cart(payload: CartAddIn, db: AsyncDb):
    """Add a product to the session's cart, merging with an identical size/color line.

    Returns the whole updated cart. Stock is checked but not reserved.
    """
    await _require_session(db, payload.session_id)
    product = await db.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")

    size = _resolve_option("size", payload.size, product.sizes)
    color = _resolve_option("color", payload.color, [c["name"] for c in product.colors])

    # Get-or-create the cart (unique per session, safe under concurrent first adds), then lock
    # its row so simultaneous adds to the same cart are applied one at a time.
    await db.execute(
        pg_insert(Cart)
        .values(session_id=payload.session_id)
        .on_conflict_do_nothing(index_elements=[Cart.session_id])
    )
    cart = (
        await db.execute(select(Cart).where(Cart.session_id == payload.session_id).with_for_update())
    ).scalar_one()

    in_cart = (
        await db.scalar(
            select(func.coalesce(func.sum(CartItem.quantity), 0)).where(
                CartItem.cart_id == cart.id, CartItem.product_id == product.id
            )
        )
        or 0
    )
    if in_cart + payload.quantity > product.stock:
        # No explicit rollback: closing the request's session as the error propagates rolls back,
        # discarding the empty cart created above and releasing the row lock.
        detail = (
            "Out of stock"
            if product.stock <= 0
            else f"Only {product.stock} in stock ({in_cart} already in cart)"
        )
        raise HTTPException(status.HTTP_409_CONFLICT, detail)

    line = await db.scalar(
        select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.product_id == product.id,
            CartItem.size.is_not_distinct_from(size),
            CartItem.color.is_not_distinct_from(color),
        )
    )
    if line:
        line.quantity += payload.quantity
    else:
        db.add(
            CartItem(
                cart_id=cart.id, product_id=product.id, size=size, color=color, quantity=payload.quantity
            )
        )
    cart.updated_at = func.now()
    await db.commit()

    logger.info(
        "cart_item_added",
        extra={
            "session_id": str(payload.session_id),
            "product_id": str(product.id),
            "quantity": payload.quantity,
            "merged": line is not None,
        },
    )
    return await _build_cart(db, payload.session_id)


@router.patch("/{session_id}/items/{item_id}", response_model=CartOut)
async def set_item_quantity(
    session_id: uuid.UUID, item_id: uuid.UUID, payload: CartItemUpdateIn, db: AsyncDb
):
    """Set one line's quantity (1 or more) and return the updated cart.

    Raising it is checked against stock across every line of that product, as when adding. Lowering it is
    always allowed, even if stock has since dropped below what is in the cart. The line must belong to this
    session's cart, otherwise 404. To take a line out entirely, use DELETE.
    """
    await _require_session(db, session_id)
    cart = (
        await db.execute(select(Cart).where(Cart.session_id == session_id).with_for_update())
    ).scalar_one_or_none()
    line = None
    if cart:
        line = await db.scalar(select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart.id))
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item is not in the cart")

    if payload.quantity > line.quantity:
        product = await db.get(Product, line.product_id)
        elsewhere = (
            await db.scalar(
                select(func.coalesce(func.sum(CartItem.quantity), 0)).where(
                    CartItem.cart_id == cart.id,
                    CartItem.product_id == line.product_id,
                    CartItem.id != line.id,
                )
            )
            or 0
        )
        if elsewhere + payload.quantity > product.stock:
            if product.stock <= 0:
                detail = "Out of stock"
            elif elsewhere:
                detail = f"Only {product.stock} in stock ({elsewhere} already in your cart in other options)"
            else:
                detail = f"Only {product.stock} in stock"
            raise HTTPException(status.HTTP_409_CONFLICT, detail)

    previous = line.quantity
    if payload.quantity != previous:
        line.quantity = payload.quantity
        cart.updated_at = func.now()
        await db.commit()
        logger.info(
            "cart_item_quantity_set",
            extra={
                "session_id": str(session_id),
                "item_id": str(item_id),
                "from": previous,
                "to": payload.quantity,
            },
        )
    return await _build_cart(db, session_id)


@router.delete("/{session_id}/items/{item_id}", response_model=CartOut)
async def remove_from_cart(session_id: uuid.UUID, item_id: uuid.UUID, db: AsyncDb):
    """Remove one line (all of its quantity) from the session's cart and return the updated cart.

    The line must belong to this session's cart: another session's line id is a 404, so a session id
    cannot be used to delete someone else's items. An id that is already gone is also a 404, which
    a client that double-tapped can treat as "done".
    """
    await _require_session(db, session_id)
    # Same row lock as /cart/add, so a removal and a simultaneous add are applied one at a time.
    cart = (
        await db.execute(select(Cart).where(Cart.session_id == session_id).with_for_update())
    ).scalar_one_or_none()
    removed = None
    if cart:
        removed = await db.scalar(
            delete(CartItem)
            .where(CartItem.id == item_id, CartItem.cart_id == cart.id)
            .returning(CartItem.product_id)
        )
    if removed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item is not in the cart")
    cart.updated_at = func.now()
    await db.commit()

    logger.info(
        "cart_item_removed",
        extra={"session_id": str(session_id), "item_id": str(item_id), "product_id": str(removed)},
    )
    return await _build_cart(db, session_id)


@router.get("/{session_id}", response_model=CartOut)
async def get_cart(session_id: uuid.UUID, db: AsyncDb):
    """The session's cart. A session that has not added anything yet gets an empty cart."""
    await _require_session(db, session_id)
    return await _build_cart(db, session_id)
