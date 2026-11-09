"""Benchmark a try-on provider: average latency and cost per image.

    # against a real RunPod endpoint (spends real money: one render per --jobs)
    RUNPOD_API_KEY=... RUNPOD_ENDPOINT_ID=... python -m worker.benchmark --jobs 10 --price-per-second 0.00019

    # against the built-in fake (simulated numbers, free): checks the script and the wiring
    python -m worker.benchmark --fake --jobs 5

What is measured, per job: the wall-clock time the worker waits (submit to result), and RunPod's own
`delayTime` (queue wait, which includes a cold start) and `executionTime` (the GPU working). Cost per image
is `executionTime x price-per-second`, with a second figure that also bills the cold-start wait of the jobs
that hit one. `--price-per-second` is the serverless rate for the GPU the endpoint uses, from RunPod's pricing
page: it is an input, not something this script knows. It does not include the idle time a worker is kept
alive after its last job (the endpoint's idle timeout), storage or network.

Jobs run one after another by default (`--concurrency 1`) so each sees the endpoint as a single shopper would.
The first job after the endpoint has scaled to zero is the cold one; `--cold-gap` waits that many seconds
before the first job (set it above the endpoint's idle timeout to be sure the first job is cold).
"""

import argparse
import io
import json
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from PIL import Image

from worker.providers.base import GarmentInput, TryOnProvider, TryOnRequest

COLD_THRESHOLD_MS = 3000  # a queue wait longer than this means the job paid for a worker start


@dataclass(frozen=True)
class Sample:
    index: int
    ok: bool
    wall_seconds: float
    execution_ms: int | None = None
    delay_ms: int | None = None
    error: str | None = None

    @property
    def cold(self) -> bool:
        return self.delay_ms is not None and self.delay_ms > COLD_THRESHOLD_MS


def synthetic_request(category: str = "top") -> TryOnRequest:
    """A 3:4 stand-in photo and garment. Real latency depends on the image content little, but use real photos
    (`--person`, `--garment`) for a figure you will quote."""
    person = Image.new("RGB", (864, 1296), (150, 150, 160))
    garment = Image.new("RGBA", (600, 800), (0, 0, 0, 0))
    garment.paste(Image.new("RGBA", (400, 600), (180, 40, 60, 255)), (100, 100))
    p, g = io.BytesIO(), io.BytesIO()
    person.save(p, format="WEBP")
    garment.save(g, format="PNG")
    return TryOnRequest(
        person_image=p.getvalue(),
        garments=[GarmentInput(uuid.uuid4(), "Benchmark garment", category, g.getvalue())],
    )


def run_benchmark(
    make_provider, make_request, jobs: int, *, concurrency: int = 1, clock=time.monotonic
) -> list[Sample]:
    """Run `jobs` renders. `make_provider()` is called per job so metrics never leak between jobs."""

    def one(i: int) -> Sample:
        provider: TryOnProvider = make_provider()
        started = clock()
        try:
            provider.run(make_request(), lambda pct: None)
        except Exception as e:  # a failed render is a data point, not a reason to stop the benchmark
            message = getattr(e, "message", None) or str(e)
            return Sample(i, False, clock() - started, error=f"{type(e).__name__}: {message}")
        metrics = getattr(provider, "last_metrics", None)
        return Sample(
            i,
            True,
            clock() - started,
            execution_ms=getattr(metrics, "execution_ms", None),
            delay_ms=getattr(metrics, "delay_ms", None),
        )

    if concurrency <= 1:
        return [one(i) for i in range(jobs)]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(one, range(jobs)))


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def summarize(samples: list[Sample], price_per_second: float | None) -> dict:
    ok = [s for s in samples if s.ok]
    out: dict = {"jobs": len(samples), "succeeded": len(ok), "failed": len(samples) - len(ok)}
    if not ok:
        return out
    walls = [s.wall_seconds for s in ok]
    out["latency_seconds"] = {
        "average": statistics.fmean(walls),
        "median": statistics.median(walls),
        "p95": _percentile(walls, 95),
        "min": min(walls),
        "max": max(walls),
    }
    timed = [s for s in ok if s.execution_ms is not None]
    if timed:
        execution = [s.execution_ms / 1000 for s in timed]
        delay = [(s.delay_ms or 0) / 1000 for s in timed]
        cold = [s for s in timed if s.cold]
        out["execution_seconds_average"] = statistics.fmean(execution)
        out["queue_delay_seconds_average"] = statistics.fmean(delay)
        out["cold_starts"] = len(cold)
        warm = [s for s in timed if not s.cold]
        if warm:
            out["warm_latency_seconds_average"] = statistics.fmean(s.wall_seconds for s in warm)
        if cold:
            out["cold_latency_seconds_average"] = statistics.fmean(s.wall_seconds for s in cold)
        if price_per_second is not None:
            exec_cost = [e * price_per_second for e in execution]
            with_cold = [
                (e + (s.delay_ms or 0) / 1000 * (1 if s.cold else 0)) * price_per_second
                for e, s in zip(execution, timed, strict=True)
            ]
            out["cost_per_image"] = {
                "price_per_second": price_per_second,
                "execution_only": statistics.fmean(exec_cost),
                "including_cold_start_wait": statistics.fmean(with_cold),
                "note": "excludes idle time kept alive after the last job, storage and network",
            }
    return out


def render_report(summary: dict, samples: list[Sample]) -> str:
    lines = [f"jobs: {summary['jobs']}  ok: {summary['succeeded']}  failed: {summary['failed']}"]
    for s in samples:
        detail = f"{s.wall_seconds:7.2f}s"
        if s.execution_ms is not None:
            cold = "  COLD" if s.cold else ""
            detail += f"  exec {s.execution_ms / 1000:6.2f}s  queue {(s.delay_ms or 0) / 1000:6.2f}s{cold}"
        lines.append(
            f"  #{s.index + 1:<3} {'ok ' if s.ok else 'ERR'} {detail}" + (f"  {s.error}" if s.error else "")
        )
    lat = summary.get("latency_seconds")
    if lat:
        lines.append(
            f"average latency {lat['average']:.2f}s   median {lat['median']:.2f}s   p95 {lat['p95']:.2f}s   "
            f"min {lat['min']:.2f}s   max {lat['max']:.2f}s"
        )
    if "execution_seconds_average" in summary:
        lines.append(
            f"average GPU execution {summary['execution_seconds_average']:.2f}s   "
            f"average queue wait {summary['queue_delay_seconds_average']:.2f}s   "
            f"cold starts {summary['cold_starts']}"
        )
    cost = summary.get("cost_per_image")
    if cost:
        lines.append(
            f"cost per image at ${cost['price_per_second']}/s: "
            f"${cost['execution_only']:.5f} (execution only), "
            f"${cost['including_cold_start_wait']:.5f} (also billing cold-start waits)"
        )
        lines.append(f"  ({cost['note']})")
    elif "execution_seconds_average" in summary:
        lines.append("cost per image: pass --price-per-second (the GPU's serverless rate) to get it")
    else:
        lines.append("this provider reports no execution time, so there is no cost figure")
    return "\n".join(lines)


def _load_request(args) -> TryOnRequest:
    if not args.person:
        return synthetic_request(args.category)
    person = open(args.person, "rb").read()
    garments = [open(path, "rb").read() for path in args.garment or []]
    if not garments:
        sys.exit("--person needs at least one --garment")
    return TryOnRequest(
        person_image=person,
        garments=[
            GarmentInput(uuid.uuid4(), f"garment {i + 1}", args.category, data)
            for i, data in enumerate(garments)
        ],
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--jobs", type=int, default=10)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--person", help="a photo to dress (default: a synthetic one)")
    p.add_argument("--garment", action="append", help="a garment image; repeat for an outfit")
    p.add_argument("--category", default="top", choices=["top", "bottom", "dress"])
    p.add_argument("--price-per-second", type=float, help="the GPU's serverless price in USD per second")
    p.add_argument("--cold-gap", type=float, default=0.0, help="seconds to wait before the first job")
    p.add_argument("--json", help="also write the samples and summary to this file")
    p.add_argument("--fake", action="store_true", help="use the built-in fake RunPod (simulated, free)")
    p.add_argument("--fake-cold-start", type=float, default=2.0)
    p.add_argument("--fake-render", type=float, default=1.0)
    args = p.parse_args(argv)

    from worker.config import settings
    from worker.providers.catvton import CatVTONProvider

    server = None
    if args.fake:
        from worker.fake_runpod import FakeRunPod, serve_in_thread

        fake = FakeRunPod(cold_start=args.fake_cold_start, render_seconds=args.fake_render, idle_timeout=60)
        server, base = serve_in_thread(fake)

        def make_provider():
            return CatVTONProvider("fake-key", "fake", base_url=base, poll_interval=0.2)

        print(f"using the fake RunPod at {base}: the numbers below are simulated\n")
    else:
        if not (settings.runpod_api_key and settings.runpod_endpoint_id):
            sys.exit("Set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID (or use --fake)")

        def make_provider():
            return CatVTONProvider()

    request = _load_request(args)
    if args.cold_gap:
        print(f"waiting {args.cold_gap:.0f}s so the first job meets a scaled-to-zero endpoint...")
        time.sleep(args.cold_gap)
    samples = run_benchmark(make_provider, lambda: request, args.jobs, concurrency=args.concurrency)
    summary = summarize(samples, args.price_per_second)
    print(render_report(summary, samples))
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"summary": summary, "samples": [asdict(s) for s in samples]}, f, indent=2)
    if server:
        server.shutdown()
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
