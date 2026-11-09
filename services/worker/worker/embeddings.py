"""FashionCLIP image embeddings for the catalog.

`embed_products` computes a 512-d embedding for each product's garment image and stores it in
`products.embedding`,
which the API's pgvector queries (`/recommend`, `/products/{id}/similar`) rank by cosine distance. Run it
from the
command line (`python -m worker.embed_products`) or as an RQ job from the admin app.

The encoder is a small interface so tests (and other models) can stand in for FashionCLIP; the real one
imports
`torch` and `transformers` only when first used, so the try-on worker does not need them installed.
"""

import io
import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image

from worker import db, storage
from worker.config import settings

logger = logging.getLogger("worker.embeddings")

EMBEDDING_DIM = 512


class ImageEncoder(Protocol):
    def encode(self, images: list[Image.Image]) -> list[list[float]]:
        """One L2-normalised EMBEDDING_DIM vector per image."""
        ...


def prepare_image(raw: bytes) -> Image.Image:
    """Decode an image for the encoder: transparency becomes white (as in a catalog photo), then RGB."""
    img = Image.open(io.BytesIO(raw))
    img.load()
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        canvas.alpha_composite(rgba)
        return canvas.convert("RGB")
    return img.convert("RGB")


def normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm > 0 else vector


class FashionClipEncoder:
    """Hugging Face `patrickjohncyh/fashion-clip` (a CLIP ViT-B/32 fine-tuned on fashion images)."""

    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.model_name = model_name or settings.fashion_clip_model
        self._device_name = device
        self._model = None
        self._processor = None

    def _load(self):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self._torch = torch
        self.device = self._device_name or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("loading_fashion_clip", extra={"model": self.model_name, "device": self.device})
        self._processor = CLIPProcessor.from_pretrained(self.model_name)
        self._model = CLIPModel.from_pretrained(self.model_name).to(self.device).eval()

    def encode(self, images: list[Image.Image]) -> list[list[float]]:
        if self._model is None:
            self._load()
        torch = self._torch
        inputs = self._processor(images=images, return_tensors="pt").to(self.device)
        with torch.no_grad():
            # The vision tower plus CLIP's visual projection, which is what `get_image_features` computes.
            # Calling
            # the two parts directly avoids depending on its return type (a tensor in transformers 4, an
            # output
            # object in 5).
            pooled = self._model.vision_model(pixel_values=inputs["pixel_values"]).pooler_output
            features = self._model.visual_projection(pooled)
            features = features / features.norm(dim=-1, keepdim=True)
        vectors = features.cpu().tolist()
        if any(len(v) != EMBEDDING_DIM for v in vectors):
            raise ValueError(
                f"{self.model_name} gives {len(vectors[0])}-d embeddings, expected {EMBEDDING_DIM}"
            )
        return vectors


@dataclass
class EmbedReport:
    updated: list[uuid.UUID] = field(default_factory=list)
    failed: dict[uuid.UUID, str] = field(default_factory=dict)  # product id -> why

    def __str__(self) -> str:
        return f"{len(self.updated)} embedded, {len(self.failed)} failed"


def embed_products(
    product_ids: list[uuid.UUID] | None = None,
    *,
    only_missing: bool = False,
    encoder: ImageEncoder | None = None,
    batch_size: int | None = None,
    load_image: Callable[[str], bytes] = storage.load_image_from_url,
    progress: Callable[[int, int], None] | None = None,
) -> EmbedReport:
    """Embed `product_ids` (every product when None) and store the vectors.

    One product that cannot be loaded or decoded is recorded in the report and skipped; it never stops the
    rest.
    A batch that fails to encode is retried one image at a time, so a single bad image cannot cost its
    neighbours.
    """
    encoder = encoder or FashionClipEncoder()
    size = batch_size or settings.embedding_batch_size
    rows = db.list_product_images(product_ids, only_missing=only_missing)
    report = EmbedReport()

    pending: list[tuple[uuid.UUID, Image.Image]] = []

    def store(pid: uuid.UUID, vector: list[float]) -> None:
        if len(vector) != EMBEDDING_DIM:
            report.failed[pid] = f"the encoder returned {len(vector)} values, expected {EMBEDDING_DIM}"
        elif not db.set_embedding(pid, normalise(vector)):
            report.failed[pid] = "the product no longer exists"
        else:
            report.updated.append(pid)

    def flush() -> None:
        if not pending:
            return
        batch = list(pending)
        pending.clear()
        try:
            vectors = encoder.encode([img for _, img in batch])
            for (pid, _), vec in zip(batch, vectors, strict=True):
                store(pid, vec)
        except Exception:
            logger.warning("batch_encode_failed_retrying_singly", exc_info=True)
            for pid, img in batch:
                try:
                    store(pid, encoder.encode([img])[0])
                except Exception as e:
                    report.failed[pid] = f"could not be encoded: {e}"

    for done, row in enumerate(rows, start=1):
        try:
            pending.append((row.id, prepare_image(load_image(row.garment_image_url))))
        except Exception as e:  # unreachable URL, missing object, not an image
            logger.warning("product_image_unusable", extra={"product_id": str(row.id)}, exc_info=True)
            report.failed[row.id] = f"image could not be loaded: {e}"
        if len(pending) >= size:
            flush()
        if progress:
            progress(done, len(rows))
    flush()
    logger.info("embeddings_done", extra={"updated": len(report.updated), "failed": len(report.failed)})
    return report


__all__ = [
    "EMBEDDING_DIM",
    "EmbedReport",
    "FashionClipEncoder",
    "ImageEncoder",
    "embed_products",
    "prepare_image",
]
