"""Dev-grade admin auth: a shared key in the X-Admin-Key header.

Replace with a real identity provider before exposing the admin API publicly.
"""

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")
