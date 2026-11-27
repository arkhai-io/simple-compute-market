"""The authority's migration chain, its command, and the startup check.

The chain begins at its baselines and, under the example root's floor of
``0.0.0``, adopts no database: a fresh database is migrated, and every
non-empty database it did not build is refused unchanged.
A service root's startup only checks, refusing any database not exactly at the
chain with a message naming the root's migration command.

External boundary: file-backed SQLite in a temp directory, migrated through
the engine as a root's migration command runs it. No application is started.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from market_resource_pools.db import Base as PoolsBase
from market_schema_migrations import (
    Chain,
    CheckState,
    MigrationRefused,
    migrate,
    schema_snapshot,
)
from market_schema_migrations.sqlalchemy_adapter import SqlAlchemyMigrationConnection
from market_site.db import Base as SiteBase
from market_site.migrations import CAPACITY_BUCKET_HOST_INDEX
from market_site.migrations import MIGRATIONS as SITE_MIGRATIONS
from sqlalchemy import Engine, create_engine, inspect, text

from arkhai_api_authority import (
    IncompatibleDatabase,
    authority_chain,
    check_database,
    create_db_engine,
    migrate_database,
    require_migrated,
)
from arkhai_api_authority import migrate as migrate_command
from arkhai_api_authority.migrations import GRANT_TERMS
from arkhai_api_authority.models import Base

from tests.integration.profiles import CHAIN, COMMAND

_AUTHORITY_TABLES = ("api_keys", "credit_grants", "consumption_events", "grant_terms")
_UNKNOWN_ID = "20991231_001_from_a_newer_image"


def _engine(path: Path) -> Engine:
    return create_db_engine(f"sqlite:///{path}", is_sqlite=True)


def _migrated(path: Path) -> Path:
    engine = _engine(path)
    try:
        migrate_database(engine, CHAIN)
    finally:
        engine.dispose()
    return path


def _snapshot(path: Path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


def _recorded(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute("SELECT id FROM schema_migrations")]
    finally:
        connection.close()


def _execute(path: Path, *statements: str) -> None:
    connection = sqlite3.connect(path)
    try:
        with connection:
            for statement in statements:
                connection.execute(statement)
    finally:
        connection.close()


def _behind(path: Path) -> Path:
    """A database its baselines built and no later migration reached."""
    engine = _engine(path)
    try:
        with engine.connect() as connection:
            migrate(
                Chain(
                    service=CHAIN.service,
                    command=CHAIN.command,
                    baselines=CHAIN.baselines,
                    floor=CHAIN.floor,
                ),
                SqlAlchemyMigrationConnection(connection),
            )
    finally:
        engine.dispose()
    return path


class TestTheChain:
    def test_the_site_ledgers_migrations_precede_the_authoritys_own(self):
        assert CHAIN.migrations == (*SITE_MIGRATIONS, CAPACITY_BUCKET_HOST_INDEX, GRANT_TERMS)

    def test_each_root_names_its_own_service_and_command(self):
        other = authority_chain(
            service="another service", command="another-migrate", floor=CHAIN.floor
        )

        assert (other.service, other.command) == ("another service", "another-migrate")
        assert other.ids == CHAIN.ids


class TestAFreshDatabase:
    def test_migrates_to_the_chain_and_writes_no_row(self, tmp_path):
        path = _migrated(tmp_path / "authority.db")

        assert sorted(_recorded(path)) == sorted(CHAIN.ids)
        engine = _engine(path)
        try:
            assert check_database(engine, CHAIN).compatible
            with engine.connect() as connection:
                for table in inspect(engine).get_table_names():
                    if table == "schema_migrations":
                        continue
                    assert connection.execute(text(f"SELECT * FROM {table}")).all() == [], table
        finally:
            engine.dispose()

    def test_the_chain_reproduces_the_authoritys_own_tables(self, tmp_path):
        """The authority's baseline and migrations build its tables as its models do."""
        migrated = _snapshot(_migrated(tmp_path / "authority.db"))
        modelled = tmp_path / "modelled.db"
        engine = create_engine(f"sqlite:///{modelled}")
        Base.metadata.create_all(engine)
        engine.dispose()

        expected = _snapshot(modelled)
        assert sorted(expected["tables"]) == sorted(_AUTHORITY_TABLES)
        assert {t: migrated["tables"][t] for t in _AUTHORITY_TABLES} == expected["tables"]

    def test_every_mapped_table_and_column_exists(self, tmp_path):
        """Nothing but the chain creates schema, so every table and column the
        three metadata sets map must be one the chain creates."""
        engine = _engine(_migrated(tmp_path / "authority.db"))
        try:
            inspector = inspect(engine)
            for metadata in (Base.metadata, PoolsBase.metadata, SiteBase.metadata):
                for table in metadata.tables.values():
                    columns = {c["name"] for c in inspector.get_columns(table.name)}
                    assert set(table.columns.keys()) <= columns, table.name
        finally:
            engine.dispose()

    def test_a_rerun_changes_nothing(self, tmp_path):
        path = _migrated(tmp_path / "authority.db")
        before = path.read_bytes()

        engine = _engine(path)
        try:
            report = migrate_database(engine, CHAIN)
        finally:
            engine.dispose()

        assert report.applied == ()
        assert path.read_bytes() == before


class TestAnExistingDatabase:
    """No authority database from before the baseline is supported."""

    def test_one_with_another_migration_history_is_refused_unchanged(self, tmp_path):
        path = tmp_path / "authority.db"
        engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(engine)
        PoolsBase.metadata.create_all(engine)
        SiteBase.metadata.create_all(engine)
        engine.dispose()
        _execute(
            path,
            "CREATE TABLE schema_migrations (id VARCHAR PRIMARY KEY, "
            "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "INSERT INTO schema_migrations (id) VALUES ('another_history_001')",
            "INSERT INTO api_keys (key_id, secret_hash, status, balance, created_at, "
            "updated_at) VALUES ('k1', 'hash', 'active', 42, CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP)",
        )
        before = path.read_bytes()

        engine = _engine(path)
        try:
            assert check_database(engine, CHAIN).state is CheckState.UNSUPPORTED
            with pytest.raises(MigrationRefused) as refused:
                migrate_database(engine, CHAIN)
            with pytest.raises(IncompatibleDatabase) as startup:
                require_migrated(engine, CHAIN)
        finally:
            engine.dispose()

        assert f"`{COMMAND}`" in str(refused.value)
        assert "was not built by" in str(refused.value)
        assert f"`{COMMAND}`" in str(startup.value)
        assert path.read_bytes() == before

    def test_tables_without_a_ledger_are_refused_unchanged(self, tmp_path):
        path = tmp_path / "authority.db"
        engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(engine)
        engine.dispose()
        before = path.read_bytes()

        engine = _engine(path)
        try:
            assert check_database(engine, CHAIN).state is CheckState.UNSUPPORTED
            with pytest.raises(MigrationRefused):
                migrate_database(engine, CHAIN)
        finally:
            engine.dispose()

        assert path.read_bytes() == before
        assert "schema_migrations" not in _snapshot(path)["tables"]


class TestTheStartupCheck:
    def test_a_behind_database_is_refused_naming_the_pending_migrations(self, tmp_path):
        path = _behind(tmp_path / "authority.db")
        before = path.read_bytes()

        engine = _engine(path)
        try:
            result = check_database(engine, CHAIN)
            with pytest.raises(IncompatibleDatabase) as refused:
                require_migrated(engine, CHAIN)
        finally:
            engine.dispose()

        assert result.state is CheckState.BEHIND
        assert result.pending == tuple(m.id for m in CHAIN.migrations)
        assert f"`{COMMAND}`" in str(refused.value)
        for pending in result.pending:
            assert pending in str(refused.value)
        assert path.read_bytes() == before

    def test_an_ahead_database_is_refused_and_the_command_changes_nothing(self, tmp_path):
        path = _migrated(tmp_path / "authority.db")
        _execute(path, f"INSERT INTO schema_migrations (id) VALUES ('{_UNKNOWN_ID}')")
        before = path.read_bytes()

        engine = _engine(path)
        try:
            assert check_database(engine, CHAIN).state is CheckState.AHEAD
            with pytest.raises(IncompatibleDatabase) as startup:
                require_migrated(engine, CHAIN)
            with pytest.raises(MigrationRefused) as command:
                migrate_database(engine, CHAIN)
        finally:
            engine.dispose()

        for message in (str(startup.value), str(command.value)):
            assert _UNKNOWN_ID in message
            assert f"`{COMMAND}`" in message
        assert path.read_bytes() == before

    def test_no_database_is_refused_and_none_is_created(self, tmp_path):
        path = tmp_path / "missing" / "authority.db"

        engine = _engine(path)
        try:
            assert check_database(engine, CHAIN).state is CheckState.ABSENT
            with pytest.raises(IncompatibleDatabase) as refused:
                require_migrated(engine, CHAIN)
        finally:
            engine.dispose()

        assert f"`{COMMAND}`" in str(refused.value)
        assert not path.parent.exists()

    def test_a_migrated_database_passes_unchanged(self, tmp_path):
        path = _migrated(tmp_path / "authority.db")
        before = path.read_bytes()

        engine = _engine(path)
        try:
            require_migrated(engine, CHAIN)
        finally:
            engine.dispose()

        assert path.read_bytes() == before


@pytest.fixture
def command() -> Callable[..., int]:
    """Run a root's migration command over ``database`` with the settings a root loads."""

    def run(database: Path, *arguments: str) -> int:
        settings = SimpleNamespace(database_url=f"sqlite:///{database}", log_level="info")
        try:
            migrate_command.main(CHAIN, lambda: settings, list(arguments))
        except SystemExit as exit_:
            return int(exit_.code or 0)
        return 0

    return run


class TestTheCommand:
    def test_check_reports_a_behind_database_and_changes_nothing(
        self, tmp_path, command, capsys,
    ):
        path = _behind(tmp_path / "authority.db")
        before = path.read_bytes()

        assert command(path, "--check") == 1

        output = capsys.readouterr()
        assert "behind" in output.out
        for migration in CHAIN.migrations:
            assert migration.id in output.out
        assert path.read_bytes() == before

    def test_check_on_no_database_creates_none(self, tmp_path, command):
        path = tmp_path / "authority.db"

        assert command(path, "--check") == 1

        assert not path.exists()

    def test_check_passes_once_the_command_has_migrated(self, tmp_path, command):
        path = tmp_path / "authority.db"

        assert command(path) == 0
        assert command(path) == 0
        assert command(path, "--check") == 0

    def test_the_command_refuses_an_ahead_database(self, tmp_path, command, capsys):
        path = _migrated(tmp_path / "authority.db")
        _execute(path, f"INSERT INTO schema_migrations (id) VALUES ('{_UNKNOWN_ID}')")
        before = path.read_bytes()

        assert command(path) == 1

        assert _UNKNOWN_ID in capsys.readouterr().err
        assert path.read_bytes() == before


class TestCreateDbEngineIsSqliteOnly:
    def test_raises_for_a_non_sqlite_url(self):
        with pytest.raises(ValueError):
            create_db_engine("postgresql://user:pass@host/db", is_sqlite=False)

    def test_accepts_a_sqlite_url(self):
        engine = create_db_engine("sqlite:///:memory:", is_sqlite=True)
        assert engine is not None
