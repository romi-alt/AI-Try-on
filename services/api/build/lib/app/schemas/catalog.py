from pydantic import BaseModel

from app.schemas.product import ProductOut


class CatalogPage(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int
    pages: int
