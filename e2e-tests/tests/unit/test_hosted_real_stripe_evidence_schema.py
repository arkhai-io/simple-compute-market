"""The published evidence contract, held to what the harness actually writes.

evidence.schema.json is the only thing a reader outside this repository has.
Nothing loaded it, so it agreed with the dataclasses in evidence.py by hand
alone, and a widened field could publish a contract that rejects reports the
protected lane legitimately produces. These checks need no credentials: they
write evidence through the ordinary path and read the schema off disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from src.hosted_real_stripe.evidence import (
    CollectionEvidence,
    DiagnosticEvidence,
    FundingEvidence,
    HostedReleaseIdentityEvidence,
    IdentityEvidence,
    LossEvidence,
    MarketplaceIdentityEvidence,
    PaymentOutcomeEvidence,
    ProviderEvidence,
    RecoveryEvidence,
    RefundEvidence,
    StripeTestEvidence,
    opaque_ref,
    write_evidence,
)

# The same builders the allowlist tests use, so a valid identity block has one
# definition and the two files cannot drift apart from each other either.
from tests.unit.test_hosted_real_stripe_evidence import (
    _collection,
    _funding,
    _identities,
    _local_hosted,
    _signing_env,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "hosted_real_stripe"
    / "evidence.schema.json"
)


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# Every shape the lane writes
# ---------------------------------------------------------------------------


def _refund() -> RefundEvidence:
    return RefundEvidence(
        operation_ref=opaque_ref("op", "marketplace-operation"),
        checkout_count=1,
        payment_intent_count=1,
        charge_count=1,
        refund_count=1,
        transfer_count=0,
        amount=1250,
        currency="usd",
        operation_metadata_matches=True,
        marketplace_state="reclaimed",
        authority_state="refunded",
    )


def _outcome(outcome: str, funding_artifacts: int) -> PaymentOutcomeEvidence:
    return PaymentOutcomeEvidence(
        operation_ref=opaque_ref("op", "marketplace-operation"),
        outcome=outcome,  # type: ignore[arg-type]
        checkout_count=1,
        payment_intent_count=funding_artifacts,  # type: ignore[arg-type]
        charge_count=funding_artifacts,
        transfer_count=0,
        refund_count=0,
        operation_metadata_matches=True,
    )


def _passed(
    scenario: str, *, funding: FundingEvidence | None = None, **effects: Any
) -> StripeTestEvidence:
    """A passed report for one scenario, carrying exactly that scenario's effects."""

    return StripeTestEvidence(
        identities=_identities(),
        provider=ProviderEvidence(connected_account_ready=True, loopback_webhook_verified=True),
        scenario=scenario,  # type: ignore[arg-type]
        result="passed",
        stage="complete",
        funding=funding if funding is not None else _funding(),
        operation_ref=opaque_ref("op", "marketplace-operation"),
        **effects,
    )


def _withheld() -> StripeTestEvidence:
    """A lane this run declined to attempt, exactly as the driver records one.

    Nothing ran, so the funding bindings are all false and the report carries a
    stage-matched diagnostic in place of an effect.
    """

    return StripeTestEvidence(
        identities=_identities(),
        provider=ProviderEvidence(),
        scenario="post_collection_loss",
        result="excluded",
        stage="authorization",
        funding=FundingEvidence(
            profile="card.v1",
            interaction="interactive",
            payer_profile_bound=False,  # type: ignore[arg-type]
            authorization_obligation_bound=False,  # type: ignore[arg-type]
            authorization_operation_scoped=False,  # type: ignore[arg-type]
            accepted_profile_preserved=False,  # type: ignore[arg-type]
            authoritative_funding_observed=False,
            transient_action_observed=False,
            delayed_state_observed=False,
        ),
        diagnostic=DiagnosticEvidence(
            stage="authorization", code="loss_projection_unimplemented"
        ),
    )


def _development_run() -> StripeTestEvidence:
    """A build the binding gate admitted, which records the producer it ran."""

    report = _passed("collection", collection=_collection())
    return replace(
        report,
        identities=replace(
            report.identities,
            release_mode="local",
            marketplace=replace(
                report.identities.marketplace, image="localhost/arkhai:storefront"
            ),
            hosted_release=_local_hosted(),
        ),
    )


REPORTS = {
    "collection": lambda: _passed("collection", collection=_collection()),
    "refund": lambda: _passed("reclaim", refund=_refund()),
    "refusal": lambda: _passed(
        "decline",
        funding=replace(_funding(), authoritative_funding_observed=False),
        payment_outcome=_outcome("declined", 0),
    ),
    "authentication": lambda: _passed(
        "authentication",
        payment_outcome=_outcome("authentication_succeeded", 1),
    ),
    "recovery": lambda: _passed(
        "missed_webhook",
        collection=_collection(),
        recovery=RecoveryEvidence(
            kind="missed_webhook",
            process="webhook_forwarder",
            original_operation_preserved=True,
            checkout_count=1,
            terminal_effect_count=1,
        ),
    ),
    "loss": lambda: _passed(
        "ach_return",
        funding=replace(_funding(), profile="us_ach_debit.v1"),
        loss=LossEvidence(
            kind="ach_return",
            accepted_operation_preserved=True,
            fulfillment_blocked=True,
            operator_incident_observed=True,
        ),
    ),
    "withheld": _withheld,
    "development_run": _development_run,
}


def _write(tmp_path: Path, report: StripeTestEvidence) -> dict[str, Any]:
    output = tmp_path / "evidence.json"
    write_evidence(output, report)
    return json.loads(output.read_text(encoding="utf-8"))


@pytest.mark.parametrize("shape", sorted(REPORTS))
def test_written_evidence_satisfies_the_published_contract(
    shape: str, validator: Draft202012Validator, tmp_path: Path, monkeypatch
) -> None:
    """What the harness writes is what an outside reader is told to expect."""

    _signing_env(monkeypatch)
    errors = sorted(validator.iter_errors(_write(tmp_path, REPORTS[shape]())), key=str)
    assert not errors, "\n".join(
        f"{list(error.absolute_path)}: {error.message}" for error in errors
    )


# ---------------------------------------------------------------------------
# The contract refuses something
# ---------------------------------------------------------------------------


def _drop_required(document: dict[str, Any]) -> dict[str, Any]:
    document["collection"].pop("payment_intent_count")
    return document


def _wrong_state(document: dict[str, Any]) -> dict[str, Any]:
    document["collection"]["marketplace_state"] = "reclaimed"
    return document


def _unknown_field(document: dict[str, Any]) -> dict[str, Any]:
    document["collection"]["stripe_charge_id"] = "leaked"
    return document


def _provider_shaped_ref(document: dict[str, Any]) -> dict[str, Any]:
    document["operation_ref"] = "an-internal-identifier"
    return document


def _unsigned(document: dict[str, Any]) -> dict[str, Any]:
    document.pop("evidence_signature")
    return document


@pytest.mark.parametrize(
    "corrupt",
    [_drop_required, _wrong_state, _unknown_field, _provider_shaped_ref, _unsigned],
    ids=lambda corrupt: corrupt.__name__.lstrip("_"),
)
def test_the_published_contract_refuses_an_invalid_document(
    corrupt, validator: Draft202012Validator, tmp_path: Path, monkeypatch
) -> None:
    """A contract that accepts anything would let the checks above pass vacuously."""

    _signing_env(monkeypatch)
    document = _write(tmp_path, _passed("collection", collection=_collection()))
    assert validator.is_valid(document)
    assert not validator.is_valid(corrupt(document))


# ---------------------------------------------------------------------------
# The contract and the dataclasses describe the same fields
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Shape:
    """One dataclass and the subschema that is supposed to describe it."""

    produced_by: type
    pointer: tuple[str, ...]
    #: Keys the signing step adds, which no dataclass declares.
    added_at_signing: frozenset[str] = frozenset()


SHAPES = (
    _Shape(StripeTestEvidence, (), frozenset({"evidence_signature"})),
    _Shape(IdentityEvidence, ("$defs", "identities")),
    _Shape(MarketplaceIdentityEvidence, ("$defs", "identities", "properties", "marketplace")),
    _Shape(MarketplaceIdentityEvidence, ("$defs", "attested_marketplace")),
    _Shape(HostedReleaseIdentityEvidence, ("$defs", "identities", "properties", "hosted_release")),
    _Shape(HostedReleaseIdentityEvidence, ("$defs", "attested_hosted_release")),
    _Shape(ProviderEvidence, ("$defs", "provider")),
    _Shape(FundingEvidence, ("$defs", "funding")),
    _Shape(CollectionEvidence, ("$defs", "collection")),
    _Shape(RefundEvidence, ("$defs", "refund")),
    _Shape(PaymentOutcomeEvidence, ("$defs", "paymentOutcome")),
    _Shape(RecoveryEvidence, ("$defs", "recovery")),
    _Shape(LossEvidence, ("$defs", "loss")),
    _Shape(DiagnosticEvidence, ("$defs", "diagnostic")),
)


@pytest.mark.parametrize(
    "shape", SHAPES, ids=lambda shape: "/".join(shape.pointer) or "document"
)
def test_the_contract_names_every_field_the_dataclass_writes(shape: _Shape) -> None:
    """A field added on either side has to be added on the other or fail here.

    `asdict` writes every field, defaults included, and every subschema closes
    itself to anything else. So a field the contract does not name is a
    contract that rejects ordinary evidence.
    """

    node: Any = _schema()
    for step in shape.pointer:
        node = node[step]
    expected = {field.name for field in fields(shape.produced_by)} | set(shape.added_at_signing)
    assert node["additionalProperties"] is False
    assert set(node["properties"]) == expected
    assert set(node["required"]) == expected
