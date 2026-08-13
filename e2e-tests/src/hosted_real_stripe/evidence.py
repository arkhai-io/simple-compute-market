"""Sanitized evidence for the opt-in Stripe test-mode system lane."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal

SchemaId = Literal["arkhai.hosted-settlement-real-stripe-evidence.v1"]
SCHEMA_ID: Final[SchemaId] = "arkhai.hosted-settlement-real-stripe-evidence.v1"
_FORBIDDEN_VALUE = re.compile(
    r"(?:sk_(?:test|live)_|rk_(?:test|live)_|whsec_|https://checkout\.stripe\.com/|"
    r"https://connect\.stripe\.com/|\b(?:acct|cs|pi|ch|tr|re)_[A-Za-z0-9_]+)",
    re.IGNORECASE,
)
_OPERATION_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

Outcome = Literal["passed", "failed", "unavailable"]
RefundOutcome = Literal["passed", "unavailable", "not_requested"]


class EvidenceValidationError(ValueError):
    """Raised rather than writing evidence outside the public allowlist."""


@dataclass(frozen=True)
class IdentityEvidence:
    marketplace_repository: Literal["arkhai/simple-market-service"]
    marketplace_commit: str
    hosted_repository: Literal["arkhai/hosted-settlement-service"]
    hosted_source_commit: str
    hosted_workflow_run_id: str
    hosted_manifest_sha256: str
    hosted_image_digest: str


@dataclass(frozen=True)
class ProviderEvidence:
    name: Literal["stripe"] = "stripe"
    mode: Literal["test"] = "test"
    connected_account_ready: bool = False


@dataclass(frozen=True)
class UnavailableEvidence:
    phase: Literal[
        "authorization",
        "account_readiness",
        "webhook_forwarding",
        "hosted_release",
        "marketplace_lifecycle",
        "browser_checkout",
        "provider_inspection",
        "refund",
    ]
    code: Literal[
        "credentials_missing",
        "account_unavailable",
        "account_not_ready",
        "stripe_cli_unavailable",
        "webhook_unavailable",
        "hosted_release_unavailable",
        "marketplace_lifecycle_unavailable",
        "chromium_unavailable",
        "provider_inspection_unavailable",
        "refund_externally_unavailable",
    ]


@dataclass(frozen=True)
class FailureEvidence:
    phase: Literal[
        "authorization",
        "release_identity",
        "marketplace_lifecycle",
        "browser_checkout",
        "provider_inspection",
        "refund",
    ]
    code: Literal[
        "authorization_contract_rejected",
        "release_identity_rejected",
        "lifecycle_contract_rejected",
        "checkout_contract_rejected",
        "collection_invariant_failed",
        "refund_invariant_failed",
    ]


@dataclass(frozen=True)
class CollectionEvidence:
    operation_ref: str
    checkout_count: int
    transfer_count: int
    amount: int
    currency: str
    destination_matches: bool
    transfer_group_matches: bool
    source_transaction_matches: bool
    operation_metadata_matches: bool
    marketplace_state: str
    authority_state: str
    fulfillment_state: str


@dataclass(frozen=True)
class RefundEvidence:
    outcome: RefundOutcome
    operation_ref: str | None = None
    checkout_count: int | None = None
    refund_count: int | None = None
    transfer_count: int | None = None
    amount: int | None = None
    currency: str | None = None
    operation_metadata_matches: bool | None = None
    marketplace_state: str | None = None
    authority_state: str | None = None
    unavailable: UnavailableEvidence | None = None


@dataclass(frozen=True)
class RealStripeEvidence:
    identities: IdentityEvidence
    provider: ProviderEvidence
    outcome: Outcome
    collection: CollectionEvidence | None = None
    refund: RefundEvidence = RefundEvidence(outcome="not_requested")
    unavailable: UnavailableEvidence | None = None
    failure: FailureEvidence | None = None
    schema: SchemaId = SCHEMA_ID
    lane: Literal["external"] = "external"


def _validate_evidence(report: RealStripeEvidence) -> dict[str, object]:
    payload = asdict(report)
    if report.schema != SCHEMA_ID or report.lane != "external":
        raise EvidenceValidationError("report must use the exact external evidence contract")
    identities = report.identities
    if (
        identities.marketplace_repository != "arkhai/simple-market-service"
        or not _COMMIT.fullmatch(identities.marketplace_commit)
        or identities.hosted_repository != "arkhai/hosted-settlement-service"
        or not _COMMIT.fullmatch(identities.hosted_source_commit)
        or not identities.hosted_workflow_run_id.isdigit()
    ):
        raise EvidenceValidationError("source identities must name exact trusted repositories and revisions")
    for digest in (identities.hosted_manifest_sha256, identities.hosted_image_digest):
        if not _DIGEST.fullmatch(digest):
            raise EvidenceValidationError("release identities must be exact sha256 digests")

    if report.outcome == "passed":
        if report.collection is None or report.unavailable is not None or report.failure is not None:
            raise EvidenceValidationError("passed evidence requires collection and no lane error")
    elif report.outcome == "unavailable":
        if report.unavailable is None or report.collection is not None or report.failure is not None:
            raise EvidenceValidationError("unavailable evidence requires one unavailable reason")
    elif report.failure is None or report.collection is not None or report.unavailable is not None:
        raise EvidenceValidationError("failed evidence requires one allowlisted failure")

    if report.collection is not None:
        _validate_operation_ref(report.collection.operation_ref)
        if report.collection.checkout_count != 1 or report.collection.transfer_count != 1:
            raise EvidenceValidationError("collection evidence requires exactly one Checkout and transfer")
        if report.collection.amount <= 0 or not _valid_currency(report.collection.currency):
            raise EvidenceValidationError("collection amount/currency are invalid")
        if not all(
            (
                report.collection.destination_matches,
                report.collection.transfer_group_matches,
                report.collection.source_transaction_matches,
                report.collection.operation_metadata_matches,
            )
        ):
            raise EvidenceValidationError("collection relationship evidence is incomplete")

    refund = report.refund
    if refund.outcome == "passed":
        if refund.unavailable is not None or None in (
            refund.operation_ref,
            refund.checkout_count,
            refund.refund_count,
            refund.transfer_count,
            refund.amount,
            refund.currency,
            refund.operation_metadata_matches,
            refund.marketplace_state,
            refund.authority_state,
        ):
            raise EvidenceValidationError("passed refund evidence is incomplete")
        assert refund.operation_ref is not None
        _validate_operation_ref(refund.operation_ref)
        if (refund.checkout_count, refund.refund_count, refund.transfer_count) != (1, 1, 0):
            raise EvidenceValidationError("refund evidence requires one Checkout/refund and no transfer")
        if not refund.operation_metadata_matches:
            raise EvidenceValidationError("refund metadata does not match the operation")
    elif refund.outcome == "unavailable":
        if refund.unavailable is None or refund.unavailable.phase != "refund":
            raise EvidenceValidationError("unavailable refund requires a refund reason")
    elif refund.unavailable is not None:
        raise EvidenceValidationError("unrequested refund cannot have an unavailable reason")

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if _FORBIDDEN_VALUE.search(encoded):
        raise EvidenceValidationError("provider secret, identifier, or action URL reached evidence")
    return payload


def _validate_operation_ref(value: str) -> None:
    if not _OPERATION_REF.fullmatch(value) or _FORBIDDEN_VALUE.search(value):
        raise EvidenceValidationError("operation_ref is not a safe marketplace identity")


def _valid_currency(value: str) -> bool:
    return len(value) == 3 and value.isascii() and value.islower() and value.isalpha()


def write_evidence(path: Path, report: RealStripeEvidence) -> None:
    """Atomically write only schema-validated, provider-identifier-free evidence."""
    payload = _validate_evidence(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
