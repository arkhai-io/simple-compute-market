"""The VM storefront's migration command and the startup check it answers.

``market-storefront-migrate`` applies the storefront's chain to the database its
settings name, reading only the database path and the log level; ``--check``
reports the database's state, changes nothing, and succeeds only for a
compatible database. The startup check the composition makes before anything
opens the database, ``require_compatible_storefront_database``, refuses any
other state naming the command, and creates no file.

External boundary: file-backed SQLite in a temp directory; the command runs
through its entry point with its settings in the loader's environment layer and
no configuration file. No application is started.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from market_schema_migrations import Chain, SqliteMigrationConnection, migrate, schema_snapshot

from market_storefront import migrate as migrate_command
from market_storefront.utils.migrations import (
    CHAIN,
    MIGRATION_COMMAND,
    IncompatibleStorefrontDatabase,
    migrate_storefront_database,
    require_compatible_storefront_database,
)

_UNKNOWN_ID = "20991231_001_from_a_newer_image"


def _behind(path: Path) -> Path:
    """A database its baselines built and no later migration reached."""
    connection = sqlite3.connect(path)
    try:
        migrate(
            Chain(service=CHAIN.service, command=CHAIN.command, baselines=CHAIN.baselines),
            SqliteMigrationConnection(connection),
        )
    finally:
        connection.close()
    return path


def _ahead(path: Path) -> Path:
    migrate_storefront_database(path)
    connection = sqlite3.connect(path)
    try:
        with connection:
            connection.execute("INSERT INTO schema_migrations (id) VALUES (?)", (_UNKNOWN_ID,))
    finally:
        connection.close()
    return path


def _contents(path: Path) -> tuple[dict, list[str], dict[str, list]]:
    """The schema, the recorded IDs, and every other table's rows."""
    connection = sqlite3.connect(path)
    try:
        snapshot = schema_snapshot(connection)
        recorded = sorted(r[0] for r in connection.execute("SELECT id FROM schema_migrations"))
        rows = {
            table: sorted(map(repr, connection.execute(f'SELECT * FROM "{table}"')))
            for table in snapshot["tables"]
        }
    finally:
        connection.close()
    return snapshot, recorded, rows


@pytest.fixture
def command(monkeypatch, tmp_path) -> Callable[..., int]:
    """Run the command with ``configuration`` in the loader's environment layer."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-configuration"))

    def run(database: Path, *arguments: str, **configuration: str) -> int:
        monkeypatch.setenv("STOREFRONT_DB_PATH", str(database))
        for name, value in configuration.items():
            monkeypatch.setenv(f"STOREFRONT_{name.upper()}", value)
        try:
            migrate_command.main(list(arguments))
        except SystemExit as exit_:
            return int(exit_.code or 0)
        return 0

    return run


def test_the_console_script_is_the_command():
    (script,) = entry_points(group="console_scripts", name=MIGRATION_COMMAND)
    assert script.load() is migrate_command.main


def test_check_reports_a_behind_database_and_changes_nothing(tmp_path, command, capsys):
    path = _behind(tmp_path / "storefront.db")
    before = path.read_bytes()

    assert command(path, "--check") == 1

    output = capsys.readouterr()
    assert "behind" in output.out
    for migration in CHAIN.migrations:
        assert migration.id in output.out
    assert MIGRATION_COMMAND in output.err
    assert path.read_bytes() == before


def test_check_on_no_database_creates_none(tmp_path, command):
    path = tmp_path / "missing" / "storefront.db"

    assert command(path, "--check") == 1

    assert not path.parent.exists()


def test_check_passes_once_the_command_has_migrated(tmp_path, command):
    path = tmp_path / "storefront.db"

    assert command(path) == 0
    assert command(path) == 0
    assert command(path, "--check") == 0


def test_the_command_refuses_an_ahead_database(tmp_path, command, capsys):
    path = _ahead(tmp_path / "storefront.db")
    before = path.read_bytes()

    assert command(path) == 1

    assert _UNKNOWN_ID in capsys.readouterr().err
    assert path.read_bytes() == before


def test_two_configurations_give_one_schema_and_one_set_of_rows(tmp_path, command):
    """Settings beyond the database path leave no trace in what it migrates."""
    first, second = tmp_path / "first.db", tmp_path / "second.db"

    assert command(first) == 0
    assert command(
        second,
        log_level="DEBUG",
        agent_name="another-storefront",
        base_url="http://elsewhere.test:8001",
    ) == 0

    assert _contents(first) == _contents(second)


def test_the_command_resolves_none_of_the_storefronts_configuration():
    """The storefront's configuration module resolves its chains, agent id and
    base URL when it is imported; the command never imports it."""
    probe = (
        "import sys, market_storefront.migrate; "
        "sys.exit('market_storefront.utils.config' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", probe], check=False).returncode == 0


def test_a_configuration_naming_no_database_is_refused(tmp_path, command, capsys):
    assert command(tmp_path / "unused.db", db_path='""') == 1

    assert "db_path" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("database", "named"),
    [
        (_behind, lambda: [m.id for m in CHAIN.migrations]),
        (_ahead, lambda: [_UNKNOWN_ID]),
    ],
    ids=["behind", "ahead"],
)
def test_the_startup_check_refuses_a_database_not_at_the_chain(tmp_path, database, named):
    path = database(tmp_path / "storefront.db")
    before = path.read_bytes()

    with pytest.raises(IncompatibleStorefrontDatabase) as refused:
        require_compatible_storefront_database(path)

    assert f"`{MIGRATION_COMMAND}`" in str(refused.value)
    for migration_id in named():
        assert migration_id in str(refused.value)
    assert path.read_bytes() == before


def test_the_startup_check_refuses_no_database_and_creates_none(tmp_path):
    path = tmp_path / "missing" / "storefront.db"

    with pytest.raises(IncompatibleStorefrontDatabase) as refused:
        require_compatible_storefront_database(path)

    assert f"`{MIGRATION_COMMAND}`" in str(refused.value)
    assert not path.parent.exists()
