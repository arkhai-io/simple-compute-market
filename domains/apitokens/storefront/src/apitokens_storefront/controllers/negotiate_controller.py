"""Negotiate controller — buyer ↔ seller negotiation protocol.

Buyer-facing protocol endpoints; auth is EIP-191 signed by the buyer.
Same wire shape as the VM storefront — ``provision_terms`` carries the
api_tokens.v1 payload (quantity + key disposition).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_utils.cbv import cbv

import apitokens_storefront.container as _container
from apitokens_storefront.middleware import buyer_auth
from core_storefront.models.negotiation_models import (
    NegotiateContinueRequest,
    NegotiateContinueResponse,
    NegotiateNewRequest,
    NegotiateNewResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/negotiate", tags=["negotiate"])


@cbv(router)
class NegotiateController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
    ) -> None:
        self._db = db

    @router.post(
        "/new",
        response_model=NegotiateNewResponse,
        summary="Start a new negotiation",
        description=(
            "Buyer-facing protocol endpoint. Requires EIP-191 signed "
            "`X-Signature` + `X-Timestamp` headers."
        ),
    )
    async def negotiate_new(
        self,
        body: NegotiateNewRequest,
        request: Request,
    ) -> NegotiateNewResponse:
        from apitokens_storefront.utils.config import BASE_URL_OVERRIDE
        from apitokens_storefront.utils.sync_negotiation import (
            OfferUnfulfillableError,
            StorefrontPausedError,
            start_sync_negotiation,
        )

        buyer_auth._verify(
            request, "negotiate_new", body.listing_id, body.buyer_address,
        )

        try:
            result = await start_sync_negotiation(
                sqlite_client=self._db,
                our_listing_id=body.listing_id,
                buyer_address=body.buyer_address,
                provision_terms=body.provision_terms,
                proposal=body.proposal,
                our_base_url=BASE_URL_OVERRIDE or "",
                their_agent_url=body.buyer_agent_url or body.buyer_address,
            )
        except StorefrontPausedError as exc:
            raise HTTPException(status_code=503, detail={
                "error": "paused", "reason": exc.reason,
                "hint": "Storefront or listing is paused.",
            })
        except OfferUnfulfillableError as exc:
            raise HTTPException(status_code=409, detail={
                "error": "offer_unfulfillable",
                "reason": exc.reason,
                "listing_id": exc.listing_id,
                "hint": (
                    "Seller refused: listing is closed, the quota cannot "
                    "cover the requested quantity, or the key claim was "
                    "rejected. See `reason`."
                ),
            })
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATE/new] %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return NegotiateNewResponse(**result)

    @router.post(
        "/{neg_id}",
        response_model=NegotiateContinueResponse,
        summary="Advance an existing negotiation",
        description=(
            "Buyer-facing protocol endpoint. Requires EIP-191 signed "
            "`X-Signature` + `X-Timestamp` headers."
        ),
    )
    async def negotiate_continue(
        self,
        neg_id: str,
        body: NegotiateContinueRequest,
        request: Request,
    ) -> NegotiateContinueResponse:
        from apitokens_storefront.utils.sync_negotiation import (
            continue_sync_negotiation,
        )

        buyer_auth._verify(request, "negotiate_continue", neg_id, body.buyer_address)

        if body.action == "counter" and body.proposal is None:
            raise HTTPException(
                status_code=400, detail="'proposal' required for counter",
            )

        try:
            result = await continue_sync_negotiation(
                sqlite_client=self._db,
                neg_id=neg_id,
                buyer_action=body.action,
                buyer_proposal=body.proposal,
                buyer_reason=body.reason,
                buyer_address=body.buyer_address,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATE/%s] %s", neg_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return NegotiateContinueResponse(**result)
