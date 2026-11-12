"""What a buyer is shown before approval: the default refusals as a seller reads
them (``default_buyer_refusals``), the codec-derived lifecycle rows
(``lifecycle_disclosure``), and the money the selected mechanism presents, which
the registry holds to the option's basis and asset and to the accepted quote
(``present_payment``, ``compute_disclosure``)."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

import pytest
from market_core.schemas import AgreedPrice, Agreement, PriceBasis, SettlementOption
from market_deal_lifecycle.terms import TermContext, decode_terms
from market_settlement_runtime import (
    MechanismRegistration,
    MechanismReadiness,
    SettlementConfigurationError,
    SettlementConfigurationRegistry,
)
from market_settlement_runtime.buyer_terms import compute_disclosure, lifecycle_disclosure
from market_settlement_runtime.presentation import PaymentPresentation, amount_rate_quote
from market_settlement_runtime.rate_publication import default_buyer_refusals
from pydantic import BaseModel, ConfigDict

from test_buyer_terms import ENTRY, MECHANISM, ON_DEMAND, SPOT, _option

#: The fixture options' PT15M period: 2,500,000 an hour is 625,000 a period.
PERIOD = PriceBasis(unit="per_period", period="PT15M", period_seconds=900)
PERIOD_PRICE = 625_000


def _rows(rows: tuple[tuple[str, str], ...]) -> dict[str, list[str]]:
    named: dict[str, list[str]] = {}
    for name, value in rows:
        named.setdefault(name, []).append(value)
    return named


# ---------------------------------------------------------------------------
# default_buyer_refusals: the seller's diagnostic of the buyer's policy
# ---------------------------------------------------------------------------


def test_a_seller_reads_no_refusal_for_an_option_whose_mechanism_has_no_adapter():
    assert default_buyer_refusals(None, has_adapter=False) == ()


def test_a_seller_reads_no_refusal_for_protected_terms():
    for early in (None, ON_DEMAND, SPOT):
        option = _option(early=early)
        assert default_buyer_refusals(decode_terms(option.lifecycle), has_adapter=True) == (), early


def test_a_seller_reads_each_term_a_default_buyer_refuses_in_one_wording():
    assert default_buyer_refusals(None, has_adapter=True) == (
        "a default buyer refuses this option: no delivery deadline",
    )
    early = deepcopy(SPOT)
    early["entitlements"]["payee"]["settles_through"] = "started_period"
    early["settles_through"] = "started_period"
    option = _option(deadline=False, early=early)
    assert default_buyer_refusals(decode_terms(option.lifecycle), has_adapter=True) == (
        "a default buyer refuses this option: no delivery deadline",
        "a default buyer refuses this option: payee stop does not return the final partial period",
        "a default buyer refuses this option: term end does not return the final partial period",
    )
    unpenalized = {**ON_DEMAND, "premature_stop_penalty": "0"}
    assert default_buyer_refusals(decode_terms(_option(early=unpenalized).lifecycle), has_adapter=True) == (
        "a default buyer refuses this option: on-demand has no positive premature-stop penalty",
    )


# ---------------------------------------------------------------------------
# lifecycle_disclosure: the codec's values, never a stored class
# ---------------------------------------------------------------------------


def _context(*, adapter: bool = True, mechanism: str = MECHANISM) -> TermContext:
    return TermContext(mechanism=mechanism, has_adapter=adapter)


def test_an_on_demand_option_discloses_each_stopper_its_term_end_and_its_penalty():
    rows = _rows(lifecycle_disclosure(_option(early=ON_DEMAND), context=_context()))
    assert rows["Delivery deadline"] == [
        "Active within 1200 seconds after your approval (or the agreed start, if later), "
        "or the seller has not delivered."
    ]
    assert rows["Buyer stop"] == [
        "Entitled with 0 seconds' notice; settles_through=started_period (final partial period charged)."
    ]
    assert rows["Seller stop"] == ["No entitled payment stop."]
    assert rows["Term end"] == ["settles_through=last_boundary (final partial period returned)."]
    (penalty,) = rows["Premature-stop penalty"]
    assert penalty.startswith("Up to 15000000 minor units of USD/6; for an unentitled seller end")
    assert "Nothing earned and held means nothing taken. This is a ceiling, not a guaranteed payment." in penalty
    (end,) = rows["Buyer end"]
    assert end.startswith("Stop at the payment authority first under the agreed notice, then hint the seller.")
    assert rows["Dispute authority"] == [
        f"{ENTRY.interface} at {ENTRY.origin}; account={ENTRY.account}; "
        f"record_key={ENTRY.record_key}; params={{}}"
    ]
    assert rows["Dispute window"] == ["604800 seconds"]
    assert rows["Case-hold cap"] == ["Unbounded"]
    assert {"Notice enforcement", "Rate start", "Reserve protection", "Setup charge",
            "Cases and holds", "Evidence retention"} <= set(rows)
    assert "Default buyer policy" not in rows


def test_a_spot_option_discloses_the_seller_s_notice_stop():
    rows = _rows(lifecycle_disclosure(_option(early=SPOT), context=_context()))
    assert rows["Seller stop"] == [
        "Entitled with 120 seconds' notice; settles_through=last_boundary (final partial period returned)."
    ]
    assert rows["Premature-stop penalty"][0].startswith("Up to 0 minor units of USD/6")


def test_a_once_option_discloses_no_entitled_stop():
    rows = _rows(lifecycle_disclosure(_option(), context=_context()))
    assert rows["Early termination"] == [
        "No entitled payment stops; no early-termination penalty is promised."
    ]
    assert not {"Buyer end", "Term end", "Premature-stop penalty"} & set(rows)
    assert rows["Buyer stop"] == rows["Seller stop"] == ["No entitled payment stop."]


def test_an_option_without_a_deadline_says_so_beside_the_refusal():
    rows = _rows(lifecycle_disclosure(_option(deadline=False), context=_context()))
    assert rows["Delivery deadline"] == ["No delivery deadline is promised."]
    assert rows["Default buyer policy"] == ["a default buyer refuses this option: no delivery deadline"]


def test_an_option_with_no_adapter_makes_no_delivery_promise():
    option = _option(adapter=False)
    rows = _rows(lifecycle_disclosure(option, context=_context(adapter=False, mechanism=option.settlement_schema)))
    assert rows == {
        "Delivery promise": ["None: this option has no lifecycle adapter and makes no delivery promise."],
        "Adjudication": ["No lifecycle adjudication is promised by this option."],
    }


def test_the_disclosure_refuses_a_context_that_does_not_fit_the_option():
    with pytest.raises(ValueError, match="names another mechanism"):
        lifecycle_disclosure(_option(), context=_context(mechanism="fixture.other.v1"))
    with pytest.raises(ValueError, match="has no lifecycle adapter"):
        lifecycle_disclosure(_option(), context=_context(adapter=False))
    no_terms = _option(adapter=False)
    with pytest.raises(ValueError, match="a lifecycle adapter requires adjudication"):
        lifecycle_disclosure(no_terms, context=_context(mechanism=no_terms.settlement_schema))


# ---------------------------------------------------------------------------
# present_payment: the registry holds the owner's numbers to the option
# ---------------------------------------------------------------------------


class _Settings(BaseModel):
    enabled: bool = False


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


Presenter = Callable[[SettlementOption, int | None, AgreedPrice | None], PaymentPresentation]


def _quoting(option: SettlementOption, duration: int | None, quote: AgreedPrice | None) -> PaymentPresentation:
    """A mechanism owner's presenter: one period's quote and a two-period reserve."""
    quote = quote or amount_rate_quote(option, duration, PERIOD)
    return PaymentPresentation(quote=quote, setup_once=0, initial_reserve=2 * quote.amount)


def _registry(
    *, present: Presenter | None = _quoting, basis: PriceBasis | None = PERIOD,
) -> SettlementConfigurationRegistry:
    async def preflight(config, resources, role):
        return MechanismReadiness(mechanism=MECHANISM, configured=True, enabled=True, ready=True)

    return SettlementConfigurationRegistry((MechanismRegistration(
        mechanism_id=MECHANISM, config_key="fixture", config_model=_Settings,
        roles=frozenset({"buyer", "seller"}), preflight=preflight, client_factory=None,
        option_builder=lambda *_args: {}, buyer_compatibility=lambda *_args: True,
        clause_fields=(), publication_input_model=_Input,
        publication_input_validator=lambda section, value, role: value,
        project_billing=(lambda _option: basis) if basis is not None else None,
        present_payment=present,
    ),))


def _quote(**changes) -> AgreedPrice:
    return AgreedPrice(**{**PERIOD.model_dump(), "amount": PERIOD_PRICE, "asset": "USD/6", **changes})


def _presenting(quote: AgreedPrice) -> Presenter:
    return lambda option, duration, accepted: PaymentPresentation(quote=quote, setup_once=0, initial_reserve=0)


def test_the_owner_s_presentation_is_returned_when_it_matches_the_option():
    option = _option(early=ON_DEMAND)
    shown = _registry().present_payment(option)
    assert shown == PaymentPresentation(quote=_quote(), setup_once=0, initial_reserve=2 * PERIOD_PRICE)
    assert _registry().present_payment(option, quote=_quote()) == shown


@pytest.mark.parametrize("quote", [
    AgreedPrice(unit="total", amount=PERIOD_PRICE, asset="USD/6"),
    AgreedPrice(unit="per_period", period="PT1M", period_seconds=60, amount=PERIOD_PRICE, asset="USD/6"),
    AgreedPrice(unit="per_period", period="PT15M", period_seconds=900, amount=PERIOD_PRICE, asset="USD/2"),
], ids=["basis", "period", "asset"])
def test_a_presentation_off_the_option_s_basis_or_asset_is_refused(quote):
    with pytest.raises(SettlementConfigurationError, match="differs from selected or accepted quote"):
        _registry(present=_presenting(quote)).present_payment(_option(early=ON_DEMAND))


def test_a_presentation_that_changes_accepted_money_is_refused():
    accepted = _quote()
    with pytest.raises(SettlementConfigurationError, match="differs from selected or accepted quote"):
        _registry(present=_presenting(_quote(amount=PERIOD_PRICE + 1))).present_payment(
            _option(early=ON_DEMAND), quote=accepted,
        )


def test_a_mechanism_without_a_presenter_or_projection_is_refused():
    option = _option(early=ON_DEMAND)
    with pytest.raises(SettlementConfigurationError, match="has no payment presentation"):
        _registry(present=None).present_payment(option)
    with pytest.raises(SettlementConfigurationError, match="has no billing projection"):
        _registry(basis=None).present_payment(option)


# ---------------------------------------------------------------------------
# compute_disclosure: one period's price shown as such, never scaled
# ---------------------------------------------------------------------------


def _agreement(option: SettlementOption, amount: int, duration_seconds: int) -> Agreement:
    return Agreement(
        negotiation_id="neg-1", listing_id="listing-1", listing_hash="0" * 64,
        buyer={"scheme": "ed25519", "identifier": "buyer"},
        seller={"scheme": "ed25519", "identifier": "seller"},
        settlement=option, amount=amount, asset="USD/6", duration_seconds=duration_seconds,
        start_utc="2026-01-01T00:00:00Z", accepted_at="2026-01-01T00:00:00Z",
    )


def test_an_accepted_per_period_agreement_is_shown_as_one_period_s_price():
    option = _option(early=ON_DEMAND)
    # Two days: a reader taking the amount for a total would show 625,000 for
    # the whole horizon, one scaling it again 192 times as much.
    rows = _rows(compute_disclosure(
        option, registry=_registry(), agreement=_agreement(option, PERIOD_PRICE, 172_800),
    ))
    assert rows["Class"] == ["on-demand"]
    assert rows["Accepted price"] == ["625000 minor units of USD/6 per_period (PT15M, 900 seconds)"]
    assert rows["Initial reserve"] == ["1250000 minor units of USD/6; reserved funds, not spend or a loss cap."]
    assert rows["Effective horizon"] == ["172800 seconds (not rounded to periods)"]
    assert rows["Maximum accepted end"] == ["2026-01-03T00:00:00+00:00"]
    assert not any("120000000" in value for values in rows.values() for value in values)


def test_a_selected_recurring_option_is_shown_with_its_class_and_omitted_horizon():
    rows = _rows(compute_disclosure(
        _option(early=SPOT), registry=_registry(),
        listing={"max_duration_seconds": 7200, "available_until_utc": "2026-12-31T00:00:00Z"},
    ))
    assert rows["Class"] == ["spot"]
    assert rows["Selected price"] == ["625000 minor units of USD/6 per_period (PT15M, 900 seconds)"]
    assert rows["Asking rate"] == ["2500000 minor units of USD/6 per hour (amount)"]
    assert rows["Maximum duration"] == ["7200 seconds"]
    assert rows["Available until"] == ["2026-12-31T00:00:00Z"]
    assert rows["Requested horizon"][0].startswith("Omitted; seller resolves the finite bound")


def test_a_whole_term_option_is_shown_as_a_reserved_total():
    def whole_term(option, duration, quote):
        quote = quote or amount_rate_quote(option, duration, PriceBasis(unit="total"))
        return PaymentPresentation(quote=quote, setup_once=0, initial_reserve=0)

    option = _option()
    registry = _registry(present=whole_term, basis=PriceBasis(unit="total"))
    rows = _rows(compute_disclosure(option, registry=registry, duration_seconds=7200))
    assert rows["Class"] == ["reserved"]
    assert rows["Selected price"] == ["5000000 minor units of USD/6 total"]
    assert rows["Requested horizon"] == ["7200 seconds (not rounded to periods)"]


def test_the_disclosure_refuses_an_option_other_than_the_accepted_one():
    accepted = _agreement(_option(early=ON_DEMAND), PERIOD_PRICE, 7200)
    with pytest.raises(ValueError, match="differs from accepted Agreement"):
        compute_disclosure(_option(early=SPOT), registry=_registry(), agreement=accepted)
