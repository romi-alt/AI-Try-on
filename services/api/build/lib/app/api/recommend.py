import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import AsyncDb
from app.models import Product
from app.schemas.product import SimilarProductOut
from app.schemas.recommend import LookSuggestionOut, RecommendOut
from app.services import recommend as rules

router = APIRouter(tags=["recommend"])
logger = logging.getLogger("app.recommend")

MAX_SELECTED = 5
MORE_STYLES_LIMIT = 8
CANDIDATES_PER_CATEGORY = 40


def _parse_ids(raw: str) -> list[uuid.UUID]:
    try:
        ids = [uuid.UUID(part) for part in raw.split(",") if part.strip()]
    except ValueError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "product_ids must be comma-separated UUIDs"
        ) from e
    ids = list(dict.fromkeys(ids))
    if not 1 <= len(ids) <= MAX_SELECTED:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Give 1 to {MAX_SELECTED} product ids")
    return ids


def _centroid(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(len(vectors[0]))]


@router.get("/recommend", response_model=RecommendOut)
async def recommend(
    db: AsyncDb,
    product_ids: Annotated[
        str,
        Query(max_length=250, description="Comma-separated ids of the items the shopper picked (1 to 5)"),
    ],
) -> RecommendOut:
    """Suggestions for a selection: more styles like it, and one item for each missing part of the outfit.

    - **more_styles:** for each selected item, its nearest neighbours in the same category by cosine distance
      between FashionCLIP embeddings. Items are merged by their closest distance. Products with no
      embedding yet
      are skipped, and if a selected item has none, the newest in-stock items of its category stand in.
    - **complete_your_look:** for each of top, bottom, shoes and bag that the selection does not cover (a
      dress covers
      top and bottom) the best item that passes the rules in `app.services.recommend` (in stock, a colour
      that goes
      with every selected item, a price within a sensible band), ranked by similarity to the selection.

    Items already selected and items out of stock are never suggested.
    """
    ids = _parse_ids(product_ids)
    selected = list((await db.scalars(select(Product).where(Product.id.in_(ids)))).all())
    if len(selected) != len(ids):
        found = {p.id for p in selected}
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Products not found: {', '.join(str(i) for i in ids if i not in found)}",
        )
    available = (Product.stock > 0) & Product.id.not_in(ids)

    # --- More styles -------------------------------------------------------------------------
    best: dict[uuid.UUID, SimilarProductOut] = {}
    for item in selected:
        if item.embedding is not None:
            distance = Product.embedding.cosine_distance(item.embedding)
            rows = await db.execute(
                select(Product, distance.label("distance"))
                .where(available, Product.category == item.category, Product.embedding.is_not(None))
                .order_by(distance, Product.id)
                .limit(MORE_STYLES_LIMIT)
            )
            found = [(p, float(d)) for p, d in rows.all()]
        else:
            newest = await db.scalars(
                select(Product)
                .where(available, Product.category == item.category)
                .order_by(Product.created_at.desc(), Product.id)
                .limit(MORE_STYLES_LIMIT)
            )
            found = [(p, None) for p in newest.all()]
        for product, dist in found:
            current = best.get(product.id)
            if current is None or (
                dist is not None and (current.distance is None or dist < current.distance)
            ):
                best[product.id] = SimilarProductOut.model_validate(
                    {**_product_dict(product), "distance": dist}
                )
    # Stable sort: items with a distance by distance, then the fallback items in the (newest first) order
    # found.
    more_styles = sorted(best.values(), key=lambda p: (p.distance is None, p.distance or 0.0))[
        :MORE_STYLES_LIMIT
    ]

    # --- Complete your look ------------------------------------------------------------------
    centroid = _centroid([list(p.embedding) for p in selected if p.embedding is not None])
    selected_colors = [p.colors for p in selected]
    selected_prices = [p.current_price_pkr for p in selected]
    suggestions: list[LookSuggestionOut] = []
    for category in rules.missing_categories(p.category for p in selected):
        query = select(Product).where(available, Product.category == category)
        if centroid is not None:
            distance = Product.embedding.cosine_distance(centroid)
            query = query.add_columns(distance.label("distance")).order_by(
                distance.asc().nulls_last(), Product.id
            )
        else:
            query = query.add_columns(func.cast(None, Product.price_pkr.type).label("distance")).order_by(
                Product.created_at.desc(), Product.id
            )
        rows = (await db.execute(query.limit(CANDIDATES_PER_CATEGORY))).all()

        ranked = []
        for product, dist in rows:
            match = rules.look_match(product.colors, selected_colors)
            if match is None or not rules.price_ok(product.current_price_pkr, selected_prices):
                continue
            similarity = None if dist is None else 1.0 - float(dist)
            ranked.append(
                (similarity if similarity is not None else -1.0, match[1], product, similarity, match[0])
            )
        if ranked:
            ranked.sort(key=lambda r: (-r[0], -r[1], -r[2].created_at.timestamp(), str(r[2].id)))
            _, _, product, similarity, kind = ranked[0]
            suggestions.append(
                LookSuggestionOut(
                    category=category,
                    product=product,
                    similarity=None if similarity is None else round(similarity, 4),
                    reason=rules.REASONS[kind],
                )
            )

    logger.info(
        "recommended",
        extra={"selected": len(ids), "more_styles": len(more_styles), "complete": len(suggestions)},
    )
    return RecommendOut(more_styles=more_styles, complete_your_look=suggestions)


def _product_dict(product: Product) -> dict:
    from app.schemas.product import ProductOut

    return ProductOut.model_validate(product).model_dump()
