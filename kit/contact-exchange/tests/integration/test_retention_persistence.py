"""Retention against a real SQLite database: the triggers, atomic redaction,
the window applied as current policy, and convergence after a failed sweep."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from market_contact_exchange import (
    CONTACT_EXCHANGE_MIGRATIONS,
    IntroductionRecord,
    IntroductionRetentionPolicy,
    IntroductionRetentionService,
    delete_introduction_payloads,
    format_introduction_timestamp,
    insert_introduction,
    load_introduction,
    select_expired_introductions,
)

_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

DeletePayloads = Callable[[str, datetime], Awaitable[bool]]


def _record(ref: str) -> IntroductionRecord:
    return IntroductionRecord(
        obligation_ref=ref,
        agreement_ref=f"neg-{ref[:4]}",
        buyer_contact={"email": "buyer@example.com"},
        seller_contact={"telegram": "@capacity_broker"},
        introduction_package={"channel": "telegram", "terms": "Net-30 prose."},
    )


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "storefront.db")
    conn = sqlite3.connect(path)
    try:
        for migration in CONTACT_EXCHANGE_MIGRATIONS:
            migration.apply(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path, timeout=5)


def _backdate(path: str, ref: str, revealed_at: datetime) -> None:
    """Give one unredacted row an older reveal time.

    The triggers refuse any change to ``created_at``, as they should. A fixture
    needing an older reveal therefore goes through the database owner's escape
    hatch, dropping and restoring the triggers around the change, exactly as an
    operator repairing data would; production code has no such path.
    """

    conn = _connect(path)
    try:
        triggers = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='contact_introductions'"
        ).fetchall()
        conn.execute("DROP TRIGGER contact_introductions_redaction_only")
        conn.execute("DROP TRIGGER contact_introductions_keep_unredacted")
        conn.execute(
            "UPDATE contact_introductions SET created_at=? WHERE obligation_ref=?",
            (format_introduction_timestamp(revealed_at), ref),
        )
        for (sql,) in triggers:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def _service(
    path: str,
    window: int,
    *,
    wrap_delete: Callable[[DeletePayloads], DeletePayloads] | None = None,
) -> IntroductionRetentionService:
    async def select_expired(cutoff: datetime, limit: int) -> list[str]:
        def run() -> list[str]:
            conn = _connect(path)
            try:
                return select_expired_introductions(conn, cutoff=cutoff, limit=limit)
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def delete_payloads(ref: str, deleted_at: datetime) -> bool:
        def run() -> bool:
            conn = _connect(path)
            try:
                redacted = delete_introduction_payloads(conn, ref, deleted_at=deleted_at)
                conn.commit()
                return redacted
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def load(ref: str) -> IntroductionRecord | None:
        def run() -> IntroductionRecord | None:
            conn = _connect(path)
            try:
                return load_introduction(conn, ref)
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    return IntroductionRetentionService(
        policy=IntroductionRetentionPolicy(window_seconds=window, sweep_interval_seconds=60),
        select_expired=select_expired,
        delete_payloads=wrap_delete(delete_payloads) if wrap_delete else delete_payloads,
        load=load,
        clock=lambda: _NOW,
    )


def test_the_triggers_refuse_restoring_rewriting_or_removing(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        insert_introduction(conn, _record("aa" * 32))
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="cannot be removed"):
            conn.execute(
                "DELETE FROM contact_introductions WHERE obligation_ref=?",
                ("aa" * 32,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="one-way payload redaction"):
            conn.execute(
                "UPDATE contact_introductions SET buyer_contact='{}' "
                "WHERE obligation_ref=?",
                ("aa" * 32,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="one-way payload redaction"):
            # A redaction that also rewrites the agreed context is refused.
            conn.execute(
                "UPDATE contact_introductions SET payloads_deleted_at='x', "
                "buyer_contact='{}', seller_contact='{}', introduction_package='{}' "
                "WHERE obligation_ref=?",
                ("aa" * 32,),
            )
        assert delete_introduction_payloads(conn, "aa" * 32, deleted_at=_NOW)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="one-way payload redaction"):
            conn.execute(
                "UPDATE contact_introductions SET payloads_deleted_at=NULL, "
                "buyer_contact='{\"email\": \"buyer@example.com\"}' "
                "WHERE obligation_ref=?",
                ("aa" * 32,),
            )
        # A tombstone may be removed; bounding their growth depends on it.
        conn.execute(
            "DELETE FROM contact_introductions WHERE obligation_ref=?", ("aa" * 32,)
        )
        conn.commit()
        assert load_introduction(conn, "aa" * 32) is None
    finally:
        conn.close()


def test_a_reader_interleaved_with_redaction_sees_whole_or_tombstone(
    db_path: str,
) -> None:
    writer = _connect(db_path)
    reader = _connect(db_path)
    try:
        insert_introduction(writer, _record("bb" * 32))
        writer.commit()
        # The redaction is applied but not committed: the independent reader
        # sees the complete introduction.
        assert delete_introduction_payloads(writer, "bb" * 32, deleted_at=_NOW)
        before = load_introduction(reader, "bb" * 32)
        assert before == _record("bb" * 32)
        writer.commit()
        after = load_introduction(reader, "bb" * 32)
        assert after is not None
        assert after.payloads_deleted_at == "2026-10-01T12:00:00Z"
        assert after.buyer_contact == {} and after.seller_contact == {}
    finally:
        writer.close()
        reader.close()


async def test_a_shortened_window_applies_to_introductions_revealed_before_it(
    db_path: str,
) -> None:
    conn = _connect(db_path)
    try:
        insert_introduction(conn, _record("cc" * 32))
        conn.commit()
    finally:
        conn.close()
    _backdate(db_path, "cc" * 32, _NOW - timedelta(days=2))
    # Revealed under a 30-day window, which nothing recorded on the row.
    assert await _service(db_path, 30 * 86400).sweep_once() == {
        "loop": "introduction_retention",
        "deleted": 0,
    }
    # The storefront restarts with a one-day window: the next sweep deletes it.
    assert await _service(db_path, 86400).sweep_once() == {
        "loop": "introduction_retention",
        "deleted": 1,
    }


async def test_a_sweep_failing_part_way_converges_on_retry(db_path: str) -> None:
    refs = ["d1" * 32, "d2" * 32, "d3" * 32]
    conn = _connect(db_path)
    try:
        for ref in refs:
            insert_introduction(conn, _record(ref))
        conn.commit()
    finally:
        conn.close()
    for offset, ref in enumerate(refs):
        _backdate(db_path, ref, _NOW - timedelta(days=10 - offset))
    # The second redaction fails as a locked database would.
    calls: list[str] = []

    def fail_second(delete: DeletePayloads) -> DeletePayloads:
        async def wrapped(ref: str, deleted_at: datetime) -> bool:
            calls.append(ref)
            if len(calls) == 2:
                raise sqlite3.OperationalError("database is locked")
            return await delete(ref, deleted_at)

        return wrapped

    service = _service(db_path, 86400, wrap_delete=fail_second)
    with pytest.raises(sqlite3.OperationalError):
        await service.sweep_once()
    assert [ref for ref in refs if _is_redacted(db_path, ref)] == [refs[0]]
    retry = _service(db_path, 86400)
    assert await retry.sweep_once() == {"loop": "introduction_retention", "deleted": 2}
    assert all(_is_redacted(db_path, ref) for ref in refs)


def _is_redacted(path: str, ref: str) -> bool:
    conn = _connect(path)
    try:
        record = load_introduction(conn, ref)
        return record is not None and record.payloads_deleted_at is not None
    finally:
        conn.close()
