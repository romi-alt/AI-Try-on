"""Helpers shared by the route tests."""

import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Product, ProductCategory

ADMIN_HEADERS = {"X-Admin-Key": settings.admin_api_key}


async def make_product(adb: AsyncSession, **overrides) -> Product:
    fields = {
        "name": f"Test Product {uuid.uuid4().hex[:8]}",
        "category": ProductCategory.top,
        "price_pkr": 1000,
        "sale_price_pkr": None,
        "sizes": ["S", "M"],
        "colors": [{"name": "Ivory", "hex": "#efe6d2"}],
        "stock": 10,
        "garment_image_url": "http://example.test/p.png",
        **overrides,
    }
    product = Product(**fields)
    adb.add(product)
    await adb.flush()
    return product


async def make_session(api: httpx.AsyncClient) -> str:
    r = await api.post("/sessions", json={"consent_given": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]
