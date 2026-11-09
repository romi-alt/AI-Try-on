import json

import pytest

from worker.benchmark import Sample, main, render_report, run_benchmark, summarize, synthetic_request
from worker.fake_runpod import FakeRunPod, serve_in_thread
from worker.providers.catvton import CatVTONProvider


def s(i, wall, exec_ms=None, delay_ms=None, ok=True):
    return Sample(i, ok, wall, exec_ms, delay_ms, None if ok else "boom")


def test_summary_averages_latency_and_separates_cold_from_warm():
    samples = [s(0, 20.0, 8000, 11000), s(1, 9.0, 8000, 500), s(2, 11.0, 10000, 600)]
    out = summarize(samples, None)
    assert out["jobs"] == 3 and out["succeeded"] == 3 and out["failed"] == 0
    assert out["latency_seconds"]["average"] == pytest.approx(13.3333, abs=1e-3)
    assert out["latency_seconds"]["median"] == 11.0
    assert out["latency_seconds"]["max"] == 20.0 and out["latency_seconds"]["min"] == 9.0
    assert out["cold_starts"] == 1
    assert out["cold_latency_seconds_average"] == 20.0 and out["warm_latency_seconds_average"] == 10.0
    assert out["execution_seconds_average"] == pytest.approx(8.6667, abs=1e-3)
    assert "cost_per_image" not in out


def test_cost_per_image_is_execution_time_times_the_price_and_can_include_cold_waits():
    samples = [s(0, 20.0, 8000, 11000), s(1, 9.0, 8000, 500), s(2, 11.0, 10000, 600)]
    cost = summarize(samples, 0.001)["cost_per_image"]
    assert cost["execution_only"] == pytest.approx((8 + 8 + 10) / 3 * 0.001)
    assert cost["including_cold_start_wait"] == pytest.approx(
        (8 + 11 + 8 + 10) / 3 * 0.001
    )  # only the cold job's wait


def test_failures_are_counted_and_excluded_from_the_averages():
    out = summarize([s(0, 10.0, 5000, 100), s(1, 99.0, ok=False)], 0.001)
    assert (out["succeeded"], out["failed"]) == (1, 1)
    assert out["latency_seconds"]["average"] == 10.0
    assert summarize([s(0, 1.0, ok=False)], 0.001) == {"jobs": 1, "succeeded": 0, "failed": 1}


def test_a_provider_without_execution_times_gives_latency_but_no_cost():
    out = summarize([s(0, 2.0), s(1, 4.0)], 0.001)
    assert out["latency_seconds"]["average"] == 3.0 and "cost_per_image" not in out
    assert "no cost figure" in render_report(out, [s(0, 2.0), s(1, 4.0)])


def test_the_report_says_what_it_needs_when_no_price_is_given():
    samples = [s(0, 9.0, 8000, 500)]
    assert "--price-per-second" in render_report(summarize(samples, None), samples)


def test_a_failing_job_is_recorded_not_raised():
    class Boom:
        def run(self, request, on_progress):
            raise RuntimeError("endpoint down")

    out = run_benchmark(lambda: Boom(), synthetic_request, 2)
    assert [x.ok for x in out] == [False, False] and "endpoint down" in out[0].error


def test_against_the_fake_runpod_the_first_job_is_cold_and_the_rest_are_warm():
    fake = FakeRunPod(cold_start=3.2, render_seconds=0.3, idle_timeout=60)
    server, base = serve_in_thread(fake)
    try:
        samples = run_benchmark(
            lambda: CatVTONProvider("fake-key", "ep", base_url=base, poll_interval=0.1), synthetic_request, 3
        )
    finally:
        server.shutdown()
    assert all(x.ok for x in samples)
    assert [x.cold for x in samples] == [True, False, False]
    assert samples[0].wall_seconds > samples[1].wall_seconds + 2.5
    assert samples[1].execution_ms == 300 and samples[0].delay_ms == 3200


def test_the_command_line_runs_against_the_fake_and_writes_json(tmp_path, capsys):
    out_file = tmp_path / "bench.json"
    code = main(
        [
            "--fake",
            "--jobs",
            "2",
            "--fake-cold-start",
            "0",
            "--fake-render",
            "0.2",
            "--price-per-second",
            "0.0005",
            "--json",
            str(out_file),
        ]
    )
    text = capsys.readouterr().out
    assert code == 0
    assert "simulated" in text and "average latency" in text and "cost per image" in text
    saved = json.loads(out_file.read_text())
    assert saved["summary"]["succeeded"] == 2 and len(saved["samples"]) == 2
