"""The one rule every provider validates a pool's ``relay_id`` by."""

from __future__ import annotations

import pytest

from compute_provisioning.relays import validate_relay_reference


@pytest.mark.parametrize("config", [{}, {"relay_id": None}])
def test_absent_or_null_names_no_relay(config):
    assert validate_relay_reference(config) == (None, ())


def test_a_non_empty_string_names_its_relay():
    assert validate_relay_reference({"relay_id": "site-a"}) == ("site-a", ())


@pytest.mark.parametrize("value", ["", "  ", 7, ["site-a"]])
def test_anything_but_a_non_empty_string_is_a_problem(value):
    relay_id, problems = validate_relay_reference({"relay_id": value})

    assert relay_id is None
    assert [(p.path, p.code) for p in problems] == [("relay_id", "invalid_type")]
