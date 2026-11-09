"""Background removal and garment mask generation (rembg + SAM 2).

`process_image` turns an uploaded garment photo into
- a **cutout**: the garment on a transparent background (PNG), and
- a **mask**: white where the garment is, black elsewhere (PNG), which try-on models use to know what to
  replace.

rembg finds the garment's outline; SAM 2, prompted with that outline's bounding box, draws a cleaner edge.
SAM 2 is optional (set `SAM2_CHECKPOINT`); without it the rembg outline is the mask. SAM 2 is only allowed to
trim or fill within a few pixels of the rembg outline, and if it disagrees badly the rembg outline wins, so a
SAM 2 failure cannot turn a good cutout into a wrong one.

The models are imported lazily, so the try-on worker does not need them installed.
"""

import io
import logging
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image, ImageFilter

from worker.config import settings

logger = logging.getLogger("worker.garment")

MIN_COVERAGE = 0.01  # less of the image than this and nothing garment-like was found
SAM_TRUST = 0.5  # SAM 2's mask must keep at least this share of the rembg outline, or it is ignored
EDGE_SLACK_PX = 6  # how far SAM 2 may extend beyond the rembg outline
BOX_MARGIN = 0.02  # the box prompt is the outline's bounding box grown by this share of the image


class ProcessingError(Exception):
    """The image could not be processed; the message is fit to show an admin."""


class BackgroundRemover(Protocol):
    def alpha(self, image: Image.Image) -> np.ndarray:
        """A boolean array (height x width): True where the garment is."""
        ...


class MaskRefiner(Protocol):
    def refine(
        self, image: Image.Image, box: tuple[int, int, int, int], point: tuple[int, int]
    ) -> np.ndarray:
        """A boolean array (height x width) for the object inside `box` (x0, y0, x1, y1) containing
        `point`."""
        ...


class RembgRemover:
    def __init__(self, model: str | None = None):
        self.model = model or settings.rembg_model
        self._session = None

    def alpha(self, image: Image.Image) -> np.ndarray:
        from rembg import new_session, remove

        if self._session is None:
            logger.info("loading_rembg", extra={"model": self.model})
            self._session = new_session(self.model)
        matte = remove(image, session=self._session, only_mask=True)  # an 'L' image, 255 = foreground
        return np.asarray(matte.convert("L")) >= 128


class Sam2Refiner:
    def __init__(self, checkpoint: str | None = None, config: str | None = None, device: str | None = None):
        self.checkpoint = checkpoint or settings.sam2_checkpoint
        self.config = config or settings.sam2_config
        self._device = device
        self._predictor = None

    def _load(self):
        import torch
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        device = self._device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("loading_sam2", extra={"checkpoint": self.checkpoint, "device": device})
        self._predictor = SAM2ImagePredictor(build_sam2(self.config, self.checkpoint, device=device))

    def refine(
        self, image: Image.Image, box: tuple[int, int, int, int], point: tuple[int, int]
    ) -> np.ndarray:
        if self._predictor is None:
            self._load()
        self._predictor.set_image(np.asarray(image.convert("RGB")))
        masks, _scores, _ = self._predictor.predict(
            point_coords=np.array([point]),
            point_labels=np.array([1]),
            box=np.array(box),
            multimask_output=False,
        )
        return np.asarray(masks[0]) > 0.5


def bounding_box(mask: np.ndarray, margin: float = BOX_MARGIN) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) around the True pixels, grown by `margin` of the image size and clipped to it."""
    ys, xs = np.nonzero(mask)
    h, w = mask.shape
    mx, my = int(w * margin), int(h * margin)
    return (
        max(int(xs.min()) - mx, 0),
        max(int(ys.min()) - my, 0),
        min(int(xs.max()) + mx, w - 1),
        min(int(ys.max()) + my, h - 1),
    )


def interior_point(mask: np.ndarray) -> tuple[int, int]:
    """A pixel well inside the mask, close to its centre of mass (the centroid itself can lie outside it)."""
    eroded = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(9))) > 0
    candidates = eroded if eroded.any() else mask
    ys, xs = np.nonzero(candidates)
    cy, cx = np.nonzero(mask)[0].mean(), np.nonzero(mask)[1].mean()
    nearest = int(np.argmin((ys - cy) ** 2 + (xs - cx) ** 2))
    return int(xs[nearest]), int(ys[nearest])


def dilate(mask: np.ndarray, pixels: int) -> np.ndarray:
    size = 2 * pixels + 1
    return np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(size))) > 0


def combine(outline: np.ndarray, sam: np.ndarray | None) -> np.ndarray:
    """The final mask: SAM 2's edge where it agrees with the rembg outline, the outline where it does not."""
    if sam is None:
        return outline
    candidate = sam & dilate(outline, EDGE_SLACK_PX)
    if candidate.sum() < SAM_TRUST * outline.sum():
        logger.warning("sam2_disagrees_using_outline")
        return outline
    return candidate


@dataclass(frozen=True)
class ProcessedGarment:
    cutout_png: bytes
    mask_png: bytes
    coverage: float  # share of the image that is garment
    used_sam2: bool


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def process_image(
    raw: bytes, remover: BackgroundRemover, refiner: MaskRefiner | None = None, *, max_side: int | None = None
) -> ProcessedGarment:
    """Cut the garment out of `raw` and make its mask. Raises `ProcessingError` if there is no garment to
    find."""
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as e:
        raise ProcessingError("The image could not be read.") from e
    # Transparency in the upload is not trusted as an outline: flatten it onto white like a catalog photo.
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        canvas.alpha_composite(rgba)
        image = canvas
    image = image.convert("RGB")
    limit = max_side or settings.garment_max_side
    if max(image.size) > limit:
        image.thumbnail((limit, limit), Image.LANCZOS)

    outline = remover.alpha(image)
    coverage = float(outline.mean())
    if coverage < MIN_COVERAGE:
        raise ProcessingError(
            "No garment was found in the image. Use a photo with the garment clearly visible."
        )

    sam = None
    if refiner is not None:
        try:
            sam = refiner.refine(image, bounding_box(outline), interior_point(outline))
        except Exception:
            logger.warning("sam2_failed_using_outline", exc_info=True)
    mask = combine(outline, sam)

    mask_img = Image.fromarray((mask * 255).astype(np.uint8), "L")
    cutout = image.convert("RGBA")
    cutout.putalpha(mask_img.filter(ImageFilter.GaussianBlur(0.8)))  # a slightly soft edge, not a jagged one
    return ProcessedGarment(
        cutout_png=_png(cutout),
        mask_png=_png(mask_img),
        coverage=float(mask.mean()),
        used_sam2=sam is not None and mask is not outline,
    )
