"""Builds a RunPod `test_input.json` from real images, to smoke-test the container on a GPU machine.

    python make_test_input.py person.jpg top.png [bottom.png ...] > test_input.json
    docker run --rm --gpus all -v $PWD/test_input.json:/app/test_input.json <image>  # one job, then exits

Garment categories default to top, bottom, dress in that order; pass CATEGORIES=top,bottom to choose.
"""

import base64
import json
import os
import sys

paths = sys.argv[1:]
if len(paths) < 2:
    sys.exit(__doc__)
categories = os.environ.get("CATEGORIES", "top,bottom,dress").split(",")


def b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


print(
    json.dumps(
        {
            "input": {
                "person_image": b64(paths[0]),
                "garments": [{"category": categories[i], "image": b64(p)} for i, p in enumerate(paths[1:])],
                "steps": 30,
                "guidance_scale": 2.5,
                "seed": 555,
            }
        }
    )
)
