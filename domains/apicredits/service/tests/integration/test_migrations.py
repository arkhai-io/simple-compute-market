"""Ordered SQLite migrations: schema_migrations tracking, idempotency,
and adoption of a database that predates this migration system.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from market_site.db import Base as SiteBase

import apicredits_service.db.migrations as migrations_module
from apicredits_service.db.database import create_db_engine, run_migrations
from apicredits_service.db.migrations import (
    SchemaDriftError,
    apply_schema_migrations,
    check_schema_version,
)
from apicredits_service.db.models import Base


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

        tables = set(inspect(engine).get_table_names())
        columns = {
            column["name"] for column in inspect(engine).get_columns("credit_grants")
        }
        assert columns == set(Base.metadata.tables["credit_grants"].columns.keys())
        assert "negotiation_id" in columns
        assert {"escrow_uid", "obligation_ref", "mechanism"}.isdisjoint(columns)
        unique_columns = {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints("credit_grants")
        }
        assert {("fulfillment_id",), ("negotiation_id",)} <= unique_columns
        assert {
            "api_keys",
            "credit_grants",
            "consumption_events",
            "schema_migrations",
            "capacity_buckets",
            "capacity_reservations",
        } <= tables

    def test_records_baseline_migration(self):
        # A fresh bootstrap adopts the existing create_all schema into
        # durable migration versioning.
        engine = _sqlite_memory_engine()
        run_migrations(engine)

        with engine.begin() as connection:
            rows = connection.execute(
                text("SELECT id FROM schema_migrations")
            ).fetchall()
        assert rows == [
            ("20260731_001_apicredits_schema_baseline",),
            ("20260811_002_canonical_owner_principals",),
            ("20260815_003_fulfillment_grants",),
            ("20260922_004_pool_advertisement_and_backing",),
            ("20261005_005_reservation_release_requested_at",),
            ("20261028_006_retired_reservation_states",),
            ("20261106_007_reservation_activated_at",),
        ]

    def test_a_reservation_table_from_before_release_timing_gains_the_column(self):
        """The site ledger this service composes records when a reservation
        began releasing; a table created before that column existed gains it."""
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE capacity_reservations DROP COLUMN release_requested_at")
            )
            connection.execute(
                text(
                    "DELETE FROM schema_migrations "
                    "WHERE id = '20261005_005_reservation_release_requested_at'"
                )
            )

        run_migrations(engine)

        with engine.begin() as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    text("PRAGMA table_info(capacity_reservations)")
                ).fetchall()
            }
        assert "release_requested_at" in columns


_ACTIVATION_MIGRATION_ID = "20261106_007_reservation_activated_at"

_RESERVATION_COLUMNS = (
    "capacity_reservation_id, units, state, offering_mode, hold_expires_at, "
    "executor_target, lease_start_utc, lease_end_utc, release_requested_at, "
    "released_at"
)

# Quota grants are open-ended holds, so no row carries a lease end.
_RESERVATIONS_BEFORE_ACTIVATION = (
    ("r-leased", 1, "leased", "api_credits", None, "grant-leased",
     "2026-11-01T00:00:00+00:00", None, None, None),
    ("r-releasing", 2, "releasing", "api_credits", None, "grant-releasing",
     "2026-10-01T00:00:00+00:00", None, "2026-11-01T00:00:05+00:00", None),
    ("r-released", 1, "released", "api_credits", "2026-08-31T00:05:00+00:00",
     None, "2026-09-01T00:00:00+00:00", None,
     "2026-10-01T00:00:05+00:00", "2026-10-01T00:10:00+00:00"),
)


def _database_before_activation():
    """A migrated database as it stood before the activation column, holding
    leased, releasing and released reservations."""
    engine = _sqlite_memory_engine()
    run_migrations(engine)
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE capacity_reservations DROP COLUMN activated_at_utc")
        )
        connection.execute(
            text("DELETE FROM schema_migrations WHERE id = :id"),
            {"id": _ACTIVATION_MIGRATION_ID},
        )
        for row in _RESERVATIONS_BEFORE_ACTIVATION:
            connection.execute(
                text(
                    f"INSERT INTO capacity_reservations ({_RESERVATION_COLUMNS}) "
                    "VALUES (:id, :units, :state, :mode, :hold, :target, "
                    ":start, :end, :requested, :released)"
                ),
                dict(zip(
                    ("id", "units", "state", "mode", "hold", "target", "start",
                     "end", "requested", "released"),
                    row,
                )),
            )
    return engine


def _reservation_rows(engine) -> set[tuple]:
    with engine.connect() as connection:
        return {
            tuple(row)
            for row in connection.execute(text(
                f"SELECT {_RESERVATION_COLUMNS}, activated_at_utc "
                "FROM capacity_reservations"
            ))
        }


class TestTheActivationColumn:
    """The site ledger this service hosts maps a lease's activation instant on
    the reservation row it shares with every quota grant."""

    def test_existing_reservations_migrate_with_no_activation_recorded(self):
        engine = _database_before_activation()

        run_migrations(engine)

        expected = {row + (None,) for row in _RESERVATIONS_BEFORE_ACTIVATION}
        assert _reservation_rows(engine) == expected
        check_schema_version(engine)

        run_migrations(engine)

        assert _reservation_rows(engine) == expected

    def test_a_database_already_carrying_the_column_migrates_unchanged(self):
        engine = _database_before_activation()
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE capacity_reservations ADD COLUMN activated_at_utc VARCHAR"
            ))
            connection.execute(text(
                "UPDATE capacity_reservations "
                "SET activated_at_utc = '2026-11-01T00:07:00+00:00' "
                "WHERE capacity_reservation_id = 'r-leased'"
            ))
        before = _reservation_rows(engine)

        run_migrations(engine)

        assert _reservation_rows(engine) == before
        columns = [
            column["name"]
            for column in inspect(engine).get_columns("capacity_reservations")
        ]
        assert columns.count("activated_at_utc") == 1


class TestRunMigrationsIsIdempotent:
    def test_running_twice_does_not_error_or_duplicate_bookkeeping(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        run_migrations(engine)  # must not raise

        with engine.begin() as connection:
            count = connection.execute(
                text("SELECT COUNT(*) FROM schema_migrations")
            ).scalar()
        assert count == 7


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
        SiteBase.metadata.create_all(bind=engine)

        assert "schema_migrations" not in set(inspect(engine).get_table_names())

        # The real startup path, run against this old-shaped database.
        run_migrations(engine)

        tables = set(inspect(engine).get_table_names())
        assert "schema_migrations" in tables
        assert "api_keys" in tables  # pre-existing table untouched, not recreated

    def test_adopts_a_database_with_existing_data_without_touching_it(self):
        engine = _sqlite_memory_engine()
        Base.metadata.create_all(bind=engine)
        SiteBase.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO api_keys "
                    "(key_id, secret_hash, status, balance, created_at, updated_at) "
                    "VALUES ('k1', 'hash1', 'active', 42, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        run_migrations(engine)

        with engine.begin() as connection:
            row = connection.execute(
                text("SELECT balance FROM api_keys WHERE key_id = 'k1'")
            ).fetchone()
        assert row is not None
        assert row[0] == 42

    def test_migrates_wallet_owner_to_canonical_eip191_principal(self):
        engine = _sqlite_memory_engine()
        Base.metadata.create_all(bind=engine)
        SiteBase.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO api_keys "
                    "(key_id, secret_hash, owner_scheme, owner_id, status, balance, "
                    "created_at, updated_at) VALUES "
                    "('k1', 'hash1', 'wallet', "
                    "'0xABCDEF0000000000000000000000000000000001', "
                    "'active', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        run_migrations(engine)

        with engine.begin() as connection:
            row = connection.execute(
                text("SELECT owner_scheme, owner_id FROM api_keys WHERE key_id = 'k1'")
            ).one()
        assert row == (
            "eip191",
            "0xabcdef0000000000000000000000000000000001",
        )

    def test_incompatible_grant_schema_requires_explicit_reset(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE credit_grants ADD COLUMN escrow_uid VARCHAR")
            )

        for check in (run_migrations, check_schema_version):
            with pytest.raises(SchemaDriftError, match="explicitly reset"):
                check(engine)
        assert "escrow_uid" in {
            column["name"] for column in inspect(engine).get_columns("credit_grants")
        }

    def test_malformed_owner_rolls_back_principal_migration(self):
        engine = _sqlite_memory_engine()
        Base.metadata.create_all(bind=engine)
        SiteBase.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO api_keys "
                    "(key_id, secret_hash, owner_scheme, owner_id, status, balance, "
                    "created_at, updated_at) VALUES "
                    "('good', 'hash1', 'wallet', "
                    "'0xABCDEF0000000000000000000000000000000001', "
                    "'active', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                    "('bad', 'hash2', 'wallet', 'not-an-address', "
                    "'active', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        with pytest.raises(SchemaDriftError):
            run_migrations(engine)

        with engine.begin() as connection:
            rows = connection.execute(
                text(
                    "SELECT key_id, owner_scheme, owner_id FROM api_keys ORDER BY key_id"
                )
            ).fetchall()
        assert rows == [
            ("bad", "wallet", "not-an-address"),
            (
                "good",
                "wallet",
                "0xABCDEF0000000000000000000000000000000001",
            ),
        ]


class TestCheckSchemaVersion:
    """The fail-fast primitive itself. This service's startup migrates in
    process and does not call it (see migrations.py's module docstring).
    """

    def test_passes_after_baseline_is_applied(self):
        engine = _sqlite_memory_engine()
        Base.metadata.create_all(bind=engine)
        SiteBase.metadata.create_all(bind=engine)
        apply_schema_migrations(engine)
        check_schema_version(engine)

    def test_raises_when_schema_migrations_table_is_entirely_missing(self):
        engine = _sqlite_memory_engine()
        Base.metadata.create_all(bind=engine)
        # A single known migration stands in for the real chain, so the
        # check's verdict does not depend on which migrations exist.
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
    engine = _sqlite_memory_engine()
    Base.metadata.create_all(bind=engine)
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


