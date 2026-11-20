"""Drift controls for the neutral optional-read boundary."""

from dataclasses import replace

import pytest

from market_deal_lifecycle.fixtures.once_accounting import (
    build_once_accounting_read, validate_once_accounting_read,
)


def validate(read):
    validate_once_accounting_read(
        read, negotiation_id="deal", commitment_ref="commitment",
        seller_account="seller-account", minimum_sequence=0,
    )


def test_canonical_read_and_unknown_observation_satisfy_the_capture_contract():
    validate(build_once_accounting_read())
    validate(build_once_accounting_read(
        all_parts_terminal=False, accounting={"classification": "UNKNOWN", "returnAdmitted": False},
    ))


@pytest.mark.parametrize("field,value", [
    ("negotiation_id", "other"), ("commitment_ref", "other"), ("seller_account", "other"),
    ("minimum_sequence", -1), ("minimum_sequence", True), ("minimum_sequence", 2),
    ("latest_event_sequence", False), ("latest_event_sequence", -1), ("latest_event_sequence", 129),
    ("provider_observed_at", True), ("provider_observed_at", -1),
    ("verified_signature_sha256", "A" * 64), ("financial_facts_sha256", "b" * 63),
    ("part_count", 0), ("part_count", 33), ("part_count", True),
    ("livemode", True), ("all_parts_terminal", 1), ("all_parts_terminal", False),
    ("accounting", {"classification": "ACCOUNTING_TERMINAL", "returnAdmitted": True}),
    ("accounting", {"classification": "ACCOUNTING_TERMINAL"}),
    ("accounting", {"classification": "other", "returnAdmitted": False}),
])
def test_consumer_invariant_drift_is_refused(field, value):
    read = build_once_accounting_read()
    validate(read)
    with pytest.raises(AssertionError):
        validate(replace(read, projection=replace(read.projection, **{field: value})))


def test_optional_absence_and_a_foreign_normal_view_cannot_supply_capture():
    read = build_once_accounting_read()
    with pytest.raises(AssertionError):
        validate(replace(read, projection=None))
    foreign = build_once_accounting_read(negotiation_id="other")
    with pytest.raises(AssertionError):
        validate(replace(read, view=foreign.view))
