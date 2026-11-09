"""RunPod serverless entry point.

The model is loaded once, when the worker starts, and reused for every job that worker serves. Job input and
output are documented in README.md; the client is `services/worker/worker/providers/catvton.py`.
"""

import json
import logging
import time

from catvton_runner import CatVTONRunner, RunnerError

logger = logging.getLogger("catvton.handler")
PROGRESS_MIN_INTERVAL = 0.75  # seconds: every step would be an HTTP call to RunPod, so thin them out


def make_handler(runner: CatVTONRunner, send_progress=None, clock=time.monotonic):
    def handler(job: dict) -> dict:
        last_sent = -1.0
        last_pct = -1

        def on_progress(pct: int) -> None:
            nonlocal last_sent, last_pct
            now = clock()
            if (
                send_progress
                and pct != last_pct
                and (pct in (0, 100) or now - last_sent >= PROGRESS_MIN_INTERVAL)
            ):
                last_sent, last_pct = now, pct
                try:
                    send_progress(job, json.dumps({"progress": pct}))
                except Exception:  # progress is a nicety: never fail a render over it
                    logger.warning("progress_update_failed", exc_info=True)

        try:
            return runner.run(job.get("input") or {}, on_progress)
        except RunnerError as e:
            logger.warning("job_rejected", extra={"code": e.code, "reason": e.message})
            return {"error": e.as_error_string()}
        except Exception as e:  # anything else: log the traceback here, tell the client only that it failed
            logger.exception("job_failed")
            return {"error": json.dumps({"code": "internal", "message": type(e).__name__})}

    return handler


if __name__ == "__main__":
    import runpod

    from loader import load

    logging.basicConfig(level=logging.INFO)
    pipeline, automasker = load()  # once, before the first job
    runpod.serverless.start(
        {"handler": make_handler(CatVTONRunner(pipeline, automasker), runpod.serverless.progress_update)}
    )
