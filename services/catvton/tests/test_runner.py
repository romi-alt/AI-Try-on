"""The CatVTON runner and RunPod handler, with fake model objects (no GPU, no torch, no weights)."""

import base64
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catvton_runner import (  # noqa: E402
    HEIGHT,
    WIDTH,
    CatVTONRunner,
    RunnerError,
    count_diffusion_steps,
    fit_garment,
    fit_person,
    mask_fraction,
)
from handler import make_handler  # noqa: E402


def b64(img: Image.Image, fmt="JPEG") -> str:
    out = io.BytesIO()
    img.save(out, format=fmt)
    return base64.b64encode(out.getvalue()).decode()


def photo(size=(864, 1296), color=(120, 140, 160)) -> str:
    return b64(Image.new("RGB", size, color))


def cloth(color=(200, 30, 60), size=(300, 400)) -> str:
    return b64(Image.new("RGB", size, color))


class FakeScheduler:
    def __init__(self):
        self.calls = 0

    def step(self, *args, **kwargs):
        self.calls += 1
        return "stepped"


class FakePipeline:
    """Stands in for CatVTONPipeline: steps its scheduler once per inference step, like the real loop does."""

    def __init__(self, result_size=(WIDTH, HEIGHT), fail=None):
        self.noise_scheduler = FakeScheduler()
        self.calls: list[dict] = []
        self.result_size = result_size
        self.fail = fail

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail
        for _ in range(kw["num_inference_steps"]):
            assert self.noise_scheduler.step() == "stepped"  # the wrapper must not change what step returns
        shade = 60 * len(self.calls)
        return [Image.new("RGB", self.result_size, (shade, shade, shade))]


class FakeMasker:
    def __init__(self, fraction=0.4):
        self.fraction = fraction
        self.calls: list[tuple] = []

    def __call__(self, person, cloth_type):
        self.calls.append((person.size, cloth_type))
        mask = Image.new("L", person.size, 0)
        h = int(person.height * self.fraction)
        mask.paste(255, (0, 0, person.width, h))
        return {"mask": mask}


def runner(pipeline=None, masker=None):
    return CatVTONRunner(
        pipeline or FakePipeline(),
        masker or FakeMasker(),
        make_generator=lambda seed: ("gen", seed),
    )


def payload(*categories, **over):
    return {
        "person_image": photo(),
        "garments": [{"category": c, "image": cloth()} for c in categories],
        "steps": 10,
        "guidance_scale": 2.5,
        "seed": 7,
        **over,
    }


# --- result --------------------------------------------------------------------------------------


def test_returns_a_768x1024_jpeg():
    out = runner().run(payload("top"), lambda p: None)
    img = Image.open(io.BytesIO(base64.b64decode(out["image"])))
    assert img.format == "JPEG" and img.size == (768, 1024)
    assert (out["width"], out["height"], out["content_type"]) == (
        768,
        1024,
        "image/jpeg",
    )
    assert set(out["timings"]) == {"mask_s", "diffusion_s", "total_s"}


def test_a_pipeline_result_of_another_size_is_brought_to_768x1024():
    out = runner(FakePipeline(result_size=(512, 640))).run(payload("top"), lambda p: None)
    assert Image.open(io.BytesIO(base64.b64decode(out["image"]))).size == (768, 1024)


def test_the_model_gets_768x1024_inputs_and_the_requested_settings():
    pipe, masker = FakePipeline(), FakeMasker()
    runner(pipe, masker).run(payload("top", steps=12, guidance_scale=3.0, seed=99), lambda p: None)
    call = pipe.calls[0]
    assert call["image"].size == call["condition_image"].size == call["mask"].size == (768, 1024)
    assert (call["height"], call["width"]) == (1024, 768)
    assert (call["num_inference_steps"], call["guidance_scale"]) == (12, 3.0)
    assert call["generator"] == ("gen", 99)


# --- preprocessing per job -----------------------------------------------------------------------


def test_the_mask_is_computed_for_every_job_and_every_pass_with_the_right_cloth_type():
    masker = FakeMasker()
    r = runner(FakePipeline(), masker)
    r.run(payload("top", "bottom"), lambda p: None)
    r.run(payload("dress"), lambda p: None)  # a second job: nothing is cached from the first
    assert [c[1] for c in masker.calls] == ["upper", "lower", "overall"]
    assert all(size == (768, 1024) for size, _ in masker.calls)


def test_an_outfit_is_built_by_feeding_each_result_into_the_next_pass():
    pipe, masker = FakePipeline(), FakeMasker()
    two = payload("top", "bottom")
    two["garments"][0]["image"], two["garments"][1]["image"] = (
        cloth((200, 0, 0)),
        cloth((0, 0, 200)),
    )
    runner(pipe, masker).run(two, lambda p: None)
    first, second = pipe.calls
    assert all(
        abs(a - b) <= 2 for a, b in zip(first["image"].getpixel((10, 10)), (120, 140, 160), strict=True)
    )
    assert second["image"].getpixel((10, 10)) == (60, 60, 60)  # the first pass's result
    assert first["condition_image"].getpixel((384, 512))[0] > 150  # each pass gets its own garment, in order
    assert second["condition_image"].getpixel((384, 512))[2] > 150


def test_no_person_found_is_a_clear_error_and_the_pipeline_is_not_run():
    pipe = FakePipeline()
    with pytest.raises(RunnerError) as e:
        runner(pipe, FakeMasker(fraction=0.0)).run(payload("top"), lambda p: None)
    assert e.value.code == "no_person" and pipe.calls == []


# --- progress ------------------------------------------------------------------------------------


def test_progress_follows_the_diffusion_steps_across_all_passes():
    seen: list[int] = []
    runner().run(payload("top", "bottom", steps=10), seen.append)
    assert seen[0] == 0 and seen[-1] == 100
    assert seen == sorted(seen) and len(set(seen)) == len(seen)
    assert {50, 55, 95} <= set(seen)  # 10 steps per pass, 20 in all: step 10, 11 and 19 of 20
    assert max(seen[:-1]) == 99  # the last step reports 99; 100 is only sent once the image is ready


def test_the_step_counter_is_removed_afterwards_even_when_the_pipeline_fails():
    pipe = FakePipeline(fail=RuntimeError("boom"))
    original = pipe.noise_scheduler.step
    with pytest.raises(RuntimeError):
        runner(pipe).run(payload("top"), lambda p: None)
    assert pipe.noise_scheduler.step == original


def test_counting_steps_works_with_either_scheduler_name_and_fails_loudly_without_one():
    class Alt:
        scheduler = FakeScheduler()

    n = []
    with count_diffusion_steps(Alt, lambda: n.append(1)):
        Alt.scheduler.step()
        Alt.scheduler.step()
    assert len(n) == 2
    with (
        pytest.raises(RuntimeError, match="no scheduler"),
        count_diffusion_steps(object(), lambda: None),
    ):
        pass


# --- validation ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        ({"person_image": ""}, "bad_image"),
        ({"garments": []}, "bad_image"),
        ({"garments": [{"category": "top", "image": cloth()}] * 5}, "bad_image"),
        (
            {"garments": [{"category": "shoes", "image": cloth()}]},
            "unsupported_category",
        ),
        ({"garments": [{"image": cloth()}]}, "unsupported_category"),
        ({"steps": 0}, "bad_image"),
        ({"steps": 500}, "bad_image"),
        ({"steps": "many"}, "bad_image"),
        ({"person_image": "!!!"}, "bad_image"),
        ({"person_image": b64(Image.new("RGB", (4, 4)))[:20]}, "bad_image"),
    ],
)
def test_bad_requests_are_rejected_with_a_code(bad, code):
    pipe = FakePipeline()
    with pytest.raises(RunnerError) as e:
        runner(pipe).run({**payload("top"), **bad}, lambda p: None)
    assert e.value.code == code and pipe.calls == []


def test_fitting_the_person_crops_and_fitting_a_garment_pads():
    wide = Image.new("RGB", (2000, 1000), (255, 0, 0))
    assert fit_person(wide).size == (768, 1024)
    padded = fit_garment(Image.new("RGB", (1000, 1000), (0, 0, 255)))
    assert padded.size == (768, 1024)
    assert padded.getpixel((384, 512)) == (0, 0, 255) and padded.getpixel((5, 5)) == (
        255,
        255,
        255,
    )
    assert (
        mask_fraction(Image.new("L", (10, 10), 255)) == 1.0
        and mask_fraction(Image.new("L", (10, 10), 0)) == 0.0
    )


# --- the RunPod handler --------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.3
        return self.now


def test_the_handler_returns_the_result_and_reports_json_progress():
    sent = []
    handler = make_handler(
        runner(),
        lambda job, update: sent.append(json.loads(update)["progress"]),
        clock=Clock(),
    )
    out = handler({"id": "j1", "input": payload("top", steps=20)})
    assert out["width"] == 768 and "error" not in out
    assert sent[0] == 0 and sent[-1] == 100 and sent == sorted(sent)
    assert len(sent) < 22  # thinned out: not one HTTP call per step


def test_the_handler_turns_runner_errors_into_a_coded_error():
    out = make_handler(runner(masker=FakeMasker(0.0)))({"id": "j", "input": payload("top")})
    assert json.loads(out["error"]) == {
        "code": "no_person",
        "message": "No body was found to dress in the photo",
    }


def test_an_unexpected_crash_is_reported_without_leaking_details():
    out = make_handler(runner(FakePipeline(fail=RuntimeError("secret path /root/x"))))(
        {"id": "j", "input": payload("top")}
    )
    err = json.loads(out["error"])
    assert err == {"code": "internal", "message": "RuntimeError"}


def test_a_gpu_out_of_memory_is_its_own_code():
    class OutOfMemoryError(RuntimeError):
        pass

    out = make_handler(runner(FakePipeline(fail=OutOfMemoryError("CUDA out of memory"))))(
        {"id": "j", "input": payload("top")}
    )
    assert json.loads(out["error"])["code"] == "out_of_memory"


def test_a_failing_progress_call_does_not_fail_the_render():
    def broken(job, update):
        raise OSError("runpod unreachable")

    out = make_handler(runner(), broken, clock=Clock())({"id": "j", "input": payload("top")})
    assert "image" in out


def test_a_missing_input_is_a_clean_error():
    out = make_handler(runner())({"id": "j"})
    assert json.loads(out["error"])["code"] == "bad_image"
