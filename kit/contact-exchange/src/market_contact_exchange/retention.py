"""Retention of revealed contact payloads: the window, its disclosure, and the sweep.

The window is a policy over everything a storefront holds, not a term of any
deal: the storefront pays for the storage and carries the liability, so it
sets the policy, and a party chooses by choosing a storefront. The policy is
therefore built from the running configuration and applied to every
introduction, including those revealed under an earlier window. See
openspec/specs/contact-exchange-settlement/spec.md, "Contact payloads are
retained for a configured window".

Framework-free, like the reveal service: a storefront binds the service into
its own router behind its own administrator authentication, and registers the
sweep with its own loop controller, which this kit cannot import.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from .introduction_routes import LoadIntroduction
from .settlement_config import INDEFINITE_RETENTION, ContactSettlementConfig

#: The loop name a storefront registers the sweep under, and the route name its
#: lifecycle controls step and preview it by.
INTRODUCTION_RETENTION_LOOP = "introduction_retention"
INTRODUCTION_RETENTION_ROUTE = "introduction-retention"

#: The disclosure states the window as current storefront policy, which the
#: operator may change or act ahead of at any time, rather than a commitment.
DISCLOSURE_BASIS = "current_policy"
#: The disclosure governs the storefront's introduction record only: not copies
#: either side's delivery sinks or tooling already hold, and not responses the
#: storefront recorded to answer an exact retry identically.
DISCLOSURE_SCOPE = "introduction_record"

#: How many introductions one sweep cycle redacts at most. A backlog larger
#: than this drains over successive cycles; the bound keeps one cycle, and the
#: preview describing it, a bounded amount of work.
SWEEP_BATCH_LIMIT = 1000

#: How often a held sweep loop re-reads its gate.
_HELD_POLL_SECONDS = 0.05


class SelectExpiredIntroductions(Protocol):
    def __call__(self, cutoff: datetime, limit: int) -> Awaitable[list[str]]: ...


class DeleteIntroductionPayloads(Protocol):
    def __call__(self, obligation_ref: str, deleted_at: datetime) -> Awaitable[bool]: ...


@dataclass(frozen=True, slots=True)
class IntroductionRetentionPolicy:
    """The effective window and sweep cadence. ``window_seconds`` None is indefinite."""

    window_seconds: int | None
    sweep_interval_seconds: int

    def __post_init__(self) -> None:
        if self.window_seconds is not None and self.window_seconds <= 0:
            raise ValueError("a finite retention window must be positive")
        if self.sweep_interval_seconds <= 0:
            raise ValueError("the retention sweep interval must be positive")

    @classmethod
    def from_config(cls, config: ContactSettlementConfig) -> IntroductionRetentionPolicy:
        window = config.retention_seconds
        return cls(
            window_seconds=None if window == INDEFINITE_RETENTION else int(window),
            sweep_interval_seconds=int(config.retention_sweep_interval_seconds),
        )

    def cutoff(self, now: datetime) -> datetime | None:
        """The latest reveal time already past the window, or None if indefinite."""

        if self.window_seconds is None:
            return None
        return now - timedelta(seconds=self.window_seconds)


def retention_disclosure(policy: IntroductionRetentionPolicy) -> dict[str, Any]:
    """The one machine-readable disclosure of the effective window.

    The same object is served on the storefront's public readiness projection,
    before a buyer commits contact data, and in the reveal itself, so the two
    cannot disagree. Enumerated ``basis`` and ``scope`` carry what the window
    means without prose that could drift between storefronts.
    """

    return {
        "window_seconds": policy.window_seconds,
        "basis": DISCLOSURE_BASIS,
        "scope": DISCLOSURE_SCOPE,
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IntroductionRetentionService:
    """One deletion operation behind both the scheduled sweep and an operator.

    The single deletion and every sweep redact through the same injected
    operation, so neither path can delete differently from the other. The
    sweep step is the operation the timer runs, and the preview selects what
    that step would delete if it ran now, writing nothing.
    """

    def __init__(
        self,
        *,
        policy: IntroductionRetentionPolicy,
        select_expired: SelectExpiredIntroductions,
        delete_payloads: DeleteIntroductionPayloads,
        load: LoadIntroduction,
        clock: Callable[[], datetime] = _utc_now,
        batch_limit: int = SWEEP_BATCH_LIMIT,
    ) -> None:
        if batch_limit <= 0:
            raise ValueError("a retention sweep requires a positive batch limit")
        self._policy = policy
        self._select_expired = select_expired
        self._delete_payloads = delete_payloads
        self._load = load
        self._clock = clock
        self._batch_limit = batch_limit

    @property
    def policy(self) -> IntroductionRetentionPolicy:
        return self._policy

    def disclosure(self) -> dict[str, Any]:
        return retention_disclosure(self._policy)

    async def delete_one(self, obligation_ref: str) -> dict[str, Any]:
        """Delete one introduction's payloads now, whatever the window says.

        Converges rather than failing on an already-deleted introduction or a
        deal that never started one. ``payloads_deleted_at`` reports when the
        payloads were deleted, by this call or an earlier one, and is None
        when there was nothing revealed to delete.
        """

        redacted = await self._delete_payloads(obligation_ref, self._clock())
        record = await self._load(obligation_ref)
        return {
            "obligation_ref": obligation_ref,
            "redacted": redacted,
            "payloads_deleted_at": (
                record.payloads_deleted_at if record is not None else None
            ),
        }

    async def _eligible(self, now: datetime) -> list[str]:
        cutoff = self._policy.cutoff(now)
        if cutoff is None:
            return []
        return await self._select_expired(cutoff, self._batch_limit)

    async def sweep_once(self) -> Mapping[str, Any]:
        """Run one sweep cycle: redact every introduction past the window.

        A cycle that fails part-way leaves the introductions it reached
        redacted and the rest eligible, so the next cycle converges: an
        already-redacted introduction is no longer selected, and redacting one
        again would return ``False`` rather than raise.
        """

        now = self._clock()
        deleted = 0
        for obligation_ref in await self._eligible(now):
            if await self._delete_payloads(obligation_ref, now):
                deleted += 1
        return {"loop": INTRODUCTION_RETENTION_LOOP, "deleted": deleted}

    async def preview(self) -> Mapping[str, Any]:
        """Report what a sweep cycle would delete now, deleting nothing.

        A snapshot: eligibility only grows with time, so the next cycle deletes
        everything reported here that is still unredacted, and may also delete
        introductions that expired in between. Selection is oldest first, so
        that holds under the batch limit too.
        """

        eligible = await self._eligible(self._clock())
        return {
            "loop": INTRODUCTION_RETENTION_LOOP,
            "dry_run": True,
            "eligible": eligible,
            "eligible_count": len(eligible),
        }


async def run_introduction_retention_sweep(
    service: IntroductionRetentionService,
    *,
    paused: Callable[[], bool] | None = None,
    wait: Callable[[float], Awaitable[None]] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Run the sweep on the policy's interval until the task is cancelled.

    Each cycle reads the gate, sweeps if a sweep is due, then waits one
    interval through ``wait`` -- a storefront's loop controller, which returns
    early on a pause request. The gate is read on entry and immediately before
    every sweep, so a pause requested during the wait is observed before the
    next sweep. The first sweep is due one interval after start, as for the
    storefront's other timer loops; an operator who wants one sooner steps it.
    """

    if paused is not None and wait is None:
        # Gated but uninterruptible is the combination that lets a pause
        # outlast its own bounded wait.
        raise TypeError("a gated retention sweep requires an interruptible wait")
    active_logger = logger or logging.getLogger(__name__)
    interval = float(service.policy.sweep_interval_seconds)
    sweep_not_before = asyncio.get_running_loop().time() + interval
    while True:
        try:
            if paused is not None and paused():
                await asyncio.sleep(_HELD_POLL_SECONDS)
                continue
            if asyncio.get_running_loop().time() >= sweep_not_before:
                report = await service.sweep_once()
                if report.get("deleted"):
                    active_logger.info(
                        "introduction_retention: deleted payloads of %d introduction(s)",
                        report["deleted"],
                    )
        except asyncio.CancelledError:
            break
        except Exception:
            active_logger.exception("introduction_retention: sweep failed")
        # Outside the sweep's handler so a failing sweep still waits its
        # interval rather than retrying in a tight loop.
        try:
            if wait is not None:
                await wait(interval)
            else:
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break


__all__ = [
    "DISCLOSURE_BASIS",
    "DISCLOSURE_SCOPE",
    "INTRODUCTION_RETENTION_LOOP",
    "INTRODUCTION_RETENTION_ROUTE",
    "SWEEP_BATCH_LIMIT",
    "DeleteIntroductionPayloads",
    "IntroductionRetentionPolicy",
    "IntroductionRetentionService",
    "SelectExpiredIntroductions",
    "retention_disclosure",
    "run_introduction_retention_sweep",
]
