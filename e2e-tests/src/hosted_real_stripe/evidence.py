"""Allowlisted evidence for the protected Stripe test-mode system lane."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal

SchemaId = Literal["arkhai.hosted-settlement-stripe-test-evidence.v2"]
SCHEMA_ID: Final[SchemaId] = "arkhai.hosted-settlement-stripe-test-evidence.v2"
_FORBIDDEN_VALUE = re.compile(
    r"(?:sk_(?:test|live)_|rk_(?:test|live)_|whsec_|https?://|"
    r"\b(?:acct|cs|pi|ch|tr|re|evt|cus|pm)_[A-Za-z0-9_]+)",
    re.IGNORECASE,
)
_OPAQUE_REF = re.compile(r"^(?:run|op)_[0-9a-f]{24}$")
_WORKFLOW_REF = re.compile(r"^[A-Za-z0-9.][A-Za-z0-9._/@:-]{7,255}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

ResultClass = Literal["passed", "product", "account", "environment", "timeout"]
Scenario = Literal[
    "collection",
    "reclaim",
    "missed_webhook",
    "api_restart",
    "worker_restart",
    "decline",
    "insufficient_funds",
    "authentication",
]
Stage = Literal[
    "release_identity",
    "authorization",
    "account_readiness",
    "browser_preflight",
    "webhook_forwarding",
    "hosted_release",
    "marketplace_lifecycle",
    "browser_checkout",
    "provider_inspection",
    "recovery",
    "complete",
]
DiagnosticCode = Literal[
    "credentials_missing",
    "authorization_rejected",
    "stripe_unavailable",
    "account_not_ready",
    "chromium_unavailable",
    "stripe_cli_unavailable",
    "webhook_route_unavailable",
    "hosted_release_unavailable",
    "marketplace_unavailable",
    "lifecycle_contract_rejected",
    "checkout_contract_rejected",
    "provider_invariant_failed",
    "convergence_timeout",
]


class EvidenceValidationError(ValueError):
    """Raised rather than writing evidence outside the public allowlist."""


@dataclass(frozen=True)
class MarketplaceIdentityEvidence:
    repository: Literal["arkhai/simple-market-service"]
    commit: str


@dataclass(frozen=True)
class HostedReleaseIdentityEvidence:
    repository: Literal["arkhai/hosted-settlement-service"]
    source_commit: str
    workflow_run_id: str
    workflow_ref: str
    manifest_sha256: str
    client_wheel_sha256: str
    image_digest: str


@dataclass(frozen=True)
class IdentityEvidence:
    marketplace: MarketplaceIdentityEvidence
    hosted_release: HostedReleaseIdentityEvidence
    run_ref: str


@dataclass(frozen=True)
class ProviderEvidence:
    name: Literal["stripe"] = "stripe"
    mode: Literal["test"] = "test"
    connected_account_ready: bool = False
    loopback_webhook_verified: bool = False


@dataclass(frozen=True)
class DiagnosticEvidence:
    stage: Stage
    code: DiagnosticCode


@dataclass(frozen=True)
class CollectionEvidence:
    operation_ref: str
    checkout_count: Literal[1]
    payment_intent_count: Literal[1]
    charge_count: Literal[1]
    transfer_count: Literal[1]
    amount: int
    currency: str
    destination_matches: Literal[True]
    transfer_group_matches: Literal[True]
    source_transaction_matches: Literal[True]
    operation_metadata_matches: Literal[True]
    marketplace_state: Literal["collected"]
    authority_state: Literal["collected"]
    fulfillment_state: Literal["fulfilled"]


@dataclass(frozen=True)
class RefundEvidence:
    operation_ref: str
    checkout_count: Literal[1]
    payment_intent_count: Literal[1]
    charge_count: Literal[1]
    refund_count: Literal[1]
    transfer_count: Literal[0]
    amount: int
    currency: str
    operation_metadata_matches: Literal[True]
    marketplace_state: Literal["reclaimed"]
    authority_state: Literal["refunded"]


@dataclass(frozen=True)
class PaymentOutcomeEvidence:
    operation_ref: str
    outcome: Literal[
        "declined",
        "insufficient_funds",
        "authentication_succeeded",
    ]
    checkout_count: Literal[1]
    payment_intent_count: int
    charge_count: int
    transfer_count: Literal[0]
    refund_count: Literal[0]
    operation_metadata_matches: Literal[True]


@dataclass(frozen=True)
class RecoveryEvidence:
    kind: Literal["missed_webhook", "api_restart", "worker_restart"]
    process: Literal["webhook_forwarder", "api", "worker"]
    original_operation_preserved: Literal[True]
    checkout_count: Literal[1]
    terminal_effect_count: Literal[1]


@dataclass(frozen=True)
class StripeTestEvidence:
    identities: IdentityEvidence
    provider: ProviderEvidence
    scenario: Scenario
    result: ResultClass
    stage: Stage
    operation_ref: str | None = None
    collection: CollectionEvidence | None = None
    refund: RefundEvidence | None = None
    payment_outcome: PaymentOutcomeEvidence | None = None
    recovery: RecoveryEvidence | None = None
    diagnostic: DiagnosticEvidence | None = None
    schema: SchemaId = SCHEMA_ID
    lane: Literal["stripe-test"] = "stripe-test"


def opaque_ref(kind: Literal["run", "op"], value: str) -> str:
    """Return a stable report identity without exposing an internal/provider reference."""

    if not value or any(character.isspace() for character in value):
        raise EvidenceValidationError("opaque evidence identity source is invalid")
    return f"{kind}_{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def _validate_evidence(report: StripeTestEvidence) -> dict[str, object]:
    payload = asdict(report)
    if report.schema != SCHEMA_ID or report.lane != "stripe-test":
        raise EvidenceValidationError("report must use the exact Stripe test evidence contract")
    identities = report.identities
    if (
        identities.marketplace.repository != "arkhai/simple-market-service"
        or not _COMMIT.fullmatch(identities.marketplace.commit)
        or identities.hosted_release.repository != "arkhai/hosted-settlement-service"
        or not _COMMIT.fullmatch(identities.hosted_release.source_commit)
        or not identities.hosted_release.workflow_run_id.isdigit()
        or not _WORKFLOW_REF.fullmatch(identities.hosted_release.workflow_ref)
        or not _OPAQUE_REF.fullmatch(identities.run_ref)
        or not identities.run_ref.startswith("run_")
    ):
        raise EvidenceValidationError("consumer, hosted release, and run identities must be exact")
    for digest in (
        identities.hosted_release.manifest_sha256,
        identities.hosted_release.client_wheel_sha256,
        identities.hosted_release.image_digest,
    ):
        if not _DIGEST.fullmatch(digest):
            raise EvidenceValidationError("release identities must be exact sha256 digests")

    if report.operation_ref is not None:
        _validate_operation_ref(report.operation_ref)
    if report.result == "passed":
        if report.stage != "complete" or report.diagnostic is not None:
            raise EvidenceValidationError(
                "passed evidence must terminate at complete without diagnostics"
            )
        _validate_passed_scenario(report)
    else:
        if report.diagnostic is None or report.diagnostic.stage != report.stage:
            raise EvidenceValidationError("failed evidence requires one stage-matched diagnostic")
        if any(
            value is not None
            for value in (report.collection, report.refund, report.payment_outcome, report.recovery)
        ):
            raise EvidenceValidationError("failed evidence cannot claim completed Stripe effects")

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if _FORBIDDEN_VALUE.search(encoded):
        raise EvidenceValidationError(
            "secret, provider identity, payload URL, or customer data reached evidence"
        )
    return payload


def _validate_passed_scenario(report: StripeTestEvidence) -> None:
    if report.operation_ref is None:
        raise EvidenceValidationError("passed evidence requires an opaque operation identity")
    scenario = report.scenario
    if scenario in {"collection", "missed_webhook", "api_restart"}:
        if (
            report.collection is None
            or report.refund is not None
            or report.payment_outcome is not None
        ):
            raise EvidenceValidationError("collection scenario evidence is incomplete")
    elif scenario in {"reclaim", "worker_restart"}:
        if (
            report.refund is None
            or report.collection is not None
            or report.payment_outcome is not None
        ):
            raise EvidenceValidationError("reclaim scenario evidence is incomplete")
    elif (
        report.payment_outcome is None or report.collection is not None or report.refund is not None
    ):
        raise EvidenceValidationError("payment-outcome scenario evidence is incomplete")

    if scenario in {"missed_webhook", "api_restart", "worker_restart"}:
        if report.recovery is None or report.recovery.kind != scenario:
            raise EvidenceValidationError("recovery scenario requires matching recovery evidence")
    elif report.recovery is not None:
        raise EvidenceValidationError("ordinary scenario cannot claim recovery evidence")

    for effect in (report.collection, report.refund, report.payment_outcome):
        if effect is not None:
            _validate_operation_ref(effect.operation_ref)
            if effect.operation_ref != report.operation_ref:
                raise EvidenceValidationError("effect and report operation identities differ")
    for effect in (report.collection, report.refund):
        if effect is not None and (effect.amount <= 0 or not _valid_currency(effect.currency)):
            raise EvidenceValidationError("effect amount/currency are invalid")
    if report.payment_outcome is not None:
        expected = {
            "decline": "declined",
            "insufficient_funds": "insufficient_funds",
            "authentication": "authentication_succeeded",
        }.get(scenario)
        if report.payment_outcome.outcome != expected:
            raise EvidenceValidationError("payment outcome does not match the selected scenario")


def _validate_operation_ref(value: str) -> None:
    if not _OPAQUE_REF.fullmatch(value) or not value.startswith("op_"):
        raise EvidenceValidationError("operation_ref must be an opaque marketplace identity")


def _valid_currency(value: str) -> bool:
    return len(value) == 3 and value.isascii() and value.islower() and value.isalpha()


def write_evidence(path: Path, report: StripeTestEvidence) -> None:
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
