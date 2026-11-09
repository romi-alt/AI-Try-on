# CatVTON on RunPod serverless

The GPU half of the `catvton` try-on provider. The worker (`services/worker`, `TRYON_PROVIDER=catvton`) sends each
try-on job to a RunPod serverless endpoint over HTTPS; this directory is what runs on that endpoint.

```
kiosk -> API -> Redis -> worker (CatVTONProvider) --HTTPS--> RunPod endpoint -> this container (GPU)
```

| File | What it is |
| --- | --- |
| `Dockerfile` | CUDA 12.1 + PyTorch 2.4 image. Clones CatVTON, installs DensePose's detectron2, bakes the weights in. |
| `loader.py` | Loads CatVTON (pipeline + AutoMasker) onto the GPU **once**, when the worker starts. |
| `handler.py` | The RunPod handler. Reuses the loaded model for every job; reports progress; turns errors into codes. |
| `catvton_runner.py` | One request end to end: per-job human-parsing mask + DensePose, one diffusion pass per garment, 768x1024 result, progress from the diffusion steps. No GPU imports, so it is unit tested. |
| `deploy.py` | Creates/updates the template and endpoint, scaled to zero (`workersMin = 0`). |
| `make_test_input.py` | Builds a `test_input.json` from real images to smoke-test the container on a GPU box. |
| `../worker/worker/providers/catvton.py` | The client in the worker. |
| `../worker/worker/benchmark.py` | Average latency and cost per image. |
| `../worker/worker/fake_runpod.py` | A fake RunPod for tests and for trying the pipeline without a GPU. |

## How a job flows

1. The worker builds one request for the whole outfit and `POST`s it to `{RUNPOD_BASE_URL}/{RUNPOD_ENDPOINT_ID}/run`.
2. RunPod starts a GPU worker if none is running (scale from zero: this is the **cold start**) and runs `handler.py`.
3. For **each garment** the handler runs CatVTON's AutoMasker on the current person image (DensePose + SCHP human parsing,
   fresh for every job and every pass), then the diffusion pipeline. The result of one garment is the person image for
   the next, so tops, bottoms and dresses stack up.
4. The number of denoising steps taken (counted on the pipeline's noise scheduler) becomes the progress, 0-100 across all
   passes. The handler sends it to RunPod with `progress_update`; the worker polls `/status/{id}` every 2 s and maps it
   onto the progress ring the shopper sees.
5. The result is a 768x1024 JPEG, returned base64-encoded in the job output.

### Input

```json
{
  "input": {
    "person_image": "<base64 JPEG>",
    "garments": [{"category": "top|bottom|dress", "image": "<base64 JPEG>"}],
    "steps": 30,
    "guidance_scale": 2.5,
    "seed": 555
  }
}
```

1 to 4 garments. `top` is dressed as CatVTON's `upper`, `bottom` as `lower`, `dress` as `overall`. Shoes, bags and
accessories are not supported by the model; the worker refuses them before sending anything. RunPod limits a `/run`
body to 10 MB, so the worker scales images down first (person to 2048 px, garments to 1536 px).

### Output

```json
{"image": "<base64 JPEG>", "content_type": "image/jpeg", "width": 768, "height": 1024,
 "timings": {"mask_s": 0.9, "diffusion_s": 6.1, "total_s": 7.2}}
```

On failure the handler returns `{"error": "{\"code\": \"...\", \"message\": \"...\"}"}`. Codes: `no_person`,
`bad_image`, `unsupported_category`, `out_of_memory`, `internal`. The worker turns each into a sentence fit to show a
shopper; tracebacks never leave the container.

## Build, push, deploy

```bash
# 1. Pin the CatVTON commit you have tested (see "Before you build"), then build and push:
docker build --build-arg CATVTON_REF=<commit> -t <registry>/elevariq-catvton:1 services/catvton
docker push <registry>/elevariq-catvton:1

# 2. Smoke-test on a machine with a GPU (optional but recommended):
python services/catvton/make_test_input.py person.jpg top.png > test_input.json
docker run --rm --gpus all -v $PWD/test_input.json:/app/test_input.json <registry>/elevariq-catvton:1

# 3. Create the endpoint (scale to zero is the default). Look first, then do it:
export RUNPOD_API_KEY=...        # never commit this
python services/catvton/deploy.py --image <registry>/elevariq-catvton:1 --dry-run
python services/catvton/deploy.py --image <registry>/elevariq-catvton:1

# 4. Point the worker at it (the key is a secret, not a file in the repo):
TRYON_PROVIDER=catvton
RUNPOD_ENDPOINT_ID=<printed by deploy.py>
RUNPOD_API_KEY=<a key allowed to run the endpoint>
```

Scale to zero: `workersMin = 0` means no GPU is billed while the mirror is idle. The price is the cold start the first
shopper after a quiet spell waits through (`--idle-timeout`, default 30 s, is how long a worker lingers after its last
job). Raise `--workers-min` to 1 to keep one worker warm during opening hours, at the cost of paying for it. The
worker's `CATVTON_TIMEOUT_SECONDS` (default 420) must cover a cold start plus a render.

## Benchmark

```bash
cd services/worker
# real endpoint: spends real money, one render per job. --price-per-second is RunPod's serverless rate for the GPU.
RUNPOD_API_KEY=... RUNPOD_ENDPOINT_ID=... \
  python -m worker.benchmark --jobs 10 --person person.jpg --garment top.png --price-per-second 0.00019 --cold-gap 60

# simulated, free (checks the script itself):
python -m worker.benchmark --fake --jobs 5 --price-per-second 0.00031
```

It reports average / median / p95 wall-clock latency, RunPod's own execution and queue times, how many jobs hit a cold
start, and the cost per image (`executionTime x price`, plus a figure that also bills the cold-start waits). It does not
include idle time kept alive after the last job, storage or network.

## What has and has not been verified

Verified (automated tests, in this repository):

- `CatVTONProvider` against a fake RunPod, both in-process and over real sockets through the worker's job pipeline: request
  shape, https only, retries, polling, progress mapping, error mapping, timeout and cancellation, result decoding.
- `catvton_runner.py` and `handler.py` with fake model objects: per-job masks with the right cloth type, garment
  chaining, 768x1024 output, step-counted progress, coded errors, no leaked tracebacks.
- `deploy.py` against a fake RunPod REST API (create, update-in-place, errors).
- `benchmark.py` against the fake RunPod.

**Not verified. Nobody has built, run or deployed any of the following**, because that needs a GPU, a Docker daemon and a
RunPod account:

- The **Docker image**: that it builds (the detectron2 install in particular), that the pinned versions agree, and its size.
- **`loader.py` and the real CatVTON API**: it follows CatVTON's published `CatVTONPipeline` / `AutoMasker` interfaces and
  the `zhengchong/CatVTON` weight layout from memory of the project; check them against the commit you pin. The
  step-counting trick in `count_diffusion_steps` assumes the pipeline's scheduler is exposed as `noise_scheduler` or
  `scheduler` (it fails loudly, at the first job, if not).
- **Real latency and cost.** Any number printed by `--fake` is simulated. Measure on your endpoint.
- **RunPod's behaviour**: that `progress_update` output appears in `/status` while a job runs in the form the client
  parses (if it does not, the ring simply holds at 6% while the job runs, then completes; nothing breaks), the exact REST
  field names `deploy.py` sends (use `--dry-run` and compare with RunPod's current API reference), and the cold-start time.
- **Image quality**: whether CatVTON's results are good enough for your garments and your shoppers.
