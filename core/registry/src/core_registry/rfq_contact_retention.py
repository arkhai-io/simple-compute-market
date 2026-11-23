"""Startup and periodic retention for registry RFQ contacts."""

import asyncio
import logging
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from core_registry.db.models import utcnow
from core_registry.rfq_contact_crypto import RfqContactKeys
from core_registry.rfq_contact_store import (
    redact_restored_contacts,
    require_retained_keys,
    sweep_contact_batch,
)

logger = logging.getLogger(__name__)
_SWEEP_INTERVAL_SECONDS = 300
_OVERDUE_LIMIT_SECONDS = 3600


def sweep_expired_contacts(sessions: sessionmaker[Session]) -> None:
    removed = 0
    oldest_overdue = 0.0
    while True:
        with sessions.begin() as db:
            result = sweep_contact_batch(db, utcnow())
        if not result.removed:
            break
        removed += result.removed
        oldest_overdue = max(oldest_overdue, result.oldest_overdue_seconds)
    if removed:
        logger.info(
            "rfq_contact_retention removed=%d oldest_overdue_seconds=%.0f",
            removed, oldest_overdue,
        )
    if oldest_overdue > _OVERDUE_LIMIT_SECONDS:
        logger.warning("rfq_contact_retention exceeded the healthy cleanup window")


def prepare_rfq_contact_access(
    sessions: sessionmaker[Session],
    *,
    key_file: str | Path | None,
    redact_restore: bool,
) -> RfqContactKeys | None:
    if redact_restore:
        with sessions.begin() as db:
            removed = redact_restored_contacts(db, utcnow())
        logger.info("rfq_contact_restore redacted_payloads=%d", removed)
        return None
    sweep_expired_contacts(sessions)
    if key_file is None:
        return None
    keys = RfqContactKeys.load(str(key_file))
    with sessions() as db:
        require_retained_keys(db, keys)
    return keys


class RfqContactRetention:
    """Serialize timer-driven and manually advanced retention cycles."""

    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions
        self._wake = asyncio.Event()
        self._work = asyncio.Lock()
        self._paused = False
        self._stopping = False

    async def pause(self) -> None:
        self._paused = True
        self._wake.set()
        async with self._work:
            pass

    def resume(self) -> None:
        self._paused = False
        self._wake.set()

    async def step(self) -> None:
        await self._cycle(manual=True)

    async def _cycle(self, *, manual: bool = False) -> None:
        async with self._work:
            if manual or not self._paused:
                await asyncio.to_thread(sweep_expired_contacts, self._sessions)

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    async def run(self) -> None:
        while not self._stopping:
            interval = None if self._paused else _SWEEP_INTERVAL_SECONDS
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            except TimeoutError:
                try:
                    await self._cycle()
                except Exception:
                    logger.exception("rfq_contact_retention failed; cleanup will retry")
            else:
                self._wake.clear()
