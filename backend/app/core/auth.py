from __future__ import annotations

from fastapi import Header, HTTPException, Query, status

from .config import settings


async def require_token(
    x_api_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """Simple shared-secret auth. The Android app sends X-Api-Token; the web UI may use ?token=."""
    supplied = x_api_token or token
    if settings.demo_mode and not supplied:
        return
    if supplied != settings.app_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
