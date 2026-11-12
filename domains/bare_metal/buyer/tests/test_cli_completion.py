"""Both bare-metal negotiating commands complete an agreed negotiation, and ``buy``
pays exactly the quote its option names for the requested duration: the buyer's,
or for a reserved option its one-hour default. ``buy`` refuses what a default buyer
refuses unless that term's own waiver is given, and records and names every waiver.

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
from arkhai_bare_metal_buyer.config import BareMetalBuyerConfig
from market_arkhai_payments import ArkhaiPaymentsConfig
from market_deal_lifecycle.configuration import DisputeConfig, DisputeEntry
from arkhai_bare_metal_buyer.settlement_stages import purchase_quote, requested_duration
from core_buyer.negotiation_client import NegotiationOutcome
from market_core.schemas import (
    Agreement,
    PriceBasis,
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

_DISPUTE = {
    "interface": "arkhai.mediation.v1", "origin": "https://dispute.example",
    "account": "11111111-1111-4111-8111-111111111111",
    "record_key": "example-record-key", "params": {},
    "advertisement": {"mechanisms": ["arkhai.payments.v1"],
                      "minimum_dispute_window_seconds": 60, "minimum_case_hold_seconds": None},
}

_ACCEPTED_TERMS = {
    "domain": "bare_metal",
    "payload": {"duration_seconds": 3600, "access_method": "ssh"},
}


def _option(
    mechanism: str, asset: str, rates: list[dict[str, Any]], *, deadline: bool = True,
) -> SettlementOption:
    values = [RateValue.model_validate(rate) for rate in rates]
    body = {"price": {"asset": asset, "rates": values}, "settlement": {"schema": mechanism}}
    if mechanism == "arkhai.payments.v1":
        body["settlement"]["payee_account"] = "22222222-2222-4222-8222-222222222222"
        body["lifecycle"] = {"adjudication": {
            "version": 1, "dispute": {key: _DISPUTE[key] for key in ("interface", "origin", "account", "record_key", "params")},
            "dispute_window_seconds": 120, "case_hold_max_seconds": None,
        }, **({"delivery_deadline_seconds": 60} if deadline else {})}
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


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
             outcome: NegotiationOutcome, *, accept_inside: bool = False,
             bounds: dict[str, Any] | None = None,
             default_duration_seconds: int | None = None) -> dict[str, Any]:
    """Replace the command's collaborators; the returned record names what each saw.

    With ``accept_inside`` the negotiator calls the command's acceptance check on the
    accepted outcome before returning it, as the real negotiator does. ``bounds`` are
    the listing's advertised capacity bounds. ``default_duration_seconds`` is the
    buyer's configured reserved default, left unconfigured when ``None``.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    config = BareMetalBuyerConfig(
        payer_account="11111111-1111-4111-8111-111111111111",
        disputes=DisputeConfig(entries=[DisputeEntry.model_validate(_DISPUTE)]),
        arkhai_payments=ArkhaiPaymentsConfig(enabled=True),
        registry_principals=(_SELLER.identity,),
        registry_url="https://registry.example",
        registry_authority="registry-test",
        default_max_rounds=3,
        timeout_seconds=5.0,
        **({"default_duration_seconds": default_duration_seconds}
           if default_duration_seconds is not None else {}),
    )
    listing = SimpleNamespace(
        storefront_url="https://seller.example",
        publisher_principals=TrustedIdentitySet(identities=(_SELLER.identity,)),
        publisher_id=7,
        settlement_options=[option.model_dump(mode="json")],
        **(bounds or {}),
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
    monkeypatch.setattr(cli, "BUYER_STAGES", {option.settlement_schema: stage})
    monkeypatch.setattr(cli, "payment_approval", lambda _config: object())
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


def _payment_outcome(
    *, amount: int, duration_seconds: int, option: SettlementOption = _PAYMENT,
) -> NegotiationOutcome:
    """An agreed payment negotiation whose Agreement pays ``amount`` for ``duration_seconds``."""

    return NegotiationOutcome(
        status="agreed",
        negotiation_id="negotiation-1",
        agreed_amount=amount,
        accepted_provision_terms=dict(_ACCEPTED_TERMS),
        settlement_selection=SettlementSelection(
            option_id=option.option_id,
            settlement={"schema": option.settlement_schema, "payer_account": "buyer-account"},
        ),
        agreement=Agreement(
            negotiation_id="negotiation-1",
            listing_id="listing-1",
            listing_hash="0" * 64,
            buyer=_BUYER.identity.model_dump(mode="json"),
            seller=_SELLER.identity.model_dump(mode="json"),
            settlement=option,
            settlement_params={"payer_account": "buyer-account"},
            amount=amount,
            asset=option.price_asset,
            duration_seconds=duration_seconds,
            start_utc="2030-01-01T00:00:00Z",
            accepted_at="2030-01-01T00:00:00Z",
        ),
    )


def _buy(duration_seconds: int, option: SettlementOption = _PAYMENT, *flags: str) -> Any:
    return CliRunner().invoke(cli.bare_metal_app, [
        "buy", "listing-1", "--option-id", option.option_id,
        "--ssh-public-key", "ssh-ed25519 AAAA", "--duration-seconds", str(duration_seconds),
        *flags,
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
    assert {"negotiation_completed", "payment_approved"}.isdisjoint(e["event"] for e in events)
    ended = _run_ended(tmp_path)
    assert ended["status"] == "exited"
    assert ended["reason"].startswith("agreement_off_quote: seller Agreement")
    assert ended["negotiation_id"] == "negotiation-1"
    assert [e["event"] for e in events].count("run_ended") == 1


@pytest.mark.parametrize("accept_inside", [True, False], ids=["inside-negotiation", "after-return"])
@pytest.mark.parametrize(
    ("bounds", "refusal"),
    [
        # The Agreement runs 7200 seconds from 2030-01-01T00:00:00Z.
        ({"max_duration_seconds": 3600}, "exceeds the listing's bound of 3600"),
        ({"available_until_utc": "2030-01-01T01:00:00Z"}, "exceeds the listing's bound of 3600"),
    ],
    ids=["above-the-relative-bound", "past-absolute-availability"],
)
def test_a_signed_horizon_outside_the_listing_bounds_ends_the_run_before_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    bounds: dict[str, Any], refusal: str, accept_inside: bool,
) -> None:
    signed = _payment_outcome(amount=2_000_000, duration_seconds=7200)
    seen = _compose(monkeypatch, tmp_path, _PAYMENT, signed, accept_inside=accept_inside, bounds=bounds)

    result = _buy(7200)

    assert result.exit_code == 1, result.output
    assert seen["acceptances"] == [] and seen["settlements"] == []
    ended = _run_ended(tmp_path)
    assert ended["status"] == "exited"
    assert ended["reason"].startswith("agreement_off_quote: accepted duration_seconds 7200")
    assert refusal in ended["reason"]


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


def _run_started(tmp_path: Path) -> dict[str, Any]:
    return next(event for event in _events(tmp_path) if event["event"] == "run_started")


# The option's synthetic rate is 1000000 base units of USD/6 an hour.
@pytest.mark.parametrize(
    ("configured", "requested", "quote"),
    [(None, 3600, 1_000_000), (5400, 5400, 1_500_000)],
    ids=["unconfigured-hour", "configured"],
)
def test_a_reserved_buy_naming_no_duration_requests_the_buyer_s_configured_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    configured: int | None, requested: int, quote: int,
) -> None:
    """The reserved default is the buyer configuration's ``default_duration_seconds``,
    an hour where it is not configured; it reaches the provision terms, the quote,
    the disclosure before approval and the run log."""
    seen = _compose(
        monkeypatch, tmp_path, _PAYMENT, _payment_outcome(amount=quote, duration_seconds=requested),
        accept_inside=True, default_duration_seconds=configured,
    )

    result = CliRunner().invoke(cli.bare_metal_app, [
        "buy", "listing-1", "--option-id", _PAYMENT.option_id, "--ssh-public-key", "ssh-ed25519 AAAA",
    ])

    assert result.exit_code == 0, result.output
    (negotiation,) = seen["negotiations"]
    assert negotiation["provision_terms"].payload["duration_seconds"] == requested
    assert (negotiation["initial_price"], negotiation["max_price"]) == (quote, quote)
    assert (
        f"Requested horizon: {requested} seconds, this buyer's default for a reserved option"
        in result.output
    )
    started = _run_started(tmp_path)
    assert (started["duration_seconds"], started["default_duration"]) == (requested, True)
    assert _run_ended(tmp_path)["status"] == "agreed"


def test_a_named_duration_is_not_shown_as_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _compose(monkeypatch, tmp_path, _PAYMENT, _payment_outcome(amount=500_000, duration_seconds=1800))

    result = _buy(1800)

    assert result.exit_code == 0, result.output
    assert "Requested horizon: 1800 seconds (not rounded to periods)" in result.output
    assert "buyer's default" not in result.output
    assert _run_started(tmp_path)["default_duration"] is False


@pytest.mark.parametrize(
    ("unit", "named", "requested"),
    [
        ("total", None, (5400, True)),
        ("total", 600, (600, False)),
        ("per_period", None, (None, False)),
        ("per_period", 600, (600, False)),
    ],
    ids=["reserved-default", "reserved-named", "recurring-omitted", "recurring-named"],
)
def test_the_reserved_default_never_applies_to_a_recurring_option(
    unit: str, named: int | None, requested: tuple[int | None, bool],
) -> None:
    # The installed payments projection bills only once, so a per-period basis
    # stands for a mechanism that bills a recurring option.
    basis = {"unit": unit, **({"period": "PT15M", "period_seconds": 900} if unit == "per_period" else {})}
    registry = SimpleNamespace(project_billing=lambda _option: PriceBasis.model_validate(basis))
    assert requested_duration(
        _PAYMENT, named, registry=registry, default_duration_seconds=5400,
    ) == requested


_NO_DEADLINE = _option(
    "arkhai.payments.v1", "USD/6", [{"field": "amount", "value": "1000000", "per": "hour"}],
    deadline=False,
)


@pytest.mark.parametrize("flags", [[], ["--allow-no-penalty"], ["--allow-charged-term-end"]],
                         ids=["no-waiver", "another-term's-waiver", "a-third-term's-waiver"])
def test_an_option_without_a_deadline_is_refused_unless_its_waiver_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flags: list[str],
) -> None:
    seen = _compose(
        monkeypatch, tmp_path, _NO_DEADLINE,
        _payment_outcome(amount=1_000_000, duration_seconds=3600, option=_NO_DEADLINE),
    )

    result = _buy(3600, _NO_DEADLINE, *flags)

    assert result.exit_code == 2
    # The usage error's panel wraps its message across bordered lines.
    plain = " ".join(result.output.replace("│", " ").split())
    assert "a default buyer refuses this option: no delivery deadline" in plain
    assert seen["negotiations"] == []


@pytest.mark.parametrize(
    ("flags", "recorded"),
    [
        (["--allow-no-delivery-deadline"], ["--allow-no-delivery-deadline"]),
        (["--allow-no-delivery-deadline", "--allow-no-penalty"],
         ["--allow-no-delivery-deadline", "--allow-no-penalty"]),
        (["--allow-unprotected-terms"], [
            "--allow-no-delivery-deadline", "--allow-no-penalty",
            "--allow-charged-preemption", "--allow-charged-term-end",
        ]),
    ],
    ids=["its-own-waiver", "with-another", "the-shorthand"],
)
def test_each_waiver_used_is_recorded_and_named_before_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flags: list[str], recorded: list[str],
) -> None:
    seen = _compose(
        monkeypatch, tmp_path, _NO_DEADLINE,
        _payment_outcome(amount=1_000_000, duration_seconds=3600, option=_NO_DEADLINE),
        accept_inside=True,
    )

    result = _buy(3600, _NO_DEADLINE, *flags)

    assert result.exit_code == 0, result.output
    assert len(seen["negotiations"]) == 1
    assert _run_started(tmp_path)["compute_term_waivers"] == recorded
    # Both disclosures before approval, the selected option's and the accepted
    # Agreement's, mark the waived refusal and name every waiver in force.
    selected, accepted = result.output.split("Accepted Agreement")
    for disclosure in (selected, accepted):
        assert ("Default buyer policy: a default buyer refuses this option: no delivery deadline; "
                "waived by --allow-no-delivery-deadline") in disclosure
        (named,) = [line for line in disclosure.splitlines() if "Waivers in force:" in line]
        assert [flag for flag in recorded if flag in named] == recorded


def test_a_run_without_waivers_records_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _compose(monkeypatch, tmp_path, _PAYMENT, _payment_outcome(amount=1_000_000, duration_seconds=3600))

    result = _buy(3600)

    assert result.exit_code == 0, result.output
    assert _run_started(tmp_path)["compute_term_waivers"] == []
    assert "Waivers in force" not in result.output


def test_request_introduction_records_dictionary_terms_when_the_deal_is_agreed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outcome = NegotiationOutcome(
        status="agreed",
        negotiation_id="negotiation-2",
        agreed_amount=0,
        accepted_provision_terms=dict(_ACCEPTED_TERMS),
        settlement_selection=SettlementSelection(
            option_id=_INTRODUCTION.option_id,
            settlement={"schema": _INTRODUCTION.settlement_schema},
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
