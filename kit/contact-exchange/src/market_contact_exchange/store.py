"""The introduction table, persisted for a storefront that keeps it in SQLite.

The table and its row functions belong to this kit, so the asynchronous access
a storefront needs over them does too: each operation opens its own
connection on a worker thread, runs one row function, and commits, so no
composing storefront carries a copy of the same four wrappers.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from .introduction_routes import IntroductionRecord
from .migrations import (
    delete_introduction_payloads,
    insert_introduction,
    load_introduction,
    select_expired_introductions,
)

_T = TypeVar("_T")


class SQLiteIntroductionStore:
    """Asynchronous access to the introduction table in one SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def _run(self, operation: Callable[[sqlite3.Connection], _T], *, commit: bool) -> _T:
        conn = sqlite3.connect(self._db_path)
        try:
            result = operation(conn)
            if commit:
                conn.commit()
            return result
        finally:
            conn.close()

    async def insert(self, record: IntroductionRecord) -> IntroductionRecord:
        """Persist one revealed introduction exactly once (idempotent replays)."""

        return await asyncio.to_thread(
            self._run, lambda conn: insert_introduction(conn, record), commit=True
        )

    async def load(self, obligation_ref: str) -> IntroductionRecord | None:
        return await asyncio.to_thread(
            self._run, lambda conn: load_introduction(conn, obligation_ref), commit=False
        )

    async def delete_payloads(self, obligation_ref: str, deleted_at: datetime) -> bool:
        """Redact one introduction's contact payloads; ``False`` if nothing to redact."""

        return await asyncio.to_thread(
            self._run,
            lambda conn: delete_introduction_payloads(
                conn, obligation_ref, deleted_at=deleted_at
            ),
            commit=True,
        )

    async def select_expired(self, cutoff: datetime, limit: int) -> list[str]:
        """Obligation refs of unredacted introductions revealed at or before ``cutoff``."""

        return await asyncio.to_thread(
            self._run,
            lambda conn: select_expired_introductions(conn, cutoff=cutoff, limit=limit),
            commit=False,
        )


__all__ = ["SQLiteIntroductionStore"]
