"""Terms-policy selection, loading and the packaged policies."""

from __future__ import annotations

import builtins
from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

import pytest
from market_core.schemas import SettlementOption, derive_settlement_option_id
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import TermContext, decode_terms
from market_identity import Ed25519Signer

from market_settlement_runtime.buyer_terms import BuyerTermsAdmission
from market_settlement_runtime.rate_publication import default_buyer_refusals
from market_settlement_runtime.terms_policy import (
    BUYER_TERMS_POLICY_GROUP,
    SELLER_TERMS_POLICY_GROUP,
    BuyerTermsOffer,
    DefaultBuyerTermsPolicy,
    DefaultSellerTermsPolicy,
    PermissiveBuyerTermsPolicy,
    SellerTermsOffer,
    SellerTermsReview,
    TermsPolicyError,
    TermsPolicySelection,
    flagged_buyer_selection,
    installed_terms_policies,
    load_buyer_terms_policy,
    load_seller_terms_policy,
    penalty_periods,
    review_for_publication,
    selection_refusal,
    seller_selection,
    terms_policy_selection,
)

MECHANISM = "payment.example.v1"
AUTHORITY = dict(interface="dispute.example.v1", origin="https://disputes.example",
                 account="adjudicator", record_key="record-key", params={})
EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def lifecycle(*, deadline=60, penalty="100", payee=None, term_end="last_boundary", window=120):
    entitlements = {"payer": {"notice_seconds": 0, "settles_through": "started_period"}}
    if payee is not None:
        entitlements["payee"] = {"notice_seconds": 30, "settles_through": payee}
    value = {
        "adjudication": {"version": 1, "dispute": deepcopy(AUTHORITY),
                         "dispute_window_seconds": window, "case_hold_max_seconds": None},
        "early_termination": {"version": 1, "entitlements": entitlements,
                              "settles_through": term_end, "premature_stop_penalty": penalty},
    }
    if deadline is not None:
        value["delivery_deadline_seconds"] = deadline
    return value


def option(**terms) -> SettlementOption:
    parts = dict(price={"asset": "USD/2", "rates": []}, settlement={"schema": MECHANISM},
                 lifecycle=lifecycle(**terms))
    return SettlementOption(option_id=derive_settlement_option_id(**parts), **parts)


def offer(value: SettlementOption, *, has_adapter=True) -> BuyerTermsOffer:
    return BuyerTermsOffer(value, decode_terms(value.lifecycle), has_adapter)


def admission(policy, *, accepted=True) -> BuyerTermsAdmission:
    entry = DisputeEntry.model_validate({
        **AUTHORITY, **({} if accepted else {"account": "someone-else"}),
        "advertisement": {"mechanisms": [MECHANISM], "minimum_dispute_window_seconds": 60,
                          "minimum_case_hold_seconds": None},
    })
    return BuyerTermsAdmission(AuthoritySelection({"": (entry,)}, contexts={
        MECHANISM: TermContext(
            mechanism=MECHANISM, has_adapter=True, compute=True,
            dispute_interfaces=frozenset({AUTHORITY["interface"]}), has_stoppable_part=True,
            supported_partial_periods=frozenset({"charged", "returned", "prorated"}),
        ),
    }), policy)


UNPROTECTED = [
    dict(deadline=None),
    dict(penalty="0"),
    dict(payee="started_period"),
    dict(term_end="started_period"),
    dict(deadline=None, penalty="0", payee="stop", term_end="stop"),
]


def entry(name: str, value: str, group: str = BUYER_TERMS_POLICY_GROUP) -> EntryPoint:
    return EntryPoint(name=name, value=value, group=group)


# --- selection ---------------------------------------------------------------


def test_selection_defaults_and_reads_both_forms_case_insensitively():
    assert terms_policy_selection({}) == TermsPolicySelection("default")
    assert terms_policy_selection({"TERMS_POLICY": "cautious"}).name == "cautious"
    table = terms_policy_selection({"terms_policy": {"NAME": "cautious", "Floor": 5}})
    assert (table.name, dict(table.settings)) == ("cautious", {"floor": 5})


@pytest.mark.parametrize("raw", [7, "", " padded ", {"name": 3}, ["default"]])
def test_a_malformed_selection_is_refused(raw):
    with pytest.raises(TermsPolicyError):
        terms_policy_selection({"terms_policy": raw})


def test_the_flag_selects_permissive_and_never_replaces_an_installed_policy():
    default = TermsPolicySelection()
    assert flagged_buyer_selection(default, allow_unprotected_terms=False) is default
    assert flagged_buyer_selection(default, allow_unprotected_terms=True).name == "permissive"
    custom = TermsPolicySelection("cautious", {"floor": 5})
    assert flagged_buyer_selection(custom, allow_unprotected_terms=False) is custom
    with pytest.raises(TermsPolicyError, match="'cautious'"):
        flagged_buyer_selection(custom, allow_unprotected_terms=True)


# --- loading -----------------------------------------------------------------


def test_the_packaged_policies_are_installed_under_their_names():
    """Read from this environment's metadata, so the pyproject table is what is proven."""
    assert installed_terms_policies("buyer") == ("default", "permissive")
    assert installed_terms_policies("seller") == ("default",)
    assert isinstance(load_buyer_terms_policy(), DefaultBuyerTermsPolicy)
    assert isinstance(
        load_buyer_terms_policy(TermsPolicySelection("permissive")), PermissiveBuyerTermsPolicy,
    )
    assert isinstance(load_seller_terms_policy(), DefaultSellerTermsPolicy)


def test_an_absent_policy_names_the_installed_ones_and_does_not_fall_back():
    with pytest.raises(TermsPolicyError, match=r"'cautious' is not installed; available: default, permissive"):
        load_buyer_terms_policy(TermsPolicySelection("cautious"))


def test_a_name_two_distributions_provide_is_refused():
    installed = [entry("twice", "one:factory"), entry("twice", "two:factory")]
    with pytest.raises(TermsPolicyError, match="multiple buyer terms policies named 'twice': one:factory, two:factory"):
        load_buyer_terms_policy(TermsPolicySelection("twice"), installed=installed)


def test_only_the_selected_entry_point_is_imported():
    installed = [
        entry("broken", "no_such_module_anywhere:factory"),
        *entry_points(group=BUYER_TERMS_POLICY_GROUP),
    ]
    assert isinstance(load_buyer_terms_policy(installed=installed), DefaultBuyerTermsPolicy)
    with pytest.raises(TermsPolicyError, match="'broken' failed to load"):
        load_buyer_terms_policy(TermsPolicySelection("broken"), installed=installed)


@pytest.mark.parametrize("value,message", [
    ("market_settlement_runtime.terms_policy:DEFAULT_TERMS_POLICY", "must export a factory"),
    ("builtins:dict", "at least one of refusals, prefer; got dict"),
    # A seller policy is not a buyer policy.
    ("market_settlement_runtime.terms_policy:default_seller_terms_policy", "at least one of refusals, prefer"),
])
def test_an_export_that_is_not_a_policy_factory_is_refused(value, message):
    with pytest.raises(TermsPolicyError, match=message):
        load_buyer_terms_policy(TermsPolicySelection("odd"), installed=[entry("odd", value)])


def test_a_packaged_policy_refuses_settings():
    with pytest.raises(TermsPolicyError, match="'default' rejected its settings.*floor"):
        load_buyer_terms_policy(TermsPolicySelection("default", {"floor": 5}))


# --- packaged decisions ------------------------------------------------------


@pytest.mark.parametrize("terms,reasons", [
    (dict(), ()),
    (dict(payee="last_boundary"), ()),
    (dict(deadline=None), ("no delivery deadline",)),
    (dict(penalty="0"), ("on-demand has no positive premature-stop penalty",)),
    # A payee entitlement makes the option spot, which needs no penalty.
    (dict(penalty="0", payee="last_boundary"), ()),
    (dict(payee="started_period"), ("payee stop does not return the final partial period",)),
    (dict(term_end="started_period"), ("term end does not return the final partial period",)),
    (dict(deadline=None, penalty="0", payee="stop", term_end="stop"), (
        "no delivery deadline",
        "payee stop does not return the final partial period",
        "term end does not return the final partial period",
    )),
])
def test_default_refuses_the_conservative_rights_and_permissive_declines_nothing(terms, reasons):
    value = option(**terms)
    expected = tuple(f"a default buyer refuses this option: {reason}" for reason in reasons)
    assert tuple(DefaultBuyerTermsPolicy().refusals(offer(value))) == expected
    assert default_buyer_refusals(decode_terms(value.lifecycle), has_adapter=True) == expected
    assert tuple(PermissiveBuyerTermsPolicy().refusals(offer(value))) == ()
    assert tuple(DefaultBuyerTermsPolicy().refusals(offer(value, has_adapter=False))) == ()


def test_the_default_seller_publishes_everything_and_reports_the_buyer_refusals():
    policy = DefaultSellerTermsPolicy()
    assert policy.default_penalty_periods() == 24
    value = option(deadline=None)
    reported: list[dict] = []
    assert review_for_publication(policy, value, reported.append) is True
    assert reported == [{
        "code": "default_buyer_refusal",
        "detail": "a default buyer refuses this option: no delivery deadline",
        "mechanism": MECHANISM, "option_id": value.option_id,
    }]


def test_a_seller_refusal_withholds_the_option_with_its_own_diagnostic():
    class Withholding(DefaultSellerTermsPolicy):
        def review(self, offer: SellerTermsOffer) -> SellerTermsReview:
            return SellerTermsReview(refusals=("not this one",), diagnostics=(("note", "seen"),))

    reported: list[dict] = []
    assert review_for_publication(Withholding(), option(), reported.append) is False
    assert [item["code"] for item in reported] == ["note", "seller_terms_policy_refusal"]
    assert reported[1]["detail"] == "not this one"


@pytest.mark.parametrize("periods", [-1, 1.5, True, None])
def test_a_seller_policy_with_unusable_penalty_periods_is_refused_at_load(periods, monkeypatch):
    class Odd(DefaultSellerTermsPolicy):
        def default_penalty_periods(self):
            return periods

    # An entry point resolves an importable attribute, so the factory is given one.
    monkeypatch.setattr(builtins, "_odd_seller_factory", lambda settings: Odd(), raising=False)
    with pytest.raises(TermsPolicyError, match="non-negative integer"):
        load_seller_terms_policy(TermsPolicySelection("odd"), installed=[
            entry("odd", "builtins:_odd_seller_factory", SELLER_TERMS_POLICY_GROUP),
        ])


# --- what a policy cannot waive ----------------------------------------------


@pytest.mark.parametrize("terms", UNPROTECTED)
def test_admission_follows_the_policy_for_rights(terms):
    value = option(**terms)
    with pytest.raises(ValueError, match="a default buyer refuses this option"):
        admission(DefaultBuyerTermsPolicy()).rank(value)
    assert admission(None).policy.__class__ is DefaultBuyerTermsPolicy
    assert admission(PermissiveBuyerTermsPolicy()).rank(value) == 0


def test_a_permissive_policy_does_not_admit_an_unaccepted_authority():
    with pytest.raises(ValueError, match="unaccepted dispute authority; mismatched account"):
        admission(PermissiveBuyerTermsPolicy(), accepted=False).rank(option())


def test_a_permissive_policy_does_not_waive_term_validation():
    # The window must cover the stated deadline plus the authority's minimum.
    with pytest.raises(ValueError, match="dispute window is below"):
        admission(PermissiveBuyerTermsPolicy()).rank(option(window=119))


def test_a_policy_that_fails_refuses_the_option():
    class Broken:
        def refusals(self, offer):
            raise RuntimeError("boom")

    reports: list[str] = []
    gate = admission(Broken())
    gate.authority.report = reports.append
    assert gate(option(), {}) is None
    assert reports == ["buyer terms policy failed (RuntimeError: boom)"]


# --- the documented example --------------------------------------------------


@pytest.fixture
def example_entry_points(monkeypatch):
    """The entry points docs/terms-policy-authoring.md tells an author to declare."""
    monkeypatch.syspath_prepend(str(EXAMPLES))
    return {
        "buyer": [entry("example", "terms_policies:example_buyer")],
        "seller": [entry("example", "terms_policies:example_seller", SELLER_TERMS_POLICY_GROUP)],
    }


def test_the_example_buyer_states_each_right_on_its_own(example_entry_points):
    policy = load_buyer_terms_policy(
        TermsPolicySelection("example", {"minimum_penalty": 50}),
        installed=example_entry_points["buyer"],
    )
    gate = admission(policy)
    assert gate.rank(option(deadline=None)) == 0
    with pytest.raises(ValueError, match="example buyer policy: premature-stop penalty 10 is below 50"):
        gate.rank(option(penalty="10"))
    strict = load_buyer_terms_policy(
        TermsPolicySelection("example", {"require_delivery_deadline": True}),
        installed=example_entry_points["buyer"],
    )
    assert tuple(strict.refusals(offer(option(deadline=None)))) == (
        "example buyer policy: no delivery deadline",
    )
    with pytest.raises(TermsPolicyError, match="rejected its settings: unknown settings: floor"):
        load_buyer_terms_policy(
            TermsPolicySelection("example", {"floor": 1}), installed=example_entry_points["buyer"],
        )


def test_the_example_seller_withholds_an_option_without_a_deadline(example_entry_points):
    policy = load_seller_terms_policy(
        TermsPolicySelection("example"), installed=example_entry_points["seller"],
    )
    assert policy.default_penalty_periods() == 12
    reported: list[dict] = []
    assert review_for_publication(policy, option(), reported.append) is True
    assert review_for_publication(policy, option(deadline=None), reported.append) is False
    assert [item["code"] for item in reported] == ["seller_terms_policy_refusal"]


# --- preference ----------------------------------------------------------------


class _Reversing:
    def prefer(self, offers):
        return tuple(reversed(offers))


def test_the_packaged_policies_keep_the_order_they_are_given():
    gate = admission(DefaultBuyerTermsPolicy())
    options = (option(), option(penalty="200"), option(penalty="300"))
    assert gate.order(options, {}) == options
    assert admission(PermissiveBuyerTermsPolicy()).order(options, {}) == options


def test_a_policy_that_only_orders_refuses_as_the_default_does():
    gate = admission(_Reversing())
    first, second = option(), option(penalty="200")
    assert gate.order((first, second), {"listing_id": "L"}) == (second, first)
    with pytest.raises(ValueError, match="a default buyer refuses this option"):
        gate.rank(option(deadline=None))


def test_ordering_can_neither_drop_nor_introduce_an_option():
    first, second, third = option(), option(penalty="200"), option(penalty="300")

    class OnlyThird:
        def prefer(self, offers):
            return [offers[2], offers[2]]

    assert admission(OnlyThird()).order((first, second, third), {}) == (third, first, second)

    class Inventing:
        def prefer(self, offers):
            return [BuyerTermsOffer(option(penalty="999"), None, True)]

    with pytest.raises(TermsPolicyError, match="preferred an option it was not offered"):
        admission(Inventing()).order((first, second), {})

    class Broken:
        def prefer(self, offers):
            raise RuntimeError("boom")

    with pytest.raises(TermsPolicyError, match="failed ordering options"):
        admission(Broken()).order((first, second), {})


def test_the_preference_sees_each_offers_terms_price_and_listing():
    seen = []

    class Looking:
        def prefer(self, offers):
            seen.extend(offers)
            return offers

    listing = {"listing_id": "L", "source_registry_url": "https://registry.example/"}
    first, second = option(), option(penalty="200")
    admission(Looking()).order((first, second), listing)
    assert [(o.option, o.lifecycle.early_termination.penalty, o.has_adapter, o.registry_url, o.listing)
            for o in seen] == [
        (first, 100, True, "https://registry.example/", listing),
        (second, 200, True, "https://registry.example/", listing),
    ]


# --- why nothing was selectable --------------------------------------------------


def test_the_admission_reports_policy_refusals_only_when_nothing_was_admitted():
    gate = admission(DefaultBuyerTermsPolicy())
    refused = option(deadline=None)
    assert gate.policy_refusal_report() == ()
    assert gate(refused, {}) is None
    assert gate(refused, {}) is None
    assert gate.policy_refusal_report() == (
        f"option {refused.option_id}: a default buyer refuses this option: no delivery deadline",
    )
    assert gate(option(), {}) == 0
    assert gate.policy_refusal_report() == ()


def test_an_authority_refusal_is_not_reported_as_the_policys():
    gate = admission(PermissiveBuyerTermsPolicy(), accepted=False)
    assert gate(option(), {}) is None
    assert gate.policy_refusal_report() == ()


# --- seller admission at selection -----------------------------------------------

# Public deterministic development identities, never for a public network.
BUYER = Ed25519Signer(b"\x41" * 32).identity
OTHER_BUYER = Ed25519Signer(b"\x42" * 32).identity
AT = datetime(2026, 11, 12, tzinfo=timezone.utc)


def test_the_default_seller_admits_every_selection():
    selection = seller_selection(
        option().model_dump(mode="json"), buyer=BUYER, listing={"listing_id": "L"}, at=AT,
    )
    assert selection_refusal(DefaultSellerTermsPolicy(), selection) is None
    assert selection_refusal(None, selection) is None


def test_a_seller_refusal_carries_its_code_and_the_policys_reasons():
    seen = []

    class NotThisBuyer:
        def admit(self, selection):
            seen.append(selection)
            return ("buyer is not served", "try another seller")

    value = option()
    selection = seller_selection(
        value.model_dump(mode="json"), buyer=BUYER, listing={"listing_id": "L"}, at=AT,
    )
    assert selection_refusal(NotThisBuyer(), selection) == (
        "seller_terms_policy_refusal: buyer is not served; try another seller"
    )
    (asked,) = seen
    assert (asked.option, asked.buyer, asked.listing, asked.at) == (value, BUYER, {"listing_id": "L"}, AT)
    assert asked.lifecycle.delivery_deadline_seconds == 60


def test_an_escrow_selection_has_no_option():
    selection = seller_selection(
        {"chain_name": "anvil", "escrow_address": "0x11"}, buyer=BUYER, listing={}, at=AT,
    )
    assert (selection.option, selection.lifecycle) == (None, None)


def test_a_seller_policy_that_fails_refuses_without_telling_the_buyer_why():
    class Broken:
        def admit(self, selection):
            raise RuntimeError("internal detail")

    refusal = selection_refusal(Broken(), seller_selection(None, buyer=BUYER, listing={}, at=AT))
    assert refusal == "seller_terms_policy_refusal: the seller's terms policy failed"


def test_a_seller_policy_implementing_only_admission_takes_the_default_for_the_rest(monkeypatch):
    class OnlyAdmission:
        def admit(self, selection):
            return ()

    monkeypatch.setattr(builtins, "_only_admission", lambda settings: OnlyAdmission(), raising=False)
    policy = load_seller_terms_policy(TermsPolicySelection("only"), installed=[
        entry("only", "builtins:_only_admission", SELLER_TERMS_POLICY_GROUP),
    ])
    assert penalty_periods(policy) == 24
    reported: list[dict] = []
    assert review_for_publication(policy, option(deadline=None), reported.append) is True
    assert [item["code"] for item in reported] == ["default_buyer_refusal"]


def test_the_example_seller_refuses_a_listed_buyer_and_the_example_buyer_prefers_spot(
    example_entry_points,
):
    seller = load_seller_terms_policy(
        TermsPolicySelection("example", {"refused_buyers": [BUYER.identifier]}),
        installed=example_entry_points["seller"],
    )
    selection = seller_selection(option().model_dump(mode="json"), buyer=BUYER, listing={}, at=AT)
    assert selection_refusal(seller, selection) == (
        "seller_terms_policy_refusal: this seller does not serve this buyer"
    )
    assert selection_refusal(seller, seller_selection(None, buyer=OTHER_BUYER, listing={}, at=AT)) is None

    buyer = load_buyer_terms_policy(
        TermsPolicySelection("example", {"prefer_spot": True}),
        installed=example_entry_points["buyer"],
    )
    on_demand, spot = option(), option(payee="last_boundary")
    assert admission(buyer).order((on_demand, spot), {}) == (spot, on_demand)
