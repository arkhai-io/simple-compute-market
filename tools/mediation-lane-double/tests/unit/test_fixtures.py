"""The committed authority fixture loads, and a fixture the double cannot serve is refused."""

from __future__ import annotations

import pytest

from mediation_lane_double.authority import (
    FixtureError,
    load_authority,
    parse_authority,
    record_key_of,
)

from conftest import FIXTURES, committed_authority


def test_the_committed_record_key_is_its_seeds() -> None:
    document = committed_authority()

    assert document["record_key"] == record_key_of(bytes.fromhex(document["record_seed"]))


def test_the_committed_fixture_loads_and_states_its_seeds_record_key() -> None:
    authority = load_authority(FIXTURES / "authority.toml")

    assert authority.record_key == record_key_of(authority.record_seed)
    assert authority.origin == "https://mediation-double:8443"
    assert authority.account == "00000000-0000-4000-8000-0000000000d1"
    assert set(authority.tokens.values()) == {
        "00000000-0000-4000-8000-0000000000b1", "00000000-0000-4000-8000-0000000000b2"}


def test_a_record_key_its_seed_does_not_yield_is_refused() -> None:
    document = committed_authority() | {"record_seed": "11" * 32}

    with pytest.raises(FixtureError, match="record_key is not the key of record_seed"):
        parse_authority(document)


def test_a_control_token_that_is_also_a_callers_token_is_refused() -> None:
    document = committed_authority()
    document["control_token"] = document["accounts"]["buyer"]["token"]

    with pytest.raises(FixtureError, match="control_token"):
        parse_authority(document)


def test_two_callers_sharing_a_token_are_refused() -> None:
    document = committed_authority()
    document["accounts"]["seller"]["token"] = document["accounts"]["buyer"]["token"]

    with pytest.raises(FixtureError, match="shared"):
        parse_authority(document)
