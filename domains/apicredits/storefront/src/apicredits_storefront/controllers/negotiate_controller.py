"""Buyer/seller negotiation authenticated by canonical marketplace principals."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_utils.cbv import cbv
from pydantic import ValidationError

import apicredits_storefront.container as _container
from apicredits_storefront.middleware import buyer_auth
from apicredits_storefront.utils.config import BASE_URL_OVERRIDE
from core_storefront.models.negotiation_models import (
    NegotiateContinueRequest,
    NegotiateContinueResponse,
    NegotiateNewRequest,
    NegotiateNewResponse,
)
from market_negotiation_runtime import (
    NegotiationRuntime,
    OfferUnfulfillableError,
    StorefrontPausedError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/negotiate", tags=["negotiate"])

def _seller_principal():
    signer = _container.resolved_marketplace_signer
    if signer is None:
        raise HTTPException(status_code=503, detail="storefront is not initialized")
    return signer.identity


def _proposal_payload(proposal: Any, settlement_selection: Any) -> Any:
    if settlement_selection is None:
        return proposal
    selection = settlement_selection.model_dump(mode="json")
    if proposal is None:
        return {"settlement_selection": selection}
    payload = (
        dict(proposal)
        if isinstance(proposal, dict)
        else proposal.model_dump(mode="json")
    )
    payload["settlement_selection"] = selection
    return payload


@cbv(router)
class NegotiateController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        runtime: NegotiationRuntime = Depends(
            lambda: _container.resolved_negotiation_runtime
        ),
    ) -> None:
        if runtime is None:
            raise RuntimeError(
                "negotiation controller requires the composed kit runtime"
            )
        self._db = db
        self._runtime = runtime

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

        seller_principal = _seller_principal()
        auth = await buyer_auth._verify(
            request,
            "negotiate_new",
            body.listing_id,
            expected_principal=body.buyer_principal,
            body=body,
            allow_exact_retry=True,
        )
        if auth.exact_retry:
            if auth.recorded_outcome is None:
                raise HTTPException(status_code=409, detail="request retry is pending")
            status_code, payload = auth.recorded_outcome
            if status_code >= 400:
                raise HTTPException(status_code=status_code, detail=payload)
            return NegotiateNewResponse.model_validate(payload)

        try:
            result = await self._runtime.start(
                repository=self._db,
                listing_id=body.listing_id,
                buyer_principal=body.buyer_principal,
                seller_principal=seller_principal,
                actor_principal=auth.principal,
                terms=body.provision_terms,
                proposal=_proposal_payload(
                    body.proposal,
                    body.settlement_selection,
                ),
                seller_agent_url=BASE_URL_OVERRIDE or "",
                buyer_agent_url=body.buyer_agent_url,
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

        seller_principal = _seller_principal()
        auth = await buyer_auth._verify(
            request,
            "negotiate_continue",
            neg_id,
            expected_principal=body.buyer_principal,
            body=body,
            allow_exact_retry=True,
        )
        if auth.exact_retry:
            if auth.recorded_outcome is None:
                raise HTTPException(status_code=409, detail="request retry is pending")
            status_code, payload = auth.recorded_outcome
            if status_code >= 400:
                raise HTTPException(status_code=status_code, detail=payload)
            return NegotiateContinueResponse.model_validate(payload)

        if (
            body.action == "counter"
            and body.proposal is None
            and body.settlement_selection is None
        ):
            raise HTTPException(
                status_code=400,
                detail="'proposal' required for counter",
            )

        try:
            result = await self._runtime.continue_negotiation(
                repository=self._db,
                negotiation_id=neg_id,
                buyer_action=body.action,
                buyer_proposal=_proposal_payload(
                    body.proposal,
                    body.settlement_selection,
                ),
                buyer_reason=body.reason,
                buyer_principal=body.buyer_principal,
                actor_principal=auth.principal,
                actor_role="buyer",
                seller_principal=seller_principal,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATE/%s] %s", neg_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return NegotiateContinueResponse(**result)
