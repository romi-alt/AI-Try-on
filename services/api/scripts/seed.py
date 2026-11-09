"""Seed 20 demo products with generated placeholder images.

Each product gets a flat-colour silhouette PNG (transparent background) and a
matching binary mask (white garment on black), uploaded to the bucket.

    python -m scripts.seed              # DB rows + images uploaded to MinIO/R2
    python -m scripts.seed --no-upload  # DB rows only (URLs still point at the bucket paths)

Idempotent: products are matched by name and skipped if they already exist.
Embeddings are deterministic placeholders, not real image features.
"""

import argparse
import io
import logging
import random
import re
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.storage import public_url, put_bytes
from app.models import Product, ProductCategory
from app.models.product import EMBEDDING_DIM

log = logging.getLogger("seed")

W, H = 600, 800

CLOTHING_SIZES = ["XS", "S", "M", "L", "XL"]
SHOE_SIZES = ["36", "37", "38", "39", "40", "41"]
ONE_SIZE = ["One Size"]
SIZES = {
    ProductCategory.top: CLOTHING_SIZES,
    ProductCategory.bottom: CLOTHING_SIZES,
    ProductCategory.dress: CLOTHING_SIZES,
    ProductCategory.shoes: SHOE_SIZES,
    ProductCategory.bag: ONE_SIZE,
    ProductCategory.accessory: ONE_SIZE,
}

IVORY = ("Ivory", "#efe6d2")
BLACK = ("Black", "#1f1f24")
SAND = ("Sand", "#cdb892")
OLIVE = ("Olive", "#5b6b4a")
NAVY = ("Navy", "#26324d")
MAROON = ("Maroon", "#7a2631")
TEAL = ("Teal", "#2f6f73")
BLUSH = ("Blush", "#e3b7b0")
INDIGO = ("Indigo", "#3f5a7a")
CAMEL = ("Camel", "#b07a45")
SKY = ("Sky", "#a9c4dc")
WHITE = ("White", "#f4f4f2")

C = ProductCategory


@dataclass(frozen=True)
class Spec:
    name: str
    category: ProductCategory
    price_pkr: int
    sale_price_pkr: int | None
    colors: tuple[tuple[str, str], ...]
    stock: int


CATALOG: list[Spec] = [
    # tops
    Spec("Embroidered Lawn Kurta", C.top, 5490, 4390, (IVORY, BLUSH, TEAL), 24),
    Spec("Cotton Crew Tee", C.top, 1990, None, (WHITE, BLACK, OLIVE), 60),
    Spec("Linen Camp Shirt", C.top, 3990, None, (SAND, SKY), 31),
    Spec("Chiffon Peplum Top", C.top, 3290, 2630, (MAROON, NAVY), 18),
    # bottoms
    Spec("Straight Fit Denim", C.bottom, 4990, None, (INDIGO, BLACK), 40),
    Spec("Wide-Leg Trouser", C.bottom, 4290, 3430, (BLACK, SAND), 22),
    Spec("Cambric Shalwar", C.bottom, 2490, None, (IVORY, TEAL), 35),
    # dresses
    Spec("Slip Midi Dress", C.dress, 7990, 5990, (MAROON, BLACK), 12),
    Spec("Printed Maxi Dress", C.dress, 6490, None, (TEAL, BLUSH), 16),
    Spec("Shirt Dress", C.dress, 5290, None, (SKY, SAND), 20),
    # shoes
    Spec("White Leather Sneakers", C.shoes, 8990, 7190, (WHITE,), 28),
    Spec("Kolhapuri Flats", C.shoes, 3490, None, (CAMEL, BLACK), 45),
    Spec("Block Heel Sandals", C.shoes, 5990, None, (BLACK, SAND), 14),
    # bags
    Spec("Structured Tote", C.bag, 7490, None, (CAMEL, BLACK), 10),
    Spec("Crossbody Bag", C.bag, 5290, 3990, (OLIVE, BLACK), 19),
    Spec("Mini Clutch", C.bag, 2990, None, (MAROON, IVORY), 25),
    # accessories
    Spec("Silk Scarf", C.accessory, 2490, None, (BLUSH, NAVY), 50),
    Spec("Wool Shawl", C.accessory, 6990, 5590, (CAMEL, MAROON), 17),
    Spec("Leather Belt", C.accessory, 1990, None, (BLACK, CAMEL), 38),
    Spec("Aviator Sunglasses", C.accessory, 3490, None, (BLACK,), 0),
]


# --- placeholder art ------------------------------------------------------------------------
# Each shape function draws one silhouette. `fill` paints the garment, `clear` punches holes
# (necklines, handle gaps). The same function renders the colour image and the binary mask.

Shape = Callable[[ImageDraw.ImageDraw, object, object], None]


def _top(d, fill, clear):
    d.rounded_rectangle((150, 180, 450, 700), radius=60, fill=fill)
    d.rounded_rectangle((60, 190, 170, 450), radius=40, fill=fill)
    d.rounded_rectangle((430, 190, 540, 450), radius=40, fill=fill)
    d.ellipse((240, 140, 360, 230), fill=clear)


def _bottom(d, fill, clear):
    d.rectangle((160, 120, 440, 190), fill=fill)
    d.polygon([(160, 180), (305, 180), (290, 740), (190, 740)], fill=fill)
    d.polygon([(295, 180), (440, 180), (410, 740), (310, 740)], fill=fill)


def _dress(d, fill, clear):
    d.rounded_rectangle((200, 130, 400, 420), radius=40, fill=fill)
    d.polygon([(200, 400), (400, 400), (520, 740), (80, 740)], fill=fill)
    d.ellipse((255, 95, 345, 175), fill=clear)


def _shoes(d, fill, clear):
    for x in (60, 330):
        d.rounded_rectangle((x, 560, x + 210, 620), radius=25, fill=fill)
        d.ellipse((x, 440, x + 210, 600), fill=fill)
        d.rectangle((x + 100, 400, x + 205, 500), fill=fill)


def _bag(d, fill, clear):
    d.arc((190, 120, 410, 400), start=180, end=360, fill=fill, width=26)
    d.rounded_rectangle((110, 300, 490, 680), radius=50, fill=fill)


def _accessory(d, fill, clear):
    d.rounded_rectangle((90, 230, 510, 400), radius=80, fill=fill)
    d.polygon([(170, 380), (270, 380), (240, 700), (150, 680)], fill=fill)
    d.polygon([(330, 380), (430, 380), (450, 700), (360, 720)], fill=fill)


SHAPES: dict[ProductCategory, Shape] = {
    C.top: _top,
    C.bottom: _bottom,
    C.dress: _dress,
    C.shoes: _shoes,
    C.bag: _bag,
    C.accessory: _accessory,
}


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def render_image(category: ProductCategory, hex_color: str, label: str) -> bytes:
    """Transparent-background RGBA PNG silhouette."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    SHAPES[category](d, (*_hex_rgb(hex_color), 255), (0, 0, 0, 0))
    d.text((24, H - 28), label, fill=(255, 255, 255, 230))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_mask(category: ProductCategory) -> bytes:
    """Binary mask: white where the garment is, black elsewhere. 8-bit greyscale PNG."""
    img = Image.new("L", (W, H), 0)
    SHAPES[category](ImageDraw.Draw(img), 255, 0)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _placeholder_embedding(seed: str) -> list[float]:
    """Deterministic unit vector so similarity queries work before a real encoder exists."""
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


def run(upload: bool = True) -> None:
    db = SessionLocal()
    created = skipped = 0
    try:
        for spec in CATALOG:
            if db.scalar(select(Product.id).where(Product.name == spec.name)):
                skipped += 1
                log.info("skip %s (exists)", spec.name)
                continue

            slug = _slug(spec.name)
            image_key = f"products/seed/{slug}.png"
            mask_key = f"products/seed/{slug}-mask.png"
            if upload:
                primary_hex = spec.colors[0][1]
                put_bytes(image_key, render_image(spec.category, primary_hex, spec.name), "image/png")
                put_bytes(mask_key, render_mask(spec.category), "image/png")

            db.add(
                Product(
                    name=spec.name,
                    category=spec.category,
                    price_pkr=spec.price_pkr,
                    sale_price_pkr=spec.sale_price_pkr,
                    sizes=SIZES[spec.category],
                    colors=[{"name": n, "hex": h} for n, h in spec.colors],
                    stock=spec.stock,
                    garment_image_url=public_url(image_key),
                    garment_mask_url=public_url(mask_key),
                    embedding=_placeholder_embedding(spec.name),
                )
            )
            created += 1
            log.info("seeded %s", spec.name)
        db.commit()
    finally:
        db.close()
    log.info("done: %d created, %d already present", created, skipped)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-upload", action="store_true", help="skip image generation/upload")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(upload=not args.no_upload)
