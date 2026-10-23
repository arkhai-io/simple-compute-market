"""Driving one schema-opaque publication cycle from an async storefront.

The shared publication runner in ``core_storefront`` is synchronous and calls a
domain's publication-source callbacks as it goes, while a storefront's
persistence, site clients, and the publication runtime are async. A cycle
therefore runs the runner in a worker thread, and each callback that needs the
storefront's own async services hands its coroutine back to the event loop the
cycle started on and waits for the result.

What a cycle derives, closes, holds, and reopens is the domain's; this module
owns only how that work is driven, what the cycle reports, the registry
convergence every publication pass ends with, and the log of each site's
latest derivation the storefront's status reports. See
openspec/specs/storefront-publication/spec.md, "Registries converge on each
listing's local status" and "A compute storefront reports and logs its site
derivation".
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import json
import logging
import threading
from collections.abc import Awaitable, Iterable, Mapping
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

logger = logging.getLogger(__name__)


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


#: One site's derivation: its ``holds``, ``refusals``, and ``reports``, each
#: entry a reason code with the pool or resource it concerns and any detail.
SiteDerivation = dict[str, list[dict[str, Any]]]

# Each derivation action a site's summary lists, by the summary's name for it.
_DERIVATION_ACTIONS = {"hold": "holds", "refuse": "refusals", "report": "reports"}


def site_derivations(
    report: PublicationCycleReport, site_ids: Iterable[str]
) -> dict[str, SiteDerivation]:
    """Each of ``site_ids``' derivation from one cycle's report.

    Every hold, refusal, and report action naming one of the sites, without
    its action and site, in the order the cycle took them. A site the cycle
    derived cleanly has empty lists, so it is told apart from one no cycle
    has derived.
    """
    summary: dict[str, SiteDerivation] = {
        site_id: {name: [] for name in _DERIVATION_ACTIONS.values()}
        for site_id in site_ids
    }
    for item in report.actions:
        name = _DERIVATION_ACTIONS.get(item["action"])
        site_id = item.get("site_id")
        site = summary.get(site_id) if isinstance(site_id, str) else None
        if name is None or site is None:
            continue
        site[name].append(
            {key: value for key, value in item.items() if key not in ("action", "site_id")}
        )
    return summary


# An entry's error text is what an unreachable source happened to answer this
# time, so it is not part of what makes the entry the same entry.
_VOLATILE_DETAIL = frozenset({"error"})


def _entry_key(entry: Mapping[str, Any]) -> str:
    return json.dumps(
        {key: value for key, value in entry.items() if key not in _VOLATILE_DETAIL},
        sort_keys=True,
        default=str,
    )


def _detail_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, (str, int, float, bool)) for item in value):
            return "; ".join(str(item) for item in value)
        return f"{len(value)} item(s)"
    if isinstance(value, Mapping):
        return f"{len(value)} field(s)"
    return str(value)


def _entry_text(entry: Mapping[str, Any]) -> str:
    details = ", ".join(
        f"{key}={_detail_text(entry[key])}" for key in sorted(entry) if key != "reason"
    )
    reason = entry.get("reason", "unspecified")
    return f"{reason} ({details})" if details else str(reason)


def _holds_the_site(entry: Mapping[str, Any]) -> bool:
    return "pool_id" not in entry


def _standing(previous: SiteDerivation, derivation: SiteDerivation) -> SiteDerivation:
    """A site's derivation as it now stands.

    A hold naming no pool holds the whole site: the cycle could not read it,
    so every other entry of the last derivation that did still describes it
    and stands beside the site's hold, rather than clearing until the site is
    read again. The earlier site hold itself is replaced by the current one.
    """
    current = {name: list(derivation.get(name, ())) for name in _DERIVATION_ACTIONS.values()}
    if not any(_holds_the_site(entry) for entry in current["holds"]):
        return current
    for name in _DERIVATION_ACTIONS.values():
        current[name].extend(
            entry
            for entry in previous.get(name, ())
            if not (name == "holds" and _holds_the_site(entry))
        )
    return current


class SiteDerivationLog:
    """Each site's latest publication derivation, kept per publication source.

    Only a publication cycle that ran records into it: a previewed cycle's
    report is ignored, and a listing-source check or capacity-event
    reconciliation has no cycle report to record, so status always reports
    what the last publication cycle derived. Each source keeps its own
    derivation of a site, so two sources composed in one storefront never clear
    or raise each other's entries. A site no cycle has recorded since start is
    absent.

    An entry is logged as a warning when it first appears in a site's
    derivation and at info when it clears; a standing entry is not logged
    again, however many cycles it stands for, nor when only its error text
    changes. While a hold naming no pool holds a whole site, the site's pool
    entries from its last derivation stand beside it (see ``_standing``).
    """

    def __init__(self) -> None:
        self._latest: dict[str, dict[str, SiteDerivation]] = {}

    def record(
        self, source: str, report: PublicationCycleReport, site_ids: Iterable[str]
    ) -> None:
        """Record ``source``'s derivation of each of ``site_ids`` from one cycle.

        A previewed cycle records and logs nothing.
        """
        if report.dry_run:
            return
        recorded = self._latest.setdefault(source, {})
        for site_id, derived in site_derivations(report, site_ids).items():
            previous = recorded.get(site_id, {})
            derivation = _standing(previous, derived)
            for name in _DERIVATION_ACTIONS.values():
                before = {_entry_key(entry): entry for entry in previous.get(name, ())}
                after = {_entry_key(entry): entry for entry in derivation.get(name, ())}
                for key in after.keys() - before.keys():
                    logger.warning(
                        "[PUBLICATION] %s site %s %s: %s",
                        source, site_id, name, _entry_text(after[key]),
                    )
                for key in before.keys() - after.keys():
                    logger.info(
                        "[PUBLICATION] %s site %s %s cleared: %s",
                        source, site_id, name, _entry_text(before[key]),
                    )
            recorded[site_id] = copy.deepcopy(
                {name: list(derivation.get(name, ())) for name in _DERIVATION_ACTIONS.values()}
            )

    def latest(self) -> dict[str, SiteDerivation]:
        """Each recorded site's derivation, every source's entries together."""
        merged: dict[str, SiteDerivation] = {}
        for derivations in self._latest.values():
            for site_id, derivation in derivations.items():
                site = merged.setdefault(
                    site_id, {name: [] for name in _DERIVATION_ACTIONS.values()}
                )
                for name in _DERIVATION_ACTIONS.values():
                    site[name].extend(copy.deepcopy(derivation[name]))
        return merged


class PublicationCycleStopped(RuntimeError):
    """The cycle a callback belongs to was cancelled, so its call cannot complete."""


class PublicationCycleDriver:
    """Runs the synchronous publication runner under an async storefront.

    :meth:`run` binds the event loop the cycle runs on, then runs the runner in
    a worker thread. A source callback, which the runner calls on that thread,
    passes each coroutine it needs to :meth:`call`, which runs it on the bound
    loop and returns its result. Calling :meth:`call` on the loop's own thread
    would deadlock, so it is only for callbacks.

    A worker thread cannot be cancelled, so cancelling the cycle stops it at
    its callbacks instead: the call waiting on the loop fails at once with
    :class:`PublicationCycleStopped`, and so does every later call, so the
    runner unwinds and the thread ends. Without that, a call whose coroutine
    the loop never completes -- a loop closing behind a cancelled cycle --
    would hold the thread forever, and an interpreter exit with it.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._pending: set[concurrent.futures.Future[Any]] = set()
        self._stopped = False

    def call(self, awaitable: Awaitable[T]) -> T:
        with self._lock:
            if self._loop is None:
                raise RuntimeError("a publication cycle is not running")
            if self._stopped:
                if asyncio.iscoroutine(awaitable):
                    awaitable.close()
                raise PublicationCycleStopped("the publication cycle was cancelled")
            future = asyncio.run_coroutine_threadsafe(
                awaitable,  # type: ignore[arg-type]
                self._loop,
            )
            self._pending.add(future)
        try:
            return future.result()
        except concurrent.futures.CancelledError as exc:
            if self._stopped:
                raise PublicationCycleStopped(
                    "the publication cycle was cancelled"
                ) from exc
            raise
        finally:
            with self._lock:
                self._pending.discard(future)

    def _stop(self) -> None:
        with self._lock:
            self._stopped = True
            pending = tuple(self._pending)
        for future in pending:
            future.cancel()

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
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._stopped = False
        try:
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
        except asyncio.CancelledError:
            self._stop()
            raise


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
    "PublicationCycleStopped",
    "PublicationCycleReport",
    "SiteDerivation",
    "SiteDerivationLog",
    "converge_registries",
    "site_derivations",
]
