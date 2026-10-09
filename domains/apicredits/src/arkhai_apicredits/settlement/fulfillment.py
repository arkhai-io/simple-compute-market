"""Mechanism-neutral credit issuance from verified domain evidence."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping

from market_core import SettlementEvidence
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Awaitable, Callable

from market_identity import Identity

from arkhai_apicredits.settlement.credits_client import (
    CreditIssuanceRequest,
    CreditKeyTarget,
    CreditsServiceClient,
    CreditsServiceError,
)

logger = logging.getLogger(__name__)

StageEventFn = Callable[..., Any]
ApplyFailurePolicyFn = Callable[..., Awaitable[None]]


class CreditDelivery(BaseModel):
    """Validated purchase inputs produced by the authoritative settlement stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    owner: Identity
    listing_resource: dict[str, Any]
    quantity: int = Field(ge=1)
    key_mode: str
    key_id: str | None = None
    listing_id: str | None = None


def credit_delivery(evidence: SettlementEvidence, *, require_verified: bool = True) -> CreditDelivery:
    if require_verified and evidence.status != "verified":
        raise ValueError("credit issuance requires verified settlement evidence")
    payload = evidence.evidence
    if payload.get("kind") != "api_credits.settlement-evidence.v1" or payload.get("schema_version") != 1:
        raise ValueError("unsupported credit settlement evidence envelope")
    digest = payload.get("agreement_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("credit settlement evidence requires its Agreement digest")
    if not isinstance(payload.get("source"), Mapping):
        raise ValueError("credit settlement evidence requires authoritative source state")
    delivery = CreditDelivery.model_validate(payload.get("delivery"))
    CreditKeyTarget.model_validate({"mode": delivery.key_mode, "key_id": delivery.key_id})
    if not str(delivery.listing_resource.get("service_name") or "").strip() or not str(delivery.listing_resource.get("resource_id") or "").strip():
        raise ValueError("credit settlement evidence requires service_name and quota resource")
    return delivery


def prepare_credit_issuance_request(
    *,
    evidence: SettlementEvidence,
    capacity_reservation_id: str | None = None,
) -> CreditIssuanceRequest:
    """Authorize the exact validated purchase over the operator-authenticated channel."""
    delivery = credit_delivery(evidence)
    return CreditIssuanceRequest.create(
        negotiation_id=evidence.negotiation_id,
        owner=delivery.owner,
        service=str(delivery.listing_resource["service_name"]),
        resource_id=str(delivery.listing_resource["resource_id"]),
        quantity=delivery.quantity,
        key=CreditKeyTarget.model_validate({"mode": delivery.key_mode, "key_id": delivery.key_id}),
        capacity_reservation_id=capacity_reservation_id,
    )


def encode_credit_fulfillment(
    *,
    listing_resource: dict[str, Any],
    key_id: str,
    quantity: int,
) -> str:
    """The seller's fulfillment obligation payload (public — no secret)."""
    return json.dumps(
        {
            "kind": "api_credits.v1",
            "service_name": listing_resource.get("service_name"),
            "base_url": listing_resource.get("base_url"),
            "key_id": key_id,
            "quantity": int(quantity),
        }
    )


async def fulfill_api_credits_obligation(
    *,
    evidence: SettlementEvidence,
    retry_uncertain: bool = False,
    credits_client: CreditsServiceClient | None = None,
    service_url: str | None = None,
    admin_key: str | None = None,
    stage_event: StageEventFn,
    apply_failure_policy: ApplyFailurePolicyFn | None = None,
    held_reservation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Issue credits from verified purchase evidence; stage continuations own attestation."""
    delivery = credit_delivery(evidence)
    settlement_ref = evidence.settlement_ref
    listing_resource = delivery.listing_resource
    quantity = delivery.quantity
    listing_id = delivery.listing_id
    capacity_reservation_id = (
        str(held_reservation.get("capacity_reservation_id"))
        if held_reservation and held_reservation.get("capacity_reservation_id")
        else None
    )
    resource_id = listing_resource.get("resource_id")
    if credits_client is None:
        if service_url is None or admin_key is None:
            raise ValueError("credits_client or service_url/admin_key is required")
        credits_client = CreditsServiceClient(service_url, admin_key)

    async def _fail(reason: str, message: str) -> dict[str, Any]:
        if apply_failure_policy is not None:
            try:
                await apply_failure_policy(
                    capacity_reservation_id=capacity_reservation_id,
                    settlement_ref=settlement_ref,
                    negotiation_id=evidence.negotiation_id,
                    listing_id=listing_id,
                    resource_id=resource_id,
                    reason=reason,
                    message=message,
                    source="settlement_issuance",
                )
            except Exception as policy_err:
                logger.warning(
                    "[FULFILLMENT_POLICY] Failed to apply issuance failure "
                    "policy for settlement %s: %s",
                    settlement_ref,
                    policy_err,
                )
        stage_event(
            "provision",
            "failed",
            settlement_ref=settlement_ref,
            listing_id=listing_id,
            resource_id=resource_id,
            error=message,
        )
        return {
            "status": "error",
            "message": message,
            "settlement_ref": settlement_ref,
        }

    service_name = str(listing_resource.get("service_name") or "")
    if not service_name or not resource_id:
        return await _fail(
            "issuance_input_invalid",
            "Issuance requires trusted service_name and resource_id",
        )
    request = prepare_credit_issuance_request(
        evidence=evidence,
        capacity_reservation_id=capacity_reservation_id,
    )
    try:
        issuance = await credits_client.submit_credit_issuance(request)
    except CreditsServiceError as error:
        retryable = (
            error.status_code == 0
            or error.status_code in {408, 425, 429}
            or error.status_code >= 500
        )
        if retry_uncertain and retryable:
            stage_event(
                "provision",
                "issuance_retryable",
                settlement_ref=settlement_ref,
                listing_id=listing_id,
                resource_id=resource_id,
                error=str(error),
            )
            return {
                "status": "pending",
                "message": f"Issuance remains retryable: {error}",
                "settlement_ref": settlement_ref,
            }
        return await _fail(error.reason, f"Issuance refused: {error}")
    except Exception as error:
        if retry_uncertain:
            stage_event(
                "provision",
                "issuance_retryable",
                settlement_ref=settlement_ref,
                listing_id=listing_id,
                resource_id=resource_id,
                error=str(error),
            )
            return {
                "status": "pending",
                "message": f"Issuance remains retryable: {error}",
                "settlement_ref": settlement_ref,
            }
        return await _fail("issuance_unreachable", f"Issuance failed: {error}")

    issued_key_id = issuance.key_id
    stage_event(
        "provision",
        "credits_issued",
        settlement_ref=settlement_ref,
        listing_id=listing_id,
        resource_id=resource_id,
        key_id=issued_key_id,
        quantity=issuance.quantity,
        balance=issuance.balance,
        capacity_reservation_id=(
            issuance.capacity_reservation_id or capacity_reservation_id
        ),
        already_issued=issuance.already_issued,
    )

    payload = encode_credit_fulfillment(
        listing_resource=listing_resource,
        key_id=issued_key_id,
        quantity=quantity,
    )
    fulfillment_uid = issuance.fulfillment_id
    stage_event(
        "provision",
        "fulfilled",
        listing_id=listing_id,
        settlement_ref=settlement_ref,
        fulfillment_uid=fulfillment_uid,
        resource_id=resource_id,
        key_id=issued_key_id,
        quantity=quantity,
    )
    credentials: dict[str, Any] = {
        "key_id": issued_key_id,
        "base_url": listing_resource.get("base_url"),
        "balance": issuance.balance,
    }
    if issuance.secret:
        credentials["secret"] = issuance.secret
    return {
        "status": "fulfilled",
        "message": "API-token obligation fulfilled",
        "settlement_ref": settlement_ref,
        "fulfillment_uid": fulfillment_uid,
        "connection_details": payload,
        "tenant_credentials": credentials,
        "issuance": issuance,
    }
