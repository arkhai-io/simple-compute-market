"""Phase 3 — scheme-tagged storage tests for the registry.

Covers:
  * The Alembic 012 migration (apply against a snapshot of pre-migration
    data and verify backfill + collision handling).
  * ``find_agent_by_identity`` (the new scheme-tagged lookup).
  * ``ensure_agent_for_eip191`` (lazy-create on first signed publication).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.database import Base
from src.db.models import Agent


# ---------------------------------------------------------------------------
# find_agent_by_identity + ensure_agent_for_eip191
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()


def test_find_agent_by_identity_eip191(db_session):
    from src.api.utils import Identity, find_agent_by_identity

    a = Agent(
        scheme="eip191",
        identifier="0xabcd000000000000000000000000000000000001",
        owner="0xABCD000000000000000000000000000000000001",
        chain_id=0,
        registry_address="",
    )
    db_session.add(a)
    db_session.commit()

    found = find_agent_by_identity(
        db_session, Identity(scheme="eip191", identifier="0xabcd000000000000000000000000000000000001"),
    )
    assert found is not None
    assert found.scheme == "eip191"
    assert found.identifier == "0xabcd000000000000000000000000000000000001"


def test_find_agent_by_identity_missing(db_session):
    from src.api.utils import Identity, find_agent_by_identity

    found = find_agent_by_identity(
        db_session, Identity(scheme="eip191", identifier="0xdeadbeef00000000000000000000000000000000"),
    )
    assert found is None


def test_find_agent_by_identity_different_scheme(db_session):
    """Same identifier under a different scheme is a different agent."""
    from src.api.utils import Identity, find_agent_by_identity

    a = Agent(
        scheme="eip191",
        identifier="0xabcd000000000000000000000000000000000001",
        owner="0xabcd000000000000000000000000000000000001",
        chain_id=0,
        registry_address="",
    )
    db_session.add(a)
    db_session.commit()

    found = find_agent_by_identity(
        db_session, Identity(scheme="did-key", identifier="0xabcd000000000000000000000000000000000001"),
    )
    assert found is None


def test_ensure_agent_for_eip191_creates_when_missing(db_session):
    from src.api.utils import ensure_agent_for_eip191

    agent = ensure_agent_for_eip191(db_session, "0xabcd000000000000000000000000000000000001")
    assert agent.scheme == "eip191"
    assert agent.identifier == "0xabcd000000000000000000000000000000000001"
    assert agent.owner == "0xabcd000000000000000000000000000000000001"
    # Placeholder values for the legacy ERC-8004 columns
    assert agent.chain_id == 0
    assert agent.registry_address == ""


def test_ensure_agent_for_eip191_returns_existing(db_session):
    from src.api.utils import ensure_agent_for_eip191

    first = ensure_agent_for_eip191(db_session, "0xabcd000000000000000000000000000000000001")
    second = ensure_agent_for_eip191(db_session, "0xabcd000000000000000000000000000000000001")
    assert first.id == second.id


def test_ux_agents_scheme_identifier_uniqueness(db_session):
    """Two rows can't share (scheme, identifier)."""
    from sqlalchemy.exc import IntegrityError

    db_session.add(Agent(
        scheme="eip191",
        identifier="0xaaaa000000000000000000000000000000000001",
        owner="0xaaaa000000000000000000000000000000000001",
        chain_id=0,
        registry_address="",
    ))
    db_session.commit()

    db_session.add(Agent(
        scheme="eip191",
        identifier="0xaaaa000000000000000000000000000000000001",
        owner="0xaaaa000000000000000000000000000000000001",
        chain_id=0,
        registry_address="",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_null_scheme_identifier_does_not_collide(db_session):
    """Multiple rows with NULL scheme/identifier coexist (NULLs distinct)."""
    db_session.add(Agent(
        agent_id="eip155:1:0x" + "0" * 40 + ":1",
        owner=None,
        chain_id=1,
        identity_registry="0x" + "0" * 40,
        registry_address="0x" + "0" * 40,
        onchain_agent_id=1,
    ))
    db_session.add(Agent(
        agent_id="eip155:1:0x" + "0" * 40 + ":2",
        owner=None,
        chain_id=1,
        identity_registry="0x" + "0" * 40,
        registry_address="0x" + "0" * 40,
        onchain_agent_id=2,
    ))
    db_session.commit()  # should not raise


# ---------------------------------------------------------------------------
# Alembic migration 012 — applied to a snapshot
# ---------------------------------------------------------------------------


@pytest.fixture
def alembic_engine(tmp_path, monkeypatch):
    """Apply migrations through 011, then 012, against a temp SQLite DB.

    The registry's ``alembic/env.py`` reads ``settings.database_url`` (which
    comes from the ``DATABASE_URL`` env var) and overrides whatever is in
    ``alembic.ini``. Monkeypatch the env var so both the migration runner
    and our test queries point at the same temp DB.
    """
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "test_migration.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    # Settings is a module-level singleton; reload so the new env applies.
    import importlib

    import src.config as config_mod

    importlib.reload(config_mod)

    engine = create_engine(db_url, poolclass=StaticPool)

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")

    # Migrate to revision just before 012 so we can prime data.
    command.upgrade(cfg, "011_listing_accepted_escrows")
    return engine, cfg


def _seed_pre_phase3(engine):
    """Insert pre-migration rows that exercise backfill paths."""
    with engine.begin() as conn:
        # Row 1: typical ERC-8004 agent with unique owner — should backfill.
        conn.execute(text(
            "INSERT INTO agents (id, agent_id, chain_id, identity_registry, "
            "onchain_agent_id, registry_address, owner, token_uri, "
            "health_status, created_at, updated_at) VALUES "
            "(1, 'eip155:31337:0xreg:1', 31337, '0xreg', 1, '0xreg', "
            "'0xAAAA000000000000000000000000000000000001', 'http://a/card', "
            "'healthy', :now, :now)"
        ), {"now": "2026-05-27 00:00:00"})

        # Row 2: another unique-owner agent — should backfill.
        conn.execute(text(
            "INSERT INTO agents (id, agent_id, chain_id, identity_registry, "
            "onchain_agent_id, registry_address, owner, token_uri, "
            "health_status, created_at, updated_at) VALUES "
            "(2, 'eip155:31337:0xreg:2', 31337, '0xreg', 2, '0xreg', "
            "'0xBBBB000000000000000000000000000000000001', 'http://b/card', "
            "'healthy', :now, :now)"
        ), {"now": "2026-05-27 00:00:00"})

        # Rows 3 + 4: collision — same lowered owner. Neither should backfill.
        conn.execute(text(
            "INSERT INTO agents (id, agent_id, chain_id, identity_registry, "
            "onchain_agent_id, registry_address, owner, token_uri, "
            "health_status, created_at, updated_at) VALUES "
            "(3, 'eip155:31337:0xreg:3', 31337, '0xreg', 3, '0xreg', "
            "'0xCCCC000000000000000000000000000000000001', 'http://c/card', "
            "'healthy', :now, :now)"
        ), {"now": "2026-05-27 00:00:00"})
        conn.execute(text(
            "INSERT INTO agents (id, agent_id, chain_id, identity_registry, "
            "onchain_agent_id, registry_address, owner, token_uri, "
            "health_status, created_at, updated_at) VALUES "
            "(4, 'eip155:31337:0xreg:4', 31337, '0xreg', 4, '0xreg', "
            "'0xcccc000000000000000000000000000000000001', 'http://d/card', "
            "'healthy', :now, :now)"
        ), {"now": "2026-05-27 00:00:00"})

        # Row 5: owner-less residue — should stay NULL after migration.
        conn.execute(text(
            "INSERT INTO agents (id, agent_id, chain_id, identity_registry, "
            "onchain_agent_id, registry_address, owner, token_uri, "
            "health_status, created_at, updated_at) VALUES "
            "(5, 'eip155:31337:0xreg:5', 31337, '0xreg', 5, '0xreg', "
            "NULL, 'http://e/card', "
            "'healthy', :now, :now)"
        ), {"now": "2026-05-27 00:00:00"})


def test_migration_012_backfills_unique_owners(alembic_engine):
    from alembic import command

    engine, cfg = alembic_engine
    _seed_pre_phase3(engine)

    command.upgrade(cfg, "012_pluggable_identity_scheme")

    with engine.begin() as conn:
        # Row 1: backfilled
        row = conn.execute(text(
            "SELECT scheme, identifier, scheme_metadata FROM agents WHERE id = 1"
        )).fetchone()
        assert row[0] == "eip191"
        assert row[1] == "0xaaaa000000000000000000000000000000000001"
        meta = json.loads(row[2])
        assert meta["agent_id"] == "eip155:31337:0xreg:1"
        assert meta["chain_id"] == 31337
        assert meta["onchain_agent_id"] == 1

        # Row 2: backfilled (independent owner)
        row = conn.execute(text(
            "SELECT scheme, identifier FROM agents WHERE id = 2"
        )).fetchone()
        assert row[0] == "eip191"
        assert row[1] == "0xbbbb000000000000000000000000000000000001"


def test_migration_012_skips_owner_collisions(alembic_engine):
    from alembic import command

    engine, cfg = alembic_engine
    _seed_pre_phase3(engine)

    command.upgrade(cfg, "012_pluggable_identity_scheme")

    with engine.begin() as conn:
        # Rows 3 + 4 share an owner (case-insensitive) — neither is backfilled.
        rows = conn.execute(text(
            "SELECT id, scheme, identifier FROM agents WHERE id IN (3, 4) ORDER BY id"
        )).fetchall()
        assert rows[0][1] is None and rows[0][2] is None
        assert rows[1][1] is None and rows[1][2] is None


def test_migration_012_leaves_owner_less_rows_null(alembic_engine):
    from alembic import command

    engine, cfg = alembic_engine
    _seed_pre_phase3(engine)

    command.upgrade(cfg, "012_pluggable_identity_scheme")

    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT scheme, identifier, scheme_metadata FROM agents WHERE id = 5"
        )).fetchone()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None


def test_migration_012_adds_unique_index(alembic_engine):
    from alembic import command

    engine, cfg = alembic_engine
    command.upgrade(cfg, "012_pluggable_identity_scheme")

    inspector = inspect(engine)
    indexes = inspector.get_indexes("agents")
    names = {idx["name"] for idx in indexes}
    assert "ux_agents_scheme_identifier" in names
    assert "idx_agents_scheme" in names

    # ux_agents_scheme_identifier should be unique. SQLite returns the
    # unique flag as int (0/1) rather than bool, so check truthiness.
    by_name = {idx["name"]: idx for idx in indexes}
    assert by_name["ux_agents_scheme_identifier"]["unique"]


def test_migration_012_downgrade_drops_columns(alembic_engine):
    from alembic import command

    engine, cfg = alembic_engine
    _seed_pre_phase3(engine)
    command.upgrade(cfg, "012_pluggable_identity_scheme")
    command.downgrade(cfg, "011_listing_accepted_escrows")

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("agents")}
    assert "scheme" not in cols
    assert "identifier" not in cols
    assert "scheme_metadata" not in cols
