"""Dev-grade admin auth: a shared key in the X-Admin-Key header.

Replace with a real identity provider before exposing the admin API publicly.
"""

import hmac

from fastapi import Header, HTTPException, Request, status

from app.core.config import settings
from app.core.ratelimit import client_ip, peek_blocked, record_failure, too_many


def _refuse_bad_key(request: Request, detail: str) -> HTTPException:
    """Count a wrong key against the caller's address, then answer 401 (too many earns a 429 first)."""
    record_failure("bad_key_ip", client_ip(request))
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def keys_match(given: str | None, expected: str) -> bool:
    """Constant-time comparison that cannot crash on non-ASCII input (compare_digest rejects it)."""
    return bool(given) and hmac.compare_digest(given.encode(), expected.encode())


def _check_not_locked_out(request: Request) -> None:
    if seconds := peek_blocked("bad_key_ip", client_ip(request)):
        raise too_many(seconds)


def require_admin(request: Request, x_admin_key: str | None = Header(default=None, max_length=256)) -> None:
    _check_not_locked_out(request)
    if not keys_match(x_admin_key, settings.admin_api_key):
        raise _refuse_bad_key(request, "Invalid admin key")


def require_staff(
    request: Request,
    x_staff_key: str | None = Header(default=None, max_length=256),
    x_admin_key: str | None = Header(default=None, max_length=256),
) -> None:
    """Floor staff (the staff page) or an admin. Dev-grade shared keys, like `require_admin`."""
    _check_not_locked_out(request)
    for given, expected in ((x_staff_key, settings.staff_api_key), (x_admin_key, settings.admin_api_key)):
        if keys_match(given, expected):
            return
    raise _refuse_bad_key(request, "Invalid staff key")
