"""S3-compatible object storage (MinIO locally, Cloudflare R2 in production)."""

import os
from functools import lru_cache

import boto3
import httpx
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from worker.config import settings

MAX_GARMENT_BYTES = 15 * 1024 * 1024


class ObjectMissing(Exception):
    """The requested object does not exist (e.g. a capture already deleted by the 1-hour cleanup)."""


def _client(endpoint_url: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@lru_cache
def client():
    return _client(settings.s3_endpoint_url)


@lru_cache
def presign_client():
    return _client(settings.presign_endpoint)


# Same reason as in db.py: a forked job process must not reuse the parent's keep-alive sockets.
os.register_at_fork(after_in_child=lambda: (client.cache_clear(), presign_client.cache_clear()))


def get_bytes(key: str) -> bytes:
    try:
        return client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
            raise ObjectMissing(key) from e
        raise


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        CacheControl="private, no-store",
    )


def presigned_get_url(key: str, expires_in: int | None = None) -> str:
    return presign_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires_in or settings.result_url_expires_seconds,
    )


def key_from_public_url(url: str) -> str | None:
    """The bucket key if `url` points at our own public bucket URL, else None (external image)."""
    base = settings.s3_public_base_url.rstrip("/") + "/"
    return url[len(base) :] if url.startswith(base) else None


def load_image_from_url(url: str) -> bytes:
    """Fetch a product image. Our own bucket is read through the S3 API (the public URL is
    host-facing and may not resolve from inside a container); anything else over HTTP."""
    if (key := key_from_public_url(url)) is not None:
        return get_bytes(key)
    resp = httpx.get(url, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    if len(resp.content) > MAX_GARMENT_BYTES:
        raise ValueError(f"image at {url} is larger than {MAX_GARMENT_BYTES} bytes")
    return resp.content
