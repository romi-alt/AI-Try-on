"""Add a bucket lifecycle rule that expires `captures/` objects (coarse safety net).

Object-store lifecycle rules (S3, R2, MinIO) have day granularity, so this cannot enforce the
one-hour retention; the API's background sweeper does that. This rule only guarantees nothing
under `captures/` outlives a day even if the API is down. Idempotent, and preserves any other
rules already on the bucket.

    python -m scripts.apply_lifecycle
"""

import logging

from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.storage import CAPTURE_PREFIX, internal_client

log = logging.getLogger("lifecycle")
RULE_ID = "captures-expire-1d"
RULE = {
    "ID": RULE_ID,
    "Status": "Enabled",
    "Filter": {"Prefix": CAPTURE_PREFIX},
    "Expiration": {"Days": 1},
    "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
}


def run() -> None:
    client = internal_client()
    try:
        existing = client.get_bucket_lifecycle_configuration(Bucket=settings.s3_bucket)["Rules"]
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("NoSuchLifecycleConfiguration", "NoSuchBucket"):
            raise
        existing = []
    # put_bucket_lifecycle_configuration replaces everything, so keep the other rules.
    rules = [r for r in existing if r.get("ID") != RULE_ID] + [RULE]
    client.put_bucket_lifecycle_configuration(
        Bucket=settings.s3_bucket, LifecycleConfiguration={"Rules": rules}
    )
    log.info(
        "lifecycle rule %r applied to bucket %s (%d rules total)", RULE_ID, settings.s3_bucket, len(rules)
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run()
