#!/usr/bin/env python3
"""Checks deploy/.env.production before the stack is started: python3 preflight.py [path-to-env-file]

It refuses the mistakes that are easy to make and expensive later: a placeholder or dev-default secret still in
place, a browser origin on http or localhost, a database connection without TLS, photo retention longer than the
promise on the kiosk's privacy notice, public API docs left on. Errors stop the deploy (exit 1); warnings do not.
Standard library only.
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

DEV_DEFAULTS = {
    "dev-admin-key",
    "dev-staff-key",
    "minioadmin",
    "minioadmin_dev_password",
    "tryon_dev_password",
    "dev-only-change-me-dev-only-change-me",
    "changeme",
    "password",
    "secret",
}
SECRETS = ("ADMIN_API_KEY", "STAFF_API_KEY", "REDIS_PASSWORD", "S3_SECRET_ACCESS_KEY")
REQUIRED = (
    "API_DOMAIN",
    "ACME_EMAIL",
    "DATABASE_URL",
    "REDIS_PASSWORD",
    "API_CORS_ORIGINS",
    "ADMIN_API_KEY",
    "STAFF_API_KEY",
    "S3_ENDPOINT_URL",
    "S3_PRESIGN_ENDPOINT_URL",
    "S3_BUCKET",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "S3_PUBLIC_BASE_URL",
)
MAX_RETENTION_SECONDS = 3600  # the kiosk's privacy notice says "within one hour"


def parse_env(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def check(env: dict[str, str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    def val(key: str) -> str:
        return env.get(key, "")

    for key in REQUIRED:
        if not val(key):
            errors.append(f"{key} is not set")
    for key, value in env.items():
        if "CHANGE_ME" in value:
            errors.append(f"{key} still has the CHANGE_ME placeholder")

    for key in SECRETS:
        v = val(key)
        if v and (v.lower() in DEV_DEFAULTS or "dev" in v.lower() and "key" in v.lower()):
            errors.append(f"{key} is a development default")
        elif v and "CHANGE_ME" not in v and len(v) < 24:
            errors.append(f"{key} is too short ({len(v)} characters; use `openssl rand -hex 24`)")
    if val("ADMIN_API_KEY") and val("ADMIN_API_KEY") == val("STAFF_API_KEY"):
        errors.append("ADMIN_API_KEY and STAFF_API_KEY must differ")
    if val("REDIS_PASSWORD") and not re.fullmatch(r"[A-Za-z0-9]+", val("REDIS_PASSWORD")):
        errors.append("REDIS_PASSWORD must be letters and digits only (it goes inside a URL)")

    domain = val("API_DOMAIN")
    if domain and (domain.startswith(("http://", "https://")) or "/" in domain or domain in ("localhost",)):
        errors.append("API_DOMAIN must be a bare host name such as api.example.com")

    origins = [o.strip() for o in val("API_CORS_ORIGINS").split(",") if o.strip()]
    for o in origins:
        u = urlparse(o)
        if u.scheme != "https":
            errors.append(f"API_CORS_ORIGINS has a non-https origin: {o}")
        elif u.hostname in ("localhost", "127.0.0.1") or u.path not in ("", "/") or o.endswith("/"):
            errors.append(f"API_CORS_ORIGINS entry must be a plain https origin without a path or slash: {o}")
    if val("API_CORS_ORIGINS") and not origins:
        errors.append("API_CORS_ORIGINS is empty")

    db = val("DATABASE_URL")
    if db:
        if not db.startswith("postgresql+psycopg://"):
            errors.append("DATABASE_URL must start with postgresql+psycopg:// (not postgres:// or postgresql://)")
        host = urlparse(db).hostname or ""
        if host in ("localhost", "127.0.0.1", "postgres", "db"):
            warnings.append("DATABASE_URL points at a local host; production should use the managed database")
        if "sslmode=require" not in db and "sslmode=verify" not in db:
            errors.append("DATABASE_URL has no sslmode=require: the database connection must use TLS")

    for key in ("S3_ENDPOINT_URL", "S3_PRESIGN_ENDPOINT_URL", "S3_PUBLIC_BASE_URL"):
        v = val(key)
        if v and not v.startswith("https://"):
            errors.append(f"{key} must be https:// in production")

    for key in ("CAPTURE_TTL_SECONDS", "RESULT_TTL_SECONDS"):
        raw = val(key)
        if not raw:
            warnings.append(f"{key} is not set (the default is 3600)")
        elif not raw.isdigit() or int(raw) > MAX_RETENTION_SECONDS or int(raw) < 60:
            errors.append(f"{key}={raw}: photos and looks must be deleted within {MAX_RETENTION_SECONDS} seconds (the privacy notice says one hour)")
    if val("CAPTURE_CLEANUP_ENABLED").lower() in ("false", "0", "no"):
        errors.append("CAPTURE_CLEANUP_ENABLED is off: nothing would delete photos")

    if val("API_DOCS_ENABLED").lower() not in ("false", "0", "no"):
        errors.append("API_DOCS_ENABLED must be false on a public server")
    if val("RATE_LIMIT_ENABLED").lower() in ("false", "0", "no"):
        errors.append("RATE_LIMIT_ENABLED is off")

    provider = val("TRYON_PROVIDER") or "mock"
    if provider == "mock":
        warnings.append("TRYON_PROVIDER=mock: shoppers will see a fake result")
    elif provider == "fashn" and not val("FASHN_API_KEY"):
        errors.append("TRYON_PROVIDER=fashn needs FASHN_API_KEY")
    elif provider == "catvton" and not (val("RUNPOD_API_KEY") and val("RUNPOD_ENDPOINT_ID")):
        errors.append("TRYON_PROVIDER=catvton needs RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID")
    elif provider not in ("fashn", "catvton"):
        errors.append(f"TRYON_PROVIDER={provider!r} is not one of mock, fashn, catvton")

    if val("PAYMENT_PROVIDER") in ("", "stub"):
        warnings.append("PAYMENT_PROVIDER=stub approves every payment: do not take real money with it")
    if not val("SENTRY_DSN"):
        warnings.append("SENTRY_DSN is empty: errors will not be reported anywhere")
    if val("NOTIFIER") in ("", "console"):
        warnings.append("NOTIFIER=console: staff are not messaged when a shopper asks for an item")
    return errors, warnings


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(__file__).with_name(".env.production")
    if not path.exists():
        print(f"{path} not found. Copy .env.production.example and fill it in.", file=sys.stderr)
        return 1
    errors, warnings = check(parse_env(path.read_text()))
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR:   {e}")
    if errors:
        print(f"\n{len(errors)} problem(s) to fix before deploying.")
        return 1
    print("preflight passed" + (f" with {len(warnings)} warning(s)" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
