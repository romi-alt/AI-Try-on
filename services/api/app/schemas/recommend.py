from pydantic import BaseModel

from app.models.product import ProductCategory
from app.schemas.product import ProductOut, SimilarProductOut


class LookSuggestionOut(BaseModel):
    category: ProductCategory
    product: ProductOut
    # How close the item is to the selection in FashionCLIP space (1 is identical); None if no embeddings yet.
    similarity: float | None
    reason: str


class RecommendOut(BaseModel):
    # Nearest neighbours of the selected items within the same category.
    more_styles: list[SimilarProductOut]
    # One best match for each of top, bottom, shoes and bag that the selection does not cover.
    complete_your_look: list[LookSuggestionOut]
