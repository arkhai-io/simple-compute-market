"""The term codec refuses malformed or unrealizable accepted rights."""

from copy import deepcopy
from dataclasses import replace

import pytest
from market_core.schemas import derive_settlement_option_id

from market_deal_lifecycle.terms import (
    AuthorityRequirements, DisputeAuthority, TermContext, decode_terms, encode_terms,
    partial_period, validate_terms,
)


AUTHORITY = dict(interface="dispute.example.v1", origin="https://disputes.example",
                 account="adjudicator", record_key="record-key", params={})


def terms():
    return {
        "adjudication": {"version": 1, "dispute": deepcopy(AUTHORITY),
                         "dispute_window_seconds": 120, "case_hold_max_seconds": None},
        "early_termination": {"version": 1,
                             "entitlements": {"payer": {"notice_seconds": 0, "settles_through": "started_period"}},
                             "settles_through": "last_boundary", "premature_stop_penalty": "100"},
        "delivery_deadline_seconds": 60,
    }


def context(**kwargs):
    authority = DisputeAuthority(**AUTHORITY)
    base = TermContext(mechanism="payment.example.v1", has_adapter=True,
                       dispute_interfaces=frozenset({authority.interface}),
                       authority=AuthorityRequirements(authority, frozenset({"payment.example.v1"}), 60, None),
                       has_stoppable_part=True, supported_partial_periods=frozenset({"charged", "returned", "prorated"}),
                       compute=True)
    return replace(base, **kwargs)


def change(data, path, value):
    parts = path.split(".")
    target = data
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    return data


@pytest.mark.parametrize("path,value", [
    ("adjudication.version", 2), ("early_termination.version", True),
    ("early_termination.entitlements", {}), ("early_termination.entitlements.stranger", {}),
    ("early_termination.entitlements.payer.notice_seconds", -1),
    ("early_termination.entitlements.payer.notice_seconds", 1.5),
    ("early_termination.entitlements.payer.settles_through", "stop+exposure"),
    ("early_termination.settles_through", "unknown"),
    ("early_termination.exposure_seconds", 0),
    ("early_termination.maximum_term_seconds", 1),
    ("early_termination.premature_stop_penalty", "-1"),
    ("early_termination.premature_stop_penalty", "01"),
    ("early_termination.premature_stop_penalty", "1.0"),
    ("early_termination.premature_stop_penalty", 1),
    ("early_termination.premature_stop_penalty", None),
    ("adjudication.case_hold_max_seconds", -1),
    ("adjudication.case_hold_max_seconds", True),
    ("adjudication.case_hold_max_seconds", 1.5),
    ("adjudication.dispute_window_seconds", -1),
    ("delivery_deadline_seconds", 0), ("delivery_deadline_seconds", -1),
    ("delivery_deadline_seconds", 1.5), ("delivery_deadline_seconds", True),
])
def test_malformed_terms_are_refused(path, value):
    with pytest.raises(ValueError):
        validate_terms(change(terms(), path, value), context())


def test_a_missing_cap_is_not_unbounded():
    data = terms()
    del data["adjudication"]["case_hold_max_seconds"]
    with pytest.raises(ValueError):
        decode_terms(data)


@pytest.mark.parametrize("cap,minimum,accepted", [
    (0, None, False), (0, 1, False), (0, 0, True),
    (10, 10, True), (9, 10, False), (None, 10, True), (None, None, True),
])
def test_case_hold_minimum(cap, minimum, accepted):
    ctx = context()
    ctx = replace(ctx, authority=replace(ctx.authority, minimum_case_hold_seconds=minimum))
    data = change(terms(), "adjudication.case_hold_max_seconds", cap)
    if accepted:
        assert validate_terms(data, ctx)
    else:
        with pytest.raises(ValueError, match="case hold"):
            validate_terms(data, ctx)


@pytest.mark.parametrize("deadline,window", [(60, 120), (600, 660)])
def test_window_includes_the_delivery_deadline_and_authority_minimum(deadline, window):
    data = change(terms(), "delivery_deadline_seconds", deadline)
    data["adjudication"]["dispute_window_seconds"] = window
    with pytest.raises(ValueError, match="dispute window"):
        validate_terms(change(deepcopy(data), "adjudication.dispute_window_seconds", window - 1), context())
    assert validate_terms(data, context())
    data = terms()
    del data["delivery_deadline_seconds"]
    data["adjudication"]["dispute_window_seconds"] = 59
    with pytest.raises(ValueError, match="dispute window"):
        validate_terms(data, context(compute=False))


@pytest.mark.parametrize("changes,reason", [
    ({"has_adapter": False}, "no lifecycle adapter"),
    ({"dispute_interfaces": frozenset()}, "no dispute adapter"),
    ({"has_stoppable_part": False}, "stoppable part"),
    ({"supported_partial_periods": frozenset()}, "installed payment contract"),
    ({"buyer": True}, "unaccepted dispute authority"),
    ({"authority": None}, "advertisement"),
])
def test_context_refusals(changes, reason):
    with pytest.raises(ValueError, match=reason):
        validate_terms(terms(), context(**changes))


def test_authority_compatibility_and_exact_identity():
    ctx = context()
    with pytest.raises(ValueError, match="does not advertise"):
        validate_terms(terms(), replace(ctx, authority=replace(ctx.authority, mechanisms=frozenset())))
    for field, value in [("origin", "https://other.example"), ("account", "other"),
                         ("record_key", "other"), ("interface", "other.v1"), ("params", {"other": True})]:
        accepted = DisputeAuthority(**dict(AUTHORITY, **{field: value}))
        with pytest.raises(ValueError, match="unaccepted"):
            validate_terms(terms(), context(buyer=True, accepted_authorities=(accepted,)))


def test_once_no_adapter_and_reserved_bond():
    data = terms()
    del data["early_termination"]
    assert validate_terms(data, context(has_stoppable_part=False))
    assert validate_terms(None, context(has_adapter=False)) is None
    with pytest.raises(ValueError, match="requires adjudication"):
        validate_terms(None, context())
    data["bond"] = {"version": 1, "amount": "1"}
    with pytest.raises(ValueError, match="reserved"):
        validate_terms(data, context())


def test_default_buyer_deadline_policy_is_separate_from_publication():
    data = terms()
    del data["delivery_deadline_seconds"]
    assert validate_terms(data, context())
    accepted = (DisputeAuthority(**AUTHORITY),)
    with pytest.raises(ValueError, match="no delivery_deadline"):
        validate_terms(data, context(buyer=True, accepted_authorities=accepted))
    assert validate_terms(data, context(buyer=True, accepted_authorities=accepted,
                                        allow_missing_delivery_deadline=True))


@pytest.mark.parametrize("value,mapped", [
    ("started_period", "charged"), ("last_boundary", "returned"), ("stop", "prorated"),
])
def test_treatments_map_without_local_money_corrections(value, mapped):
    assert partial_period(value, frozenset({mapped})) == mapped
    with pytest.raises(ValueError):
        partial_period(value, frozenset())


def test_codec_roundtrip_and_term_identity():
    data = terms()
    encoded = encode_terms(decode_terms(data))
    assert encoded == data
    assert decode_terms(encoded) == decode_terms(data)
    changed = change(deepcopy(encoded), "adjudication.dispute_window_seconds", 121)
    # Lifecycle rights participate in identity independently of mechanism parameters.
    first = derive_settlement_option_id(
        settlement={"schema": "example.v1"}, lifecycle=encoded
    )
    second = derive_settlement_option_id(
        settlement={"schema": "example.v1"}, lifecycle=changed
    )
    assert first != second


def test_absent_and_zero_penalty_both_mean_none():
    data = terms()
    del data["early_termination"]["premature_stop_penalty"]
    assert decode_terms(data).early_termination.penalty == 0
    data["early_termination"]["premature_stop_penalty"] = "0"
    assert decode_terms(data).early_termination.penalty == 0
