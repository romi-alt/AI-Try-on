import asyncio
import logging
import time
import uuid

import pytest

from app.core import storage
from app.core.config import settings
from app.services import capture_cleanup
from scripts import apply_lifecycle


def put(s3, key: str) -> None:
    s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=b"x")


def keys(s3) -> set[str]:
    return {o["Key"] for o in s3.list_objects_v2(Bucket=settings.s3_bucket).get("Contents", [])}


async def test_sweep_deletes_captures_older_than_the_ttl(s3):
    sid = uuid.uuid4()
    for i in range(3):
        put(s3, f"captures/{sid}/{i}.webp")

    assert await capture_cleanup.sweep_once(ttl_seconds=0) == 3
    assert keys(s3) == set()


async def test_sweep_keeps_captures_younger_than_the_ttl(s3):
    put(s3, "captures/a/fresh.webp")

    assert await capture_cleanup.sweep_once(ttl_seconds=3600) == 0
    assert keys(s3) == {"captures/a/fresh.webp"}


async def test_cutoff_is_what_separates_old_from_new(s3):
    put(s3, "captures/a/old.webp")
    time.sleep(1.2)  # S3 timestamps have one-second resolution
    put(s3, "captures/a/new.webp")

    assert await capture_cleanup.sweep_once(ttl_seconds=1) == 1
    assert keys(s3) == {"captures/a/new.webp"}


async def test_sweep_only_touches_the_captures_prefix(s3):
    for key in (
        "captures/a/x.webp",
        "results/a/x.webp",
        "garment/x.png",
        "captures-archive/x.webp",
        "x.webp",
    ):
        put(s3, key)

    await capture_cleanup.sweep_once(ttl_seconds=0)

    assert keys(s3) == {"results/a/x.webp", "garment/x.png", "captures-archive/x.webp", "x.webp"}


async def test_sweep_with_nothing_to_do_is_fine(s3):
    assert await capture_cleanup.sweep_once(ttl_seconds=0) == 0


async def test_deletion_is_batched_and_pages_through_every_object(s3, monkeypatch):
    monkeypatch.setattr(storage, "DELETE_BATCH_SIZE", 3)
    for i in range(8):
        put(s3, f"captures/s/{i}.webp")
    put(s3, "results/keep.webp")

    assert await capture_cleanup.sweep_once(ttl_seconds=0) == 8
    assert keys(s3) == {"results/keep.webp"}


async def test_background_loop_sweeps_repeatedly_and_stops_on_cancel(s3):
    task = asyncio.create_task(capture_cleanup.cleanup_loop(0.05, ttl_seconds=0))
    try:
        put(s3, "captures/a/one.webp")
        for _ in range(100):
            if not keys(s3):
                break
            await asyncio.sleep(0.05)
        assert keys(s3) == set()
        put(s3, "captures/a/two.webp")  # a later arrival is picked up by a later sweep
        for _ in range(100):
            if not keys(s3):
                break
            await asyncio.sleep(0.05)
        assert keys(s3) == set()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_loop_survives_a_failing_sweep(s3, monkeypatch, caplog):
    calls = {"n": 0}
    real = storage.delete_captures_older_than

    def flaky(cutoff):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("storage down")
        return real(cutoff)

    monkeypatch.setattr(capture_cleanup, "delete_captures_older_than", flaky)
    put(s3, "captures/a/x.webp")
    task = asyncio.create_task(capture_cleanup.cleanup_loop(0.05, ttl_seconds=0))
    try:
        with caplog.at_level(logging.ERROR, logger="app.capture_cleanup"):
            for _ in range(100):
                if not keys(s3):
                    break
                await asyncio.sleep(0.05)
        assert keys(s3) == set() and calls["n"] >= 2
        assert any(r.message == "capture_sweep_failed" for r in caplog.records)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_sweep_deletes_finished_looks_after_their_ttl_but_not_before(s3):
    sid = uuid.uuid4()
    put(s3, f"results/{sid}/job.webp")
    put(s3, f"garment/2026/01/01/{uuid.uuid4().hex}.png")  # not a shopper's photo: never touched

    assert await capture_cleanup.sweep_results_once(ttl_seconds=3600) == 0  # still fresh
    assert await capture_cleanup.sweep_results_once(ttl_seconds=0) == 1
    assert [k for k in keys(s3) if k.startswith("results/")] == []
    assert any(k.startswith("garment/") for k in keys(s3))


async def test_the_loop_sweeps_results_too(s3, monkeypatch):
    monkeypatch.setattr(settings, "result_ttl_seconds", 0)
    put(s3, "results/s/j.webp")
    task = asyncio.create_task(capture_cleanup.cleanup_loop(0.05, ttl_seconds=3600))
    try:
        for _ in range(100):
            if not keys(s3):
                break
            await asyncio.sleep(0.05)
        assert keys(s3) == set()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_lifecycle_rule_is_applied_idempotently_and_keeps_other_rules(s3):
    s3.put_bucket_lifecycle_configuration(
        Bucket=settings.s3_bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "other",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "logs/"},
                    "Expiration": {"Days": 30},
                }
            ]
        },
    )

    apply_lifecycle.run()
    apply_lifecycle.run()

    rules = {r["ID"]: r for r in s3.get_bucket_lifecycle_configuration(Bucket=settings.s3_bucket)["Rules"]}
    assert set(rules) == {"other", "captures-expire-1d", "results-expire-1d"}
    mine = rules["captures-expire-1d"]
    assert mine["Expiration"]["Days"] == 1 and mine["Filter"]["Prefix"] == "captures/"
    assert rules["results-expire-1d"]["Filter"]["Prefix"] == "results/"
    assert rules["other"]["Expiration"]["Days"] == 30


def test_lifecycle_rule_on_a_bucket_with_no_rules(s3):
    apply_lifecycle.run()
    rules = s3.get_bucket_lifecycle_configuration(Bucket=settings.s3_bucket)["Rules"]
    assert sorted(r["ID"] for r in rules) == ["captures-expire-1d", "results-expire-1d"]
