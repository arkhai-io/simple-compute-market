"""Buyer/seller negotiation authenticated by canonical marketplace principals."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_utils.cbv import cbv
from pydantic import ValidationError

import apicredits_storefront.container as _container
from apicredits_storefront.middleware import buyer_auth
from core_storefront.models.negotiation_models import (
    NegotiateContinueRequest,
    NegotiateContinueResponse,
    NegotiateNewRequest,
    NegotiateNewResponse,
)
from market_core import MarketDomainContract

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/negotiate", tags=["negotiate"])

def _seller_principal():
    signer = _container.resolved_marketplace_signer
    if signer is None:
        raise HTTPException(status_code=503, detail="storefront is not initialized")
    return signer.identity


@cbv(router)
class NegotiateController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        domain: MarketDomainContract = Depends(
            lambda: _container.resolved_market_domain
        ),
    ) -> None:
        if domain is None:
            raise RuntimeError("API-credit market-domain contract is unavailable")
        self._db = db
        self._domain = domain

    @router.post(
        "/new",
        response_model=NegotiateNewResponse,
        summary="Start a new negotiation",
        description=(
            "Requires shared body-bound marketplace signature version 2 headers."
        ),
    )
    async def negotiate_new(
        self,
        body: NegotiateNewRequest,
        request: Request,
    ) -> NegotiateNewResponse:
        from apicredits_storefront.utils.config import BASE_URL_OVERRIDE
        from apicredits_storefront.utils.sync_negotiation import (
            OfferUnfulfillableError,
            StorefrontPausedError,
            start_sync_negotiation,
        )

        seller_principal = _seller_principal()
        await buyer_auth._verify(
            request,
            "negotiate_new",
            body.listing_id,
            expected_principal=body.buyer_principal,
            body=body,
        )

        try:
            result = await start_sync_negotiation(
                sqlite_client=self._db,
                domain=self._domain,
                our_listing_id=body.listing_id,
                buyer_principal=body.buyer_principal,
                seller_principal=seller_principal,
                provision_terms=body.provision_terms,
                proposal=body.proposal,
                our_base_url=BASE_URL_OVERRIDE or "",
                their_agent_url=body.buyer_agent_url,
            )
        except StorefrontPausedError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "paused",
                    "reason": exc.reason,
                    "hint": "Storefront or listing is paused.",
                },
            )
        except OfferUnfulfillableError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "offer_unfulfillable",
                    "reason": exc.reason,
                    "listing_id": exc.listing_id,
                    "hint": (
                        "Seller refused: listing is closed, the quota cannot "
                        "cover the requested quantity, or the key claim was "
                        "rejected. See `reason`."
                    ),
                },
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "incompatible_provision_terms",
                    "reason": str(exc),
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATE/new] %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        result["buyer_principal"] = body.buyer_principal
        result["seller_principal"] = seller_principal
        return NegotiateNewResponse(**result)

    @router.post(
        "/{neg_id}",
        response_model=NegotiateContinueResponse,
        summary="Advance an existing negotiation",
        description=(
            "Requires shared body-bound marketplace signature version 2 headers."
        ),
    )
    async def negotiate_continue(
        self,
        neg_id: str,
        body: NegotiateContinueRequest,
        request: Request,
    ) -> NegotiateContinueResponse:
        from apicredits_storefront.utils.sync_negotiation import (
            continue_sync_negotiation,
        )

        seller_principal = _seller_principal()
        await buyer_auth._verify(
            request,
            "negotiate_continue",
            neg_id,
            expected_principal=body.buyer_principal,
            body=body,
        )

        if body.action == "counter" and body.proposal is None:
            raise HTTPException(
                status_code=400,
                detail="'proposal' required for counter",
            )

        try:
            result = await continue_sync_negotiation(
                sqlite_client=self._db,
                domain=self._domain,
                neg_id=neg_id,
                buyer_action=body.action,
                buyer_proposal=body.proposal,
                buyer_reason=body.reason,
                buyer_principal=body.buyer_principal,
                seller_principal=seller_principal,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATE/%s] %s", neg_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        result["buyer_principal"] = body.buyer_principal
        result["seller_principal"] = seller_principal
        return NegotiateContinueResponse(**result)
