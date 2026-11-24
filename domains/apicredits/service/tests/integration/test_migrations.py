"""The API-credit service's migration chain, its command, and its startup check.

The chain begins at the service's baselines and adopts no database: a fresh
database is migrated, and every non-empty database it did not build is refused
unchanged. The application's startup only checks, refusing any database not
exactly at the chain with a message naming ``apicredits-service-migrate``, and
then seeds the ``default`` pool, which no migration writes.

External boundary: file-backed SQLite in a temp directory, migrated through the
engine as ``apicredits-service-migrate`` runs it; the command itself runs
through its entry point with the service's own configuration loader. No
application is started.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session

from market_resource_pools import DEFAULT_POOL_ID, ResourcePool
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

from apicredits_service.db import migrate as migrate_command
from apicredits_service.db.database import (
    IncompatibleDatabase,
    check_database,
    create_db_engine,
    initialise_database,
    migrate_database,
)
from apicredits_service.db.migrations import CHAIN, COMMAND
from apicredits_service.db.models import Base

_SERVICE_TABLES = ("api_keys", "credit_grants", "consumption_events")
_UNKNOWN_ID = "20991231_001_from_a_newer_image"


def _engine(path: Path) -> Engine:
    return create_db_engine(f"sqlite:///{path}", is_sqlite=True)


def _migrated(path: Path) -> Path:
    engine = _engine(path)
    try:
        migrate_database(engine)
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
                Chain(service=CHAIN.service, command=CHAIN.command, baselines=CHAIN.baselines),
                SqlAlchemyMigrationConnection(connection),
            )
    finally:
        engine.dispose()
    return path


def _pool_ids(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute("SELECT id FROM resource_pools")]
    finally:
        connection.close()


class TestAFreshDatabase:
    def test_migrates_to_the_chain_and_writes_no_pool(self, tmp_path):
        path = _migrated(tmp_path / "credits.db")

        assert sorted(_recorded(path)) == sorted(CHAIN.ids)
        assert _pool_ids(path) == []
        engine = _engine(path)
        try:
            assert check_database(engine).compatible
        finally:
            engine.dispose()

    def test_the_service_baseline_reproduces_the_services_own_tables(self, tmp_path):
        """The service's baseline is its tables as its models build them."""
        migrated = _snapshot(_migrated(tmp_path / "credits.db"))
        modelled = tmp_path / "modelled.db"
        engine = create_engine(f"sqlite:///{modelled}")
        Base.metadata.create_all(engine)
        engine.dispose()

        expected = _snapshot(modelled)
        assert {t: migrated["tables"][t] for t in _SERVICE_TABLES} == expected["tables"]

    def test_every_mapped_table_and_column_exists(self, tmp_path):
        """Nothing but the chain creates schema, so every table and column the
        service's three metadata sets map must be one the chain creates."""
        engine = _engine(_migrated(tmp_path / "credits.db"))
        try:
            inspector = inspect(engine)
            for metadata in (Base.metadata, PoolsBase.metadata, SiteBase.metadata):
                for table in metadata.tables.values():
                    columns = {c["name"] for c in inspector.get_columns(table.name)}
                    assert set(table.columns.keys()) <= columns, table.name
        finally:
            engine.dispose()

    def test_a_rerun_changes_nothing(self, tmp_path):
        path = _migrated(tmp_path / "credits.db")
        before = path.read_bytes()

        engine = _engine(path)
        try:
            report = migrate_database(engine)
        finally:
            engine.dispose()

        assert report.applied == ()
        assert path.read_bytes() == before


class TestAnExistingDatabase:
    """No API-credit database from before the baseline is supported."""

    def test_one_the_earlier_startup_built_is_refused_unchanged(self, tmp_path):
        path = tmp_path / "credits.db"
        engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(engine)
        PoolsBase.metadata.create_all(engine)
        SiteBase.metadata.create_all(engine)
        engine.dispose()
        _execute(
            path,
            "CREATE TABLE schema_migrations (id VARCHAR PRIMARY KEY, "
            "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "INSERT INTO schema_migrations (id) VALUES "
            "('20260731_001_apicredits_schema_baseline')",
            "INSERT INTO api_keys (key_id, secret_hash, status, balance, created_at, "
            "updated_at) VALUES ('k1', 'hash', 'active', 42, CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP)",
        )
        before = path.read_bytes()

        engine = _engine(path)
        try:
            assert check_database(engine).state is CheckState.UNSUPPORTED
            with pytest.raises(MigrationRefused) as refused:
                migrate_database(engine)
            with pytest.raises(IncompatibleDatabase) as startup:
                initialise_database(engine)
        finally:
            engine.dispose()

        assert f"`{COMMAND}`" in str(refused.value)
        assert "fresh database" in str(refused.value)
        assert f"`{COMMAND}`" in str(startup.value)
        assert path.read_bytes() == before

    def test_tables_without_a_ledger_are_refused_unchanged(self, tmp_path):
        path = tmp_path / "credits.db"
        engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(engine)
        engine.dispose()
        before = path.read_bytes()

        engine = _engine(path)
        try:
            assert check_database(engine).state is CheckState.UNSUPPORTED
            with pytest.raises(MigrationRefused):
                migrate_database(engine)
        finally:
            engine.dispose()

        assert path.read_bytes() == before
        connection = sqlite3.connect(path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
        assert "schema_migrations" not in tables


class TestTheStartupCheck:
    def test_a_behind_database_is_refused_naming_the_pending_migration(self, tmp_path):
        path = _behind(tmp_path / "credits.db")
        before = path.read_bytes()

        engine = _engine(path)
        try:
            result = check_database(engine)
            with pytest.raises(IncompatibleDatabase) as refused:
                initialise_database(engine)
        finally:
            engine.dispose()

        assert result.state is CheckState.BEHIND
        assert result.pending == tuple(m.id for m in CHAIN.migrations)
        assert f"`{COMMAND}`" in str(refused.value)
        for pending in result.pending:
            assert pending in str(refused.value)
        assert path.read_bytes() == before

    def test_an_ahead_database_is_refused_and_the_command_changes_nothing(self, tmp_path):
        path = _migrated(tmp_path / "credits.db")
        _execute(path, f"INSERT INTO schema_migrations (id) VALUES ('{_UNKNOWN_ID}')")
        before = path.read_bytes()

        engine = _engine(path)
        try:
            assert check_database(engine).state is CheckState.AHEAD
            with pytest.raises(IncompatibleDatabase) as startup:
                initialise_database(engine)
            with pytest.raises(MigrationRefused) as command:
                migrate_database(engine)
        finally:
            engine.dispose()

        for message in (str(startup.value), str(command.value)):
            assert _UNKNOWN_ID in message
            assert f"`{COMMAND}`" in message
        assert path.read_bytes() == before

    def test_no_database_is_refused_and_none_is_created(self, tmp_path):
        path = tmp_path / "missing" / "credits.db"

        engine = _engine(path)
        try:
            assert check_database(engine).state is CheckState.ABSENT
            with pytest.raises(IncompatibleDatabase) as refused:
                initialise_database(engine)
        finally:
            engine.dispose()

        assert f"`{COMMAND}`" in str(refused.value)
        assert not path.parent.exists()

    def test_startup_seeds_the_default_pool_once(self, tmp_path):
        path = _migrated(tmp_path / "credits.db")

        engine = _engine(path)
        try:
            initialise_database(engine)
            initialise_database(engine)
            with Session(engine) as session:
                pools = session.query(ResourcePool).all()
        finally:
            engine.dispose()

        assert [pool.id for pool in pools] == [DEFAULT_POOL_ID]


@pytest.fixture
def command(monkeypatch) -> Callable[..., int]:
    """Run ``apicredits-service-migrate`` with ``configuration`` in the service's
    environment layer; the entry point loads its settings when it runs."""

    def run(database: Path, *arguments: str, **configuration: str) -> int:
        monkeypatch.setenv("APICREDITS_DATABASE_URL", f"sqlite:///{database}")
        for name, value in configuration.items():
            monkeypatch.setenv(f"APICREDITS_{name.upper()}", value)
        try:
            migrate_command.main(list(arguments))
        except SystemExit as exit_:
            return int(exit_.code or 0)
        return 0

    return run


class TestTheCommand:
    def test_the_console_script_is_the_command(self):
        """The installed ``apicredits-service-migrate`` runs this entry point."""
        (script,) = entry_points(group="console_scripts", name=COMMAND)
        assert script.load() is migrate_command.main

    def test_check_reports_a_behind_database_and_changes_nothing(
        self, tmp_path, command, capsys,
    ):
        path = _behind(tmp_path / "credits.db")
        before = path.read_bytes()

        assert command(path, "--check") == 1

        output = capsys.readouterr()
        assert "behind" in output.out
        for migration in CHAIN.migrations:
            assert migration.id in output.out
        assert path.read_bytes() == before

    def test_check_on_no_database_creates_none(self, tmp_path, command):
        path = tmp_path / "credits.db"

        assert command(path, "--check") == 1

        assert not path.exists()

    def test_check_passes_once_the_command_has_migrated(self, tmp_path, command):
        path = tmp_path / "credits.db"

        assert command(path) == 0
        assert command(path) == 0
        assert command(path, "--check") == 0

    def test_the_command_refuses_an_ahead_database(self, tmp_path, command, capsys):
        path = _migrated(tmp_path / "credits.db")
        _execute(path, f"INSERT INTO schema_migrations (id) VALUES ('{_UNKNOWN_ID}')")
        before = path.read_bytes()

        assert command(path) == 1

        assert _UNKNOWN_ID in capsys.readouterr().err
        assert path.read_bytes() == before

    def test_two_configurations_give_one_schema_and_one_set_of_rows(
        self, tmp_path, command,
    ):
        """Configuration that decides the service's trust and its admin gate
        leaves no trace in what the command migrates."""
        first, second = tmp_path / "first.db", tmp_path / "second.db"

        assert command(first) == 0
        assert command(
            second,
            log_level="debug",
            storefront_admin_key="another-admin-key",
            site_principal="0x0000000000000000000000000000000000000001",
            max_timestamp_skew="5",
        ) == 0

        assert _snapshot(first) == _snapshot(second)
        assert sorted(_recorded(first)) == sorted(_recorded(second))
        for path in (first, second):
            engine = create_engine(f"sqlite:///{path}")
            try:
                with engine.connect() as connection:
                    for table in inspect(engine).get_table_names():
                        if table == "schema_migrations":
                            continue
                        rows = connection.execute(text(f"SELECT * FROM {table}")).all()
                        assert rows == [], table
            finally:
                engine.dispose()

    def test_the_command_runs_without_the_applications_secrets(
        self, tmp_path, command,
    ):
        """The application refuses to load with its admin-key file unreadable;
        the command, which reads no secret, migrates regardless."""
        path = tmp_path / "credits.db"

        assert command(
            path, storefront_admin_key_file=str(tmp_path / "not-mounted"),
        ) == 0

        assert sorted(_recorded(path)) == sorted(CHAIN.ids)


class TestCreateDbEngineIsSqliteOnly:
    def test_raises_for_a_non_sqlite_url(self):
        with pytest.raises(ValueError):
            create_db_engine("postgresql://user:pass@host/db", is_sqlite=False)

    def test_accepts_a_sqlite_url(self):
        engine = create_db_engine("sqlite:///:memory:", is_sqlite=True)
        assert engine is not None
