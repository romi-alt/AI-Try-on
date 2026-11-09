"""deploy/preflight.py: the example file must fail until filled in, and each mistake must be caught."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import preflight  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[1] / ".env.production.example"

GOOD = {
    "API_DOMAIN": "api.shop.example",
    "ACME_EMAIL": "ops@shop.example",
    "DATABASE_URL": "postgresql+psycopg://u:p@db.managed.example:5432/tryon?sslmode=require",
    "REDIS_PASSWORD": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6",
    "API_CORS_ORIGINS": "https://mirror.shop.example,https://admin.shop.example",
    "ADMIN_API_KEY": "0123456789abcdef0123456789abcdef0123456789abcdef",
    "STAFF_API_KEY": "fedcba9876543210fedcba9876543210fedcba9876543210",
    "S3_ENDPOINT_URL": "https://acct.r2.cloudflarestorage.com",
    "S3_PRESIGN_ENDPOINT_URL": "https://acct.r2.cloudflarestorage.com",
    "S3_BUCKET": "mirror-media",
    "S3_ACCESS_KEY_ID": "AKIAEXAMPLE0000000",
    "S3_SECRET_ACCESS_KEY": "s3secret0123456789abcdef0123456789abcdef",
    "S3_PUBLIC_BASE_URL": "https://media.shop.example",
    "CAPTURE_TTL_SECONDS": "3600",
    "RESULT_TTL_SECONDS": "3600",
    "CAPTURE_CLEANUP_ENABLED": "true",
    "API_DOCS_ENABLED": "false",
    "RATE_LIMIT_ENABLED": "true",
    "TRYON_PROVIDER": "fashn",
    "FASHN_API_KEY": "fa-key",
    "SENTRY_DSN": "https://k@o1.ingest.sentry.io/1",
    "NOTIFIER": "whatsapp",
    "PAYMENT_PROVIDER": "real",
}


def run(**over):
    env = {**GOOD, **over}
    return preflight.check({k: v for k, v in env.items() if v is not None})


def test_a_complete_configuration_passes_with_no_errors():
    errors, warnings = run()
    assert errors == [] and warnings == []


def test_the_example_file_fails_until_it_is_filled_in():
    errors, _ = preflight.check(preflight.parse_env(EXAMPLE.read_text()))
    assert any("CHANGE_ME" in e for e in errors)
    assert len(errors) >= 10


def test_the_example_lists_every_required_setting():
    keys = set(preflight.parse_env(EXAMPLE.read_text()))
    assert set(preflight.REQUIRED) <= keys


@pytest.mark.parametrize("key", preflight.REQUIRED)
def test_every_required_setting_is_required(key):
    errors, _ = run(**{key: None})
    assert any(key in e for e in errors)


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"ADMIN_API_KEY": "dev-admin-key"}, "development default"),
        ({"STAFF_API_KEY": "dev-staff-key"}, "development default"),
        ({"ADMIN_API_KEY": "short"}, "too short"),
        ({"STAFF_API_KEY": GOOD["ADMIN_API_KEY"]}, "must differ"),
        ({"REDIS_PASSWORD": "has/slash+and=signs" + "x" * 10}, "letters and digits"),
        ({"API_DOMAIN": "https://api.shop.example"}, "bare host"),
        ({"API_CORS_ORIGINS": "http://mirror.shop.example"}, "non-https"),
        ({"API_CORS_ORIGINS": "https://localhost:3000"}, "plain https origin"),
        ({"API_CORS_ORIGINS": "https://mirror.shop.example/"}, "plain https origin"),
        ({"API_CORS_ORIGINS": " , "}, "empty"),
        ({"DATABASE_URL": "postgresql+psycopg://u:p@h:5432/db"}, "sslmode"),
        ({"DATABASE_URL": "postgres://u:p@h:5432/db?sslmode=require"}, "postgresql+psycopg"),
        ({"S3_PUBLIC_BASE_URL": "http://media.shop.example"}, "https"),
        ({"CAPTURE_TTL_SECONDS": "86400"}, "within 3600"),
        ({"RESULT_TTL_SECONDS": "7200"}, "within 3600"),
        ({"RESULT_TTL_SECONDS": "soon"}, "within 3600"),
        ({"CAPTURE_CLEANUP_ENABLED": "false"}, "nothing would delete"),
        ({"API_DOCS_ENABLED": "true"}, "API_DOCS_ENABLED"),
        ({"API_DOCS_ENABLED": None}, "API_DOCS_ENABLED"),
        ({"RATE_LIMIT_ENABLED": "false"}, "RATE_LIMIT_ENABLED"),
        ({"TRYON_PROVIDER": "fashn", "FASHN_API_KEY": None}, "FASHN_API_KEY"),
        ({"TRYON_PROVIDER": "catvton"}, "RUNPOD_API_KEY"),
        ({"TRYON_PROVIDER": "magic"}, "not one of"),
    ],
)
def test_each_mistake_is_caught(over, needle):
    errors, _ = run(**over)
    assert any(needle in e for e in errors), (over, errors)


def test_retention_below_the_promise_is_fine():
    assert run(CAPTURE_TTL_SECONDS="900", RESULT_TTL_SECONDS="1800")[0] == []


def test_warnings_do_not_fail_the_deploy():
    errors, warnings = run(TRYON_PROVIDER="mock", PAYMENT_PROVIDER="stub", SENTRY_DSN="", NOTIFIER="console")
    assert errors == []
    text = " ".join(warnings)
    for needle in ("mock", "stub", "SENTRY_DSN", "NOTIFIER"):
        assert needle in text


def test_the_command_line_exit_codes(tmp_path, capsys):
    bad = tmp_path / "bad.env"
    bad.write_text("API_DOMAIN=CHANGE_ME\n")
    assert preflight.main(["preflight.py", str(bad)]) == 1
    good = tmp_path / "good.env"
    good.write_text("\n".join(f"{k}={v}" for k, v in GOOD.items()))
    assert preflight.main(["preflight.py", str(good)]) == 0
    assert preflight.main(["preflight.py", str(tmp_path / "missing.env")]) == 1
    assert "preflight passed" in capsys.readouterr().out


def test_dotenv_parsing_handles_comments_quotes_and_spaces():
    env = preflight.parse_env("# c\nA=1\n B = \"two\" \nC='three'\nnot a line\nD=a=b\n")
    assert env == {"A": "1", "B": "two", "C": "three", "D": "a=b"}
