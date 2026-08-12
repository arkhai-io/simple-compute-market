"""Unit tests for database initialisation helpers.

Fresh databases are built at current metadata and stamped at head. Versioned
databases upgrade normally. Recognized unversioned schemas are stamped at their
actual boundary and upgraded, so legacy owner data is never mislabeled as head.
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.database import _apply_migrations
from src.db.models import Base, Publisher, PublisherIdentity


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

    def test_unversioned_principal_schema_is_upgraded_from_detected_boundary(self):
        legacy = _make_engine()
        with legacy.begin() as connection:
            connection.execute(text("CREATE TABLE publishers (publisher_id INTEGER)"))
            connection.execute(
                text(
                    "CREATE TABLE identities (id INTEGER, publisher_id INTEGER, "
                    "scheme VARCHAR, identifier VARCHAR)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE listings (listing_id VARCHAR, publisher_id INTEGER, "
                    "settlement_options JSON)"
                )
            )

        with (
            patch("src.db.database.engine", legacy),
            patch("alembic.command.stamp") as mock_stamp,
            patch("alembic.command.upgrade") as mock_upgrade,
        ):
            _apply_migrations()

        assert mock_stamp.call_args[0][1] == "015_listing_settlement_options"
        assert mock_upgrade.call_args[0][1] == "head"

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


def test_sqlite_rejects_a_second_primary_identity_for_one_publisher():
    engine = _make_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
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
    session.rollback()
