"""Helpers shared by the route tests."""

import io
import uuid

import httpx
from PIL import Image
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


def make_image_bytes(
    width: int = 800,
    height: int = 1200,
    fmt: str = "JPEG",
    *,
    exif: Image.Exif | None = None,
    icc_profile: bytes | None = None,
    color: tuple[int, int, int] = (180, 120, 90),
) -> bytes:
    """A real encoded image (solid colour with a gradient so it is not trivially compressible)."""
    img = Image.new("RGB", (width, height), color)
    px = img.load()
    for x in range(0, width, 16):
        for y in range(0, height, 16):
            px[x, y] = (x % 256, y % 256, (x + y) % 256)
    out = io.BytesIO()
    params: dict = {}
    if exif is not None:
        params["exif"] = exif
    if icc_profile is not None:
        params["icc_profile"] = icc_profile
    img.save(out, format=fmt, **params)
    return out.getvalue()


def exif_with_gps(orientation: int = 1) -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraCo"  # Make
    exif[0x0110] = "Model-X"
    exif[0x0112] = orientation  # Orientation
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (31.0, 33.0, 12.0)  # latitude ref / value
    gps[3], gps[4] = "E", (74.0, 21.0, 5.0)
    return exif


async def put_capture_for(session_id: str, data: bytes | None = None) -> str:
    """Store a valid capture for the session directly (as POST /capture would) and return its key."""
    from starlette.concurrency import run_in_threadpool

    from app.core.storage import capture_key, put_capture

    key = capture_key(session_id)
    await run_in_threadpool(put_capture, key, data or make_image_bytes(fmt="WEBP"), session_id)
    return key
