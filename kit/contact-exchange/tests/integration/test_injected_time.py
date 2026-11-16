"""An introduction's reveal time and its retention follow the process time source.

Library integration: the introduction table over a real SQLite database its
baseline built, with the process source injected, so the reveal time the sweep
compares is the source's and never the database's clock.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import injected_time
import pytest
from injected_time import InjectedTime
from market_contact_exchange import (
    IntroductionRecord,
    IntroductionRetentionPolicy,
    IntroductionRetentionService,
    delete_introduction_payloads,
    format_introduction_timestamp,
    insert_introduction,
    load_introduction,
    select_expired_introductions,
)
from market_contact_exchange.migrations import BASELINE

#: The instant an introduction is revealed at.
REVEALED = 1794821400
#: The retention window, in seconds.
WINDOW = 86400

_REF = "ee" * 32


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process time source, injected at ``REVEALED``; a test sets it forward."""
    before = injected_time.installed()
    installed = InjectedTime(start=REVEALED)
    injected_time.install(installed)
    yield installed
    injected_time.install(before)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "storefront.db")
    conn = sqlite3.connect(path)
    try:
        BASELINE.apply(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path, timeout=5)


def _text(instant: int) -> str:
    """An instant in the table's stored text form."""
    return format_introduction_timestamp(datetime.fromtimestamp(instant, timezone.utc))


def _service(path: str) -> IntroductionRetentionService:
    """The retention service on its default clock, the process source."""

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
        policy=IntroductionRetentionPolicy(window_seconds=WINDOW, sweep_interval_seconds=60),
        select_expired=select_expired,
        delete_payloads=delete_payloads,
        load=load,
    )


async def test_an_introduction_revealed_under_injected_time_expires_by_the_source(
    db_path: str, source: InjectedTime
) -> None:
    conn = _connect(db_path)
    try:
        insert_introduction(
            conn,
            IntroductionRecord(
                obligation_ref=_REF,
                agreement_ref="neg-ee",
                buyer_contact={"email": "buyer@example.com"},
                seller_contact={"telegram": "@capacity_broker"},
                introduction_package={"channel": "telegram"},
            ),
        )
        conn.commit()
        (created_at,) = conn.execute(
            "SELECT created_at FROM contact_introductions WHERE obligation_ref=?",
            (_REF,),
        ).fetchone()
    finally:
        conn.close()
    # The source's instant, not the database's clock.
    assert created_at == _text(REVEALED)

    service = _service(db_path)
    source.set(REVEALED + WINDOW - 1)
    assert await service.sweep_once() == {"loop": "introduction_retention", "deleted": 0}

    source.set(REVEALED + WINDOW)
    assert await service.sweep_once() == {"loop": "introduction_retention", "deleted": 1}
    conn = _connect(db_path)
    try:
        record = load_introduction(conn, _REF)
    finally:
        conn.close()
    assert record is not None
    assert record.payloads_deleted_at == _text(REVEALED + WINDOW)
