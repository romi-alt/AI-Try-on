import io
import uuid

from PIL import Image
from sqlalchemy import insert

from worker import db, storage
from worker.config import settings


def webp_bytes(width=800, height=1200, color=(120, 140, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="WEBP")
    return out.getvalue()


def garment_png(color=(200, 30, 60)) -> bytes:
    img = Image.new("RGBA", (300, 400), (0, 0, 0, 0))
    Image.Image.paste(img, Image.new("RGBA", (200, 300), (*color, 255)), (50, 50))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def add_product(
    name="Test Tee", category="top", image: bytes | None = None, *, external_url: str | None = None
):
    pid = uuid.uuid4()
    key = f"products/{pid}.png"
    if external_url is None:
        storage.put_bytes(key, image or garment_png(), "image/png")
        url = f"{settings.s3_public_base_url}/{key}"
    else:
        url = external_url
    with db.engine.begin() as conn:
        conn.execute(insert(db.products).values(id=pid, name=name, category=category, garment_image_url=url))
    return pid


def add_capture(session_id, data: bytes | None = None) -> str:
    key = f"captures/{session_id}/{uuid.uuid4()}.webp"
    storage.put_bytes(key, data or webp_bytes(), "image/webp")
    return key


def add_job(session_id, product_ids, capture_key, status="queued") -> uuid.UUID:
    jid = uuid.uuid4()
    with db.engine.begin() as conn:
        conn.execute(
            insert(db.tryon_jobs).values(
                id=jid,
                session_id=session_id,
                product_ids=list(product_ids),
                status=status,
                progress=0,
                person_image_key=capture_key,
            )
        )
    return jid


def job_row(jid):
    with db.engine.connect() as conn:
        return conn.execute(db.tryon_jobs.select().where(db.tryon_jobs.c.id == jid)).one()
