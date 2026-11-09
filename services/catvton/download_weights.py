"""Downloads CatVTON's weights into the image at build time: `python download_weights.py /models`."""

import sys

from huggingface_hub import snapshot_download

target = sys.argv[1] if len(sys.argv) > 1 else "/models"
# The adapter weights, plus the DensePose and SCHP human-parsing models the AutoMasker uses.
snapshot_download(repo_id="zhengchong/CatVTON", local_dir=f"{target}/CatVTON")
# The Stable Diffusion inpainting base model CatVTON is built on.
snapshot_download(
    repo_id="booksforcharlie/stable-diffusion-inpainting",
    local_dir=f"{target}/stable-diffusion-inpainting",
)
