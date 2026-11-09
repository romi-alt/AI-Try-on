FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install ".[dev]" || true
COPY . .
RUN pip install -e ".[dev]"

CMD ["python", "-m", "worker.main"]
