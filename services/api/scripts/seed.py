"""Seed demo garments into Postgres and generated placeholder images into the bucket.

Run via `make seed` (inside the api container) or `python -m scripts.seed` natively.
Idempotent: existing SKUs are skipped.
"""

import io
import logging
import random

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.storage import put_bytes
from app.models import Garment, GarmentCategory
from app.models.garment import EMBEDDING_DIM

log = logging.getLogger("seed")

DEMO_GARMENTS = [
    {
        "sku": "TOP-001",
        "name": "Linen Camp Shirt",
        "brand": "Atelier Nord",
        "category": "top",
        "color": "#e8dcc4",
        "price_cents": 8900,
    },
    {
        "sku": "TOP-002",
        "name": "Boxy Crew Tee",
        "brand": "Atelier Nord",
        "category": "top",
        "color": "#1f1f24",
        "price_cents": 4500,
    },
    {
        "sku": "TOP-003",
        "name": "Ribbed Knit Polo",
        "brand": "Marrow",
        "category": "top",
        "color": "#4b5d4a",
        "price_cents": 11500,
    },
    {
        "sku": "OUT-001",
        "name": "Oversized Wool Blazer",
        "brand": "Marrow",
        "category": "outerwear",
        "color": "#3a3a40",
        "price_cents": 29500,
    },
    {
        "sku": "OUT-002",
        "name": "Quilted Liner Jacket",
        "brand": "Fieldline",
        "category": "outerwear",
        "color": "#6b4f2a",
        "price_cents": 21000,
    },
    {
        "sku": "DRS-001",
        "name": "Slip Midi Dress",
        "brand": "Atelier Nord",
        "category": "dress",
        "color": "#8c2f39",
        "price_cents": 16500,
    },
    {
        "sku": "DRS-002",
        "name": "Shirt Dress",
        "brand": "Fieldline",
        "category": "dress",
        "color": "#c9d3dd",
        "price_cents": 14000,
    },
    {
        "sku": "BTM-001",
        "name": "Wide-Leg Trouser",
        "brand": "Marrow",
        "category": "bottom",
        "color": "#2b2b30",
        "price_cents": 13500,
    },
    {
        "sku": "BTM-002",
        "name": "Straight Denim",
        "brand": "Fieldline",
        "category": "bottom",
        "color": "#3f5a7a",
        "price_cents": 12000,
    },
    {
        "sku": "ACC-001",
        "name": "Silk Scarf",
        "brand": "Atelier Nord",
        "category": "accessory",
        "color": "#d7c8a8",
        "price_cents": 6500,
    },
]


def _placeholder_png(label: str, color_hex: str) -> bytes:
    """Flat-colour garment silhouette so the kiosk has something to render in dev."""
    w, h = 600, 800
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgb = tuple(int(color_hex.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    # torso
    d.rounded_rectangle((150, 180, 450, 700), radius=60, fill=(*rgb, 255))
    # sleeves
    d.rounded_rectangle((60, 190, 170, 450), radius=40, fill=(*rgb, 255))
    d.rounded_rectangle((430, 190, 540, 450), radius=40, fill=(*rgb, 255))
    # neckline
    d.ellipse((240, 140, 360, 230), fill=(0, 0, 0, 0))
    d.text((170, 720), label, fill=(255, 255, 255, 220))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fake_embedding(seed: str) -> list[float]:
    """Deterministic pseudo-embedding so similarity queries work before a real encoder is wired in."""
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


def run() -> None:
    db = SessionLocal()
    created = 0
    try:
        for spec in DEMO_GARMENTS:
            if db.scalar(select(Garment).where(Garment.sku == spec["sku"])):
                log.info("skip %s (exists)", spec["sku"])
                continue
            key = f"garment/seed/{spec['sku'].lower()}.png"
            put_bytes(key, _placeholder_png(spec["name"], spec["color"]), "image/png")
            db.add(
                Garment(
                    sku=spec["sku"],
                    name=spec["name"],
                    brand=spec["brand"],
                    category=GarmentCategory(spec["category"]),
                    color=spec["color"],
                    price_cents=spec["price_cents"],
                    image_key=key,
                    is_active=True,
                    embedding=_fake_embedding(spec["sku"]),
                )
            )
            created += 1
            log.info("seeded %s", spec["sku"])
        db.commit()
    finally:
        db.close()
    log.info("done: %d garments created", created)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run()
