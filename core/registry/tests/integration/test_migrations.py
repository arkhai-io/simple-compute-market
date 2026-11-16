"""The registry's migration over real SQLite files.

Library integration, the application not started, but for one test that runs
the application's lifespan over an unmigrated database.

A fresh database migrated through the chain reproduces the v0.3.0 floor
fixture; a database the release built (``ddl.sql`` at
``018_listing_resource_column``) is adopted at the baseline, keeping its rows;
a database from before the floor, or with tables and no revision, is refused
as unsupported and an unknown revision as ahead, each left byte for byte as it
was. The startup check refuses every state but compatible in the shared
message, naming ``registry-migrate``, and creates no file. ``registry-migrate``
and its ``--check`` run through the entry point with their settings in the
environment.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from alembic import command
from market_schema_migrations import (
    CheckState,
    MigrationRefused,
    schema_snapshot,
)
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core_registry import migrate
from core_registry.config import settings
from core_registry.db.models import Publisher, PublisherIdentity
from core_registry.main import app, lifespan
from core_registry.db.migrations import (
    FLOOR_REVISION,
    alembic_config,
    IncompatibleDatabase,
    check_database,
    migrate_database,
    require_compatible_database,
)

FLOOR = Path(__file__).resolve().parents[1] / "fixtures" / "v0_3_0_floor"
BASELINE = "v0_3_0_baseline"
HEAD = "20261106_001_registry_retained_publications"


def _url(path: Path) -> str:
    return f"sqlite:///{path}"


def _snapshot(path: Path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


def _revisions(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute("SELECT version_num FROM alembic_version")]
    finally:
        connection.close()


def _floor_database(path: Path, revision: str = FLOOR_REVISION) -> Path:
    """A database as the v0.3.0 release built it, holding a publisher and a listing."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript((FLOOR / "ddl.sql").read_text())
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        connection.execute(
            "INSERT INTO publishers VALUES (1, 'http://storefront.test/', "
            "'2026-11-01 00:00:00', '2026-11-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO listings (listing_id, publisher_id, listing_resource, status, "
            "created_at, updated_at) VALUES ('listing-1', 1, '{\"offering_mode\": \"vm\"}', "
            "'open', '2026-11-01 00:00:00', '2026-11-01 00:00:00')"
        )
        connection.commit()
    finally:
        connection.close()
    return path


def test_the_chain_reproduces_the_floor_fixture(tmp_path: Path) -> None:
    database = tmp_path / "registry.db"
    command.upgrade(alembic_config(_url(database)), BASELINE)
    assert _snapshot(database) == json.loads((FLOOR / "schema.json").read_text())
    assert _revisions(database) == [BASELINE]
    assert check_database(_url(database)).state is CheckState.BEHIND


def test_a_migrated_database_refuses_a_second_primary_identity_for_one_publisher(
    tmp_path: Path,
) -> None:
    """The baseline's partial unique index holds the one-primary rule."""
    database = tmp_path / "registry.db"
    migrate_database(_url(database))
    engine = create_engine(_url(database))
    try:
        with Session(engine) as session:
            publisher = Publisher()
            session.add(publisher)
            session.flush()
            session.add(
                PublisherIdentity(
                    publisher_id=publisher.publisher_id,
                    scheme="ed25519",
                    identifier="a" * 43,
                    status="primary",
                )
            )
            session.commit()
            session.add(
                PublisherIdentity(
                    publisher_id=publisher.publisher_id,
                    scheme="ed25519",
                    identifier="b" * 43,
                    status="primary",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()


def test_the_floor_fixture_is_the_release_revision() -> None:
    assert json.loads((FLOOR / "floor_revision.json").read_text()) == FLOOR_REVISION


def test_a_rerun_changes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "registry.db"
    migrate_database(_url(database))
    before = database.read_bytes()
    report = migrate_database(_url(database))
    assert report.applied == () and not report.adopted
    assert database.read_bytes() == before


def test_a_v0_3_0_database_is_adopted_keeping_its_rows(tmp_path: Path) -> None:
    database = _floor_database(tmp_path / "registry.db")
    result = check_database(_url(database))
    assert result.state is CheckState.BEHIND and result.adopting == (BASELINE,)
    assert result.current == FLOOR_REVISION

    report = migrate_database(_url(database))

    assert report.adopted and report.applied == (HEAD,)
    assert _revisions(database) == [HEAD]
    assert check_database(_url(database)).compatible
    fresh = tmp_path / "fresh.db"
    fresh_report = migrate_database(_url(fresh))
    assert fresh_report.applied == (BASELINE, HEAD)
    assert _snapshot(database) == _snapshot(fresh)
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT listing_id, publisher_id FROM listings").fetchall() == [
            ("listing-1", 1)
        ]
        assert connection.execute(
            "SELECT published_document, publisher_publication, publisher_updates FROM listings"
        ).fetchall() == [(None, None, None)]
        assert connection.execute("SELECT storefront_url FROM publishers").fetchall() == [
            ("http://storefront.test/",)
        ]
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("revision", "state"),
    [
        ("014_agent_to_publisher", CheckState.UNSUPPORTED),
        ("017_publisher_replay_leases", CheckState.UNSUPPORTED),
        ("021_from_a_newer_image", CheckState.AHEAD),
    ],
)
def test_a_database_at_another_revision_is_refused_unchanged(
    tmp_path: Path, revision: str, state: CheckState
) -> None:
    database = _floor_database(tmp_path / "registry.db", revision)
    before = database.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate_database(_url(database))

    assert refused.value.result.state is state
    if state is CheckState.AHEAD:
        assert revision in str(refused.value)
    assert "`registry-migrate`" in str(refused.value)
    assert database.read_bytes() == before


def test_an_earlier_revision_is_refused_naming_what_it_lacks(tmp_path: Path) -> None:
    database = _floor_database(tmp_path / "registry.db", "016_marketplace_principal_auth")
    with pytest.raises(MigrationRefused) as refused:
        migrate_database(_url(database))
    message = str(refused.value)
    assert "017_publisher_replay_leases" in message and FLOOR_REVISION in message
    assert "fresh database" in message


def test_tables_without_a_revision_are_refused_unchanged(tmp_path: Path) -> None:
    database = tmp_path / "registry.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE listings (listing_id VARCHAR PRIMARY KEY)")
    connection.commit()
    connection.close()
    before = database.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate_database(_url(database))

    assert refused.value.result.state is CheckState.UNSUPPORTED
    assert database.read_bytes() == before
    with pytest.raises(IncompatibleDatabase):
        require_compatible_database(_url(database))


def test_the_startup_check_refuses_every_state_but_compatible(tmp_path: Path) -> None:
    """Behind, ahead, absent and unsupported, each refused in the shared form,
    naming the command, with the database unchanged and no file created."""
    behind = _floor_database(tmp_path / "behind.db")
    ahead = _floor_database(tmp_path / "ahead.db", "021_from_a_newer_image")
    unsupported = _floor_database(tmp_path / "unsupported.db", "013_api_key_scope")
    absent = tmp_path / "missing" / "registry.db"
    for path, state in (
        (behind, CheckState.BEHIND),
        (ahead, CheckState.AHEAD),
        (unsupported, CheckState.UNSUPPORTED),
        (absent, CheckState.ABSENT),
    ):
        before = path.read_bytes() if path.exists() else None
        with pytest.raises(IncompatibleDatabase) as refused:
            require_compatible_database(_url(path))
        assert refused.value.result.state is state
        assert "`registry-migrate`" in str(refused.value)
        assert (path.read_bytes() if path.exists() else None) == before
    assert not absent.parent.exists()
    # The floor's refusal names both revisions: the one it is at and the
    # baseline its adoption records.
    message = str(_refusal(behind))
    assert f"at {FLOOR_REVISION} is behind" in message
    assert f"supported baseline is to be adopted (recording {BASELINE})" in message


async def test_the_application_refuses_to_start_on_an_unmigrated_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The application's lifespan checks its database before anything else and
    refuses, creating nothing, when the command has not run.

    The lifespan is entered directly, its settings object's database URL
    replaced as this suite's conftest replaces the registry's authority; the
    application serves no request here."""
    database = tmp_path / "missing" / "registry.db"
    monkeypatch.setattr(settings, "database_url", _url(database))
    with pytest.raises(IncompatibleDatabase) as refused:
        async with lifespan(app):
            raise AssertionError("the registry started on an unmigrated database")
    assert refused.value.result.state is CheckState.ABSENT
    assert "`registry-migrate`" in str(refused.value)
    assert not database.parent.exists()


def _refusal(path: Path) -> IncompatibleDatabase:
    try:
        require_compatible_database(_url(path))
    except IncompatibleDatabase as refused:
        return refused
    raise AssertionError(f"{path} was not refused")


@pytest.fixture
def command_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The command's settings in the environment, in a directory with no files."""
    monkeypatch.chdir(tmp_path)
    for name in ("CONFIG_DIRECTORY", "ACTIVE_PROFILES", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    database = tmp_path / "data" / "registry.db"
    database.parent.mkdir()
    monkeypatch.setenv("DATABASE_URL", _url(database))
    return database


def test_check_lists_the_adoption_and_changes_nothing(
    command_database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _floor_database(command_database)
    before = command_database.read_bytes()
    with pytest.raises(SystemExit) as exited:
        migrate.main(["--check"])
    assert exited.value.code == 1
    out, err = capsys.readouterr()
    assert "behind" in out and FLOOR_REVISION in out
    assert f"supported baseline to be adopted: {BASELINE}" in out
    assert "`registry-migrate`" in err
    assert command_database.read_bytes() == before


def test_check_on_a_missing_database_creates_none(
    command_database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        migrate.main(["--check"])
    assert exited.value.code == 1
    assert "absent" in capsys.readouterr().out
    assert not command_database.exists()


def test_the_command_migrates_and_then_checks_compatible(
    command_database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    migrate.main([])
    migrate.main([])
    migrate.main(["--check"])
    assert "compatible" in capsys.readouterr().out
    assert _revisions(command_database) == [HEAD]


def test_the_command_refuses_an_ahead_database_unchanged(
    command_database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _floor_database(command_database, "021_from_a_newer_image")
    before = command_database.read_bytes()
    with pytest.raises(SystemExit) as exited:
        migrate.main([])
    assert exited.value.code == 1
    assert "021_from_a_newer_image" in capsys.readouterr().err
    assert command_database.read_bytes() == before


def test_the_command_reads_only_the_database_and_log_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A profile naming a credential file that does not exist and a setting the
    application would refuse still migrates: the command reads neither."""
    monkeypatch.chdir(tmp_path)
    for name in ("DATABASE_URL", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    database = tmp_path / "registry.db"
    (tmp_path / "config-registry.env").write_text(
        f"DATABASE_URL={_url(database)}\n"
        "REGISTRY_AUTHORITY_ID=registry-a\n"
        "REGISTRY_AUTHORITY_CREDENTIAL_FILE=/run/secrets/absent/credential\n"
        "REGISTRY_REQUIRE_WRITE_API_KEY=not-a-boolean\n"
    )
    monkeypatch.setenv("CONFIG_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("ACTIVE_PROFILES", "registry")
    migrate.main([])
    assert _revisions(database) == [HEAD]


def test_the_command_does_not_load_the_application_settings() -> None:
    """Importing the command loads neither the application's settings nor its
    engine, which read every setting the files state."""
    loaded = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, core_registry.migrate; "
            "print(sorted(m for m in ('core_registry.config', 'core_registry.db.database') "
            "if m in sys.modules))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert loaded.stdout.strip() == "[]"


def test_the_console_script_entry_point_is_the_command() -> None:
    (script,) = entry_points(group="console_scripts", name="registry-migrate")
    assert script.load() is migrate.main
