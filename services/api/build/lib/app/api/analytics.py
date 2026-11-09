"""Admin analytics: which products get tried on, how often that leads to the cart, and which suggested
pairings work.

Definitions (so the numbers can be argued with):

- A *try-on* is a finished look (`tryon_jobs.status = 'done'`) created in the period. A look with two
  products counts once for each product.
- A product was *added to the cart* after a look when the same session has it in its cart (added at or after
  the look was made) or has an order for it placed at or after the look. Orders count because checkout empties
  the cart, and a purchase must not make the conversion disappear. A shopper who removes the item again still
  counts: the signal is the intent.
- The *try-on to cart rate* is per look: the share of looks after which at least one of its items was added.
- A *pairing* is a product in the look (the base) with a suggestion the shopper added to it from "More
  styles" / "Complete your look" (`recommended_product_ids`), counted per look.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.api.deps import AsyncDb
from app.core.auth import require_admin
from app.schemas.admin import AnalyticsOut, PairingStats, ProductTryOnStats

router = APIRouter(prefix="/admin/analytics", tags=["admin"], dependencies=[Depends(require_admin)])

# Filled in with the session, product and look-time columns of each query; Postgres does the counting.
_CARTED = """(
    EXISTS (SELECT 1 FROM cart_items ci JOIN carts c ON c.id = ci.cart_id
            WHERE c.session_id = {s} AND ci.product_id = {p} AND ci.created_at >= {t})
    OR EXISTS (SELECT 1 FROM order_items oi JOIN orders o ON o.id = oi.order_id
               WHERE o.session_id = {s} AND oi.product_id = {p} AND o.created_at >= {t})
)"""

_TOTALS = text(
    f"""
    SELECT count(*) AS tryons,
           count(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM unnest(j.product_ids) AS pid
               WHERE {_CARTED.format(s="j.session_id", p="pid", t="j.created_at")}
           )) AS with_cart
    FROM tryon_jobs j
    WHERE j.status = 'done' AND j.created_at >= :since
    """
)

_PRODUCT_CARTED = _CARTED.format(s="x.session_id", p="x.product_id", t="x.created_at")
_PAIRING_CARTED = _CARTED.format(s="x.session_id", p="x.rec", t="x.created_at")

_PRODUCTS = text(
    f"""
    SELECT x.product_id, coalesce(pr.name, 'Deleted product') AS name, pr.category::text AS category,
           count(*) AS tryons,
           count(*) FILTER (WHERE {_PRODUCT_CARTED}) AS carted
    FROM (
        SELECT j.session_id, j.created_at, unnest(j.product_ids) AS product_id
        FROM tryon_jobs j WHERE j.status = 'done' AND j.created_at >= :since
    ) x
    LEFT JOIN products pr ON pr.id = x.product_id
    GROUP BY x.product_id, pr.name, pr.category
    ORDER BY tryons DESC, carted DESC, name, x.product_id
    LIMIT :limit
    """
)

_PAIRINGS = text(
    f"""
    SELECT x.base AS base_id, coalesce(pb.name, 'Deleted product') AS base_name,
           x.rec AS rec_id, coalesce(pr.name, 'Deleted product') AS rec_name,
           count(*) AS tryons,
           count(*) FILTER (WHERE {_PAIRING_CARTED}) AS carted
    FROM (
        SELECT j.session_id, j.created_at, b AS base, r AS rec
        FROM tryon_jobs j
        CROSS JOIN LATERAL unnest(j.recommended_product_ids) AS r
        CROSS JOIN LATERAL unnest(j.product_ids) AS b
        WHERE j.status = 'done' AND j.created_at >= :since AND b <> ALL (j.recommended_product_ids)
    ) x
    LEFT JOIN products pb ON pb.id = x.base
    LEFT JOIN products pr ON pr.id = x.rec
    GROUP BY x.base, pb.name, x.rec, pr.name
    ORDER BY carted DESC, tryons DESC, base_name, rec_name
    LIMIT :limit
    """
)


@router.get("", response_model=AnalyticsOut)
async def analytics(
    db: AsyncDb,
    days: int = Query(default=30, ge=1, le=365, description="Look back this many days"),
    limit: int = Query(default=10, ge=1, le=100, description="Rows in each ranking"),
) -> AnalyticsOut:
    since = datetime.now(UTC) - timedelta(days=days)
    params = {"since": since}
    totals = (await db.execute(_TOTALS, params)).one()
    products = (await db.execute(_PRODUCTS, {**params, "limit": limit})).all()
    pairings = (await db.execute(_PAIRINGS, {**params, "limit": limit})).all()
    return AnalyticsOut(
        days=days,
        since=since,
        tryons=totals.tryons,
        tryons_with_cart=totals.with_cart,
        cart_rate=round(totals.with_cart / totals.tryons, 4) if totals.tryons else None,
        products=[
            ProductTryOnStats(
                product_id=r.product_id,
                name=r.name,
                category=r.category,
                tryons=r.tryons,
                added_to_cart=r.carted,
                cart_rate=round(r.carted / r.tryons, 4),
            )
            for r in products
        ],
        pairings=[
            PairingStats(
                base_product_id=r.base_id,
                base_name=r.base_name,
                recommended_product_id=r.rec_id,
                recommended_name=r.rec_name,
                tryons=r.tryons,
                added_to_cart=r.carted,
            )
            for r in pairings
        ],
    )
