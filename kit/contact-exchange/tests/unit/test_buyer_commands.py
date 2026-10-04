"""The mechanism's buyer introduction commands over an injected domain context."""

from __future__ import annotations

import json
from typing import Any

import typer
from market_contact_exchange import (
    ContactSettlementConfig,
    RecoveredIntroductionRun,
    contact_accepted_obligation_builder,
    create_contact_command_group,
)
from market_core.schemas import SettlementPlan, derive_settlement_option_id
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import derive_obligation_ref
from typer.testing import CliRunner

BUYER = Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "11" * 20)
SELLER = Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "22" * 20)


def _plan() -> tuple[dict[str, Any], str]:
    params = {
        "profile": "default",
        "channel": "email",
        "terms": "Quoted per engagement.",
        "claimant_principal": SELLER.model_dump(mode="json"),
    }
    option = {
        "option_id": derive_settlement_option_id(
            mechanism="contact-exchange.v1", asset="introduction", rates=[], params=params
        ),
        "mechanism": "contact-exchange.v1",
        "asset": "introduction",
        "rates": [],
        "params": params,
    }

    artifacts = contact_accepted_obligation_builder(
        ContactSettlementConfig(),
        option,
        {"buyer_principal": BUYER, "seller_principal": SELLER, "expiration_unix": 4_000_000_000},
    )
    plan = SettlementPlan.model_validate(
        {"obligations": [artifacts.obligation], "service_terms": dict(artifacts.service_terms)}
    )
    ref = derive_obligation_ref("neg-1", 0, plan.obligations[0].model_dump(mode="json"))
    return plan.model_dump(mode="json"), ref


class Deleted(Exception):
    def __init__(self, obligation_ref: str) -> None:
        super().__init__("deleted")
        self.obligation_ref = obligation_ref
        self.payloads_deleted_at = "2026-10-01T12:00:00Z"

    def outcome(self) -> dict[str, Any]:
        return {"code": "introduction_payloads_deleted", "obligation_ref": self.obligation_ref}


class Context:
    deleted_error = Deleted

    def __init__(self, *, deleted: bool = False, failing_sink: bool = False) -> None:
        self.plan, self.ref = _plan()
        self.deleted = deleted
        self.failing_sink = failing_sink
        self.events: list[tuple[str, dict]] = []
        self.delivered: list[Any] = []
        self.started: list[dict] = []
        self.recovered_with_delivery: list[bool] = []

    def recover(self, run_id: str, config: str | None, *, deliver: bool) -> RecoveredIntroductionRun:
        self.recovered_with_delivery.append(deliver)

        def start(**kwargs):
            self.started.append(kwargs)
            if self.deleted:
                raise Deleted(kwargs["obligation_ref"])
            return {"obligation_ref": kwargs["obligation_ref"], "revealed": True}

        def read(*, obligation_ref: str):
            if self.deleted:
                raise Deleted(obligation_ref)
            return {"obligation_ref": obligation_ref, "revealed": True}

        def deliver_copy(projection):
            if self.failing_sink:
                # A domain's delivery reports failures itself and never raises.
                self.delivered.append("failed")
                return
            self.delivered.append(projection)

        return RecoveredIntroductionRun(
            negotiation_id="neg-1",
            settlement_plan=self.plan,
            start=start,
            read=read,
            record=lambda name, **fields: self.events.append((name, fields)),
            deliver=deliver_copy if deliver else None,
        )


def _app(context: Context) -> typer.Typer:
    app = typer.Typer()
    app.add_typer(create_contact_command_group(lambda: context), name="contact")
    return app


def test_introduce_reveals_records_and_delivers_after_printing() -> None:
    context = Context()
    result = CliRunner().invoke(
        _app(context),
        ["contact", "introduce", "--run-id", "run-1", "--contact", "email=buyer@example.com"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["obligation_ref"] == context.ref
    assert context.started == [
        {
            "negotiation_id": "neg-1",
            "obligation_ref": context.ref,
            "contact_payload": {"email": "buyer@example.com"},
        }
    ]
    assert context.events == [("introduction_revealed", {"obligation_ref": context.ref})]
    assert len(context.delivered) == 1
    assert context.recovered_with_delivery == [True]


def test_a_malformed_contact_is_refused_before_anything_is_recovered() -> None:
    context = Context()
    result = CliRunner().invoke(
        _app(context), ["contact", "introduce", "--run-id", "run-1", "--contact", "email"]
    )
    assert result.exit_code != 0
    assert context.recovered_with_delivery == []


def test_a_deleted_introduction_is_reported_and_exits_successfully() -> None:
    context = Context(deleted=True)
    result = CliRunner().invoke(
        _app(context),
        ["contact", "introduce", "--run-id", "run-1", "--contact", "email=b@example.com"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["code"] == "introduction_payloads_deleted"
    assert context.events[0][0] == "introduction_payloads_deleted"
    assert context.delivered == []


def test_reading_delivers_only_when_asked() -> None:
    context = Context()
    plain = CliRunner().invoke(_app(context), ["contact", "introduction", "--run-id", "run-1"])
    assert plain.exit_code == 0, plain.output
    assert context.delivered == []
    again = CliRunner().invoke(
        _app(context), ["contact", "introduction", "--run-id", "run-1", "--deliver"]
    )
    assert again.exit_code == 0, again.output
    assert len(context.delivered) == 1
    assert context.recovered_with_delivery == [False, True]


def test_a_failing_sink_leaves_the_reveal_printed() -> None:
    context = Context(failing_sink=True)
    result = CliRunner().invoke(
        _app(context),
        ["contact", "introduce", "--run-id", "run-1", "--contact", "email=b@example.com"],
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["revealed"] is True


def test_a_run_that_is_not_an_introduction_is_refused() -> None:
    context = Context()
    context.plan = {"obligations": [], "service_terms": {}}
    result = CliRunner().invoke(_app(context), ["contact", "introduction", "--run-id", "run-1"])
    assert result.exit_code != 0
