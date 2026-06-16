"""Deal-servicing engine mechanics: persisted claims driven to terminal.

The seller half of the settlement lifecycle engine
(``docs/development/ARCHITECTURE.md``, "Settlement Lifecycle"). A
claim is the claimant-side servicing record for one settlement-plan
obligation: once the deal is fulfilled, someone must check the
obligation's conditions, collect when they pass, retry when they
don't yet, and give up cleanly when the window closes. That someone
is this engine — fulfillment submits a claim and nothing else.

Core owns the mechanics only: the claim state machine, the
retry/backoff scheduler, and the event hook points. The engine drives
injected per-mechanism hooks (``check_conditions`` / ``collect``) and
never learns which settlement mechanism it is driving — the same
altitude as ``negotiation_sync``/``stage_log``. The alkahest hooks live
in the VM domain over ``kit/alkahest``; a fiat mechanism plugs in the
same way.

States::

    awaiting_conditions ──ready──▶ collectable ──collect ok──▶ collected
            │  ▲                        │  ▲
            │  └──── backoff ◀──────────┘  │ (collect raised / pending)
            │
            └──(conditions failed, or expiration + grace passed)──▶ abandoned

The degenerate case is current behavior: a RecipientArbiter-only deal's
conditions are immediately ready and servicing collapses to a single
collect.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from typing import Any, Awaitable, Callable, Literal, Mapping, Protocol, runtime_checkable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ClaimState = Literal["awaiting_conditions", "collectable", "collected", "abandoned"]
ConditionStatus = Literal["pending", "ready", "failed"]

TERMINAL_STATES: frozenset[str] = frozenset({"collected", "abandoned"})


class ClaimRecord(BaseModel):
    """One persisted claim: an obligation the local party must drive to
    collection.

    ``obligation`` is the settlement-plan obligation dict (the
    ``{mechanism, params}`` envelope from ``market_core``); the engine
    reads only ``mechanism`` and ``expiration_unix`` from it.
    ``mechanism_state`` is hook-owned scratch space persisted across
    sweeps (e.g. "arbitration already requested"); core never
    interprets it.
    """

    claim_ref: str = Field(description="Unique claim id (e.g. the escrow uid).")
    deal_ref: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque deal context (negotiation id, listing id, …).",
    )
    obligation: dict[str, Any] = Field(
        default_factory=dict,
        description="Settlement-plan obligation envelope being claimed.",
    )
    fulfillment_ref: str | None = Field(
        default=None,
        description="Mechanism-scoped fulfillment handle (e.g. fulfillment uid).",
    )
    state: str = "awaiting_conditions"
    attempts: int = 0
    next_attempt_unix: float | None = None
    mechanism_state: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None
    result: dict[str, Any] | None = None


@runtime_checkable
class ClaimStore(Protocol):
    """Persistence the composition root supplies (e.g. a SQLite table)."""

    async def due_claims(self, now_unix: float, limit: int = 50) -> list[dict[str, Any]]:
        """Non-terminal claims whose ``next_attempt_unix`` is null or due."""
        ...

    async def upsert_claim(self, claim: dict[str, Any]) -> None:
        """Insert the claim if new; no-op on existing claim_ref."""
        ...

    async def save_claim(self, claim: dict[str, Any]) -> None:
        """Persist the full updated claim row."""
        ...


@runtime_checkable
class MechanismHooks(Protocol):
    """Per-mechanism servicing operations, supplied from below.

    ``check_conditions`` may mutate ``claim.mechanism_state`` (persisted
    by the engine after every step) and returns whether the obligation's
    condition set currently passes. ``collect`` performs the actual
    collection; raising means "retry later", returning means collected.
    Both receive the full record — mechanism params live in
    ``claim.obligation["params"]``.
    """

    async def check_conditions(self, claim: ClaimRecord) -> ConditionStatus: ...

    async def collect(self, claim: ClaimRecord) -> dict[str, Any] | None: ...


EventHook = Callable[..., Any]


class ClaimsEngine:
    """Sweeps due claims and drives each through its mechanism hooks.

    Restartable by construction: all state lives in the store, a sweep
    loads only due claims, and every transition is persisted before the
    next step runs. Run it with ``asyncio.create_task(engine.run())``
    (the lease-watchdog embedding pattern) or call ``tick()`` from a
    test/CLI.
    """

    def __init__(
        self,
        store: ClaimStore,
        hooks: Mapping[str, MechanismHooks],
        *,
        on_event: EventHook | None = None,
        base_backoff_seconds: float = 30.0,
        max_backoff_seconds: float = 1800.0,
        expiration_grace_seconds: float = 86_400.0,
        clock: Callable[[], float] = _time.time,
    ) -> None:
        self._store = store
        self._hooks = dict(hooks)
        self._on_event = on_event
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._expiration_grace = expiration_grace_seconds
        self._clock = clock

    # -- intake ---------------------------------------------------------

    async def submit(self, claim: ClaimRecord) -> None:
        """Register a claim for servicing (idempotent by claim_ref)."""
        await self._store.upsert_claim(claim.model_dump())
        self._emit(
            "claim_submitted",
            claim_ref=claim.claim_ref,
            mechanism=claim.obligation.get("mechanism"),
            **claim.deal_ref,
        )

    # -- sweep ----------------------------------------------------------

    async def run(self, interval_seconds: float = 30.0) -> None:
        """Watchdog loop: sweep until cancelled, never let a sweep crash it."""
        logger.info("[CLAIMS] engine started (interval=%ss)", interval_seconds)
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                n = await self.tick()
                if n:
                    logger.info("[CLAIMS] sweep processed %d claim(s)", n)
            except asyncio.CancelledError:
                logger.info("[CLAIMS] engine cancelled, shutting down")
                break
            except Exception:
                logger.exception("[CLAIMS] sweep failed; continuing")

    async def tick(self) -> int:
        """Process every due claim once. Returns the number processed."""
        now = self._clock()
        rows = await self._store.due_claims(now)
        processed = 0
        for row in rows:
            claim = ClaimRecord.model_validate(row)
            if claim.state in TERMINAL_STATES:
                continue
            try:
                await self._service(claim, now)
            except Exception as exc:  # hook bug — record, back off, keep sweeping
                claim.last_error = f"{type(exc).__name__}: {exc}"
                self._reschedule(claim, now)
                await self._store.save_claim(claim.model_dump())
                logger.exception(
                    "[CLAIMS] servicing %s failed; retry at %s",
                    claim.claim_ref, claim.next_attempt_unix,
                )
            processed += 1
        return processed

    # -- per-claim ------------------------------------------------------

    async def _service(self, claim: ClaimRecord, now: float) -> None:
        if self._expired(claim, now):
            self._abandon(claim, reason="expiration window passed")
            await self._store.save_claim(claim.model_dump())
            return

        hooks = self._hooks.get(str(claim.obligation.get("mechanism")))
        if hooks is None:
            claim.last_error = (
                f"no hooks for mechanism {claim.obligation.get('mechanism')!r}"
            )
            self._reschedule(claim, now)
            await self._store.save_claim(claim.model_dump())
            return

        if claim.state == "awaiting_conditions":
            status = await hooks.check_conditions(claim)
            if status == "failed":
                self._abandon(claim, reason=claim.last_error or "conditions failed")
                await self._store.save_claim(claim.model_dump())
                return
            if status == "pending":
                self._reschedule(claim, now)
                await self._store.save_claim(claim.model_dump())
                self._emit(
                    "claim_conditions_pending",
                    claim_ref=claim.claim_ref,
                    attempts=claim.attempts,
                )
                return
            claim.state = "collectable"
            claim.last_error = None
            await self._store.save_claim(claim.model_dump())
            self._emit("claim_collectable", claim_ref=claim.claim_ref)

        if claim.state == "collectable":
            try:
                receipt = await hooks.collect(claim)
            except Exception as exc:
                claim.last_error = f"{type(exc).__name__}: {exc}"
                self._reschedule(claim, now)
                await self._store.save_claim(claim.model_dump())
                self._emit(
                    "claim_collect_retry",
                    claim_ref=claim.claim_ref,
                    attempts=claim.attempts,
                    error=claim.last_error,
                )
                return
            claim.state = "collected"
            claim.result = receipt if isinstance(receipt, dict) else (
                {"receipt": str(receipt)} if receipt is not None else None
            )
            claim.last_error = None
            claim.next_attempt_unix = None
            await self._store.save_claim(claim.model_dump())
            self._emit(
                "claim_collected",
                claim_ref=claim.claim_ref,
                attempts=claim.attempts,
                **claim.deal_ref,
            )

    # -- helpers --------------------------------------------------------

    def _expired(self, claim: ClaimRecord, now: float) -> bool:
        exp = claim.obligation.get("expiration_unix")
        try:
            exp_f = float(exp) if exp is not None else None
        except (TypeError, ValueError):
            exp_f = None
        return exp_f is not None and now > exp_f + self._expiration_grace

    def _reschedule(self, claim: ClaimRecord, now: float) -> None:
        claim.attempts += 1
        backoff = min(
            self._base_backoff * (2 ** (claim.attempts - 1)), self._max_backoff
        )
        claim.next_attempt_unix = now + backoff

    def _abandon(self, claim: ClaimRecord, *, reason: str) -> None:
        claim.state = "abandoned"
        claim.last_error = reason
        claim.next_attempt_unix = None
        self._emit(
            "claim_abandoned",
            claim_ref=claim.claim_ref,
            reason=reason,
            **claim.deal_ref,
        )

    def _emit(self, event: str, **fields: Any) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(event, **fields)
        except Exception:
            logger.exception("[CLAIMS] event hook failed for %s", event)
