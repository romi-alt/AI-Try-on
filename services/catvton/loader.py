"""Loads CatVTON once, when the worker starts. Needs the GPU image (see the Dockerfile).

The weights are baked into the image at build time (`download_weights.py`), so a cold start only pays for
loading them onto the GPU, not for downloading them.
"""

import logging
import os

logger = logging.getLogger("catvton.loader")

CATVTON_DIR = os.environ.get("CATVTON_DIR", "/opt/CatVTON")  # the cloned repository
WEIGHTS_DIR = os.environ.get("CATVTON_WEIGHTS", "/models")
BASE_CKPT = os.environ.get("CATVTON_BASE", f"{WEIGHTS_DIR}/stable-diffusion-inpainting")
ATTN_CKPT = os.environ.get("CATVTON_ATTN", f"{WEIGHTS_DIR}/CatVTON")
ATTN_VERSION = os.environ.get(
    "CATVTON_ATTN_VERSION", "mix"
)  # "mix" is the checkpoint trained on all three datasets


def load():
    """Returns `(pipeline, automasker)`, both on the GPU."""
    import sys

    import torch

    sys.path.insert(0, CATVTON_DIR)  # CatVTON is a plain repository, not a package
    from model.cloth_masker import AutoMasker  # noqa: PLC0415
    from model.pipeline import CatVTONPipeline  # noqa: PLC0415

    if not torch.cuda.is_available():
        raise RuntimeError("No CUDA device: this image must run on a GPU worker")
    logger.info("loading_catvton", extra={"gpu": torch.cuda.get_device_name(0)})
    pipeline = CatVTONPipeline(
        base_ckpt=BASE_CKPT,
        attn_ckpt=ATTN_CKPT,
        attn_ckpt_version=ATTN_VERSION,
        weight_dtype=torch.bfloat16,
        use_tf32=True,
        device="cuda",
    )
    automasker = AutoMasker(
        densepose_ckpt=os.path.join(ATTN_CKPT, "DensePose"),
        schp_ckpt=os.path.join(ATTN_CKPT, "SCHP"),
        device="cuda",
    )
    logger.info("catvton_loaded")
    return pipeline, automasker
