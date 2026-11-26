"""How a database's tables and recorded IDs classify against a chain."""

from __future__ import annotations

import pytest

from market_schema_migrations import (
    Chain,
    CheckResult,
    CheckState,
    Floor,
    Migration,
    UnsupportedCause,
    classify,
)

_RELEASE = "example 1.0.0"
_TABLES = {"hosts", "schema_migrations"}


def _noop(_connection: object) -> None:
    return None


def _chain(*, floor: Floor = Floor(_RELEASE, ("floor_a", "floor_b"))) -> Chain[object]:
    return Chain(
        service="example-service",
        command="example-service-migrate",
        baselines=(Migration("base_1", _noop), Migration("base_2", _noop)),
        migrations=(Migration("later_1", _noop), Migration("later_2", _noop)),
        floor=floor,
    )


def test_no_file_is_absent() -> None:
    assert classify(_chain(), tables=None, recorded=None) == CheckResult(
        CheckState.ABSENT, floor=_RELEASE
    )


def test_an_empty_ledger_and_no_tables_is_absent() -> None:
    result = classify(_chain(), tables={"schema_migrations"}, recorded=[])
    assert result == CheckResult(CheckState.ABSENT, floor=_RELEASE)


@pytest.mark.parametrize("recorded", [None, []], ids=["no-ledger", "empty-ledger"])
def test_tables_without_records_are_not_this_chains(recorded: list[str] | None) -> None:
    result = classify(_chain(), tables={"hosts", "schema_migrations"}, recorded=recorded)
    assert result == CheckResult(
        CheckState.UNSUPPORTED, floor=_RELEASE, cause=UnsupportedCause.NOT_THIS_CHAIN
    )


def test_part_of_the_floor_is_older_or_shared_naming_what_it_lacks() -> None:
    result = classify(_chain(), tables=_TABLES, recorded=["floor_b", "older"])
    assert result == CheckResult(
        CheckState.UNSUPPORTED,
        missing=("floor_a",),
        floor=_RELEASE,
        cause=UnsupportedCause.OLDER_OR_SHARED,
    )


def test_a_ledger_recording_none_of_the_floor_is_not_this_chains() -> None:
    result = classify(_chain(), tables=_TABLES, recorded=["other_1", "other_2"])
    assert result == CheckResult(
        CheckState.UNSUPPORTED, floor=_RELEASE, cause=UnsupportedCause.NOT_THIS_CHAIN
    )


def test_a_zero_floor_refuses_a_database_it_did_not_build_as_not_its_own() -> None:
    result = classify(
        _chain(floor=Floor("0.0.0")), tables={"grants", "schema_migrations"}, recorded=["old_1"]
    )
    assert result == CheckResult(
        CheckState.UNSUPPORTED, floor="0.0.0", cause=UnsupportedCause.NOT_THIS_CHAIN
    )
    assert not result.adoption_pending


def test_a_zero_floor_still_builds_and_judges_its_own_database() -> None:
    chain = _chain(floor=Floor("0.0.0"))
    assert classify(chain, tables=None, recorded=None).state is CheckState.ABSENT
    assert classify(
        chain, tables=_TABLES, recorded=["base_1", "base_2", "later_1", "later_2"]
    ) == CheckResult(CheckState.COMPATIBLE, current="later_2", floor="0.0.0")


def test_the_whole_floor_is_behind_with_adoption_pending() -> None:
    result = classify(_chain(), tables=_TABLES, recorded=["floor_a", "floor_b"])
    assert result == CheckResult(
        CheckState.BEHIND,
        pending=("later_1", "later_2"),
        adopting=("base_1", "base_2"),
        floor=_RELEASE,
    )
    assert result.adoption_pending


def test_the_floor_with_a_later_migration_already_applied_is_still_adopted() -> None:
    result = classify(
        _chain(), tables=_TABLES, recorded=["floor_a", "later_1", "floor_b"]
    )
    assert result == CheckResult(
        CheckState.BEHIND,
        pending=("later_2",),
        adopting=("base_1", "base_2"),
        floor=_RELEASE,
    )


def test_records_beside_the_floor_are_set_aside_sorted_and_the_database_adopted() -> None:
    result = classify(
        _chain(),
        tables=_TABLES,
        recorded=["zeta_retired", "floor_a", "floor_b", "alpha_retired"],
    )
    assert result == CheckResult(
        CheckState.BEHIND,
        pending=("later_1", "later_2"),
        adopting=("base_1", "base_2"),
        set_aside=("alpha_retired", "zeta_retired"),
        floor=_RELEASE,
    )


def test_a_chain_database_missing_migrations_is_behind_in_chain_order() -> None:
    result = classify(_chain(), tables=_TABLES, recorded=["base_2", "base_1"])
    assert result == CheckResult(
        CheckState.BEHIND, pending=("later_1", "later_2"), current="base_2", floor=_RELEASE
    )


def test_a_partly_built_fresh_database_is_behind_with_its_remaining_baselines() -> None:
    result = classify(_chain(), tables=_TABLES, recorded=["base_1"])
    assert result.state is CheckState.BEHIND
    assert result.pending == ("base_2", "later_1", "later_2")


def test_an_unknown_id_beside_the_baselines_is_ahead() -> None:
    result = classify(_chain(), tables=_TABLES, recorded=["base_1", "base_2", "newer"])
    assert result == CheckResult(
        CheckState.AHEAD,
        pending=("later_1", "later_2"),
        unknown=("newer",),
        current="base_2",
        floor=_RELEASE,
    )


def test_an_unknown_id_takes_precedence_over_pending_ones() -> None:
    result = classify(
        _chain(),
        tables=_TABLES,
        recorded=["base_1", "base_2", "later_1", "zeta", "alpha"],
    )
    assert result == CheckResult(
        CheckState.AHEAD,
        pending=("later_2",),
        unknown=("alpha", "zeta"),
        current="later_1",
        floor=_RELEASE,
    )


def test_floor_records_left_beside_the_baselines_are_unknown() -> None:
    result = classify(
        _chain(),
        tables=_TABLES,
        recorded=["base_1", "base_2", "later_1", "later_2", "floor_a"],
    )
    assert result.state is CheckState.AHEAD
    assert result.unknown == ("floor_a",)


def test_exactly_the_chain_is_compatible() -> None:
    result = classify(
        _chain(), tables=_TABLES, recorded=["later_2", "base_1", "later_1", "base_2"]
    )
    assert result == CheckResult(CheckState.COMPATIBLE, current="later_2", floor=_RELEASE)
    assert result.compatible


def test_a_chain_without_a_floor_is_refused() -> None:
    with pytest.raises(TypeError, match="floor"):
        Chain(  # type: ignore[call-arg]
            service="s", command="s-migrate", baselines=(Migration("base", _noop),)
        )


def test_a_chain_whose_floor_is_not_a_floor_is_refused() -> None:
    with pytest.raises(TypeError, match="declares no Floor"):
        Chain(
            service="s",
            command="s-migrate",
            baselines=(Migration("base", _noop),),
            floor=None,  # type: ignore[arg-type]
        )


def test_a_chain_without_a_baseline_is_refused() -> None:
    with pytest.raises(ValueError, match="no baseline"):
        Chain(service="s", command="s-migrate", baselines=(), floor=Floor("0.0.0"))


def test_a_chain_listing_an_id_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="more than once: twice"):
        Chain(
            service="s",
            command="s-migrate",
            baselines=(Migration("twice", _noop),),
            migrations=(Migration("twice", _noop),),
            floor=Floor("0.0.0"),
        )


def test_a_floor_naming_a_chain_migration_is_refused() -> None:
    with pytest.raises(ValueError, match="floor names migrations its chain lists: later"):
        Chain(
            service="s",
            command="s-migrate",
            baselines=(Migration("base", _noop),),
            migrations=(Migration("later", _noop),),
            floor=Floor(_RELEASE, ("old", "later")),
        )


def test_a_floor_listing_an_id_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="floor lists migrations more than once: old"):
        Chain(
            service="s",
            command="s-migrate",
            baselines=(Migration("base", _noop),),
            floor=Floor(_RELEASE, ("old", "old")),
        )
