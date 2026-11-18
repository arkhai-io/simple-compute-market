"""The family's storefront chain and the command a storefront root runs it through.

Library integration: real SQLite files migrated through the chain's engine
under a neutral table prefix; no application is started.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest
from market_schema_migrations import CheckState, MigrationRefused

from arkhai_api_selling import migrate as migrate_command
from arkhai_api_selling.migrations import (
    IncompatibleStorefrontDatabase,
    baseline_tables,
    check_storefront_database,
    migrate_storefront_database,
    require_compatible_storefront_database,
)
from tests.bundles import EXAMPLE, example_chain

CHAIN = example_chain()


def _tables(path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        connection.close()


def test_a_fresh_database_gets_the_whole_chain_and_a_rerun_changes_nothing(tmp_path):
    path = tmp_path / "storefront.db"

    report = migrate_storefront_database(CHAIN, path)

    assert report.applied == CHAIN.ids
    assert baseline_tables("example") <= _tables(path)
    before = path.read_bytes()
    assert migrate_storefront_database(CHAIN, path).applied == ()
    assert path.read_bytes() == before
    assert check_storefront_database(CHAIN, path).compatible


def test_a_database_the_chain_did_not_build_is_refused_and_unchanged(tmp_path):
    path = tmp_path / "unledgered.db"
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE listings (listing_id TEXT PRIMARY KEY)")
    connection.close()
    before = path.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate_storefront_database(CHAIN, path)

    assert refused.value.result.state is CheckState.UNSUPPORTED
    assert CHAIN.command in str(refused.value)
    assert path.read_bytes() == before


def test_the_startup_check_refuses_no_database_naming_the_command_and_creates_none(tmp_path):
    path = tmp_path / "missing" / "storefront.db"

    with pytest.raises(IncompatibleStorefrontDatabase) as refused:
        require_compatible_storefront_database(CHAIN, path)

    assert f"`{CHAIN.command}`" in str(refused.value)
    assert not path.parent.exists()


def test_a_database_built_under_another_prefix_and_baseline_is_refused(tmp_path):
    path = tmp_path / "storefront.db"
    migrate_storefront_database(CHAIN, path)
    other = example_chain(
        replace(EXAMPLE, table_prefix="other"), baseline_id="v0_3_0_baseline_other_storefront"
    )
    before = path.read_bytes()

    assert not check_storefront_database(other, path).compatible
    with pytest.raises(IncompatibleStorefrontDatabase) as refused:
        require_compatible_storefront_database(other, path)

    assert f"`{other.command}`" in str(refused.value)
    assert path.read_bytes() == before
    assert check_storefront_database(CHAIN, path).compatible


def _run(path, *arguments: str, **settings: str) -> int:
    try:
        migrate_command.main(CHAIN, lambda: {"db_path": str(path), **settings}, list(arguments))
    except SystemExit as exit_:
        return int(exit_.code or 0)
    return 0


def test_the_command_migrates_and_its_check_changes_nothing(tmp_path, capsys):
    path = tmp_path / "storefront.db"

    assert _run(path, "--check") == 1
    assert not path.exists()
    assert CHAIN.command in capsys.readouterr().err

    assert _run(path) == 0
    assert _run(path) == 0
    assert _run(path, "--check") == 0


def test_a_configuration_naming_no_database_is_refused(tmp_path, capsys):
    assert _run("") == 1

    assert "db_path" in capsys.readouterr().err
