"""Ordered SQLite migrations: schema_migrations tracking, idempotency,
and adoption of a database that predates this migration system.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from db.database import create_db_engine, run_migrations
from db.migrations import (
    SchemaDriftError,
    apply_schema_migrations,
    check_schema_version,
)
from db.models import Base


def _sqlite_memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


class TestRunMigrationsFreshBootstrap:
    def test_creates_every_expected_table(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)

        from sqlalchemy import inspect
        tables = set(inspect(engine).get_table_names())
        assert {
            "api_keys", "credit_grants", "consumption_events",
            "schema_migrations", "capacity_buckets", "capacity_reservations",
        } <= tables

    def test_records_baseline_migration(self):
        # A fresh bootstrap adopts the existing create_all schema into
        # durable migration versioning.
        engine = _sqlite_memory_engine()
        run_migrations(engine)

        with engine.begin() as connection:
            rows = connection.execute(text("SELECT id FROM schema_migrations")).fetchall()
        assert rows == [("20260731_001_apicredits_schema_baseline",)]


class TestRunMigrationsIsIdempotent:
    def test_running_twice_does_not_error_or_duplicate_bookkeeping(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        run_migrations(engine)  # must not raise

        with engine.begin() as connection:
            count = connection.execute(
                text("SELECT COUNT(*) FROM schema_migrations")
            ).scalar()
        assert count == 1


class TestAdoptingAPreCreateAllOnlyDatabase:
    """A database this service already created via the old
    Base.metadata.create_all()-only startup (no schema_migrations table
    at all) must be adopted cleanly -- not treated as corrupt, and not
    silently skipped in a way that leaves it unable to receive future
    migrations.
    """

    def test_adopts_a_database_with_no_schema_migrations_table(self):
        engine = _sqlite_memory_engine()
        # Simulate the pre-migration-system startup path directly,
        # bypassing run_migrations entirely.
        Base.metadata.create_all(bind=engine)
        from market_site.db import Base as SiteBase
        SiteBase.metadata.create_all(bind=engine)

        from sqlalchemy import inspect
        assert "schema_migrations" not in set(inspect(engine).get_table_names())

        # The real startup path, run against this old-shaped database.
        run_migrations(engine)

        tables = set(inspect(engine).get_table_names())
        assert "schema_migrations" in tables
        assert "api_keys" in tables  # pre-existing table untouched, not recreated

    def test_adopts_a_database_with_existing_data_without_touching_it(self):
        engine = _sqlite_memory_engine()
        Base.metadata.create_all(bind=engine)
        from market_site.db import Base as SiteBase
        SiteBase.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO api_keys "
                "(key_id, secret_hash, status, balance, created_at, updated_at) "
                "VALUES ('k1', 'hash1', 'active', 42, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))

        run_migrations(engine)

        with engine.begin() as connection:
            row = connection.execute(text(
                "SELECT balance FROM api_keys WHERE key_id = 'k1'"
            )).fetchone()
        assert row is not None
        assert row[0] == 42


class TestCheckSchemaVersion:
    """Not called by this service's own startup today (see migrations.py's
    module docstring -- there's no separate deployment step to check
    against yet), but this proves the fail-fast primitive itself is
    correct and ready for when one exists.
    """

    def test_passes_after_baseline_is_applied(self):
        engine = _sqlite_memory_engine()
        Base.metadata.create_all(bind=engine)
        from market_site.db import Base as SiteBase
        SiteBase.metadata.create_all(bind=engine)
        apply_schema_migrations(engine)
        check_schema_version(engine)

    def test_raises_when_schema_migrations_table_is_entirely_missing(self):
        engine = _sqlite_memory_engine()
        Base.metadata.create_all(bind=engine)
        # Only meaningful once _MIGRATIONS is non-empty; document the
        # intended behavior now so it's exercised the moment a real
        # migration is added, rather than discovered broken then.
        import db.migrations as migrations_module
        original = migrations_module._MIGRATIONS
        migrations_module._MIGRATIONS = (
            migrations_module.Migration("00000000_placeholder", lambda engine: None),
        )
        try:
            with pytest.raises(SchemaDriftError):
                check_schema_version(engine)
        finally:
            migrations_module._MIGRATIONS = original


class TestCreateDbEngineIsSqliteOnly:
    def test_raises_for_a_non_sqlite_url(self):
        with pytest.raises(ValueError):
            create_db_engine("postgresql://user:pass@host/db", is_sqlite=False)

    def test_accepts_a_sqlite_url(self):
        engine = create_db_engine("sqlite:///:memory:", is_sqlite=True)
        assert engine is not None


def test_failed_migration_is_not_recorded_and_prior_success_is_preserved(monkeypatch):
    import db.migrations as migrations_module

    engine = _sqlite_memory_engine()
    Base.metadata.create_all(bind=engine)
    from market_site.db import Base as SiteBase
    SiteBase.metadata.create_all(bind=engine)

    calls: list[str] = []

    def first(_engine):
        calls.append("first")

    def fail(_engine):
        calls.append("fail")
        raise RuntimeError("boom")

    monkeypatch.setattr(
        migrations_module,
        "_MIGRATIONS",
        (
            migrations_module.Migration("001", first),
            migrations_module.Migration("002", fail),
        ),
    )

    with pytest.raises(RuntimeError, match="boom"):
        migrations_module.apply_schema_migrations(engine)

    with engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id FROM schema_migrations ORDER BY id")
        ).fetchall()

    assert rows == [("001",)]
    with pytest.raises(SchemaDriftError):
        migrations_module.check_schema_version(engine)
    assert calls == ["first", "fail"]
