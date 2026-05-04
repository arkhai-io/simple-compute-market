"""Negotiate controller — buyer ↔ seller negotiation protocol.

Buyer auth is verified by calling the buyer_auth module directly inside
each handler (rather than via Depends) to avoid interactions between
fastapi_utils @cbv and method-level Depends dependencies.
Tests bypass auth by monkeypatching buyer_auth._verify to a no-op.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.models.negotiation_models import (
    NegotiateContinueRequest,
    NegotiateNewRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/negotiate", tags=["negotiate"])


@cbv(router)
class NegotiateController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
    ) -> None:
        self._db = db

    @router.post("/new", summary="Start a new negotiation (EIP-191 signed by buyer)")
    async def negotiate_new(
        self,
        body: NegotiateNewRequest,
        request: Request,
    ) -> dict[str, Any]:
        from market_storefront.middleware import buyer_auth
        from market_storefront.utils.config import CONFIG
        from market_storefront.utils.sync_negotiation import (
            StorefrontPausedError,
            start_sync_negotiation,
        )

        buyer_auth._verify(request, "negotiate_new", body.listing_id, body.buyer_address)

        base_url = CONFIG.base_url_override or ""
        try:
            return await start_sync_negotiation(
                sqlite_client=self._db,
                our_listing_id=body.listing_id,
                buyer_address=body.buyer_address,
                their_proposed_price=body.initial_price,
                requested_duration_seconds=body.duration_seconds,
                our_base_url=base_url,
                their_agent_url=body.buyer_agent_url or body.buyer_address,
            )
        except StorefrontPausedError as exc:
            raise HTTPException(status_code=503, detail={
                "error": "paused", "reason": exc.reason,
                "hint": "Storefront or order is paused; use admin API to advance or resume",
            })
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATE/new] %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/{neg_id}", summary="Advance an existing negotiation (EIP-191 signed by buyer)")
    async def negotiate_continue(
        self,
        neg_id: str,
        body: NegotiateContinueRequest,
        request: Request,
    ) -> dict[str, Any]:
        from market_storefront.middleware import buyer_auth
        from market_storefront.utils.sync_negotiation import continue_sync_negotiation

        buyer_auth._verify(request, "negotiate_continue", neg_id, body.buyer_address)

        if body.action == "counter" and body.price is None:
            raise HTTPException(status_code=400, detail="'price' required as int for counter")

        try:
            return await continue_sync_negotiation(
                sqlite_client=self._db,
                neg_id=neg_id,
                buyer_action=body.action,
                buyer_price=body.price,
                buyer_reason=body.reason,
                buyer_address=body.buyer_address,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATE/%s] %s", neg_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
