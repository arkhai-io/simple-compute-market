"""Both bare-metal negotiating commands complete an agreed negotiation.

A negotiation outcome carries the accepted terms decoded, or as the plain
dictionary the seller echoed when the client was given no decoder; each
command's ``run_ended`` event must carry them as they arrived, and these tests
give the dictionary. The commands take no
injected collaborators, so the ones around the completion path are replaced at
the command's module, as the composition tests do; the run log is real, under a
temporary state directory.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from arkhai_bare_metal_buyer import cli
from core_buyer.negotiation_client import NegotiationOutcome
from market_core.schemas import (
    RateValue,
    SettlementObligation,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
    derive_settlement_option_id,
)
from market_identity import Ed25519Signer, TrustedIdentitySet
from typer.testing import CliRunner

# Deterministic development keys for these tests only; never used on any network.
_BUYER = Ed25519Signer(bytes([1]) * 32)
_SELLER = Ed25519Signer(bytes([2]) * 32)

_ACCEPTED_TERMS = {
    "domain": "bare_metal",
    "payload": {"duration_seconds": 3600, "access_method": "ssh"},
}


def _option(mechanism: str, asset: str, rates: list[dict[str, Any]]) -> SettlementOption:
    values = [RateValue.model_validate(rate) for rate in rates]
    option_id = derive_settlement_option_id(
        mechanism=mechanism, asset=asset, rates=values, params={}
    )
    return SettlementOption(
        option_id=option_id, mechanism=mechanism, asset=asset, rates=values, params={}
    )


_PAYMENT = _option(
    "arkhai.payments.v1", "USD/6", [{"field": "amount", "value": "1000000", "per": "hour"}]
)
_INTRODUCTION = _option("contact-exchange.v1", "introduction", [])


def _introduction_plan() -> SettlementPlan:
    buyer = _BUYER.identity.model_dump(mode="json")
    seller = _SELLER.identity.model_dump(mode="json")
    return SettlementPlan(
        buyer_principal=buyer,
        seller_principal=seller,
        service_terms={"contact-exchange.v1": {"option_id": _INTRODUCTION.option_id}},
        obligations=[
            SettlementObligation(
                payer="buyer",
                claimant="seller",
                payer_principal=buyer,
                claimant_principal=seller,
                amount=None,
                asset="introduction",
                expiration_unix=4_000_000_000,
                conditions=[],
                mechanism="contact-exchange.v1",
                params={},
            )
        ],
    )


def _compose(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, option: SettlementOption,
             outcome: NegotiationOutcome) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    config = SimpleNamespace(
        payer_account="buyer-account",
        arkhai_payments=SimpleNamespace(enabled=True),
        registry_url="https://registry.example",
        registry_authority="registry-test",
        default_max_rounds=3,
        timeout_seconds=5.0,
    )
    listing = SimpleNamespace(
        storefront_url="https://seller.example",
        publisher_principals=TrustedIdentitySet(identities=(_SELLER.identity,)),
        publisher_id=7,
        settlement_options=[option.model_dump(mode="json")],
    )

    @contextmanager
    def registry(_config, _identity):
        yield SimpleNamespace(get_listing=lambda _listing_id: listing)

    stage = SimpleNamespace(
        validate_option=lambda _option: None,
        validate_acceptance=lambda _outcome, _approval: None,
        settle=lambda **_kwargs: ("transaction-1", {"fulfillment_id": "fulfillment-1"}),
    )
    monkeypatch.setattr(cli, "load_bare_metal_buyer_config", lambda _path: config)
    monkeypatch.setattr(
        cli,
        "fresh_identity",
        lambda: SimpleNamespace(
            profile_id=uuid.UUID(int=1), principal=_BUYER.identity, signer=_BUYER
        ),
    )
    monkeypatch.setattr(cli, "registry_client", registry)
    monkeypatch.setattr(cli, "negotiate_with_seller", lambda **_kwargs: outcome)
    monkeypatch.setattr(cli, "BUYER_STAGES", {_PAYMENT.mechanism: stage})
    monkeypatch.setattr(cli, "payment_approval", lambda _config: object())
    monkeypatch.setattr(cli, "BareMetalSettlementTransport", lambda **_kwargs: object())


def _run_ended(tmp_path: Path) -> dict[str, Any]:
    (log,) = (tmp_path / "arkhai" / "buy-runs").glob("*.jsonl")
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return next(event for event in events if event["event"] == "run_ended")


def test_buy_records_dictionary_terms_when_the_deal_is_agreed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outcome = NegotiationOutcome(
        status="agreed",
        negotiation_id="negotiation-1",
        agreed_amount=1_000_000,
        accepted_provision_terms=dict(_ACCEPTED_TERMS),
        settlement_selection=SettlementSelection(
            mechanism=_PAYMENT.mechanism,
            option_id=_PAYMENT.option_id,
            params={"payer_account": "buyer-account"},
        ),
    )
    _compose(monkeypatch, tmp_path, _PAYMENT, outcome)

    result = CliRunner().invoke(cli.bare_metal_app, [
        "buy", "listing-1", "--option-id", _PAYMENT.option_id,
        "--ssh-public-key", "ssh-ed25519 AAAA", "--duration-seconds", "3600",
    ])

    assert result.exit_code == 0, result.output
    ended = _run_ended(tmp_path)
    assert ended["status"] == "agreed"
    assert ended["accepted_provision_terms"] == _ACCEPTED_TERMS
    assert ended["transaction_id"] == "transaction-1"


def test_request_introduction_records_dictionary_terms_when_the_deal_is_agreed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outcome = NegotiationOutcome(
        status="agreed",
        negotiation_id="negotiation-2",
        agreed_amount=0,
        accepted_provision_terms=dict(_ACCEPTED_TERMS),
        settlement_selection=SettlementSelection(
            mechanism=_INTRODUCTION.mechanism,
            option_id=_INTRODUCTION.option_id,
            expiration_unix=4_000_000_000,
        ),
        settlement_plan=_introduction_plan(),
    )
    _compose(monkeypatch, tmp_path, _INTRODUCTION, outcome)

    result = CliRunner().invoke(cli.bare_metal_app, [
        "request-introduction", "listing-2", "--option-id", _INTRODUCTION.option_id,
    ])

    assert result.exit_code == 0, result.output
    ended = _run_ended(tmp_path)
    assert ended["status"] == "agreed"
    assert ended["accepted_provision_terms"] == _ACCEPTED_TERMS
