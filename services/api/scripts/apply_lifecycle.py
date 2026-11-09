"""Add bucket lifecycle rules that expire `captures/` and `results/` objects (coarse safety net).

Object-store lifecycle rules (S3, R2, MinIO) have day granularity, so this cannot enforce the
one-hour retention; the API's background sweeper does that. This rule only guarantees nothing
under `captures/` or `results/` outlives a day even if the API is down. Idempotent, and preserves any other
rules already on the bucket.

    python -m scripts.apply_lifecycle
"""

import logging

from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.storage import CAPTURE_PREFIX, RESULT_PREFIX, internal_client

log = logging.getLogger("lifecycle")
RULE_ID = "captures-expire-1d"  # kept for buckets that already have it
RESULT_RULE_ID = "results-expire-1d"
RULES = [
    {
        "ID": rule_id,
        "Status": "Enabled",
        "Filter": {"Prefix": prefix},
        "Expiration": {"Days": 1},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
    }
    for rule_id, prefix in ((RULE_ID, CAPTURE_PREFIX), (RESULT_RULE_ID, RESULT_PREFIX))
]
RULE = RULES[0]


def run() -> None:
    client = internal_client()
    try:
        existing = client.get_bucket_lifecycle_configuration(Bucket=settings.s3_bucket)["Rules"]
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("NoSuchLifecycleConfiguration", "NoSuchBucket"):
            raise
        existing = []
    # put_bucket_lifecycle_configuration replaces everything, so keep the other rules.
    ours = {r["ID"] for r in RULES}
    rules = [r for r in existing if r.get("ID") not in ours] + RULES
    client.put_bucket_lifecycle_configuration(
        Bucket=settings.s3_bucket, LifecycleConfiguration={"Rules": rules}
    )
    log.info(
        "lifecycle rules %s applied to bucket %s (%d rules total)",
        sorted(ours),
        settings.s3_bucket,
        len(rules),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run()
