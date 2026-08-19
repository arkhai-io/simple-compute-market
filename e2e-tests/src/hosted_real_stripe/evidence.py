"""Allowlisted evidence for the protected Stripe test-mode system lane."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Literal

from market_identity import Identity, create_signer, get_identity_verifier

# v4 adds the release mode. The identity bumps rather than defaulting, so a
# reader that predates the field fails on the schema instead of silently
# treating a development run as protected evidence.
SchemaId = Literal["arkhai.hosted-settlement-stripe-test-evidence.v4"]
SCHEMA_ID: Final[SchemaId] = "arkhai.hosted-settlement-stripe-test-evidence.v4"
_FORBIDDEN_VALUE = re.compile(
    r"(?:sk_(?:test|live)_|rk_(?:test|live)_|whsec_|https?://|"
    r"\b(?:acct|cs|pi|ch|tr|re|evt|cus|pm|seti|src|ba)_[A-Za-z0-9_]+)",
    re.IGNORECASE,
)
_FORBIDDEN_KEY = re.compile(
    r"(?:secret|url|client_secret|customer|payment_method|provider_payload|"
    r"bank_(?:account|instructions)|card_(?:number|detail)|mandate)",
    re.IGNORECASE,
)
_OPAQUE_REF = re.compile(r"^(?:run|op)_[0-9a-f]{24}$")
_WORKFLOW_REF = re.compile(r"^[A-Za-z0-9.][A-Za-z0-9._/@:-]{7,255}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_IMAGE = re.compile(
    r"^(?P<reference>[a-z0-9][a-z0-9._/-]{2,255})@(?P<digest>sha256:[0-9a-f]{64})$"
)

FundingProfile = Literal["card.v1", "us_bank_transfer.v1", "us_ach_debit.v1"]
Interaction = Literal["interactive", "saved_instrument"]
ResultClass = Literal["passed", "product", "account", "environment", "timeout"]
Scenario = Literal[
    "collection",
    "reclaim",
    "missed_webhook",
    "api_restart",
    "worker_restart",
    "funding_restart",
    "delayed_funding",
    "off_session_success",
    "requires_action",
    "ach_return",
    "post_collection_loss",
    "decline",
    "insufficient_funds",
    "authentication",
]
Stage = Literal[
    "release_identity",
    "authorization",
    "account_readiness",
    "payer_profile",
    "payer_setup",
    "funding_authorization",
    "browser_preflight",
    "webhook_forwarding",
    "hosted_release",
    "marketplace_lifecycle",
    "browser_checkout",
    "funding",
    "provider_inspection",
    "recovery",
    "loss_boundary",
    "complete",
]
DiagnosticCode = Literal[
    "credentials_missing",
    "authorization_rejected",
    "stripe_unavailable",
    "account_not_ready",
    "payer_profile_unavailable",
    "setup_action_unavailable",
    "profile_prerequisite_unavailable",
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
    repository: Literal["arkhai-io/simple-compute-market"]
    commit: str
    workflow_run_id: str
    workflow_ref: str
    manifest_sha256: str
    image_digest: str
    image: str
    wheelhouse_sha256: str
    settlement_config_schema_sha256: str
    provenance_sha256: str

@dataclass(frozen=True)
class HostedReleaseIdentityEvidence:
    repository: Literal["arkhai-io/stripe-settlement-service"]
    source_commit: str
    workflow_run_id: str
    workflow_ref: str
    manifest_sha256: str
    client_wheel_sha256: str
    image_digest: str


#: Mirrors gates.ReleaseMode; evidence carries what was proven, so a reader
#: never has to infer a run's standing from which coordinates are populated.
ReleaseMode = Literal["attested", "local"]


@dataclass(frozen=True)
class IdentityEvidence:
    marketplace: MarketplaceIdentityEvidence
    hosted_release: HostedReleaseIdentityEvidence
    run_ref: str
    release_mode: ReleaseMode = "attested"

    @property
    def qualifies(self) -> bool:
        """Whether this run may be cited where protected evidence is required."""

        return self.release_mode == "attested"


@dataclass(frozen=True)
class ProviderEvidence:
    name: Literal["stripe"] = "stripe"
    mode: Literal["test"] = "test"
    connected_account_ready: bool = False
    loopback_webhook_verified: bool = False


@dataclass(frozen=True)
class FundingEvidence:
    profile: FundingProfile
    interaction: Interaction
    payer_profile_bound: Literal[True]
    authorization_obligation_bound: Literal[True]
    authorization_operation_scoped: Literal[True]
    accepted_profile_preserved: Literal[True]
    authoritative_funding_observed: bool
    transient_action_observed: bool
    delayed_state_observed: bool


@dataclass(frozen=True)
class LossEvidence:
    kind: Literal["ach_return", "post_collection_loss"]
    accepted_operation_preserved: Literal[True]
    fulfillment_blocked: bool
    operator_incident_observed: bool


@dataclass(frozen=True)
class DiagnosticEvidence:
    stage: Stage
    code: DiagnosticCode


@dataclass(frozen=True)
class CollectionEvidence:
    operation_ref: str
    checkout_count: int
    payment_intent_count: Literal[1]
    charge_count: Literal[1]
    transfer_count: Literal[1]
    amount: int
    currency: str
    destination_matches: Literal[True]
    transfer_group_matches: Literal[True]
    source_transaction_matches: bool
    operation_metadata_matches: Literal[True]
    marketplace_state: Literal["collected"]
    authority_state: Literal["collected"]
    fulfillment_state: Literal["fulfilled"]


@dataclass(frozen=True)
class RefundEvidence:
    operation_ref: str
    checkout_count: int
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
    checkout_count: int
    payment_intent_count: Literal[1]
    charge_count: int
    transfer_count: Literal[0]
    refund_count: Literal[0]
    operation_metadata_matches: Literal[True]


@dataclass(frozen=True)
class RecoveryEvidence:
    kind: Literal["missed_webhook", "api_restart", "worker_restart", "funding_restart"]
    process: Literal["webhook_forwarder", "api", "worker"]
    original_operation_preserved: Literal[True]
    checkout_count: int
    terminal_effect_count: Literal[1]


@dataclass(frozen=True)
class StripeTestEvidence:
    identities: IdentityEvidence
    provider: ProviderEvidence
    scenario: Scenario
    result: ResultClass
    stage: Stage
    funding: FundingEvidence
    operation_ref: str | None = None
    collection: CollectionEvidence | None = None
    refund: RefundEvidence | None = None
    payment_outcome: PaymentOutcomeEvidence | None = None
    recovery: RecoveryEvidence | None = None
    loss: LossEvidence | None = None
    diagnostic: DiagnosticEvidence | None = None
    schema: SchemaId = SCHEMA_ID
    lane: Literal["stripe-test"] = "stripe-test"


def opaque_ref(kind: Literal["run", "op"], value: str) -> str:
    """Return a stable report identity without exposing an internal/provider reference."""

    if not value or any(character.isspace() for character in value):
        raise EvidenceValidationError("opaque evidence identity source is invalid")
    return f"{kind}_{hashlib.sha256(value.encode()).hexdigest()[:24]}"

_SIGNATURE_PROTOCOL = "arkhai.marketplace-evidence-signature.v1"


def _signature_message(payload: dict[str, object]) -> bytes:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return _SIGNATURE_PROTOCOL.encode() + b"\x00" + canonical


def _signed_document(payload: dict[str, object]) -> dict[str, object]:
    scheme = os.environ.get(
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_SCHEME", ""
    ).strip()
    expected_identifier = os.environ.get(
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_IDENTIFIER", ""
    ).strip()
    credential = os.environ.get(
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_CREDENTIAL", ""
    ).strip()
    if not scheme or not expected_identifier or not credential:
        raise EvidenceValidationError("marketplace evidence signer is unavailable")
    try:
        signer = create_signer(scheme, credential)
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceValidationError("marketplace evidence signer is invalid") from exc
    if signer.identity.identifier != expected_identifier:
        raise EvidenceValidationError(
            "marketplace evidence credential does not match its designated principal"
        )
    signature = signer.sign(_signature_message(payload)).hex()
    document = {
        **payload,
        "evidence_signature": {
            "protocol": _SIGNATURE_PROTOCOL,
            "signer": signer.identity.model_dump(mode="json"),
            "signature": signature,
        },
    }
    _validate_public_tree(document)
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"))
    if _FORBIDDEN_VALUE.search(encoded):
        raise EvidenceValidationError("private material reached signed evidence")
    verify_evidence_signature(document, expected_signer=signer.identity)
    return document


def verify_evidence_signature(
    document: dict[str, Any],
    *,
    expected_signer: Identity | None = None,
) -> None:
    """Reject a modified report or malformed marketplace evidence signature."""

    payload = dict(document)
    signature_value = payload.pop("evidence_signature", None)
    if not isinstance(signature_value, dict):
        raise EvidenceValidationError("marketplace evidence signature is missing")
    _validate_public_tree(document)
    encoded_document = json.dumps(document, sort_keys=True, separators=(",", ":"))
    if _FORBIDDEN_VALUE.search(encoded_document):
        raise EvidenceValidationError("private material reached signed evidence")
    if signature_value.get("protocol") != _SIGNATURE_PROTOCOL:
        raise EvidenceValidationError("marketplace evidence signature protocol is invalid")
    try:
        identity = Identity.model_validate(signature_value.get("signer"))
        encoded_signature = signature_value["signature"]
        if expected_signer is not None and identity != expected_signer:
            raise ValueError("unexpected evidence signer")
        if not isinstance(encoded_signature, str) or not encoded_signature:
            raise ValueError("signature is empty")
        signature = bytes.fromhex(encoded_signature)
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceValidationError("marketplace evidence signature is malformed") from exc
    verifier = get_identity_verifier(identity.scheme)
    if not verifier.verify_signature(identity, _signature_message(payload), signature):
        raise EvidenceValidationError("marketplace evidence signature verification failed")


def _validate_evidence(report: StripeTestEvidence) -> dict[str, object]:
    payload = asdict(report)
    if report.schema != SCHEMA_ID or report.lane != "stripe-test":
        raise EvidenceValidationError("report must use the exact Stripe test evidence contract")
    identities = report.identities
    marketplace = identities.marketplace
    hosted = identities.hosted_release
    if (
        marketplace.repository != "arkhai-io/simple-compute-market"
        or not _COMMIT.fullmatch(marketplace.commit)
        or not marketplace.workflow_run_id.isdigit()
        or not _WORKFLOW_REF.fullmatch(marketplace.workflow_ref)
        or hosted.repository != "arkhai-io/stripe-settlement-service"
        or not _COMMIT.fullmatch(hosted.source_commit)
        or not hosted.workflow_run_id.isdigit()
        or not _WORKFLOW_REF.fullmatch(hosted.workflow_ref)
        or not _OPAQUE_REF.fullmatch(identities.run_ref)
        or not identities.run_ref.startswith("run_")
    ):
        raise EvidenceValidationError("consumer, hosted release, and run identities must be exact")
    for digest in (
        marketplace.manifest_sha256,
        marketplace.image_digest,
        marketplace.wheelhouse_sha256,
        marketplace.settlement_config_schema_sha256,
        marketplace.provenance_sha256,
        hosted.manifest_sha256,
        hosted.client_wheel_sha256,
        hosted.image_digest,
    ):
        if not _DIGEST.fullmatch(digest):
            raise EvidenceValidationError("release identities must be exact sha256 digests")
    image = _IMAGE.fullmatch(marketplace.image)
    if image is None or image.group("digest") != marketplace.image_digest:
        raise EvidenceValidationError(
            "marketplace evidence must name the activated immutable consumer image"
        )
    _validate_funding(report)
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
            for value in (
                report.collection,
                report.refund,
                report.payment_outcome,
                report.recovery,
                report.loss,
            )
        ):
            raise EvidenceValidationError("failed evidence cannot claim completed Stripe effects")
    _validate_public_tree(payload)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if _FORBIDDEN_VALUE.search(encoded):
        raise EvidenceValidationError(
            "secret, provider identity, payload URL, or customer data reached evidence"
        )
    return payload


def _validate_funding(report: StripeTestEvidence) -> None:
    funding = report.funding
    if (
        funding.interaction == "saved_instrument"
        and funding.profile == "us_bank_transfer.v1"
    ):
        raise EvidenceValidationError("push bank transfer cannot use a saved instrument")
    if report.result == "passed":
        if (
            not funding.payer_profile_bound
            or not funding.authorization_obligation_bound
            or not funding.authorization_operation_scoped
            or not funding.accepted_profile_preserved
        ):
            raise EvidenceValidationError("passed evidence lacks exact payer/authorization binding")
        if report.scenario not in {"decline", "insufficient_funds"}:
            if not funding.authoritative_funding_observed:
                raise EvidenceValidationError("passed funded scenario lacks authoritative funding")
        if report.scenario in {"delayed_funding", "funding_restart"}:
            if not funding.delayed_state_observed:
                raise EvidenceValidationError("delayed scenario lacks a pending funding observation")
        if report.scenario == "requires_action" and not funding.transient_action_observed:
            raise EvidenceValidationError("requires-action evidence lacks a transient action")


def _validate_passed_scenario(report: StripeTestEvidence) -> None:
    if report.operation_ref is None:
        raise EvidenceValidationError("passed evidence requires an opaque operation identity")
    scenario = report.scenario
    collection_scenarios = {
        "collection",
        "missed_webhook",
        "api_restart",
        "funding_restart",
        "delayed_funding",
        "off_session_success",
        "requires_action",
        "post_collection_loss",
    }
    if scenario in collection_scenarios:
        if report.collection is None or report.refund is not None or report.payment_outcome is not None:
            raise EvidenceValidationError("collection scenario evidence is incomplete")
    elif scenario in {"reclaim", "worker_restart"}:
        if report.refund is None or report.collection is not None or report.payment_outcome is not None:
            raise EvidenceValidationError("reclaim scenario evidence is incomplete")
    elif scenario == "ach_return":
        if any(value is not None for value in (report.collection, report.refund, report.payment_outcome)):
            raise EvidenceValidationError("pre-collection ACH return cannot claim a terminal effect")
    elif report.payment_outcome is None or report.collection is not None or report.refund is not None:
        raise EvidenceValidationError("payment-outcome scenario evidence is incomplete")

    if scenario in {"missed_webhook", "api_restart", "worker_restart", "funding_restart"}:
        if report.recovery is None or report.recovery.kind != scenario:
            raise EvidenceValidationError("recovery scenario requires matching recovery evidence")
    elif report.recovery is not None:
        raise EvidenceValidationError("ordinary scenario cannot claim recovery evidence")
    if scenario in {"ach_return", "post_collection_loss"}:
        if report.loss is None or report.loss.kind != scenario:
            raise EvidenceValidationError("loss scenario requires matching loss evidence")
    elif report.loss is not None:
        raise EvidenceValidationError("ordinary scenario cannot claim loss evidence")
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



def _validate_public_tree(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _FORBIDDEN_KEY.search(str(key)):
                raise EvidenceValidationError("provider, action, credential, or bank field reached evidence")
            _validate_public_tree(child)
    elif isinstance(value, list):
        for child in value:
            _validate_public_tree(child)

def _valid_currency(value: str) -> bool:
    return len(value) == 3 and value.isascii() and value.islower() and value.isalpha()


def write_evidence(path: Path, report: StripeTestEvidence) -> None:
    """Atomically write only schema-validated, provider-identifier-free evidence."""

    document = _signed_document(_validate_evidence(report))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
