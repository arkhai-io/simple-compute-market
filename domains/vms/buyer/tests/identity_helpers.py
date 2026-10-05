from __future__ import annotations

import base64
import json
import time
from typing import Any

from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import (
    Ed25519Signer,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
)

BUYER_SIGNER = Ed25519Signer(b"\x31" * 32)
SELLER_SIGNER = Ed25519Signer(b"\x32" * 32)
SELLER_TRUST = TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))


def seller_principals() -> TrustedIdentitySet:
    return SELLER_TRUST

def alkahest_option(proposal: dict[str, Any] | None = None) -> SettlementOption:
    params = {"accepted_escrow": proposal or {}}
    token = (proposal or {}).get("fields", {}).get("token") or "usd"
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="alkahest.v1", asset=token, rates=[], params=params,
        ),
        mechanism="alkahest.v1", asset=token, rates=[], params=params,
    )


def accepted_alkahest_agreement(negotiation_id, listing_id, amount, provision, proposal):
    option = alkahest_option(proposal.model_dump(mode="json"))
    return Agreement(
        negotiation_id=negotiation_id, listing_id=listing_id, listing_hash="0" * 64,
        buyer=BUYER_SIGNER.identity.model_dump(mode="json"),
        seller=SELLER_SIGNER.identity.model_dump(mode="json"),
        settlement=option, asset=option.asset, amount=amount,
        duration_seconds=provision.duration_seconds,
        provision_terms=provision.model_dump(mode="json"),
        start_utc="2025-01-01T00:00:00Z", accepted_at="2025-01-01T00:00:00Z",
    )


def with_accepted_agreement(request: Any, body: dict[str, Any]) -> dict[str, Any]:
    if body.get("action") != "accept" or body.get("agreement") is not None:
        return body

    request_body = (
        json.loads(request.data.decode("utf-8")) if getattr(request, "data", None) else {}
    )
    negotiation_id = body.get("negotiation_id") or request.full_url.rstrip("/").rsplit("/", 1)[-1]
    listing_id = request_body.get("listing_id") or "L-1"
    provision_terms = body.get("accepted_provision_terms") or request_body.get("provision_terms")
    if not isinstance(provision_terms, dict):
        provision_terms = None
    payload = provision_terms.get("payload", {}) if provision_terms else {}
    duration = payload.get("duration_seconds", 0) if isinstance(payload, dict) else 0
    start_utc = payload.get("start_utc") if isinstance(payload, dict) else None
    accepted_at = "2025-01-01T00:00:00Z"
    if not isinstance(start_utc, str) or start_utc.strip().lower() in {"", "now"}:
        start_utc = accepted_at
    body = dict(body)
    body.setdefault("accepted_escrow_proposal", {
        "chain_name": "anvil", "escrow_address": "0x" + "cd" * 20,
        "fields": {}, "expiration_unix": 1_800_000_000,
    })
    proposal = body.get("proposal")
    fields = proposal.get("fields") if isinstance(proposal, dict) else None
    amount = int(fields.get("amount", 0)) if isinstance(fields, dict) else 0
    buyer = request_body.get("buyer_principal") or BUYER_SIGNER.identity.model_dump(mode="json")
    seller = SELLER_SIGNER.identity.model_dump(mode="json")
    agreement = Agreement(
        negotiation_id=str(negotiation_id),
        listing_id=str(listing_id),
        listing_hash="0" * 64,
        buyer=buyer,
        seller=seller,
        settlement=alkahest_option(body.get("accepted_escrow_proposal")),
        asset=alkahest_option(body.get("accepted_escrow_proposal")).asset,
        amount=amount,
        duration_seconds=int(duration),
        start_utc=start_utc,
        provision_terms=provision_terms,
        accepted_at=accepted_at,
    )
    agreement_bytes = agreement.model_dump_json(exclude_none=True).encode("utf-8")
    return {
        **body,
        "buyer_principal": buyer,
        "seller_principal": seller,
        "agreement": agreement.model_dump(mode="json", exclude_none=True),
        "agreement_bytes": base64.b64encode(agreement_bytes).decode("ascii"),
    }


def signed_response_headers(
    request: Any,
    body: dict[str, Any],
    *,
    status: int = 200,
) -> dict[str, str]:
    request_headers = {key.lower(): value for key, value in request.header_items()}
    url = request.full_url.rstrip("/")
    if url.endswith("/negotiate/new"):
        operation = "negotiate_new"
        resource = str(body.get("listing_id") or "")
        if request.data:
            import json

            resource = str(json.loads(request.data.decode("utf-8"))["listing_id"])
    elif url.endswith("/status") and "/settle/" in url:
        operation = "settle_status"
        resource = url.rsplit("/", 2)[-2]
    elif "/settle/" in url:
        operation = "settle_escrow"
        resource = url.rsplit("/", 1)[-1]
    else:
        operation = "negotiate_continue"
        resource = url.rsplit("/", 1)[-1]
    timestamp = int(time.time())
    signed = sign_response(
        signer=SELLER_SIGNER,
        envelope=ResponseEnvelope(
            role="seller",
            principal=SELLER_SIGNER.identity,
            method=request.get_method(),
            operation=operation,
            resource=resource,
            request_id=request_headers["x-market-request-id"],
            timestamp=timestamp,
            status=status,
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        "X-Market-Signature-Version": signed.protocol,
        "X-Market-Identity-Scheme": signed.principal.scheme.value,
        "X-Market-Identity-Identifier": signed.principal.identifier,
        "X-Market-Role": signed.role,
        "X-Market-Request-ID": signed.request_id,
        "X-Market-Timestamp": str(signed.timestamp),
        "X-Market-Signature": signed.proof.value,
    }
