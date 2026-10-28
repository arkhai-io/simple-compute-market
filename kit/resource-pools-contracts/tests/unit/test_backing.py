from __future__ import annotations

import asyncio

import pytest

from market_resource_pools_contracts.backing import (
    BACKED,
    UNBACKED,
    CapacityNotAdmittedError,
    DeliveryTermsError,
    UnknownCapacityBackingError,
    admitted_backing,
    capacity_backing,
    capacity_backing_labels,
    labels_reconciled_by_availability,
    legacy_producer_backing,
)
from market_resource_pools_contracts.hints import (
    ADVERTISABLE_EXCEEDS_DELIVERABLE,
    UNBACKED_POOL_DELIVERS,
    pool_declaration_problems,
)


def _never():
    raise AssertionError("must not be called")


async def _never_async():
    raise AssertionError("must not be called")


class TestRegistry:
    @pytest.mark.parametrize("delegate", [BACKED, UNBACKED])
    def test_a_label_selects_its_delegate(self, delegate):
        assert capacity_backing(delegate.label) is delegate

    @pytest.mark.parametrize("label", ["Backed", "", None, 1, "maybe"])
    def test_a_label_with_no_delegate_is_refused(self, label):
        with pytest.raises(UnknownCapacityBackingError):
            capacity_backing(label)

    def test_the_registry_accepts_exactly_what_the_resolver_accepts(self):
        def valid(label):
            tags = {
                "advertisable_modes": [],
                "deliverable_modes": [],
                "capacity_backing": label,
            }
            return pool_declaration_problems(tags) == ()

        assert capacity_backing_labels() == {"backed", "unbacked"}
        assert all(valid(label) for label in capacity_backing_labels())
        assert not valid("maybe")

    def test_only_admitted_supply_is_reconciled_by_availability(self):
        assert labels_reconciled_by_availability() == {BACKED.label}

    def test_older_producers_and_admitted_reservations_are_backed(self):
        assert legacy_producer_backing() is BACKED
        assert admitted_backing() is BACKED

    def test_delegates_compare_by_identity(self):
        assert BACKED != UNBACKED
        assert capacity_backing("backed") == BACKED


class TestDeclarationProblems:
    def test_backed_supply_advertises_only_what_it_delivers(self):
        assert BACKED.declaration_problems(frozenset({"vm"}), frozenset({"vm"})) == ()
        (problem,) = BACKED.declaration_problems(
            frozenset({"vm", "bare_metal"}), frozenset({"vm"})
        )
        assert problem.code == ADVERTISABLE_EXCEEDS_DELIVERABLE
        assert "bare_metal" in problem.message

    def test_unbacked_supply_delivers_nothing(self):
        assert UNBACKED.declaration_problems(frozenset({"vm"}), frozenset()) == ()
        (problem,) = UNBACKED.declaration_problems(frozenset({"vm"}), frozenset({"vm"}))
        assert problem.code == UNBACKED_POOL_DELIVERS


class TestRequireAdmission:
    def test_backed_supply_is_admitted(self):
        BACKED.require_admission("reserve")

    def test_unbacked_supply_is_refused_naming_the_effect(self):
        with pytest.raises(CapacityNotAdmittedError, match="reserve"):
            UNBACKED.require_admission("reserve")


class TestPlaceHold:
    def test_backed_supply_places_the_hold(self):
        async def place():
            return "held"

        assert asyncio.run(BACKED.place_hold(place)) == "held"

    def test_unbacked_supply_never_places_it(self):
        assert asyncio.run(UNBACKED.place_hold(_never_async)) is None


class TestJudge:
    def test_backed_supply_is_judged_against_availability_when_its_declaration_fits(self):
        assert BACKED.judge(lambda: None, lambda: "unavailable") == "unavailable"
        assert BACKED.judge(lambda: None, lambda: None) is None

    def test_a_declared_refusal_is_returned_without_reading_availability(self):
        assert BACKED.judge(lambda: "declared_mismatch", _never) == "declared_mismatch"
        assert UNBACKED.judge(lambda: "declared_mismatch", _never) == "declared_mismatch"

    def test_unbacked_supply_is_never_judged_against_availability(self):
        assert UNBACKED.judge(lambda: None, _never) is None

    def test_the_async_form_decides_identically(self):
        async def fits():
            return None

        async def taken():
            return "unavailable"

        assert asyncio.run(BACKED.judge_async(fits, taken)) == "unavailable"
        assert asyncio.run(UNBACKED.judge_async(fits, _never_async)) is None


class TestAdmissibleSettlement:
    _CLAUSES = (
        {"mechanism": "alkahest.v1"},
        {"mechanism": "contact.v1"},
        {"mechanism": "alkahest.v1"},
    )

    @staticmethod
    def _split(delegate):
        return delegate.admissible_settlement(
            TestAdmissibleSettlement._CLAUSES,
            mechanism=lambda clause: clause["mechanism"],
            fulfils_through_capacity=lambda name: name == "alkahest.v1",
        )

    def test_backed_supply_keeps_every_clause(self):
        assert self._split(BACKED) == (self._CLAUSES, ())

    def test_unbacked_supply_drops_mechanisms_fulfilled_through_capacity(self):
        kept, dropped = self._split(UNBACKED)

        assert kept == ({"mechanism": "contact.v1"},)
        assert dropped == ("alkahest.v1",)


_PRESENT_TERMS = {
    "host_id": "kvm-1",
    "access_methods": ["ssh"],
    "available": True,
}
_PRESENT_VALUES = ["kvm-1", ["ssh"], {"ssh": {}}, True, False, 0, 7]
_ABSENT_VALUES = [None, "", [], (), {}]


class TestCarryDeliveryTerms:
    @pytest.mark.parametrize("value", _PRESENT_VALUES + _ABSENT_VALUES)
    def test_backed_supply_carries_the_terms_as_given(self, value):
        terms = {**_PRESENT_TERMS, "term": value}

        carried = BACKED.carry_delivery_terms(terms)

        assert carried == terms
        assert carried is not terms

    @pytest.mark.parametrize("value", _PRESENT_VALUES + _ABSENT_VALUES)
    def test_unbacked_supply_carries_none_of_them(self, value):
        assert UNBACKED.carry_delivery_terms({**_PRESENT_TERMS, "term": value}) == {}


class TestDeliveryTermConstraints:
    @pytest.mark.parametrize("value", _PRESENT_VALUES)
    def test_backed_supply_accepts_a_present_term(self, value):
        BACKED.delivery_term_constraints({"term": value})

    @pytest.mark.parametrize("value", _ABSENT_VALUES)
    def test_backed_supply_refuses_an_absent_or_empty_term(self, value):
        with pytest.raises(DeliveryTermsError) as refused:
            BACKED.delivery_term_constraints({**_PRESENT_TERMS, "term": value})

        assert refused.value.terms == ("term",)
        assert isinstance(refused.value, ValueError)

    def test_an_unavailable_backed_host_states_its_term(self):
        BACKED.delivery_term_constraints({**_PRESENT_TERMS, "available": False})

    @pytest.mark.parametrize("value", _ABSENT_VALUES)
    def test_unbacked_supply_accepts_an_absent_or_empty_term(self, value):
        UNBACKED.delivery_term_constraints({"term": value})

    @pytest.mark.parametrize("value", _PRESENT_VALUES)
    def test_unbacked_supply_refuses_a_present_term(self, value):
        with pytest.raises(DeliveryTermsError) as refused:
            UNBACKED.delivery_term_constraints({"term": value})

        assert refused.value.terms == ("term",)

    def test_a_refusal_names_every_offending_term(self):
        with pytest.raises(DeliveryTermsError, match="host_id, physical_host_id") as refused:
            BACKED.delivery_term_constraints(
                {"host_id": None, "physical_host_id": "", "available": False}
            )
        assert refused.value.terms == ("host_id", "physical_host_id")

        with pytest.raises(DeliveryTermsError) as refused:
            UNBACKED.delivery_term_constraints({**_PRESENT_TERMS, "physical_host_id": None})
        assert refused.value.terms == ("host_id", "access_methods", "available")

    def test_no_terms_constrain_nothing(self):
        BACKED.delivery_term_constraints({})
        UNBACKED.delivery_term_constraints({})
