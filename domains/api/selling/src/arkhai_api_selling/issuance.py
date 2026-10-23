"""Mechanism-neutral credit issuance from verified settlement evidence.

The selected seller stage verifies a settlement's source and records it as
evidence bound to the accepted Agreement; everything here reads that evidence
and never compares mechanism IDs. What a deal issues comes from the listing the
Agreement names, as recorded in the evidence, through the domain's issuance
projection: the Agreement pins the listing's ID, the storefront writes a
listing's resource once when it creates the listing, and republishing creates
another listing, so a settled purchase issues what its buyer accepted.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from arkhai_api.issuance import IssuanceRequest, IssuanceResult, KeyDisposition, issuance_request
from arkhai_api.purchase import provision_terms_model
from arkhai_api_client import AuthorityClient, AuthorityError
from market_core import SettlementEvidence
from market_core.schemas import Agreement
from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field

from arkhai_api_selling.contributions import IssuanceSubject, SellingContributions
from arkhai_api_selling.evidence_store import PrivateResultRepository

logger = logging.getLogger(__name__)

StageEventFn = Callable[..., Any]
ApplyFailurePolicyFn = Callable[..., Awaitable[None]]


class MissingQuotaResource(ValueError):
    """A listing names no quota resource, so the authority could issue against nothing."""


class SettlementRefusal(RuntimeError):
    """A settle, status or refund refusal carrying the HTTP status the route returns."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class SettleResult:
    """A stage's settle, status or refund response and its HTTP status."""

    status_code: int
    payload: dict[str, Any] = field(default_factory=dict)


def issuance_subject(
    contributions: SellingContributions,
    listing_resource: Mapping[str, Any],
    *,
    listing_id: str | None = None,
) -> IssuanceSubject:
    """The listing's issuance subject, refusing one that names no service or quota resource.

    Publication and acceptance both call this before anything is recorded, and
    issuance calls it again, so no path issues against a listing without a
    quota resource.
    """
    subject = contributions.issuance_projection(listing_resource)
    named = f"listing {listing_id!r}" if listing_id else "the listing"
    if not subject.service.strip():
        raise MissingQuotaResource(f"{named} names no service")
    if subject.resource_id is None or not subject.resource_id.strip():
        raise MissingQuotaResource(f"{named} names no quota resource")
    return subject


class Delivery(BaseModel):
    """Validated purchase inputs produced by the authoritative settlement stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    owner: Identity
    listing_resource: dict[str, Any]
    quantity: int = Field(ge=1)
    key_mode: str
    key_id: str | None = None
    listing_id: str | None = None


def delivery(
    contributions: SellingContributions,
    evidence: SettlementEvidence,
    *,
    require_verified: bool = True,
) -> Delivery:
    if require_verified and evidence.status != "verified":
        raise ValueError("credit issuance requires verified settlement evidence")
    payload = evidence.evidence
    if (
        payload.get("kind") != contributions.settlement_evidence_kind
        or payload.get("schema_version") != 1
    ):
        raise ValueError("unsupported credit settlement evidence envelope")
    digest = payload.get("agreement_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("credit settlement evidence requires its Agreement digest")
    if not isinstance(payload.get("source"), Mapping):
        raise ValueError("credit settlement evidence requires authoritative source state")
    accepted = Delivery.model_validate(payload.get("delivery"))
    KeyDisposition.model_validate({"mode": accepted.key_mode, "key_id": accepted.key_id})
    try:
        issuance_subject(contributions, accepted.listing_resource)
    except MissingQuotaResource as exc:
        raise ValueError(
            "credit settlement evidence requires a service and a quota resource"
        ) from exc
    return accepted


def accepted_agreement(thread: Mapping[str, Any]) -> tuple[Agreement, bytes]:
    raw = thread.get("agreement_bytes")
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if thread.get("terminal_state") != "success" or not isinstance(raw, bytes):
        raise ValueError("accepted Agreement is unavailable")
    agreement = Agreement.model_validate_json(raw)
    if agreement.settlement is None:
        raise ValueError("accepted Agreement has no selected settlement option")
    if Identity.model_validate(agreement.buyer) != Identity.model_validate(thread["buyer_principal"]):
        raise ValueError("accepted Agreement buyer differs from negotiation")
    if Identity.model_validate(agreement.seller) != Identity.model_validate(thread["seller_principal"]):
        raise ValueError("accepted Agreement seller differs from negotiation")
    if agreement.negotiation_id != thread["negotiation_id"]:
        raise ValueError("accepted Agreement negotiation binding differs")
    return agreement, raw


def stored_listing_resource(value: Any) -> Any:
    """A stored listing's ``listing_resource``, decoded when the store keeps it as JSON text."""
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def settlement_evidence(
    contributions: SellingContributions,
    agreement: Agreement,
    raw: bytes,
    *,
    reference: str,
    status: str,
    source: Mapping[str, Any],
    order: Mapping[str, Any],
) -> SettlementEvidence:
    """Evidence binding the accepted Agreement to the listing it names, ``order``."""
    provision = agreement.provision_terms or {}
    terms = provision_terms_model(contributions.kind).model_validate(
        {key: provision[key] for key in ("kind", "version", "payload")}
    )
    listing = contributions.listing_schema.model_validate(
        {"listing_resource": stored_listing_resource(order.get("listing_resource"))}
    )
    accepted = {
        "owner": agreement.buyer,
        "listing_resource": listing.listing_resource.model_dump(mode="json"),
        "quantity": terms.quantity, "key_mode": terms.key_mode, "key_id": terms.key_id,
        "listing_id": agreement.listing_id,
    }
    evidence = SettlementEvidence(
        agreement.negotiation_id, agreement.settlement.mechanism, reference, status,
        {"kind": contributions.settlement_evidence_kind, "schema_version": 1,
         "agreement_digest": hashlib.sha256(raw).hexdigest(),
         "source": dict(source), "delivery": accepted},
    )
    delivery(contributions, evidence, require_verified=False)
    return evidence


def prepare_issuance_request(
    contributions: SellingContributions,
    *,
    evidence: SettlementEvidence,
    capacity_reservation_id: str | None = None,
) -> IssuanceRequest:
    """Authorize the exact validated purchase over the operator-authenticated channel."""
    accepted = delivery(contributions, evidence)
    subject = issuance_subject(contributions, accepted.listing_resource)
    return issuance_request(
        contributions.label,
        negotiation_id=evidence.negotiation_id,
        owner=accepted.owner,
        service=subject.service,
        resource_id=str(subject.resource_id),
        quantity=accepted.quantity,
        key=KeyDisposition.model_validate({"mode": accepted.key_mode, "key_id": accepted.key_id}),
        capacity_reservation_id=capacity_reservation_id,
    )


def connection_payload(
    contributions: SellingContributions,
    *,
    subject: IssuanceSubject,
    key_id: str,
    quantity: int,
) -> str:
    """The seller's public fulfillment payload; never the secret."""
    return json.dumps(
        {
            "kind": contributions.kind,
            "service_name": subject.service,
            "base_url": subject.endpoint,
            "key_id": key_id,
            "quantity": int(quantity),
        }
    )


def result_mismatch(request: IssuanceRequest, result: IssuanceResult) -> str | None:
    """The first field in which ``result`` does not answer ``request``, or ``None``.

    The capacity reservation is not compared: the authority may replace an
    expired hold with a fresh reservation under the same grant.
    """
    expected = {
        "fulfillment_id": request.fulfillment_id,
        "grant_id": request.fulfillment_id,
        "request_digest": request.request_digest,
        "negotiation_id": request.negotiation_id,
        "owner": request.owner,
        "service": request.service,
        "resource_id": request.resource_id,
        "quantity": request.quantity,
        "key_mode": request.key.mode,
    }
    if request.key.key_id is not None:
        expected["key_id"] = request.key.key_id
    for field_name, value in expected.items():
        if getattr(result, field_name) != value:
            return field_name
    return None


async def fulfill(
    contributions: SellingContributions,
    *,
    evidence: SettlementEvidence,
    retry_uncertain: bool = False,
    credits_client: AuthorityClient,
    stage_event: StageEventFn,
    apply_failure_policy: ApplyFailurePolicyFn | None = None,
    held_reservation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Issue credits from verified purchase evidence; stage continuations own attestation."""
    accepted = delivery(contributions, evidence)
    settlement_ref = evidence.settlement_ref
    listing_resource = accepted.listing_resource
    quantity = accepted.quantity
    listing_id = accepted.listing_id
    capacity_reservation_id = (
        str(held_reservation.get("capacity_reservation_id"))
        if held_reservation and held_reservation.get("capacity_reservation_id")
        else None
    )
    subject = issuance_subject(contributions, listing_resource, listing_id=listing_id)
    resource_id = subject.resource_id

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

    request = prepare_issuance_request(
        contributions,
        evidence=evidence,
        capacity_reservation_id=capacity_reservation_id,
    )
    try:
        issuance = await credits_client.submit_issuance(request)
    except AuthorityError as error:
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

    mismatch = result_mismatch(request, issuance)
    if mismatch is not None:
        # A signed answer to another request says nothing about this one: the
        # grant this request asked for may or may not exist. Nothing is
        # delivered, and no compensation runs on a grant whose state is unknown.
        message = f"Issuance answered another request: its {mismatch} differs"
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
            "grant_unknown": True,
        }

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

    extension: dict[str, Any] | None = None
    if contributions.public_result_extension is not None:
        try:
            extension = public_extension(
                contributions.public_result_extension(
                    listing_resource, issuance.model_copy(update={"secret": None})
                ),
                public={"key_id", "base_url", "balance", "connection_details"},
                secret=issuance.secret,
            )
        except ValueError as error:
            # Checked before the delivery is reported fulfilled, so no stage
            # attests or records a delivery whose public result is unsafe.
            message = f"Public result extension refused: {error}"
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
                "grant_unknown": True,
            }

    payload = connection_payload(
        contributions, subject=subject, key_id=issued_key_id, quantity=quantity
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
        "base_url": subject.endpoint,
        "balance": issuance.balance,
    }
    if issuance.secret:
        credentials["secret"] = issuance.secret
    result: dict[str, Any] = {
        "status": "fulfilled",
        "message": "API-token obligation fulfilled",
        "settlement_ref": settlement_ref,
        "fulfillment_uid": fulfillment_uid,
        "connection_details": payload,
        "tenant_credentials": credentials,
        "issuance": issuance,
    }
    if extension is not None:
        result["public_extension"] = extension
    return result


async def fulfill_from_hold(
    contributions: SellingContributions,
    *,
    evidence: SettlementEvidence,
    db: Any,
    credits_client: AuthorityClient,
    stage_event: StageEventFn,
    apply_failure_policy: ApplyFailurePolicyFn | None = None,
    retry_uncertain: bool = False,
) -> dict[str, Any]:
    """Issue under the quota hold placed at acceptance, if one stands, then release the hold row.

    The hold row stays while issuance is pending, so a retry issues under the
    same reservation, and when the grant's state is unknown, so an operator
    resolving it still sees the hold.
    """
    delivery(contributions, evidence)
    hold = await db.load_capacity_hold(negotiation_id=evidence.negotiation_id)
    held_reservation = None
    if hold:
        held_reservation = dict(hold.get("payload") or {})
        held_reservation.setdefault("capacity_reservation_id", hold.get("capacity_reservation_id"))
    result = await fulfill(
        contributions,
        evidence=evidence,
        retry_uncertain=retry_uncertain,
        credits_client=credits_client,
        stage_event=stage_event,
        apply_failure_policy=apply_failure_policy,
        held_reservation=held_reservation,
    )
    if (
        held_reservation is not None
        and result.get("status") != "pending"
        and not result.get("grant_unknown")
    ):
        await db.delete_capacity_hold(negotiation_id=evidence.negotiation_id)
    return result


_PRIVATE_KEYS = frozenset({"secret", "tenant_credentials"})


def public_extension(
    extension: Mapping[str, Any], *, public: Iterable[str], secret: str | None
) -> dict[str, Any]:
    """A domain's public-result extension, refused unless it is safe to publish.

    It must be plain JSON, name no field the delivery already publishes or
    keeps private, and carry the bearer secret nowhere, under any key or
    nesting.
    """
    try:
        encoded = json.dumps(dict(extension), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("public result extension must be plain JSON") from exc
    plain = json.loads(encoded)
    clashing = sorted(set(plain) & (set(public) | _PRIVATE_KEYS))
    if clashing:
        raise ValueError(f"public result extension may not carry {', '.join(clashing)}")
    if secret and _carries(plain, secret):
        raise ValueError("public result extension may not carry the bearer secret")
    return plain


def _carries(value: Any, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, Mapping):
        return any(_carries(key, secret) or _carries(item, secret) for key, item in value.items())
    if isinstance(value, list):
        return any(_carries(item, secret) for item in value)
    return False


async def persist_delivery(
    contributions: SellingContributions,
    db: Any,
    evidence: SettlementEvidence,
    result: Mapping[str, Any],
    *,
    public_ref: str,
) -> dict[str, Any]:
    """Record a delivery's progress: the secret privately, everything else publicly.

    The public result is checked before anything is written, so a refused
    extension leaves no private credential behind.
    """
    credentials = result.get("tenant_credentials") or {}
    secret = credentials.get("secret")
    public = {key: value for key, value in credentials.items() if key != "secret"}
    if result.get("connection_details"):
        public["connection_details"] = result["connection_details"]
    public.update(
        public_extension(
            result.get("public_extension") or {},
            public=public,
            secret=str(secret) if secret else None,
        )
    )
    credentials_ref = None
    issuance = result.get("issuance")
    if secret:
        if issuance is None:
            raise ValueError("private delivery requires canonical issuance identity")
        stored = await asyncio.to_thread(
            PrivateResultRepository(db.db_path, contributions).store,
            fulfillment_id=issuance.fulfillment_id,
            owner=delivery(contributions, evidence).owner,
            key_id=credentials["key_id"], secret=secret,
        )
        credentials_ref = stored.credentials_ref
    return await db.save_issuance_progress(
        negotiation_id=evidence.negotiation_id, public_ref=public_ref,
        status="ready" if result.get("status") == "fulfilled" else ("provisioning" if result.get("status") == "pending" else "failed"),
        fulfillment_uid=result.get("fulfillment_uid"), public_result=public,
        credentials_ref=credentials_ref, reason=result.get("message"),
    )


async def project_progress(
    contributions: SellingContributions,
    db: Any,
    row: Mapping[str, Any],
    *,
    owner: Identity,
) -> dict[str, Any]:
    """Issuance progress as its owner reads it, with the secret from the private result."""
    evidence = await db.load_settlement_evidence(negotiation_id=row["negotiation_id"])
    if evidence is None:
        raise ValueError("settlement source evidence is missing")
    if delivery(contributions, evidence, require_verified=False).owner != owner:
        raise PermissionError("settlement result belongs to another principal")
    public = dict(row["public_result"])
    connection = public.pop("connection_details", None)
    result = {
        "escrow_uid": row["public_ref"], "negotiation_id": row["negotiation_id"],
        "status": row["status"], "settlement_ref": evidence.settlement_ref,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "fulfillment_uid": row.get("fulfillment_uid"), "reason": row.get("reason"),
    }
    if connection:
        result["connection_details"] = connection
    if public:
        result["tenant_credentials"] = public
    if row.get("credentials_ref"):
        private = await asyncio.to_thread(
            PrivateResultRepository(db.db_path, contributions).get,
            credentials_ref=row["credentials_ref"], owner=owner,
        )
        if private is not None:
            result.setdefault("tenant_credentials", {})["secret"] = private.secret
    return result


async def progress_result(
    contributions: SellingContributions,
    db: Any,
    row: Mapping[str, Any],
    *,
    buyer: Identity,
    seller: Identity,
) -> SettleResult:
    """Project issuance progress for its buyer; terminal progress answers 200, open progress 202."""
    result = await project_progress(contributions, db, row, owner=buyer)
    result["buyer_principal"] = buyer.model_dump(mode="json")
    result["seller_principal"] = seller.model_dump(mode="json")
    return SettleResult(200 if row["status"] in {"ready", "failed"} else 202, result)
