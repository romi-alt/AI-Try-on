"""Dev-grade admin auth: a shared key in the X-Admin-Key header.

Replace with a real identity provider before exposing the admin API publicly.
"""

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


def require_staff(
    x_staff_key: str | None = Header(default=None), x_admin_key: str | None = Header(default=None)
) -> None:
    """Floor staff (the staff page) or an admin. Dev-grade shared keys, like `require_admin`."""
    for given, expected in ((x_staff_key, settings.staff_api_key), (x_admin_key, settings.admin_api_key)):
        if given and hmac.compare_digest(given, expected):
            return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid staff key")
