"""Creates or updates the RunPod serverless endpoint for the CatVTON image, scaled to zero when idle.

    export RUNPOD_API_KEY=...            # a RunPod API key with read/write access; never commit it
    python deploy.py --image registry.example.com/elevariq-catvton:1 --dry-run     # show what would be sent
    python deploy.py --image registry.example.com/elevariq-catvton:1               # do it

It looks up the template and endpoint by name first and updates them if they exist, so running it again after
pushing a new image tag rolls the endpoint forward instead of creating a second one. Scale to zero is
`workersMin = 0` (the default here): no GPU is billed while nobody is using the mirror, and the first shopper
after a quiet spell waits for a cold start (see `worker/benchmark.py` for how long that is on your endpoint).

It talks to RunPod's REST API (https://rest.runpod.io/v1). Field names follow RunPod's published API reference
at the time of writing; the script prints the exact request bodies in `--dry-run` so you can compare them
with the current reference before running it for real. It prints the endpoint id to put in RUNPOD_ENDPOINT_ID.
"""

import argparse
import json
import os
import sys

import httpx

BASE_URL = "https://rest.runpod.io/v1"
# GPUs with enough memory for CatVTON at 768x1024 (about 8 GB of weights + activations; 24 GB is comfortable).
DEFAULT_GPUS = ["NVIDIA GeForce RTX 4090", "NVIDIA RTX A5000", "NVIDIA L4"]


def template_body(args) -> dict:
    return {
        "name": f"{args.name}-template",
        "imageName": args.image,
        "isServerless": True,
        "containerDiskInGb": args.disk_gb,
        "env": {"PYTHONUNBUFFERED": "1"},
    }


def endpoint_body(args, template_id: str) -> dict:
    return {
        "name": args.name,
        "templateId": template_id,
        "computeType": "GPU",
        "gpuTypeIds": args.gpu,
        "gpuCount": 1,
        "workersMin": args.workers_min,  # 0 = scale to zero
        "workersMax": args.workers_max,
        "idleTimeout": args.idle_timeout,  # seconds a worker stays up after its last job
        "executionTimeoutMs": args.execution_timeout * 1000,
        "scalerType": "QUEUE_DELAY",
        "scalerValue": args.scale_seconds,  # start another worker when a job has waited this long
        "flashboot": True,  # snapshot-based fast cold starts
    }


class RunPodApi:
    def __init__(self, api_key: str, client: httpx.Client | None = None, base_url: str = BASE_URL):
        if not base_url.startswith("https://"):
            raise ValueError("RunPod's API must be called over https")
        self._http = client or httpx.Client(timeout=30)
        self._base = base_url
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, body: dict | None = None):
        resp = self._http.request(method, f"{self._base}{path}", headers=self._headers, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"RunPod {method} {path} failed: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json() if resp.content else None

    def find(self, kind: str, name: str) -> dict | None:
        items = self._call("GET", f"/{kind}")
        return next((i for i in items or [] if i.get("name") == name), None)

    def upsert_template(self, body: dict) -> dict:
        existing = self.find("templates", body["name"])
        if existing:
            return self._call("POST", f"/templates/{existing['id']}/update", body) or existing
        return self._call("POST", "/templates", body)

    def upsert_endpoint(self, body: dict) -> dict:
        existing = self.find("endpoints", body["name"])
        if existing:
            return self._call("PATCH", f"/endpoints/{existing['id']}", body) or existing
        return self._call("POST", "/endpoints", body)


def deploy(args, api: RunPodApi | None) -> dict:
    """Returns what was (or, with no `api`, would be) sent."""
    t_body = template_body(args)
    if api is None:
        return {"template": t_body, "endpoint": endpoint_body(args, "<template id>")}
    template = api.upsert_template(t_body)
    e_body = endpoint_body(args, template["id"])
    endpoint = api.upsert_endpoint(e_body)
    return {"template": t_body, "endpoint": e_body, "endpoint_id": endpoint["id"]}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--image", required=True, help="the pushed image, including its tag")
    p.add_argument("--name", default="elevariq-catvton")
    p.add_argument("--gpu", action="append", help="a RunPod GPU type id; repeat for fallbacks")
    p.add_argument("--workers-min", type=int, default=0, help="0 scales to zero (default)")
    p.add_argument("--workers-max", type=int, default=2)
    p.add_argument(
        "--idle-timeout",
        type=int,
        default=30,
        help="seconds a worker stays up after its last job",
    )
    p.add_argument(
        "--execution-timeout",
        type=int,
        default=180,
        help="seconds before a running job is stopped",
    )
    p.add_argument("--scale-seconds", type=int, default=4)
    p.add_argument("--disk-gb", type=int, default=40)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    args.gpu = args.gpu or DEFAULT_GPUS
    if args.workers_max < max(1, args.workers_min):
        p.error("--workers-max must be at least 1 and at least --workers-min")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.dry_run:
        print(json.dumps(deploy(args, None), indent=2))
        return 0
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        sys.exit("Set RUNPOD_API_KEY (or use --dry-run)")
    result = deploy(args, RunPodApi(key))
    print(json.dumps({k: v for k, v in result.items() if k != "template"}, indent=2))
    print("\nPut this in the worker's environment:")
    print("  TRYON_PROVIDER=catvton")
    print(f"  RUNPOD_ENDPOINT_ID={result['endpoint_id']}")
    print("  RUNPOD_API_KEY=<a key allowed to run this endpoint; set it as a secret, not in a file>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
