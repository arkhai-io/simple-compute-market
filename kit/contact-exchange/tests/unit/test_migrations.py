"""Durable, idempotent introduction persistence."""

from __future__ import annotations

import sqlite3

import pytest
from market_contact_exchange import (
    CONTACT_EXCHANGE_MIGRATIONS,
    IntroductionRecord,
    delete_introduction,
    insert_introduction,
    load_introduction,
)

_RECORD = IntroductionRecord(
    obligation_ref="ab" * 32,
    agreement_ref="neg-1",
    buyer_contact={"email": "buyer@example.com"},
    seller_contact={"telegram": "@capacity_broker"},
    introduction_package={"channel": "telegram", "terms": "Net-30 prose."},
)


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(tmp_path / "introductions.db"))
    for migration in CONTACT_EXCHANGE_MIGRATIONS:
        migration.apply(connection)
    return connection


def test_round_trip_survives_a_reconnect(conn, tmp_path) -> None:
    insert_introduction(conn, _RECORD)
    conn.commit()
    conn.close()
    reopened = sqlite3.connect(str(tmp_path / "introductions.db"))
    for migration in CONTACT_EXCHANGE_MIGRATIONS:
        migration.apply(reopened)
    assert load_introduction(reopened, _RECORD.obligation_ref) == _RECORD


def test_identical_reinsert_is_idempotent(conn) -> None:
    insert_introduction(conn, _RECORD)
    assert insert_introduction(conn, _RECORD) == _RECORD


def test_conflicting_reinsert_is_rejected(conn) -> None:
    insert_introduction(conn, _RECORD)
    changed = _RECORD.model_copy(
        update={"buyer_contact": {"email": "other@example.com"}}
    )
    with pytest.raises(ValueError, match="different contact payloads"):
        insert_introduction(conn, changed)


def test_deletion_is_part_of_the_deal_lifecycle(conn) -> None:
    insert_introduction(conn, _RECORD)
    assert delete_introduction(conn, _RECORD.obligation_ref) is True
    assert load_introduction(conn, _RECORD.obligation_ref) is None
    assert delete_introduction(conn, _RECORD.obligation_ref) is False
