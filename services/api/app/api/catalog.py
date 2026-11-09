import math
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import AsyncDb
from app.models import Product, ProductCategory
from app.schemas.catalog import CatalogPage

router = APIRouter(tags=["catalog"])


@router.get("/catalog", response_model=CatalogPage)
async def catalog(
    db: AsyncDb,
    category: Annotated[
        list[ProductCategory] | None,
        Query(description="Repeat to allow several, e.g. category=top&category=dress"),
    ] = None,
    min_discount_pct: Annotated[
        int | None, Query(ge=1, le=100, description="Only items marked down by at least this percentage")
    ] = None,
    new_within_days: Annotated[
        int | None, Query(ge=1, le=365, description="Only items added in the last N days")
    ] = None,
    on_sale: Annotated[
        bool | None, Query(description="true: only discounted; false: only full price")
    ] = None,
    search: Annotated[str | None, Query(max_length=100, description="Case-insensitive name match")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CatalogPage:
    conditions = []
    if category:
        conditions.append(Product.category.in_(category))
    if min_discount_pct is not None:
        # sale <= price * (100 - pct) / 100, in integers so there is no rounding: 50% off means sale*100 <=
        # price*50.
        conditions.append(
            Product.sale_price_pkr.is_not(None)
            & (Product.sale_price_pkr * 100 <= Product.price_pkr * (100 - min_discount_pct))
        )
    if new_within_days is not None:
        conditions.append(Product.created_at >= func.now() - timedelta(days=new_within_days))
    if on_sale is not None:
        discounted = Product.sale_price_pkr.is_not(None) & (Product.sale_price_pkr < Product.price_pkr)
        conditions.append(discounted if on_sale else ~discounted)
    if search and (term := search.strip()):
        # autoescape: a literal "%" or "_" in the query must not act as a LIKE wildcard.
        conditions.append(Product.name.icontains(term, autoescape=True))

    total = await db.scalar(select(func.count()).select_from(Product).where(*conditions)) or 0
    rows = await db.scalars(
        select(Product)
        .where(*conditions)
        # Deterministic tie-breakers keep pagination stable across pages.
        .order_by(Product.created_at.desc(), Product.name, Product.id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return CatalogPage(
        items=[p for p in rows.all()],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size),
    )
