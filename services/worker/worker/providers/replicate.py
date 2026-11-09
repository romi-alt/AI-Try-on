"""Replicate-hosted virtual try-on model (e.g. IDM-VTON or similar).

Configure REPLICATE_API_TOKEN and REPLICATE_MODEL ("owner/model:version").
Inputs are sent as data URIs so no public URL for the capture is required.
"""

import base64
import time

import httpx

from worker.config import settings
from worker.providers.base import TryOnInput, TryOnOutput, TryOnProvider

_API = "https://api.replicate.com/v1/predictions"


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


class ReplicateProvider(TryOnProvider):
    name = "replicate"

    def __init__(self) -> None:
        if not settings.replicate_api_token or not settings.replicate_model:
            raise RuntimeError(
                "REPLICATE_API_TOKEN and REPLICATE_MODEL are required for the replicate provider"
            )
        self._headers = {
            "Authorization": f"Bearer {settings.replicate_api_token}",
            "Content-Type": "application/json",
        }
        _, _, self._version = settings.replicate_model.partition(":")

    def run(self, inp: TryOnInput) -> TryOnOutput:
        payload = {
            "version": self._version,
            "input": {
                "human_img": _data_uri(inp.person_image, "image/jpeg"),
                "garm_img": _data_uri(inp.garment_image, "image/png"),
                "garment_des": inp.garment_category,
                "category": _map_category(inp.garment_category),
            },
        }
        with httpx.Client(timeout=60) as http:
            r = http.post(_API, json=payload, headers=self._headers)
            r.raise_for_status()
            pred = r.json()

            deadline = time.monotonic() + settings.job_timeout_seconds
            while pred["status"] not in ("succeeded", "failed", "canceled"):
                if time.monotonic() > deadline:
                    raise TimeoutError("Replicate prediction timed out")
                time.sleep(2)
                pred = http.get(pred["urls"]["get"], headers=self._headers).json()

            if pred["status"] != "succeeded":
                raise RuntimeError(f"Replicate prediction {pred['status']}: {pred.get('error')}")

            output = pred["output"]
            url = output[0] if isinstance(output, list) else output
            img = http.get(url)
            img.raise_for_status()
            return TryOnOutput(image=img.content, content_type=img.headers.get("content-type", "image/jpeg"))


def _map_category(cat: str) -> str:
    return {"top": "upper_body", "outerwear": "upper_body", "bottom": "lower_body", "dress": "dresses"}.get(
        cat, "upper_body"
    )
