"""S3-compatible object storage (MinIO locally, Cloudflare R2 in production)."""

import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

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


def presigned_get(key: str, expires_in: int = 3600) -> str:
    """A short-lived URL the browser can GET an object from (used to show look images on the mobile page)."""
    return presign_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires_in,
        HttpMethod="GET",
    )


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    internal_client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)


def object_exists(key: str) -> bool:
    """False only when the object is definitely absent; storage outages raise."""
    try:
        internal_client().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


# --- captures ----------------------------------------------------------------------------------

CAPTURE_PREFIX = "captures/"
DELETE_BATCH_SIZE = 1000  # S3 DeleteObjects accepts at most 1000 keys per call


def capture_key(session_id: uuid.UUID | str) -> str:
    return f"{CAPTURE_PREFIX}{session_id}/{uuid.uuid4()}.webp"


def capture_key_belongs_to(key: str, session_id: uuid.UUID | str) -> bool:
    """True for `captures/{session_id}/{uuid}.webp`; blocks using another session's photo."""
    prefix = f"{CAPTURE_PREFIX}{session_id}/"
    if not key.startswith(prefix) or not key.endswith(".webp"):
        return False
    stem = key[len(prefix) : -len(".webp")]
    try:
        uuid.UUID(stem)
    except ValueError:
        return False
    return True


def put_capture(key: str, data: bytes, session_id: uuid.UUID | str) -> None:
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.capture_ttl_seconds)
    internal_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType="image/webp",
        CacheControl="private, no-store",
        Metadata={"session-id": str(session_id), "expires-at": expires_at.isoformat(timespec="seconds")},
    )


def _delete_where(prefix: str, doomed: Callable[[dict], bool]) -> int:
    """Delete every object under `prefix` for which `doomed(listing_entry)` is true. Returns the count."""
    client = internal_client()
    deleted = 0
    batch: list[dict] = []

    def flush() -> int:
        if not batch:
            return 0
        resp = client.delete_objects(
            Bucket=settings.s3_bucket, Delete={"Objects": list(batch), "Quiet": True}
        )
        n = len(batch) - len(resp.get("Errors", []))
        batch.clear()
        return n

    for page in client.get_paginator("list_objects_v2").paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if doomed(obj):
                batch.append({"Key": obj["Key"]})
                if len(batch) >= DELETE_BATCH_SIZE:
                    deleted += flush()
    return deleted + flush()


def delete_captures_older_than(cutoff: datetime) -> int:
    """Delete every object under `captures/` last modified before `cutoff`. Returns the count."""
    return _delete_where(CAPTURE_PREFIX, lambda obj: obj["LastModified"] < cutoff)


# --- garment images (uploaded by the admin app straight to the bucket) --------------------------

GARMENT_PREFIX = "garment/"
_GARMENT_KEY = re.compile(r"^garment/\d{4}/\d{2}/\d{2}/[0-9a-f]{32}\.(png|jpg|webp)$")
_EXT_CONTENT_TYPE = {ext: ct for ct, ext in _CONTENT_TYPE_EXT.items()}


def is_garment_key(key: str) -> bool:
    """True only for keys `build_key("garment", ...)` produces, so verify cannot be aimed at other objects."""
    return bool(_GARMENT_KEY.fullmatch(key))


def expected_content_type(key: str) -> str:
    return _EXT_CONTENT_TYPE[key.rsplit(".", 1)[1]]


def object_info(key: str) -> dict | None:
    """`{size, content_type}` of an object, or None when it is definitely absent; storage outages raise."""
    try:
        head = internal_client().head_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return {"size": head["ContentLength"], "content_type": head.get("ContentType", "")}


def delete_object(key: str) -> None:
    internal_client().delete_object(Bucket=settings.s3_bucket, Key=key)


def delete_oversized_garments(max_bytes: int) -> int:
    """Delete every object under `garment/` larger than `max_bytes`. Returns the count.

    An upload in progress is not listed until it completes, so only finished (and so final) sizes are seen.
    """
    return _delete_where(GARMENT_PREFIX, lambda obj: obj["Size"] > max_bytes)
