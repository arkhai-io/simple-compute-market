"""Reconciliation of a definition document follows a change to that document.

A process restart is not a change, and re-applying a document nobody submitted
reverts whatever else changed the database. The service's importer records each
document kind's last reconciled digest; these tests pin that record against the
service's migrated schema.

External boundary: SQLAlchemy against in-memory SQLite. The database is
deterministic and does no network I/O, so the real engine is used rather than a
mock.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.models import DefinitionDocumentImport
from compute_provisioning_service.services.definition_documents import (
    DefinitionDocumentImporter,
)

# A development-only Fernet key. Generated for this fixture, never used on any
# network, and safe to read here precisely because it protects nothing.
_KEY = Fernet.generate_key().decode()


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def settings():
    return SimpleNamespace(ssh_decryption_key=_KEY, relay_token="bootstrap-token")


class TestTheDigestGate:
    """Reconciliation follows a change to a document, not a process start.

    Import is idempotent with respect to the document, not the database.
    Applying it on every startup reverts whatever else changed the database,
    silently, on eviction, drain, and crash recovery.
    """

    def _importer(self, session_factory, settings):
        return DefinitionDocumentImporter(
            session_factory=session_factory,
            settings=settings,
            pool_service=None,
        )

    def test_nothing_is_recorded_before_a_first_import(self, session_factory):
        with session_factory() as db:
            assert db.get(DefinitionDocumentImport, "relays") is None

    def test_a_changed_document_produces_a_different_digest(
        self, session_factory, settings
    ):
        importer = self._importer(session_factory, settings)
        assert importer.digest_of("relays: []\n") != importer.digest_of("relays: [1]\n")

    def test_a_digest_is_written_and_read_back(self, session_factory, settings):
        importer = self._importer(session_factory, settings)
        digest = importer.digest_of("relays: []\n")
        with session_factory() as db, db.begin():
            importer._record_digest(db, "relays", digest)
        with session_factory() as db:
            assert importer._recorded_digest(db, "relays") == digest

    def test_recording_twice_updates_rather_than_duplicating(
        self, session_factory, settings
    ):
        importer = self._importer(session_factory, settings)
        with session_factory() as db, db.begin():
            importer._record_digest(db, "pools", importer.digest_of("a"))
        with session_factory() as db, db.begin():
            importer._record_digest(db, "pools", importer.digest_of("b"))
        with session_factory() as db:
            assert importer._recorded_digest(db, "pools") == importer.digest_of("b")
            assert db.query(DefinitionDocumentImport).count() == 1

    def test_pools_and_relays_are_tracked_separately(self, session_factory, settings):
        importer = self._importer(session_factory, settings)
        with session_factory() as db, db.begin():
            importer._record_digest(db, "pools", importer.digest_of("pool-doc"))
        with session_factory() as db:
            assert importer._recorded_digest(db, "relays") is None
            assert importer._recorded_digest(db, "pools") is not None
