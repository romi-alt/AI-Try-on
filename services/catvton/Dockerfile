# CatVTON as a RunPod serverless worker: CUDA 12.1, PyTorch 2.4, the model loaded once per worker start.
#
#   docker build -t <registry>/elevariq-catvton:<tag> services/catvton
#   docker push  <registry>/elevariq-catvton:<tag>
#   python services/catvton/deploy.py --image <registry>/elevariq-catvton:<tag>
#
# The build downloads about 10 GB of weights from Hugging Face into the image, so a cold start only loads them onto
# the GPU; it does not download anything. Build on a machine with a fast connection and push to a registry RunPod
# can pull from.
#
# NOT built or run in the repository's CI or by the author of this file: see README.md ("What has and has not been
# verified"). The two steps most likely to need adjusting are the detectron2 install (DensePose depends on it) and
# the CATVTON_REF pin.
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-devel

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9;9.0" \
    CATVTON_DIR=/opt/CatVTON \
    CATVTON_WEIGHTS=/models

RUN apt-get update \
    && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 ninja-build \
    && rm -rf /var/lib/apt/lists/*

# Pin a commit you have tested (see README). "main" is only the default so the file builds at all.
ARG CATVTON_REF=main
RUN git clone https://github.com/Zheng-Chong/CatVTON.git ${CATVTON_DIR} \
    && git -C ${CATVTON_DIR} checkout ${CATVTON_REF}

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# DensePose (used by CatVTON's AutoMasker) needs detectron2, which must be compiled against the torch above.
ARG DETECTRON2_REF=main
RUN pip install --no-build-isolation "git+https://github.com/facebookresearch/detectron2.git@${DETECTRON2_REF}"

WORKDIR /app
COPY download_weights.py /app/
RUN python download_weights.py ${CATVTON_WEIGHTS}

COPY catvton_runner.py loader.py handler.py /app/

# RunPod starts the container and runs this; the handler loads CatVTON before it accepts the first job.
CMD ["python", "-u", "/app/handler.py"]
