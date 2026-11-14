"""The buyer's default refusals, each waived by its own flag (``BuyerTermsPolicy``,
``term_waivers``) and named in the disclosure (``lifecycle_disclosure``)."""

from __future__ import annotations

from copy import deepcopy

import pytest
from market_core.schemas import SettlementOption, derive_settlement_option_id
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import TermContext
from market_settlement_runtime.buyer_terms import (
    ALL_TERM_WAIVERS, TERM_WAIVERS, BuyerTermsPolicy, allows_missing_delivery_deadline,
    lifecycle_disclosure, term_waivers, waiver_flags, waivers_from_flags,
)
from market_settlement_runtime.rate_publication import DEFAULT_REFUSAL_REASONS

MECHANISM = "fixture.rate.v1"
# A fictional authority: the origin is a reserved name that resolves nowhere.
ENTRY = DisputeEntry.model_validate({
    "interface": "fixture.mediation.v1", "origin": "https://mediation.invalid",
    "account": "fixture-account", "record_key": "fixture-record", "params": {},
    "advertisement": {"mechanisms": [MECHANISM], "minimum_dispute_window_seconds": 60,
                      "minimum_case_hold_seconds": None},
})

ON_DEMAND = {
    "version": 1,
    "entitlements": {"payer": {"notice_seconds": 0, "settles_through": "started_period"}},
    "settles_through": "last_boundary", "premature_stop_penalty": "15000000",
}
SPOT = deepcopy(ON_DEMAND)
SPOT["entitlements"]["payee"] = {"notice_seconds": 120, "settles_through": "last_boundary"}
del SPOT["premature_stop_penalty"]


def _option(*, deadline: bool = True, early: dict | None = None, adapter: bool = True) -> SettlementOption:
    mechanism = MECHANISM if adapter else "fixture.escrow.v1"
    body: dict = {
        "price": {"asset": "USD/6", "rates": [{"field": "amount", "per": "hour", "value": "2500000"}]},
        "settlement": {"schema": mechanism, **({"period": "PT15M"} if early else {})},
    }
    if adapter:
        body["lifecycle"] = {
            "adjudication": {"version": 1, "dispute": ENTRY.authority.model_dump(mode="json"),
                             "dispute_window_seconds": 604800, "case_hold_max_seconds": None},
            **({"delivery_deadline_seconds": 1200} if deadline else {}),
            **({"early_termination": early} if early else {}),
        }
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


def _without(early: dict, key: str) -> dict:
    return {name: value for name, value in early.items() if name != key}


def _charged_seller_stop() -> dict:
    early = deepcopy(SPOT)
    early["entitlements"]["payee"]["settles_through"] = "started_period"
    return early


# One option per default refusal, each refused for that term alone.
REFUSED = {
    "no_delivery_deadline": _option(deadline=False),
    "no_penalty": _option(early=_without(ON_DEMAND, "premature_stop_penalty")),
    "charged_preemption": _option(early=_charged_seller_stop()),
    "charged_term_end": _option(early={**ON_DEMAND, "settles_through": "started_period"}),
}


def _context(waivers: frozenset) -> TermContext:
    """The context a buyer composition builds, its deadline allowance following its waivers."""
    return TermContext(
        mechanism=MECHANISM, has_adapter=True, compute=True,
        dispute_interfaces=frozenset({ENTRY.interface}), has_stoppable_part=True,
        supported_partial_periods=frozenset({"charged", "returned"}),
        allow_missing_delivery_deadline=allows_missing_delivery_deadline(waivers),
    )


def _policy(waivers: frozenset = frozenset()) -> BuyerTermsPolicy:
    return BuyerTermsPolicy(
        AuthoritySelection({"": (ENTRY,)}, contexts={MECHANISM: _context(waivers)}), waivers=waivers,
    )


def test_each_option_is_refused_by_a_default_buyer_naming_its_term():
    for term, option in REFUSED.items():
        with pytest.raises(ValueError) as refused:
            _policy().rank(option)
        assert str(refused.value) == (
            f"a default buyer refuses this option: {DEFAULT_REFUSAL_REASONS[term]}"
        ), term
    assert _policy().rank(_option(early=ON_DEMAND)) == 0
    assert _policy().rank(_option(early={**SPOT, "premature_stop_penalty": "0"})) == 0


@pytest.mark.parametrize("waived", sorted(REFUSED))
def test_each_flag_waives_exactly_its_refusal(waived):
    # Each refusal's term is also its keyword in ``term_waivers``.
    waivers = term_waivers(**{waived: True})
    assert waivers == {waived}
    for term, option in REFUSED.items():
        if term == waived:
            assert _policy(waivers).rank(option) == 0
        else:
            with pytest.raises(ValueError, match="a default buyer refuses this option"):
                _policy(waivers).rank(option)


def test_the_shorthand_waives_all_four():
    waivers = term_waivers(unprotected_terms=True)
    assert waivers == ALL_TERM_WAIVERS == {waiver.term for waiver in TERM_WAIVERS}
    assert len(ALL_TERM_WAIVERS) == 4
    for option in REFUSED.values():
        assert _policy(waivers).rank(option) == 0


def test_a_waiver_does_not_bypass_the_codec_or_an_unsupported_treatment():
    policy = BuyerTermsPolicy(AuthoritySelection({"": (ENTRY,)}, contexts={MECHANISM: TermContext(
        mechanism=MECHANISM, has_adapter=True, compute=True,
        dispute_interfaces=frozenset({ENTRY.interface}), has_stoppable_part=True,
        supported_partial_periods=frozenset({"charged"}),
    )}), waivers=ALL_TERM_WAIVERS)
    with pytest.raises(ValueError, match="unsupported"):
        policy.rank(_option(early=ON_DEMAND))
    with pytest.raises(ValueError, match="No dispute authority is available"):
        BuyerTermsPolicy(
            AuthoritySelection({}, contexts={MECHANISM: _context(ALL_TERM_WAIVERS)}),
            waivers=ALL_TERM_WAIVERS,
        ).rank(_option(early=ON_DEMAND))


@pytest.mark.parametrize(("flags", "allowed"), [
    ({"no_delivery_deadline": True}, True),
    ({"unprotected_terms": True}, True),
    ({"no_penalty": True}, False),
    ({"charged_preemption": True}, False),
    ({"charged_term_end": True}, False),
    ({"no_penalty": True, "charged_preemption": True, "charged_term_end": True}, False),
    ({}, False),
])
def test_only_the_deadline_waiver_or_the_shorthand_sets_the_foundation_allowance(flags, allowed):
    assert allows_missing_delivery_deadline(term_waivers(**flags)) is allowed


def test_the_foundation_still_refuses_a_missing_deadline_its_allowance_does_not_admit():
    # The policy's waiver alone is moot: the codec refuses a buyer the option
    # unless the context's allowance, which follows the same waiver, is set.
    policy = BuyerTermsPolicy(
        AuthoritySelection({"": (ENTRY,)}, contexts={MECHANISM: _context(frozenset())}),
        waivers=frozenset({"no_delivery_deadline"}),
    )
    with pytest.raises(ValueError, match="compute option has no delivery_deadline_seconds"):
        policy.rank(REFUSED["no_delivery_deadline"])


def test_an_unknown_waiver_is_refused():
    with pytest.raises(ValueError, match="unknown default-refusal waivers"):
        BuyerTermsPolicy(AuthoritySelection({}, contexts={}), waivers=frozenset({"no_bond"}))


def test_waiver_flags_are_named_in_the_order_buyers_show_them():
    assert waiver_flags(ALL_TERM_WAIVERS) == (
        "--allow-no-delivery-deadline", "--allow-no-penalty",
        "--allow-charged-preemption", "--allow-charged-term-end",
    )
    assert waiver_flags({"charged_term_end", "no_penalty"}) == (
        "--allow-no-penalty", "--allow-charged-term-end",
    )
    assert waiver_flags(frozenset()) == ()


@pytest.mark.parametrize("waivers", [
    frozenset(), frozenset({"no_penalty"}), frozenset({"no_delivery_deadline", "charged_term_end"}),
    ALL_TERM_WAIVERS,
], ids=["none", "one", "two", "all"])
def test_a_recorded_run_reads_back_the_waivers_it_was_started_under(waivers):
    assert waivers_from_flags(list(waiver_flags(waivers))) == waivers


def test_an_unknown_recorded_waiver_is_refused_rather_than_dropped():
    with pytest.raises(ValueError, match="unknown recorded waivers: \\['--allow-unprotected-terms'\\]"):
        waivers_from_flags(["--allow-no-penalty", "--allow-unprotected-terms"])


def _rows(option: SettlementOption, waivers: frozenset, *, adapter: bool = True) -> dict[str, list[str]]:
    context = TermContext(mechanism=option.settlement_schema, has_adapter=adapter)
    rows: dict[str, list[str]] = {}
    for name, value in lifecycle_disclosure(option, context=context, waivers=waivers):
        rows.setdefault(name, []).append(value)
    return rows


def test_the_disclosure_names_each_waiver_and_marks_the_refusal_it_waives():
    option = _option(early={**_without(ON_DEMAND, "premature_stop_penalty"), "settles_through": "started_period"})
    rows = _rows(option, frozenset({"no_penalty"}))
    assert rows["Default buyer policy"] == [
        "a default buyer refuses this option: on-demand has no positive premature-stop penalty; "
        "waived by --allow-no-penalty",
        "a default buyer refuses this option: term end does not return the final partial period",
    ]
    (named,) = rows["Waivers in force"]
    assert "--allow-no-penalty (on-demand has no positive premature-stop penalty)" in named
    assert "--allow-charged-term-end" not in named


def test_the_disclosure_names_waivers_an_option_does_not_need():
    rows = _rows(_option(early=ON_DEMAND), ALL_TERM_WAIVERS)
    assert "Default buyer policy" not in rows
    (named,) = rows["Waivers in force"]
    assert all(flag in named for flag in waiver_flags(ALL_TERM_WAIVERS))
    no_adapter = _rows(_option(adapter=False), frozenset({"no_delivery_deadline"}), adapter=False)
    assert no_adapter["Waivers in force"] == [
        "--allow-no-delivery-deadline (no delivery deadline). "
        "This run accepts these terms a default buyer refuses."
    ]


def test_a_run_without_waivers_discloses_none():
    assert "Waivers in force" not in _rows(REFUSED["no_penalty"], frozenset())
    assert "Waivers in force" not in _rows(_option(adapter=False), frozenset(), adapter=False)
