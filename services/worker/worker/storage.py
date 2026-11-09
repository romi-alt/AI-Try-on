from functools import lru_cache

import boto3
from botocore.config import Config as BotoConfig

from worker.config import settings


@lru_cache
def client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def get_bytes(key: str) -> bytes:
    return client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
