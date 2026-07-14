"""Unit tests for database initialisation helpers.

These tests cover the branching logic in ``_apply_migrations()``:

- A database with no ``alembic_version`` table is *stamped* at head (not
  upgraded), so the full migration chain is not replayed against a schema
  that ``create_all`` already built correctly.
- A database that already has ``alembic_version`` tracking in place is
  *upgraded*, applying only migrations that have not yet been recorded.
- The Alembic ``Config`` object passed to either command carries the live
  database URL from ``settings`` and a ``script_location`` that resolves
  to the real ``alembic/`` directory on disk.

The ``alembic.command`` calls are mocked so no real migrations run and the
tests do not depend on external files beyond verifying the path exists.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.db.database import _apply_migrations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine():
    """Return a fresh in-memory SQLite engine."""
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _engine_with_alembic_version(version: str = "014_agent_to_publisher"):
    """Return an in-memory engine whose alembic_version table is populated."""
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        conn.execute(
            text("INSERT INTO alembic_version VALUES (:v)"),
            {"v": version},
        )
    return engine


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestApplyMigrations:
    """Branching logic for the three database states _apply_migrations handles."""

    def test_stamps_when_no_alembic_version_table(self):
        """Fresh DB (no alembic_version) is stamped at head, not upgraded."""
        fresh = _make_engine()

        with (
            patch("src.db.database.engine", fresh),
            patch("alembic.command.stamp") as mock_stamp,
            patch("alembic.command.upgrade") as mock_upgrade,
        ):
            _apply_migrations()

        mock_stamp.assert_called_once()
        assert mock_stamp.call_args[0][1] == "head"
        mock_upgrade.assert_not_called()

    def test_upgrades_when_alembic_version_present(self):
        """DB with existing alembic_version tracking is upgraded, not stamped."""
        versioned = _engine_with_alembic_version()

        with (
            patch("src.db.database.engine", versioned),
            patch("alembic.command.stamp") as mock_stamp,
            patch("alembic.command.upgrade") as mock_upgrade,
        ):
            _apply_migrations()

        mock_upgrade.assert_called_once()
        assert mock_upgrade.call_args[0][1] == "head"
        mock_stamp.assert_not_called()

    def test_config_carries_live_database_url(self):
        """The Config passed to stamp/upgrade uses the live settings URL."""
        from src.config import settings

        captured: list = []

        with (
            patch("src.db.database.engine", _make_engine()),
            patch("alembic.command.stamp", side_effect=lambda cfg, rev: captured.append(cfg)),
            patch("alembic.command.upgrade"),
        ):
            _apply_migrations()

        assert captured, "command.stamp was not called"
        assert captured[0].get_main_option("sqlalchemy.url") == settings.database_url

    def test_config_script_location_resolves_to_alembic_dir(self):
        """The script_location in the Config points to the real alembic/ directory."""
        captured: list = []

        with (
            patch("src.db.database.engine", _make_engine()),
            patch("alembic.command.stamp", side_effect=lambda cfg, rev: captured.append(cfg)),
            patch("alembic.command.upgrade"),
        ):
            _apply_migrations()

        assert captured, "command.stamp was not called"
        script_location = captured[0].get_main_option("script_location")

        assert os.path.isdir(script_location), (
            f"script_location {script_location!r} is not a directory; "
            "alembic/ may not be on the Python path or the relative path "
            "calculation in _apply_migrations() is wrong"
        )
        assert os.path.basename(os.path.normpath(script_location)) == "alembic", (
            f"Expected script_location to end in 'alembic', got {script_location!r}"
        )
