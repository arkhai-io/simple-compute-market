"""Recovery and unique recipient claims for explicit contact delivery intents."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from .delivery_state import recover
from .migrations import load_introduction

logger = logging.getLogger(__name__)


class ContactDeliveryWorker:
    def __init__(
        self,
        *,
        transaction: Any,
        prepare: Any,
        complete: Any,
        send: Callable[..., Awaitable[tuple[str, str | None]]],
        wall_clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transaction = transaction
        self.prepare = prepare
        self.complete = complete
        self.send = send
        self.wall_clock = wall_clock
        self.monotonic = monotonic
        self._sends: set[asyncio.Task[Any]] = set()

    async def recover(self) -> None:
        await self.transaction(lambda conn: recover(conn, int(self.wall_clock())))

    async def tick(self) -> None:
        await self.recover()
        rows = await self.transaction(
            lambda conn: conn.execute(
                "SELECT DISTINCT i.obligation_ref,f.agreement_ref FROM contact_delivery_intents i JOIN contact_finalizations f ON f.obligation_ref=i.obligation_ref AND f.status='committed' WHERE i.status='awaiting_completion'"
            ).fetchall()
        )
        for ref, agreement_ref in rows:
            try:
                agreement = await self.prepare(agreement_ref, ref)
                await self.complete(agreement)
            except Exception:
                continue
            await self.transaction(
                lambda conn: conn.execute(
                    "UPDATE contact_delivery_intents SET status='pending' WHERE obligation_ref=? AND status='awaiting_completion'",
                    (ref,),
                )
            )
        while len(self._sends) < 2:
            started = self.monotonic()
            claim = await self.transaction(self._claim)
            if claim is None:
                break
            task = asyncio.create_task(self._send(claim, started + 120))
            self._sends.add(task)
            task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[Any]) -> None:
        self._sends.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.warning(
                "contact attempt persistence unavailable (%s)", type(error).__name__
            )

    def _claim(self, conn: Any) -> dict[str, Any] | None:
        now = int(self.wall_clock())
        cursor = conn.execute(
            "SELECT * FROM contact_delivery_intents WHERE status='pending' OR (status='retry_wait' AND next_attempt_at<=?) ORDER BY intent_id LIMIT 1",
            (now,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        claim = dict(zip((c[0] for c in cursor.description), row))
        claim["attempt_id"] = str(uuid.uuid4())
        claim["attempts"] += 1
        conn.execute(
            "UPDATE contact_delivery_intents SET status='sending',attempts=?,attempt_id=?,claim_expires_at=?,next_attempt_at=NULL,failure_code=NULL WHERE intent_id=?",
            (claim["attempts"], claim["attempt_id"], now + 150, claim["intent_id"]),
        )
        conn.execute(
            "INSERT INTO contact_delivery_attempts (attempt_id,intent_id,started_at,status) VALUES (?,?,?,'sending')",
            (claim["attempt_id"], claim["intent_id"], now),
        )
        claim["record"] = load_introduction(conn, claim["obligation_ref"])
        return claim

    async def _send(self, claim: dict[str, Any], deadline: float) -> None:
        result: tuple[str, str | None]
        try:
            if claim["record"] is None or claim["route"] is None:
                result = ("failed", "configuration_unavailable")
            elif self.monotonic() >= deadline:
                result = ("needs_review", "attempt_abandoned")
            else:
                result = await self.send(
                    claim["record"],
                    claim["recipient_role"],
                    json.loads(claim["route"]),
                    claim["intent_id"],
                    claim["attempt_id"],
                    deadline,
                )
        except Exception:
            result = ("needs_review", "acceptance_unknown")
        status, code = result
        if status == "retry_wait" and claim["attempts"] >= 3:
            status = "failed"
        next_at = (
            int(self.wall_clock()) + (60 if claim["attempts"] == 1 else 300)
            if status == "retry_wait"
            else None
        )

        def finish(conn: Any) -> None:
            changed = conn.execute(
                "UPDATE contact_delivery_intents SET status=?,failure_code=?,next_attempt_at=?,route=CASE WHEN ? IN ('accepted','failed','needs_review') THEN NULL ELSE route END WHERE intent_id=? AND attempt_id=? AND status='sending'",
                (
                    status,
                    code,
                    next_at,
                    status,
                    claim["intent_id"],
                    claim["attempt_id"],
                ),
            ).rowcount
            if changed:
                conn.execute(
                    "UPDATE contact_delivery_attempts SET status=?,failure_code=?,finished_at=? WHERE attempt_id=? AND status='sending'",
                    (status, code, int(self.wall_clock()), claim["attempt_id"]),
                )

        await self.transaction(finish)

    async def _recover_loop(self) -> None:
        while True:
            try:
                await self.recover()
            except Exception as exc:
                logger.warning("contact recovery unavailable (%s)", type(exc).__name__)
            await asyncio.sleep(5)

    async def run(self) -> None:
        recovery = asyncio.create_task(self._recover_loop())
        try:
            while True:
                try:
                    await self.tick()
                except Exception as exc:
                    logger.warning(
                        "contact recovery unavailable (%s)", type(exc).__name__
                    )
                await asyncio.sleep(5)
        finally:
            recovery.cancel()
            await asyncio.gather(recovery, return_exceptions=True)
            # Socket-owning senders enforce their deadlines even during shutdown.
            if self._sends:
                await asyncio.gather(*self._sends, return_exceptions=True)
