"""Reusable stale-negotiation sweep and background lifecycle."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


class NegotiationRepository(Protocol):
    """Persistence surface required by the watchdog mechanism."""

    db_path: str

    async def update_negotiation_thread_terminal(
        self,
        *,
        negotiation_id: str,
        terminal_state: str,
    ) -> None: ...


class LoggerLike(Protocol):
    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class NegotiationWatchdogPolicy:
    """Domain-supplied timing, terminal vocabulary, and logging policy."""

    timeout_seconds: float
    interval_seconds: float
    terminal_state: str = "abandoned"
    initial_delay_seconds: float = 15.0
    log_loop_start: bool = True
    log_cutoff: bool = True

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("negotiation timeout must be greater than zero")
        if self.interval_seconds <= 0:
            raise ValueError("negotiation watchdog interval must be greater than zero")
        if self.initial_delay_seconds < 0:
            raise ValueError("negotiation watchdog initial delay cannot be negative")
        if not self.terminal_state:
            raise ValueError("negotiation watchdog terminal state is required")


def parse_timestamp(raw: str) -> datetime | None:
    """Parse persisted ISO timestamps, treating a missing timezone as UTC."""

    if not raw:
        return None
    text = raw.rstrip("Z")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def stale_negotiations(db_path: str, cutoff: datetime) -> list[dict[str, Any]]:
    """Load active negotiation rows older than ``cutoff`` from SQLite."""

    connection = sqlite3.connect(
        f"file:{db_path}?mode=ro&nolock=1",
        uri=True,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT negotiation_id, our_listing_id, updated_at
               FROM negotiation_threads
               WHERE terminal_state IS NULL""",
        ).fetchall()
    finally:
        connection.close()

    stale: list[dict[str, Any]] = []
    for row in rows:
        updated_at = parse_timestamp(row["updated_at"])
        if updated_at is not None and updated_at < cutoff:
            stale.append(dict(row))
    return stale


async def sweep_stale_negotiations(
    repository: NegotiationRepository,
    policy: NegotiationWatchdogPolicy,
    *,
    emit_stage_event: Callable[..., None] | None = None,
    now: datetime | None = None,
    logger: LoggerLike | None = None,
) -> int:
    """Mark one snapshot of stale active threads with the supplied terminal state."""

    active_logger = logger or logging.getLogger(__name__)
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(seconds=policy.timeout_seconds)
    stale = stale_negotiations(repository.db_path, cutoff)
    for thread in stale:
        negotiation_id = str(thread["negotiation_id"])
        if policy.log_cutoff:
            active_logger.warning(
                "negotiation_watchdog: marking %s as %s "
                "(updated_at=%s, cutoff=%s)",
                negotiation_id,
                policy.terminal_state,
                thread["updated_at"],
                cutoff.isoformat(),
            )
        else:
            active_logger.warning(
                "negotiation_watchdog: marking %s as %s (updated_at=%s)",
                negotiation_id,
                policy.terminal_state,
                thread["updated_at"],
            )
        try:
            await repository.update_negotiation_thread_terminal(
                negotiation_id=negotiation_id,
                terminal_state=policy.terminal_state,
            )
        except Exception as exc:
            active_logger.warning(
                "negotiation_watchdog: failed to terminate thread %s: %s",
                negotiation_id,
                exc,
            )
            continue
        if emit_stage_event is None:
            continue
        try:
            emit_stage_event(
                stage="negotiation",
                event=policy.terminal_state,
                negotiation_id=negotiation_id,
                order_id=thread.get("our_listing_id"),
                reason="watchdog_timeout",
                updated_at=thread.get("updated_at"),
            )
        except Exception as exc:
            active_logger.debug(
                "stage_event emit failed for %s: %s",
                negotiation_id,
                exc,
            )
    return len(stale)


async def run_negotiation_watchdog(
    repository: NegotiationRepository,
    policy: NegotiationWatchdogPolicy,
    *,
    emit_stage_event: Callable[..., None] | None = None,
    logger: LoggerLike | None = None,
) -> None:
    """Continuously run the shared sweep until the task is cancelled."""

    active_logger = logger or logging.getLogger(__name__)
    await asyncio.sleep(policy.initial_delay_seconds)
    if policy.log_loop_start:
        active_logger.info(
            "negotiation_watchdog_loop: started (interval=%ds, timeout=%ds)",
            policy.interval_seconds,
            policy.timeout_seconds,
        )
    while True:
        try:
            await asyncio.sleep(policy.interval_seconds)
            abandoned = await sweep_stale_negotiations(
                repository,
                policy,
                emit_stage_event=emit_stage_event,
                logger=active_logger,
            )
            if abandoned:
                active_logger.info(
                    "negotiation_watchdog_loop: marked %d stale thread(s) as %s",
                    abandoned,
                    policy.terminal_state,
                )
        except asyncio.CancelledError:
            active_logger.info("negotiation_watchdog_loop: cancelled, shutting down")
            break
        except Exception as exc:
            active_logger.exception("negotiation_watchdog_loop error: %s", exc)
