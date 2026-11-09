"""Jobs that misbehave, importable by RQ's forked work horse."""

import os
import signal


def die(job_id: str) -> None:
    os.kill(os.getpid(), signal.SIGKILL)  # no cleanup, no exception: like an OOM kill
