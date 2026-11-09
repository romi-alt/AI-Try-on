"""S3-compatible object storage (MinIO locally, Cloudflare R2 in production)."""

import uuid
from datetime import UTC, datetime
from functools import lru_cache

import boto3
from botocore.config import Config as BotoConfig

from app.core.config import settings

_CONTENT_TYPE_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


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
def internal_client():
    """Client used from inside the network (server-to-storage)."""
    return _client(settings.s3_endpoint_url)


@lru_cache
def presign_client():
    """Client whose signed URLs are valid from the browser's point of view."""
    return _client(settings.presign_endpoint)


def build_key(kind: str, content_type: str) -> str:
    ext = _CONTENT_TYPE_EXT.get(content_type, "bin")
    now = datetime.now(UTC)
    return f"{kind}/{now:%Y/%m/%d}/{uuid.uuid4().hex}.{ext}"


def public_url(key: str) -> str:
    return f"{settings.s3_public_base_url.rstrip('/')}/{key}"


def presigned_put(key: str, content_type: str) -> str:
    return presign_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.presign_expires_seconds,
        HttpMethod="PUT",
    )


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    internal_client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)


def object_exists(key: str) -> bool:
    try:
        internal_client().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except Exception:
        return False
