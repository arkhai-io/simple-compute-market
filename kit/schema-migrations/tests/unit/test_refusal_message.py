"""The message a service refuses a database with, for each check result."""

from __future__ import annotations

from market_schema_migrations import CheckResult, CheckState, describe, refusal_message

_SERVICE = "example-service"
_COMMAND = "example-service-migrate"


def _message(result: CheckResult) -> str:
    return refusal_message(result, service=_SERVICE, command=_COMMAND)


def test_absent_names_the_command_that_creates_the_database() -> None:
    message = _message(CheckResult(CheckState.ABSENT))
    assert _SERVICE in message
    assert f"Run `{_COMMAND}`" in message


def test_behind_names_each_pending_migration_and_the_preview() -> None:
    message = _message(
        CheckResult(CheckState.BEHIND, pending=("later_1", "later_2"), current="base_2")
    )
    assert "at base_2 is behind" in message
    assert "later_1, later_2" in message
    assert f"Run `{_COMMAND}`" in message
    assert f"`{_COMMAND} --check`" in message


def test_behind_with_adoption_pending_names_the_baselines_it_records() -> None:
    message = _message(
        CheckResult(
            CheckState.BEHIND, pending=("later_1",), adopting=("base_1", "base_2")
        )
    )
    assert "supported baseline is to be adopted (recording base_1, base_2)" in message
    assert "later_1" in message


def test_an_adoption_with_nothing_after_it_names_both_revisions() -> None:
    message = refusal_message(
        CheckResult(CheckState.BEHIND, adopting=("0002_baseline",), current="0001_floor"),
        service="registry",
        command="registry-migrate",
    )
    assert "at 0001_floor is behind" in message
    assert "0002_baseline" in message
    assert "pending" not in message


def test_ahead_names_unknown_and_pending_migrations_and_the_backup() -> None:
    message = _message(
        CheckResult(
            CheckState.AHEAD, pending=("later_2",), unknown=("newer",), current="later_1"
        )
    )
    assert "ahead of this image" in message
    assert "newer" in message
    assert "later_2" in message
    assert f"`{_COMMAND}` will not change it" in message
    assert "backup" in message


def test_unsupported_names_the_missing_floor_and_a_fresh_database() -> None:
    message = _message(CheckResult(CheckState.UNSUPPORTED, missing=("floor_a",)))
    assert "predates its supported baseline" in message
    assert "floor_a" in message
    assert _COMMAND in message
    assert "fresh database" in message


def test_compatible_is_stated() -> None:
    assert "compatible" in _message(CheckResult(CheckState.COMPATIBLE))


def test_a_revision_based_service_names_both_revisions() -> None:
    message = refusal_message(
        CheckResult(CheckState.BEHIND, pending=("0002_head",), current="0001_base"),
        service="registry",
        command="registry-migrate",
    )
    assert "0001_base" in message
    assert "0002_head" in message
    assert "registry-migrate" in message


def test_describe_names_the_state_and_every_differing_id() -> None:
    line = describe(
        CheckResult(
            CheckState.AHEAD,
            pending=("later_2",),
            unknown=("newer",),
            adopting=("base_1", "base_2"),
        )
    )
    assert line == (
        "ahead; supported baseline to be adopted: base_1, base_2; "
        "unknown: newer; pending: later_2"
    )
    assert describe(CheckResult(CheckState.COMPATIBLE, current="later_2")) == (
        "compatible; at later_2"
    )
