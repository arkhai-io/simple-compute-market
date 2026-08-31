"""Authenticated bounded resolution of signed API-credit issuance evidence."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from domains.apicredits.settlement.issuance_evidence import (
    SignedApiCreditsIssuanceEvidenceV1,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from market_identity import Identity

from apicredits_storefront.services.issuance_evidence import (
    ApiCreditsIssuanceEvidenceService,
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
EvidenceAuthenticator = Callable[[Request], Awaitable[Identity]]


def make_issuance_evidence_router(
    get_service: Callable[[], ApiCreditsIssuanceEvidenceService],
    authenticate: EvidenceAuthenticator,
) -> APIRouter:
    """Build the resolver route with mandatory caller authentication injection."""

    router = APIRouter(tags=["api-credit-issuance-evidence"])

    @router.get(
        "/issuance-evidence/{evidence_digest}",
        response_model=SignedApiCreditsIssuanceEvidenceV1,
        name="resolve_api_credit_issuance_evidence",
    )
    async def resolve_api_credit_issuance_evidence(
        evidence_digest: str,
        request: Request,
        service: ApiCreditsIssuanceEvidenceService = Depends(get_service),
    ) -> SignedApiCreditsIssuanceEvidenceV1:
        if not _SHA256.fullmatch(evidence_digest):
            raise HTTPException(status_code=422, detail="invalid evidence digest")
        await authenticate(request)
        evidence = service.resolve(evidence_digest)
        if evidence is None:
            raise HTTPException(status_code=404, detail="issuance evidence not found")
        return evidence

    return router
