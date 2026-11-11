"""The registry's Alembic state, read as every service's check result.

``classify`` maps the tables a database holds and the revision it records onto
the shared result; the refusal it leads to names ``registry-migrate``.
"""

from __future__ import annotations

from importlib.resources import files

from market_schema_migrations import CheckState, refusal_message

from core_registry.db.migrations import (
    COMMAND,
    FLOOR_REVISION,
    PRE_FLOOR_REVISIONS,
    SERVICE,
    classify,
    script_revisions,
)

KNOWN = ("v0_3_0_baseline", "019_later", "020_latest")
TABLES = {"alembic_version", "publishers", "listings"}


def test_the_packaged_script_holds_the_environment_and_the_baseline() -> None:
    """The scripts sit inside the package, so the command finds them through
    the package's resources rather than a path beside the source tree."""
    alembic = files("core_registry") / "alembic"
    assert (alembic / "env.py").is_file()
    assert (alembic / "script.py.mako").is_file()
    assert (alembic / "versions" / "v0_3_0_baseline.py").is_file()
    assert script_revisions() == ("v0_3_0_baseline", "20261106_001_registry_retained_publications")


def test_no_database_or_no_tables_is_absent() -> None:
    assert classify(set(), None, KNOWN).state is CheckState.ABSENT
    assert classify({"alembic_version"}, [], KNOWN).state is CheckState.ABSENT


def test_tables_without_a_revision_are_unsupported() -> None:
    assert classify({"publishers"}, None, KNOWN).state is CheckState.UNSUPPORTED
    assert classify(TABLES, [], KNOWN).state is CheckState.UNSUPPORTED


def test_the_head_is_compatible() -> None:
    result = classify(TABLES, ["020_latest"], KNOWN)
    assert result.compatible and result.current == "020_latest"


def test_an_earlier_revision_is_behind_with_the_later_ones_pending() -> None:
    result = classify(TABLES, ["v0_3_0_baseline"], KNOWN)
    assert result.state is CheckState.BEHIND
    assert result.pending == ("019_later", "020_latest")
    assert result.current == "v0_3_0_baseline"
    assert not result.adoption_pending


def test_the_floor_is_behind_with_the_baseline_to_adopt() -> None:
    result = classify(TABLES, [FLOOR_REVISION], KNOWN)
    assert result.state is CheckState.BEHIND
    assert result.adopting == ("v0_3_0_baseline",)
    assert result.pending == ("019_later", "020_latest")
    assert result.current == FLOOR_REVISION
    alone = classify(TABLES, [FLOOR_REVISION], ("v0_3_0_baseline",))
    assert alone.state is CheckState.BEHIND
    assert alone.adopting == ("v0_3_0_baseline",)
    assert alone.pending == ()


def test_a_revision_before_the_floor_is_unsupported_naming_what_it_lacks() -> None:
    result = classify(TABLES, ["015_listing_settlement_options"], KNOWN)
    assert result.state is CheckState.UNSUPPORTED
    assert result.missing == (
        "016_marketplace_principal_auth",
        "017_publisher_replay_leases",
        FLOOR_REVISION,
    )
    assert classify(TABLES, [PRE_FLOOR_REVISIONS[0]], KNOWN).missing == (
        *PRE_FLOOR_REVISIONS[1:],
        FLOOR_REVISION,
    )


def test_an_unknown_revision_is_ahead() -> None:
    result = classify(TABLES, ["021_from_a_newer_image"], KNOWN)
    assert result.state is CheckState.AHEAD
    assert result.unknown == ("021_from_a_newer_image",)


def test_several_known_revisions_are_unsupported() -> None:
    assert (
        classify(TABLES, ["v0_3_0_baseline", "019_later"], KNOWN).state
        is CheckState.UNSUPPORTED
    )


def test_each_refusal_names_the_command() -> None:
    for tables, revisions in (
        (set(), None),
        (TABLES, None),
        (TABLES, [FLOOR_REVISION]),
        (TABLES, ["v0_3_0_baseline"]),
        (TABLES, ["021_from_a_newer_image"]),
        (TABLES, ["014_agent_to_publisher"]),
    ):
        message = refusal_message(
            classify(tables, revisions, KNOWN), service=SERVICE, command=COMMAND
        )
        assert "`registry-migrate`" in message, message


def test_a_behind_refusal_names_both_revisions() -> None:
    message = refusal_message(
        classify(TABLES, ["v0_3_0_baseline"], KNOWN), service=SERVICE, command=COMMAND
    )
    assert "at v0_3_0_baseline" in message and "020_latest" in message
