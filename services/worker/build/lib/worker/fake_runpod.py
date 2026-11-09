"""A fake of the RunPod serverless HTTP API for the CatVTON provider, over real sockets.

For tests, local development and the benchmark's `--fake` mode: no GPU, no RunPod account, no cost. It speaks
the same three calls as RunPod (`/run`, `/status/{id}`, `/cancel/{id}`) and follows the contract of the GPU
handler in `services/catvton`, so the provider and the worker can be exercised end to end.

It simulates scale to zero: the first job after `idle_timeout` seconds of quiet waits `cold_start` seconds in
the queue, then "renders" for `render_seconds` while reporting step progress. The numbers are simulated;
nothing here says anything about the real model's speed.

    python -m worker.fake_runpod --port 8787 --cold-start 5 --render 4
    RUNPOD_BASE_URL=http://127.0.0.1:8787/v2 RUNPOD_ENDPOINT_ID=fake RUNPOD_API_KEY=anything ...
"""

import argparse
import base64
import io
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image


class FakeRunPod:
    def __init__(
        self,
        *,
        api_key: str = "fake-key",
        cold_start: float = 0.0,
        render_seconds: float = 0.5,
        idle_timeout: float = 5.0,
        fail_code: str | None = None,
        clock=time.monotonic,
    ):
        self.api_key = api_key
        self.cold_start = cold_start
        self.render_seconds = render_seconds
        self.idle_timeout = idle_timeout
        self.fail_code = fail_code
        self._clock = clock
        self._lock = threading.Lock()
        self._warm_until = -1.0
        self.jobs: dict[str, dict] = {}
        self.cancelled: list[str] = []
        self.runs: list[dict] = []

    # --- the three calls -------------------------------------------------------------------

    def run(self, body: dict) -> dict:
        now = self._clock()
        with self._lock:
            cold = now > self._warm_until
            delay = self.cold_start if cold else 0.0
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {"input": body.get("input", {}), "created": now, "delay": delay}
            self._warm_until = now + delay + self.render_seconds + self.idle_timeout
            self.runs.append(body)
        return {"id": job_id, "status": "IN_QUEUE"}

    def status(self, job_id: str) -> dict | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        if job_id in self.cancelled:
            return {"id": job_id, "status": "CANCELLED"}
        elapsed = self._clock() - job["created"]
        if elapsed < job["delay"]:
            return {"id": job_id, "status": "IN_QUEUE"}
        run_elapsed = elapsed - job["delay"]
        if run_elapsed < self.render_seconds:
            pct = int(100 * run_elapsed / max(self.render_seconds, 1e-9))
            return {"id": job_id, "status": "IN_PROGRESS", "output": {"progress": pct}}
        if self.fail_code:
            error = json.dumps({"code": self.fail_code, "message": "simulated failure"})
            return {"id": job_id, "status": "FAILED", "error": error}
        return {
            "id": job_id,
            "status": "COMPLETED",
            "delayTime": int(job["delay"] * 1000),
            "executionTime": int(self.render_seconds * 1000),
            "output": {
                "image": self._render(job["input"]),
                "content_type": "image/jpeg",
                "width": 768,
                "height": 1024,
            },
        }

    def cancel(self, job_id: str) -> dict:
        self.cancelled.append(job_id)
        return {"id": job_id, "status": "CANCELLED"}

    @staticmethod
    def _render(payload: dict) -> str:
        """The person photo at 768x1024 with a tile per garment, so a result is recognisably theirs."""
        person = (
            Image.open(io.BytesIO(base64.b64decode(payload["person_image"])))
            .convert("RGB")
            .resize((768, 1024))
        )
        garments = payload.get("garments", [])
        for i, g in enumerate(garments):
            tile = Image.open(io.BytesIO(base64.b64decode(g["image"]))).convert("RGB").resize((200, 200))
            person.paste(tile, (284, 260 + i * 220))
        out = io.BytesIO()
        person.save(out, format="JPEG", quality=85)
        return base64.b64encode(out.getvalue()).decode()


def make_server(fake: FakeRunPod, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, status: int, body: dict | None):
            data = json.dumps(body if body is not None else {"error": "not found"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authed(self) -> bool:
            if self.headers.get("Authorization") == f"Bearer {fake.api_key}":
                return True
            self._send(401, {"error": "unauthorized"})
            return False

        def do_POST(self):
            if not self._authed():
                return
            parts = self.path.strip("/").split("/")  # v2/{endpoint}/run | cancel/{id}
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if len(parts) == 3 and parts[2] == "run":
                self._send(200, fake.run(body))
            elif len(parts) == 4 and parts[2] == "cancel":
                self._send(200, fake.cancel(parts[3]))
            else:
                self._send(404, None)

        def do_GET(self):
            if not self._authed():
                return
            parts = self.path.strip("/").split("/")
            if len(parts) == 4 and parts[2] == "status":
                result = fake.status(parts[3])
                self._send(200 if result else 404, result)
            else:
                self._send(404, None)

    return ThreadingHTTPServer((host, port), Handler)


def serve_in_thread(fake: FakeRunPod) -> tuple[ThreadingHTTPServer, str]:
    server = make_server(fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v2"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--api-key", default="fake-key")
    p.add_argument("--cold-start", type=float, default=5.0, help="seconds a cold worker takes to start")
    p.add_argument("--render", type=float, default=4.0, help="seconds a render takes")
    p.add_argument("--idle-timeout", type=float, default=5.0, help="seconds of quiet before scaling to zero")
    args = p.parse_args()
    fake = FakeRunPod(
        api_key=args.api_key,
        cold_start=args.cold_start,
        render_seconds=args.render,
        idle_timeout=args.idle_timeout,
    )
    server = make_server(fake, port=args.port)
    print(f"fake RunPod on http://127.0.0.1:{args.port}/v2 (api key {args.api_key!r})")
    server.serve_forever()


if __name__ == "__main__":
    main()
