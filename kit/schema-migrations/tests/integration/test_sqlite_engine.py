"""The engine against real SQLite files through the ``sqlite3`` adapter."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from market_schema_migrations import (
    Chain,
    CheckState,
    Floor,
    Migration,
    MigrationFailed,
    MigrationRefused,
    SqliteMigrationConnection,
    UnsupportedCause,
    check,
    check_sqlite_file,
    connect_read_only,
    migrate,
    schema_snapshot,
)

_FLOOR = Floor("example 1.0.0", ("floor_hosts", "floor_jobs"))


def _create_hosts(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE hosts (host_id TEXT PRIMARY KEY, port INTEGER)")


def _create_jobs(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE jobs (job_id TEXT PRIMARY KEY, host_id TEXT)")


def _add_port_default(connection: sqlite3.Connection) -> None:
    connection.execute("UPDATE hosts SET port = 22 WHERE port IS NULL")


def _add_index(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE INDEX ix_jobs_host ON jobs (host_id)")


def _baseline_must_not_run(_connection: sqlite3.Connection) -> None:
    raise AssertionError("adoption ran a baseline")


def _chain(
    *,
    baselines: tuple[Migration[sqlite3.Connection], ...] | None = None,
    migrations: tuple[Migration[sqlite3.Connection], ...] | None = None,
    floor: Floor = _FLOOR,
) -> Chain[sqlite3.Connection]:
    return Chain(
        service="example-service",
        command="example-service-migrate",
        baselines=baselines
        or (Migration("base_hosts", _create_hosts), Migration("base_jobs", _create_jobs)),
        migrations=migrations
        if migrations is not None
        else (
            Migration("later_port_default", _add_port_default),
            Migration("later_jobs_index", _add_index),
        ),
        floor=floor,
    )


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "service.db"


@pytest.fixture
def connection(database: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(database)
    yield connection
    connection.close()


def _recorded(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT id FROM schema_migrations")}


def _floor_database(connection: sqlite3.Connection, *extra_ids: str) -> None:
    """A database an earlier release's chain built: its tables and its records,
    with any ``extra_ids`` beside them, as a release before the floor left."""

    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            id VARCHAR PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE hosts (host_id TEXT PRIMARY KEY, port INTEGER);
        CREATE TABLE jobs (job_id TEXT PRIMARY KEY, host_id TEXT);
        INSERT INTO hosts VALUES ('h1', NULL);
        """
    )
    for migration_id in ("floor_hosts", "floor_jobs", *extra_ids):
        connection.execute("INSERT INTO schema_migrations (id) VALUES (?)", (migration_id,))
    connection.commit()


def test_a_fresh_database_runs_every_migration_and_records_it(
    connection: sqlite3.Connection, database: Path
) -> None:
    report = migrate(_chain(), SqliteMigrationConnection(connection))

    assert report.adopted is False
    assert report.applied == (
        "base_hosts",
        "base_jobs",
        "later_port_default",
        "later_jobs_index",
    )
    assert _recorded(connection) == set(report.applied)
    assert set(schema_snapshot(connection)["tables"]) == {"hosts", "jobs"}
    assert check_sqlite_file(_chain(), database).state is CheckState.COMPATIBLE


def test_a_rerun_changes_nothing(connection: sqlite3.Connection) -> None:
    adapter = SqliteMigrationConnection(connection)
    migrate(_chain(), adapter)
    before = (schema_snapshot(connection), _recorded(connection))

    report = migrate(_chain(), adapter)

    assert report.applied == ()
    assert (schema_snapshot(connection), _recorded(connection)) == before


def test_a_floor_database_is_adopted_without_running_the_baselines(
    connection: sqlite3.Connection, database: Path
) -> None:
    _floor_database(connection)
    chain = _chain(
        baselines=(
            Migration("base_hosts", _baseline_must_not_run),
            Migration("base_jobs", _baseline_must_not_run),
        )
    )

    report = migrate(chain, SqliteMigrationConnection(connection))

    assert report.adopted is True
    assert report.applied == ("later_port_default", "later_jobs_index")
    assert _recorded(connection) == {
        "base_hosts",
        "base_jobs",
        "later_port_default",
        "later_jobs_index",
    }
    assert connection.execute("SELECT port FROM hosts").fetchall() == [(22,)]
    assert check_sqlite_file(chain, database).state is CheckState.COMPATIBLE


def test_a_floor_database_with_a_later_migration_keeps_it_and_applies_the_rest(
    connection: sqlite3.Connection,
) -> None:
    _floor_database(connection, "later_port_default")

    report = migrate(_chain(), SqliteMigrationConnection(connection))

    assert report.adopted is True
    assert report.applied == ("later_jobs_index",)
    assert "later_port_default" in _recorded(connection)


def test_a_floor_database_carrying_earlier_records_is_adopted_with_them_forgotten(
    connection: sqlite3.Connection, database: Path
) -> None:
    _floor_database(connection, "zeta_retired", "alpha_retired")
    connection.execute("CREATE TABLE retired_lifecycle (id TEXT)")
    connection.execute("INSERT INTO retired_lifecycle VALUES ('kept')")
    connection.commit()

    report = migrate(_chain(), SqliteMigrationConnection(connection))

    assert report.adopted is True
    assert report.set_aside == ("alpha_retired", "zeta_retired")
    assert report.applied == ("later_port_default", "later_jobs_index")
    assert _recorded(connection) == set(_chain().ids)
    assert connection.execute("SELECT port FROM hosts").fetchall() == [(22,)]
    assert connection.execute("SELECT id FROM retired_lifecycle").fetchall() == [("kept",)]
    assert check_sqlite_file(_chain(), database).state is CheckState.COMPATIBLE

    before = database.read_bytes()
    assert migrate(_chain(), SqliteMigrationConnection(connection)).applied == ()
    assert database.read_bytes() == before


def test_the_check_of_a_floor_database_carrying_earlier_records_changes_nothing(
    connection: sqlite3.Connection, database: Path
) -> None:
    _floor_database(connection, "retired_1")
    connection.close()
    before = database.read_bytes()
    siblings = set(database.parent.iterdir())

    result = check_sqlite_file(_chain(), database)

    assert result.state is CheckState.BEHIND
    assert result.set_aside == ("retired_1",)
    assert result.floor == "example 1.0.0"
    assert database.read_bytes() == before
    assert set(database.parent.iterdir()) == siblings


def test_a_zero_floor_chain_builds_a_fresh_database_and_refuses_a_foreign_one(
    tmp_path: Path,
) -> None:
    chain = _chain(floor=Floor("0.0.0"))
    fresh = sqlite3.connect(tmp_path / "fresh.db")
    assert migrate(chain, SqliteMigrationConnection(fresh)).applied == chain.ids
    fresh.close()

    foreign_path = tmp_path / "foreign.db"
    foreign = sqlite3.connect(foreign_path)
    _floor_database(foreign)
    before = foreign_path.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate(chain, SqliteMigrationConnection(foreign))

    assert refused.value.result.cause is UnsupportedCause.NOT_THIS_CHAIN
    assert refused.value.result.adopting == ()
    foreign.close()
    assert foreign_path.read_bytes() == before


@pytest.mark.parametrize(
    ("records", "state", "cause"),
    [
        (("base_hosts", "base_jobs", "newer"), CheckState.AHEAD, None),
        (("floor_hosts",), CheckState.UNSUPPORTED, UnsupportedCause.OLDER_OR_SHARED),
        (("other_service",), CheckState.UNSUPPORTED, UnsupportedCause.NOT_THIS_CHAIN),
    ],
    ids=["ahead", "older-or-shared", "not-this-chain"],
)
def test_an_ahead_or_unsupported_database_is_refused_byte_identical(
    database: Path,
    records: tuple[str, ...],
    state: CheckState,
    cause: UnsupportedCause | None,
) -> None:
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (id VARCHAR PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE hosts (host_id TEXT PRIMARY KEY, port INTEGER);
        """
    )
    for migration_id in records:
        connection.execute("INSERT INTO schema_migrations (id) VALUES (?)", (migration_id,))
    connection.commit()
    before = database.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate(_chain(), SqliteMigrationConnection(connection))

    assert refused.value.result.state is state
    assert refused.value.result.cause is cause
    assert "example-service-migrate" in str(refused.value)
    connection.close()
    assert database.read_bytes() == before


def test_tables_without_a_ledger_are_refused_and_no_ledger_is_created(
    connection: sqlite3.Connection,
) -> None:
    _create_hosts(connection)
    connection.commit()

    with pytest.raises(MigrationRefused) as refused:
        migrate(_chain(), SqliteMigrationConnection(connection))

    assert refused.value.result.state is CheckState.UNSUPPORTED
    assert refused.value.result.cause is UnsupportedCause.NOT_THIS_CHAIN
    assert set(schema_snapshot(connection)["tables"]) == {"hosts"}
    assert connection.execute(
        "SELECT count(*) FROM sqlite_master WHERE name = 'schema_migrations'"
    ).fetchone() == (0,)


def _fails_after_ddl(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE half_done (id INTEGER)")
    connection.execute("ALTER TABLE hosts ADD COLUMN half_column TEXT")
    raise RuntimeError("the migration broke")


@pytest.mark.parametrize(
    "transaction_control",
    [{}, {"isolation_level": None}, {"autocommit": True}],
    ids=["default", "isolation-level-none", "autocommit"],
)
def test_a_failing_migration_leaves_earlier_ones_recorded_and_no_trace_of_itself(
    database: Path, transaction_control: dict
) -> None:
    connection = sqlite3.connect(database, **transaction_control)
    chain = _chain(
        migrations=(
            Migration("later_port_default", _add_port_default),
            Migration("later_broken", _fails_after_ddl),
            Migration("later_jobs_index", _add_index),
        )
    )

    with pytest.raises(MigrationFailed) as failed:
        migrate(chain, SqliteMigrationConnection(connection))

    assert failed.value.migration_id == "later_broken"
    assert "later_broken" in str(failed.value)
    assert _recorded(connection) == {"base_hosts", "base_jobs", "later_port_default"}
    snapshot = schema_snapshot(connection)
    assert "half_done" not in snapshot["tables"]
    assert [c["name"] for c in snapshot["tables"]["hosts"]["columns"]] == ["host_id", "port"]
    result = check_sqlite_file(chain, database)
    assert result.state is CheckState.BEHIND
    assert result.pending == ("later_broken", "later_jobs_index")
    connection.close()


class _RecordingFailsForBaselines(SqliteMigrationConnection):
    """Fails at the moment adoption records the baseline IDs."""

    def record(self, ids) -> None:
        ids = tuple(ids)
        if "base_hosts" in ids:
            raise RuntimeError("the disk filled")
        super().record(ids)


def test_a_failed_adoption_keeps_the_floor_records(connection: sqlite3.Connection) -> None:
    _floor_database(connection)

    with pytest.raises(RuntimeError, match="the disk filled"):
        migrate(_chain(), _RecordingFailsForBaselines(connection))

    assert _recorded(connection) == {"floor_hosts", "floor_jobs"}
    assert connection.execute("SELECT port FROM hosts").fetchall() == [(None,)]


def test_the_read_only_check_of_a_missing_file_is_absent_and_creates_no_file(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nowhere" / "service.db"

    assert check_sqlite_file(_chain(), missing).state is CheckState.ABSENT
    assert not missing.exists()
    assert not missing.parent.exists()


def test_the_check_changes_nothing_on_a_behind_database(
    connection: sqlite3.Connection, database: Path
) -> None:
    _floor_database(connection)
    before = database.read_bytes()

    result = check_sqlite_file(_chain(), database)

    assert result.state is CheckState.BEHIND
    assert result.adoption_pending is True
    assert result.adopting == ("base_hosts", "base_jobs")
    assert result.pending == ("later_port_default", "later_jobs_index")
    assert database.read_bytes() == before


def test_the_check_runs_on_a_connection_that_refuses_writes(
    connection: sqlite3.Connection, database: Path
) -> None:
    _create_hosts(connection)
    connection.commit()

    read_only = connect_read_only(database)
    try:
        assert check(_chain(), SqliteMigrationConnection(read_only)).state is (
            CheckState.UNSUPPORTED
        )
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            read_only.execute("CREATE TABLE written (id INTEGER)")
    finally:
        read_only.close()


def test_the_engine_refuses_a_connection_already_inside_a_transaction(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("CREATE TABLE outside (id INTEGER)")
    connection.execute("INSERT INTO outside VALUES (1)")
    assert connection.in_transaction

    with pytest.raises(RuntimeError, match="already inside one"):
        migrate(_chain(), SqliteMigrationConnection(connection))
