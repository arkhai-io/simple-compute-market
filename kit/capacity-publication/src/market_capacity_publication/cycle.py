"""Driving one schema-opaque publication cycle from an async storefront.

The shared publication runner in ``core_storefront`` is synchronous and calls a
domain's publication-source callbacks as it goes, while a storefront's
persistence, site clients, and the publication runtime are async. A cycle
therefore runs the runner in a worker thread, and each callback that needs the
storefront's own async services hands its coroutine back to the event loop the
cycle started on and waits for the result.

What a cycle derives, closes, holds, and reopens is the domain's; this module
owns only how that work is driven, what the cycle reports, and the registry
convergence every publication pass ends with. See
openspec/specs/storefront-publication/spec.md, "Registries converge on each
listing's local status".
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from core_storefront.publication_runner import (
    PayloadBuilder,
    PublicationCycleResult,
    PublishOffer,
    run_publication_cycle,
)
from core_storefront.publication_sources import PublicationSource

from .publication import PublicationRuntime

T = TypeVar("T")


@dataclass
class PublicationCycleReport:
    """What one cycle did, or in a dry run would do, and why.

    Each action is a dictionary naming the action and its details, recorded in
    the order the cycle took it.
    """

    dry_run: bool = False
    actions: list[dict[str, Any]] = field(default_factory=list)

    def record(self, action: str, **details: Any) -> None:
        self.actions.append({"action": action, **details})

    def of(self, action: str) -> list[dict[str, Any]]:
        return [item for item in self.actions if item["action"] == action]

    def as_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.actions:
            counts[item["action"]] = counts.get(item["action"], 0) + 1
        return {
            "dry_run": self.dry_run,
            "actions": list(self.actions),
            "counts": dict(sorted(counts.items())),
        }


class PublicationCycleDriver:
    """Runs the synchronous publication runner under an async storefront.

    :meth:`run` binds the event loop the cycle runs on, then runs the runner in
    a worker thread. A source callback, which the runner calls on that thread,
    passes each coroutine it needs to :meth:`call`, which runs it on the bound
    loop and returns its result. Calling :meth:`call` on the loop's own thread
    would deadlock, so it is only for callbacks.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None

    def call(self, awaitable: Awaitable[T]) -> T:
        if self._loop is None:
            raise RuntimeError("a publication cycle is not running")
        return asyncio.run_coroutine_threadsafe(
            awaitable,  # type: ignore[arg-type]
            self._loop,
        ).result()

    async def run(
        self,
        sources: Iterable[PublicationSource],
        *,
        db_path: str,
        base_url: str,
        build_payload: PayloadBuilder,
        publish_listing: PublishOffer,
        close_stale: bool = True,
        skip_open: bool = False,
    ) -> PublicationCycleResult:
        self._loop = asyncio.get_running_loop()
        return await asyncio.to_thread(
            run_publication_cycle,
            tuple(sources),
            db_path=db_path,
            base_url=base_url,
            build_payload=build_payload,
            publish_listing=publish_listing,
            close_stale=close_stale,
            skip_open=skip_open,
        )


async def converge_registries(
    runtime: PublicationRuntime[Any],
    report: PublicationCycleReport,
) -> None:
    """Repair every registry that missed a publish, close, or reopen.

    Run after a cycle's own publication, so it sees that cycle's outcomes. Each
    diverged listing is reported; a dry run reports what it would resend and
    sends nothing, and a registry still unreachable afterwards is reported as a
    failure, to be repaired by a later pass.
    """
    divergences = await runtime.publication_divergence()
    for divergence in divergences:
        report.record(
            "converge",
            listing_id=divergence.listing_id,
            status=divergence.listing_status,
            registries=list(divergence.registry_urls),
        )
    if report.dry_run or not divergences:
        return
    result = await runtime.converge(divergences)
    for listing_id in result["unrepaired"]:
        report.record("fail", listing_id=listing_id, reason="registry_not_converged")


__all__ = [
    "PublicationCycleDriver",
    "PublicationCycleReport",
    "converge_registries",
]
