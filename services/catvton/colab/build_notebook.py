# ruff: noqa: E501  (the notebook text and code live in strings; their line lengths are for Colab, not for this file)
"""Writes catvton_tryon.ipynb. Run: python build_notebook.py. (The notebook is generated so its code cells can be
syntax-checked in tests; edit this file, not the .ipynb.)"""

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def md(s: str) -> None:
    cells.append((MD, s.strip("\n")))


def code(s: str) -> None:
    cells.append((CODE, s.strip("\n")))


md("""
# ELEVARIQ: free, private virtual try-on on Colab (CatVTON)

Dresses **your own photo** in garment photos, using the same CatVTON model as `services/catvton`, on Colab's free GPU.
Your photos stay inside this Colab session (nothing is sent to any try-on service; only model weights are downloaded
from Hugging Face). Delete the session when you are done and they are gone.

**Before you start:** *Runtime > Change runtime type > T4 GPU*, then run the cells top to bottom.

| Step | What | Time (T4, estimate) |
|---|---|---|
| 1 | Install libraries and build DensePose's detectron2 | 8 to 15 min, once per session |
| 2 | Download the weights (about 10 GB) | 3 to 10 min, once per session |
| 3 | Upload the photos | seconds |
| 4 | Load the model | about 1 min |
| 5 | Render the outfits | roughly 30 to 90 s per garment |

> Not verified by the author on a real Colab GPU: see "If something fails" at the bottom.

**Garment photos that work well:** one garment per image, flat-lay or on a mannequin, plain light background,
upright, the whole garment visible. CatVTON dresses tops (`upper`), bottoms (`lower`) and whole outfits (`overall`).
It does not do dupattas, shoes, bags or jewellery. A kurta with a sharara is two passes: kurta as `upper`, then sharara as `lower`.
""")

md("## 1. Install")
code("""
import os, torch
assert torch.cuda.is_available(), "No GPU: Runtime > Change runtime type > T4 GPU, then run this cell again"
major, minor = torch.cuda.get_device_capability(0)
os.environ["TORCH_CUDA_ARCH_LIST"] = f"{major}.{minor}"   # build detectron2 for this GPU only: much faster
print(torch.__version__, torch.cuda.get_device_name(0), "capability", major, minor)

!pip -q install "diffusers==0.31.0" "transformers>=4.41,<5" accelerate "huggingface-hub>=0.23" omegaconf einops fvcore pycocotools scikit-image opencv-python-headless cloudpickle ninja
!pip -q install --no-build-isolation "git+https://github.com/facebookresearch/detectron2.git"
print("installed")
""")

md("## 2. Get CatVTON and its weights")
code("""
!git clone -q https://github.com/Zheng-Chong/CatVTON.git /content/CatVTON
from huggingface_hub import snapshot_download
CKPT = snapshot_download("zhengchong/CatVTON")                       # adapter + DensePose + SCHP human parsing
BASE = snapshot_download("booksforcharlie/stable-diffusion-inpainting")  # the base model CatVTON builds on
print("weights ready:", CKPT, BASE, sep="\\n  ")
""")

md("""
## 3. Upload your photos

First the **person** photo(s) (a full-body photo works best), then the **garment** photos. They are saved in
`/content/person` and `/content/garments` and live only in this session.
""")
code("""
from google.colab import files
import os, shutil
os.makedirs("/content/person", exist_ok=True)
print("Choose the PERSON photo(s):")
for name, data in files.upload().items():
    open(f"/content/person/{name}", "wb").write(data)
print(sorted(os.listdir("/content/person")))
""")
code("""
os.makedirs("/content/garments", exist_ok=True)
print("Choose the GARMENT photos (kurtas, shararas, trousers, ...):")
for name, data in files.upload().items():
    open(f"/content/garments/{name}", "wb").write(data)
print(sorted(os.listdir("/content/garments")))
""")

md("## 4. Load the model")
code("""
import sys, torch
sys.path.insert(0, "/content/CatVTON")
from model.cloth_masker import AutoMasker
from model.pipeline import CatVTONPipeline

pipeline = CatVTONPipeline(
    base_ckpt=BASE, attn_ckpt=CKPT, attn_ckpt_version="mix",
    weight_dtype=torch.float16,   # a T4 has no fast bfloat16; the repo's RunPod image uses bfloat16 on newer GPUs
    use_tf32=True, device="cuda",
)
automasker = AutoMasker(densepose_ckpt=os.path.join(CKPT, "DensePose"), schp_ckpt=os.path.join(CKPT, "SCHP"), device="cuda")
print("model loaded; GPU memory used: %.1f GB" % (torch.cuda.memory_allocated() / 1e9))
""")

md("""
## 5. Describe the outfits and render

Edit `OUTFITS`: each look is a list of `(garment file, kind)` where kind is `"upper"` (kurta, shirt, top),
`"lower"` (sharara, trouser, skirt) or `"overall"` (a one-piece dress). Garments are put on one after another, so list
the kurta first, then the bottom.
""")
code("""
PERSON = sorted(os.listdir("/content/person"))[0]          # or set a file name: PERSON = "photo.jpg"
OUTFITS = {
    "Look 1": [("ivory_kurta.png", "upper"), ("black_sharara.png", "lower")],
    "Look 2": [("emerald_kurta.png", "upper"), ("cream_trouser.png", "lower")],
    "Look 3": [("maroon_kurta.png", "upper"), ("gold_sharara.png", "lower")],
}
STEPS, GUIDANCE, SEED = 40, 2.5, 555        # more steps = slower, slightly cleaner; keep the seed for repeatable results
print("garments available:", sorted(os.listdir("/content/garments")))
""")
code('''
import time
from PIL import Image, ImageOps

W, H = 768, 1024

def fit_person(img):    # cover-crop to 3:4, as the kiosk's photo is
    return ImageOps.fit(ImageOps.exif_transpose(img).convert("RGB"), (W, H), Image.LANCZOS, centering=(0.5, 0.5))

def fit_garment(img):   # pad onto white to 3:4 without cropping any of the garment
    img = ImageOps.exif_transpose(img).convert("RGB")
    s = min(W / img.width, H / img.height)
    r = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    canvas.paste(r, ((W - r.width) // 2, (H - r.height) // 2))
    return canvas

def dress(person, garments):
    """garments: [(path, 'upper'|'lower'|'overall')]. One pass per garment; each result is the next pass's person."""
    cur = person
    for path, kind in garments:
        assert kind in ("upper", "lower", "overall"), f"unknown kind {kind!r} for {path}"
        cloth = fit_garment(Image.open(f"/content/garments/{path}"))
        mask = automasker(cur, kind)["mask"]
        t = time.time()
        cur = pipeline(image=cur, condition_image=cloth, mask=mask, num_inference_steps=STEPS, guidance_scale=GUIDANCE,
                       height=H, width=W, generator=torch.Generator(device="cuda").manual_seed(SEED))[0].convert("RGB")
        print(f"   {kind:8s} {path}: {time.time() - t:.0f}s")
    return cur

os.makedirs("/content/results", exist_ok=True)
base = fit_person(Image.open(f"/content/person/{PERSON}"))
base.save("/content/results/00_original.jpg", quality=95)
for i, (name, garments) in enumerate(OUTFITS.items(), 1):
    print(name)
    out = dress(base, garments)
    out.save(f"/content/results/{i:02d}_{name.replace(' ', '_').lower()}.jpg", quality=95)
    sheet = Image.new("RGB", (W * 2, H), "white"); sheet.paste(base, (0, 0)); sheet.paste(out, (W, 0))
    display(sheet.resize((W, H // 2)))
    torch.cuda.empty_cache()
''')

md("## 6. Download")
code("""
shutil.make_archive("/content/tryon_results", "zip", "/content/results")
files.download("/content/tryon_results.zip")
""")

md("""
## If something fails

- **The install cell errors while building detectron2:** it compiles against Colab's current PyTorch and is the most
  fragile step. Run the cell again once; if it still fails, check *Runtime > Change runtime type* shows a GPU, and try
  *Runtime > Restart session* followed by running the install cell first.
- **`numpy` / binary-incompatibility errors after installing:** *Runtime > Restart session*, then run from step 2
  (the installs are already done).
- **Out of memory:** *Runtime > Restart session*, skip step 3's re-upload (files stay), run 4 and 5 again. Close other
  notebooks using the GPU. A free T4 should be enough at 768x1024.
- **The result looks wrong (the garment is mangled or in the wrong place):** use a cleaner garment photo (plain
  background, nothing else in the picture) and the right kind (`upper` or `lower`). Shararas and other wide, long bottoms
  are the hardest: the model was trained mostly on trousers, skirts and dresses.
- **Colab disconnects after about 90 minutes idle or 12 hours total on the free tier,** and everything is lost: download
  the zip as soon as it is made.
- Each model has its own licence (see its Hugging Face page; CatVTON's is non-commercial): fine for a demo, check
  before selling anything made with it.
""")


def build() -> dict:
    nb_cells = []
    for kind, src in cells:
        lines = src.split("\n")
        source = [ln + "\n" for ln in lines[:-1]] + [lines[-1]]
        cell = {"cell_type": kind, "metadata": {}, "source": source}
        if kind == CODE:
            cell.update(execution_count=None, outputs=[])
        nb_cells.append(cell)
    return {
        "cells": nb_cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"gpuType": "T4", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


if __name__ == "__main__":
    out = Path(__file__).with_name("catvton_tryon.ipynb")
    out.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", out)
