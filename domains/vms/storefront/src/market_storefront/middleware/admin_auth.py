"""Fail-closed administrator dependency with service-callback bypass."""

from __future__ import annotations

from fastapi import HTTPException, Request




async def require_admin_key(request: Request) -> None:
    """Reject legacy admin-key auth; service callbacks are verified upstream."""

    if getattr(request.state, "service_peer_authenticated", False) or getattr(
        request.state, "administrator_authenticated", False
    ):
        return
    raise HTTPException(
        status_code=401,
        detail="Administrator requests require marketplace v2 principal authentication",
    )
