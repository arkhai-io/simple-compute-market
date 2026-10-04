"""Durable, idempotent introduction persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from market_contact_exchange import (
    CONTACT_EXCHANGE_MIGRATIONS,
    IntroductionPayloadsDeletedError,
    IntroductionRecord,
    delete_introduction_payloads,
    format_introduction_timestamp,
    insert_introduction,
    load_introduction,
    select_expired_introductions,
)

_DELETED_AT = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

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


def test_redaction_keeps_a_tombstone_with_the_agreed_context(conn) -> None:
    insert_introduction(conn, _RECORD)
    assert (
        delete_introduction_payloads(
            conn, _RECORD.obligation_ref, deleted_at=_DELETED_AT
        )
        is True
    )
    redacted = load_introduction(conn, _RECORD.obligation_ref)
    assert redacted is not None
    assert redacted.payloads_deleted_at == "2026-10-01T12:00:00Z"
    assert redacted.buyer_contact == {}
    assert redacted.seller_contact == {}
    assert redacted.introduction_package == _RECORD.introduction_package
    assert redacted.agreement_ref == _RECORD.agreement_ref


def test_repeat_redaction_converges_and_keeps_the_first_time(conn) -> None:
    insert_introduction(conn, _RECORD)
    delete_introduction_payloads(conn, _RECORD.obligation_ref, deleted_at=_DELETED_AT)
    later = _DELETED_AT + timedelta(days=1)
    assert (
        delete_introduction_payloads(conn, _RECORD.obligation_ref, deleted_at=later)
        is False
    )
    record = load_introduction(conn, _RECORD.obligation_ref)
    assert record is not None
    assert record.payloads_deleted_at == "2026-10-01T12:00:00Z"


def test_redacting_a_never_started_introduction_converges(conn) -> None:
    assert (
        delete_introduction_payloads(conn, "cd" * 32, deleted_at=_DELETED_AT)
        is False
    )
    assert load_introduction(conn, "cd" * 32) is None


def test_a_redacted_introduction_is_never_persisted_over(conn) -> None:
    insert_introduction(conn, _RECORD)
    delete_introduction_payloads(conn, _RECORD.obligation_ref, deleted_at=_DELETED_AT)
    with pytest.raises(IntroductionPayloadsDeletedError) as raised:
        insert_introduction(conn, _RECORD)
    assert raised.value.payloads_deleted_at == "2026-10-01T12:00:00Z"
    # Distinct from the different-payload refusal, though both are ValueErrors.
    assert "different contact payloads" not in str(raised.value)


def _insert_revealed_at(conn: sqlite3.Connection, ref: str, created_at: str) -> None:
    # Fixture rows state their reveal time; insertion is unrestricted, and
    # created_at is otherwise set by SQLite at the moment of insert.
    conn.execute(
        "INSERT INTO contact_introductions (obligation_ref, agreement_ref, "
        "buyer_contact, seller_contact, introduction_package, created_at) "
        "VALUES (?, 'neg', '{\"email\": \"b@example.com\"}', "
        "'{\"telegram\": \"@s\"}', '{}', ?)",
        (ref, created_at),
    )


def test_expired_selection_is_inclusive_of_the_cutoff_and_skips_tombstones(
    conn,
) -> None:
    _insert_revealed_at(conn, "00" * 32, "2026-09-01T00:00:00Z")
    _insert_revealed_at(conn, "01" * 32, "2026-09-02T00:00:00Z")
    _insert_revealed_at(conn, "02" * 32, "2026-09-02T00:00:01Z")
    cutoff = datetime(2026, 9, 2, tzinfo=timezone.utc)
    assert select_expired_introductions(conn, cutoff=cutoff, limit=10) == [
        "00" * 32,
        "01" * 32,
    ]
    assert select_expired_introductions(conn, cutoff=cutoff, limit=1) == ["00" * 32]
    delete_introduction_payloads(conn, "00" * 32, deleted_at=_DELETED_AT)
    assert select_expired_introductions(conn, cutoff=cutoff, limit=10) == ["01" * 32]


def test_expired_selection_requires_a_positive_limit(conn) -> None:
    with pytest.raises(ValueError, match="positive limit"):
        select_expired_introductions(conn, cutoff=_DELETED_AT, limit=0)


def test_timestamps_render_in_the_column_text_form() -> None:
    assert (
        format_introduction_timestamp(
            datetime(2026, 10, 1, 14, 30, 5, 999999, tzinfo=timezone(timedelta(hours=2)))
        )
        == "2026-10-01T12:30:05Z"
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        format_introduction_timestamp(datetime(2026, 10, 1))
