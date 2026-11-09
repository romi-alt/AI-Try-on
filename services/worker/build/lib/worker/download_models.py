"""Download the model weights the assets worker uses, so the first job does not have to.

    python -m worker.download_models            # FashionCLIP, the rembg model and SAM 2 (tiny)
    python -m worker.download_models --only sam2

Weights go to MODELS_DIR (default ~/.cache/tryon-models) except FashionCLIP, which uses the Hugging Face cache
(HF_HOME). Point SAM2_CHECKPOINT at the printed path. The SAM 2 file is not checksummed here: the download
URL is
Meta's official one over HTTPS, and a truncated file fails to load rather than loading wrongly.
"""

import argparse
import os
import pathlib
import sys

import httpx

from worker.config import settings

SAM2_URL = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"
SAM2_FILE = "sam2.1_hiera_tiny.pt"


def models_dir() -> pathlib.Path:
    path = pathlib.Path(os.path.expanduser(settings.models_dir))
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_sam2() -> pathlib.Path:
    target = models_dir() / SAM2_FILE
    if target.exists() and target.stat().st_size > 0:
        return target
    tmp = target.with_suffix(".part")
    with httpx.stream("GET", SAM2_URL, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.rename(target)  # only a complete download gets the real name
    return target


def download_rembg() -> str:
    from rembg import new_session

    new_session(settings.rembg_model)  # downloads the ONNX model into U2NET_HOME on first use
    return settings.rembg_model


def download_fashion_clip() -> str:
    from transformers import CLIPModel, CLIPProcessor

    CLIPProcessor.from_pretrained(settings.fashion_clip_model)
    CLIPModel.from_pretrained(settings.fashion_clip_model)
    return settings.fashion_clip_model


STEPS = {"sam2": download_sam2, "rembg": download_rembg, "fashion-clip": download_fashion_clip}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--only", choices=sorted(STEPS), action="append", help="download just these")
    args = parser.parse_args(argv)
    for name in args.only or list(STEPS):
        print(f"{name}: {STEPS[name]()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
