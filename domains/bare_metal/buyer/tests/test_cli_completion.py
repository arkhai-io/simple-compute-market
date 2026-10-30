"""Both bare-metal negotiating commands complete an agreed negotiation, and ``buy``
pays exactly the quote its option names for the requested duration.

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
from arkhai_bare_metal_buyer.settlement_stages import purchase_quote
from core_buyer.negotiation_client import NegotiationOutcome
from market_core.schemas import (
    Agreement,
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
             outcome: NegotiationOutcome, *, accept_inside: bool = False) -> dict[str, Any]:
    """Replace the command's collaborators; the returned record names what each saw.

    With ``accept_inside`` the negotiator calls the command's acceptance check on the
    accepted outcome before returning it, as the real negotiator does.
    """
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

    seen: dict[str, Any] = {"negotiations": [], "acceptances": [], "settlements": []}

    def negotiate(**kwargs: Any) -> NegotiationOutcome:
        seen["negotiations"].append(kwargs)
        if accept_inside:
            kwargs["validate_acceptance"](outcome)
        return outcome

    def settle(**kwargs: Any) -> tuple[str, dict[str, Any]]:
        seen["settlements"].append(kwargs)
        return "transaction-1", {"fulfillment_id": "fulfillment-1"}

    stage = SimpleNamespace(
        validate_option=lambda _option: None,
        validate_acceptance=lambda accepted, _approval: seen["acceptances"].append(accepted),
        settle=settle,
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
    monkeypatch.setattr(cli, "negotiate_with_seller", negotiate)
    monkeypatch.setattr(cli, "BUYER_STAGES", {option.mechanism: stage})
    monkeypatch.setattr(cli, "payment_approval", lambda _config: object())
    monkeypatch.setattr(cli, "BareMetalSettlementTransport", lambda **_kwargs: object())
    return seen


def _events(tmp_path: Path) -> list[dict[str, Any]]:
    (log,) = (tmp_path / "arkhai" / "buy-runs").glob("*.jsonl")
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _run_ended(tmp_path: Path) -> dict[str, Any]:
    return next(event for event in _events(tmp_path) if event["event"] == "run_ended")


def test_buy_records_dictionary_terms_when_the_deal_is_agreed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outcome = _payment_outcome(amount=1_000_000, duration_seconds=3600)
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


def _payment_outcome(*, amount: int, duration_seconds: int) -> NegotiationOutcome:
    """An agreed payment negotiation whose Agreement pays ``amount`` for ``duration_seconds``."""

    return NegotiationOutcome(
        status="agreed",
        negotiation_id="negotiation-1",
        agreed_amount=amount,
        accepted_provision_terms=dict(_ACCEPTED_TERMS),
        settlement_selection=SettlementSelection(
            mechanism=_PAYMENT.mechanism,
            option_id=_PAYMENT.option_id,
            params={"payer_account": "buyer-account"},
        ),
        agreement=Agreement(
            negotiation_id="negotiation-1",
            listing_id="listing-1",
            listing_hash="0" * 64,
            buyer=_BUYER.identity.model_dump(mode="json"),
            seller=_SELLER.identity.model_dump(mode="json"),
            settlement=_PAYMENT,
            settlement_params={"payer_account": "buyer-account"},
            amount=amount,
            asset=_PAYMENT.asset,
            duration_seconds=duration_seconds,
            start_utc="2030-01-01T00:00:00Z",
            accepted_at="2030-01-01T00:00:00Z",
        ),
    )


def _buy(duration_seconds: int, option: SettlementOption = _PAYMENT) -> Any:
    return CliRunner().invoke(cli.bare_metal_app, [
        "buy", "listing-1", "--option-id", option.option_id,
        "--ssh-public-key", "ssh-ed25519 AAAA", "--duration-seconds", str(duration_seconds),
    ])


# The option's synthetic rate is 1000000 base units of USD/6 an hour.
@pytest.mark.parametrize(
    ("duration_seconds", "quote"),
    [(1800, 500_000), (3600, 1_000_000), (7200, 2_000_000), (1801, 500_277)],
)
def test_buy_negotiates_the_option_total_for_the_requested_duration_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, duration_seconds: int, quote: int
) -> None:
    seen = _compose(
        monkeypatch, tmp_path, _PAYMENT,
        _payment_outcome(amount=quote, duration_seconds=duration_seconds),
    )

    result = _buy(duration_seconds)

    assert result.exit_code == 0, result.output
    (negotiation,) = seen["negotiations"]
    # The bounds are the lease's whole total, truncated to base units, and are not
    # scaled again: the negotiator multiplies them by the unit count it is given.
    assert (negotiation["initial_price"], negotiation["max_price"]) == (quote, quote)
    assert negotiation["unit_count"] == 1
    assert len(seen["settlements"]) == 1


def test_a_quote_that_truncates_to_zero_is_refused_before_any_negotiation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cheap = _option(
        "arkhai.payments.v1", "USD/6", [{"field": "amount", "value": "1", "per": "hour"}]
    )
    seen = _compose(monkeypatch, tmp_path, cheap, _payment_outcome(amount=0, duration_seconds=60))

    result = _buy(60, cheap)

    assert result.exit_code != 0
    assert "zero base units" in result.output
    assert seen["negotiations"] == [] and seen["settlements"] == []
    assert not list((tmp_path / "arkhai").glob("buy-runs/*.jsonl"))


@pytest.mark.parametrize("accept_inside", [True, False], ids=["inside-negotiation", "after-return"])
@pytest.mark.parametrize(
    ("agreed_amount", "agreed_duration"),
    [(250_000, 1800), (1_000_000, 1800), (500_000, 3600)],
    ids=["half-the-quote", "double-the-quote", "another-duration"],
)
def test_an_agreement_off_the_quote_ends_the_run_before_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    agreed_amount: int, agreed_duration: int, accept_inside: bool,
) -> None:
    bad = _payment_outcome(amount=agreed_amount, duration_seconds=agreed_duration)
    seen = _compose(monkeypatch, tmp_path, _PAYMENT, bad, accept_inside=accept_inside)

    result = _buy(1800)

    assert result.exit_code == 1, result.output
    assert seen["acceptances"] == [] and seen["settlements"] == []
    events = _events(tmp_path)
    assert {"agreement_accepted", "payment_approved"}.isdisjoint(e["event"] for e in events)
    ended = _run_ended(tmp_path)
    assert ended["status"] == "exited"
    assert ended["reason"].startswith("agreement_off_quote: seller Agreement")
    assert ended["negotiation_id"] == "negotiation-1"
    assert [e["event"] for e in events].count("run_ended") == 1


@pytest.mark.parametrize(
    "rates",
    [
        [{"field": "deposit", "value": "7", "per": "hour"},
         {"field": "amount", "value": "1000000", "per": "hour"}],
        [{"field": "deposit", "value": "1000000", "per": "hour"}],
    ],
    ids=["amount-and-another-charge", "another-charge-only"],
)
def test_an_option_charging_another_field_is_refused(rates: list[dict[str, Any]]) -> None:
    option = _option("arkhai.payments.v1", "USD/6", rates)
    with pytest.raises(ValueError, match="only an amount rate"):
        purchase_quote(option, 1800)


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
