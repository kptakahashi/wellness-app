from __future__ import annotations

from fastapi import Header, HTTPException, Query, Request, status

from .config import settings

# In demo mode anyone may browse and answer cards, but nobody may feed data or change settings.
DEMO_PROTECTED_PREFIXES = ("/api/ingest", "/api/settings", "/api/calendar", "/api/notes")


async def require_token(
    request: Request,
    x_api_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """Simple shared-secret auth. The Android app sends X-Api-Token; the web UI may use ?token=."""
    supplied = x_api_token or token
    if settings.demo_mode and not request.url.path.startswith(DEMO_PROTECTED_PREFIXES):
        return
    if supplied != settings.app_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
