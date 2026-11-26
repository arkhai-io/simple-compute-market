"""The message a service refuses a database with, for each check result."""

from __future__ import annotations

import pytest

from market_schema_migrations import (
    CheckResult,
    CheckState,
    UnsupportedCause,
    describe,
    refusal_message,
)

_SERVICE = "example-service"
_COMMAND = "example-service-migrate"
_RELEASE = "example 1.0.0"


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


def test_behind_with_adoption_pending_names_the_baselines_and_the_floor_release() -> None:
    message = _message(
        CheckResult(
            CheckState.BEHIND,
            pending=("later_1",),
            adopting=("base_1", "base_2"),
            floor=_RELEASE,
        )
    )
    assert "supported baseline is to be adopted (recording base_1, base_2)" in message
    assert f"replacing the records of {_RELEASE}" in message
    assert "setting aside" not in message
    assert "later_1" in message


def test_behind_with_records_set_aside_lists_each_of_them() -> None:
    message = _message(
        CheckResult(
            CheckState.BEHIND,
            pending=("later_1",),
            adopting=("base_1",),
            set_aside=("alpha_retired", "zeta_retired"),
            floor=_RELEASE,
        )
    )
    assert (
        "setting aside records earlier releases wrote: alpha_retired, zeta_retired"
        in message
    )
    assert f"Run `{_COMMAND}`" in message


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


def test_older_or_shared_names_the_floor_and_directs_the_upgrade_once_confirmed() -> None:
    message = _message(
        CheckResult(
            CheckState.UNSUPPORTED,
            missing=("floor_a",),
            floor=_RELEASE,
            cause=UnsupportedCause.OLDER_OR_SHARED,
        )
    )
    assert message == (
        f"{_SERVICE}'s database lacks migrations floor_a that {_RELEASE}'s "
        f"{_SERVICE} recorded. If it is {_SERVICE}'s database, it predates "
        f"{_RELEASE}, the release it is supported from: upgrade it through "
        f"{_RELEASE} first — run {_RELEASE}'s {_SERVICE} on it — then run "
        f"`{_COMMAND}`. Confirm it is first: `{_COMMAND}` cannot tell another "
        "service's database from an older one of its own."
    )


def test_older_or_shared_names_the_service_as_the_floor_release_shipped_it() -> None:
    message = refusal_message(
        CheckResult(
            CheckState.UNSUPPORTED,
            missing=("floor_a",),
            floor="example 1.0.0",
            cause=UnsupportedCause.OLDER_OR_SHARED,
        ),
        service="the billing service",
        command="billing-migrate",
    )
    assert message.startswith(
        "the billing service's database lacks migrations floor_a that example "
        "1.0.0's billing service recorded. If it is the billing service's database,"
    )
    assert "run example 1.0.0's billing service on it" in message


def test_not_this_chain_says_the_command_did_not_build_it_and_names_no_upgrade() -> None:
    message = _message(
        CheckResult(
            CheckState.UNSUPPORTED, floor=_RELEASE, cause=UnsupportedCause.NOT_THIS_CHAIN
        )
    )
    assert f"was not built by `{_COMMAND}`" in message
    assert "upgrade" not in message
    assert _RELEASE not in message


@pytest.mark.parametrize(
    "result",
    [
        CheckResult(CheckState.ABSENT, floor=_RELEASE),
        CheckResult(CheckState.BEHIND, adopting=("base_1",), floor=_RELEASE),
        CheckResult(CheckState.AHEAD, unknown=("newer",), floor=_RELEASE),
        CheckResult(
            CheckState.UNSUPPORTED,
            missing=("floor_a",),
            floor=_RELEASE,
            cause=UnsupportedCause.OLDER_OR_SHARED,
        ),
        CheckResult(
            CheckState.UNSUPPORTED, floor=_RELEASE, cause=UnsupportedCause.NOT_THIS_CHAIN
        ),
    ],
    ids=lambda result: f"{result.state.value}-{result.cause}",
)
def test_no_refusal_sends_the_operator_to_a_fresh_database(result: CheckResult) -> None:
    assert "fresh database" not in _message(result)


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
            current="base_1",
        )
    )
    assert line == "ahead; at base_1; unknown: newer; pending: later_2"
    assert describe(CheckResult(CheckState.COMPATIBLE, current="later_2")) == (
        "compatible; at later_2"
    )


def test_describe_of_an_adoption_names_the_floor_release_and_the_records_set_aside() -> None:
    line = describe(
        CheckResult(
            CheckState.BEHIND,
            pending=("later_1",),
            adopting=("base_1", "base_2"),
            set_aside=("retired_1",),
            floor=_RELEASE,
        )
    )
    assert line == (
        "behind; supported baseline to be adopted: base_1, base_2; "
        f"replacing the records of {_RELEASE}; records set aside: retired_1; "
        "pending: later_1"
    )


def test_describe_of_an_unsupported_database_names_its_cause() -> None:
    line = describe(
        CheckResult(
            CheckState.UNSUPPORTED,
            missing=("floor_a",),
            floor=_RELEASE,
            cause=UnsupportedCause.OLDER_OR_SHARED,
        )
    )
    assert line == "unsupported (older than the floor, or another service's); missing: floor_a"
