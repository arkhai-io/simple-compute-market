"""Fan-in/fan-out wrapper over N RegistryClients.

The marketplace treats "registry" as a role rather than a canonical
service: providers may run private registries for their own listings,
public registries may exist alongside them, and a buyer's discovery
is the *union* of every registry it's configured to consult. The
seller side is symmetric — a published listing should appear in every
registry the seller decided to broadcast to, so the union seen by
buyers stays complete even if one registry is offline.

This module exposes ``MultiRegistryClient`` with the same async
context-manager surface and method signatures as
``registry_client.RegistryClient``:

  * **Reads** (``list_listings``, ``get_listing``,
    ``wait_for_agent_indexed``) fan in across every configured
    registry concurrently. Per-registry failures are swallowed with a
    warning so one dead registry doesn't gate the whole discovery
    pass.

  * **Writes** (``publish_listing``, ``update_listing``,
    ``delete_listing``) fan out concurrently. The call succeeds when
    *at least one* registry accepts the write — partial failures are
    logged. Callers that need stricter convergence should layer a
    reconcile loop on top.

Method signatures intentionally mirror ``RegistryClient`` so call
sites (and the tests that mock them) don't change shape.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from registry_client import (
    RegistryClient,
    RegistryClientError,
    ListingRequest,
    UpdateListingRequest,
)
from registry_client.models import (
    AgentIndexedResponse,
    ListingListResponse,
    ListingSummary,
)

logger = logging.getLogger(__name__)


class MultiRegistryClient:
    """Async context manager that fans calls out over N RegistryClients."""

    def __init__(self, urls: list[str], *, timeout: float | None = None) -> None:
        # Preserve order for log readability and deterministic dedupe
        # tiebreaks (first-seen wins).
        self._urls: list[str] = list(urls)
        self._clients: list[RegistryClient] = []
        # Per-call deadline; ``None`` means no deadline (rely on the
        # underlying httpx client's own timeouts). When set, every
        # fan-in / fan-out call is wrapped in ``asyncio.wait_for`` so
        # one slow registry can't extend the wall time.
        self._timeout = timeout

    @property
    def urls(self) -> list[str]:
        return list(self._urls)

    async def __aenter__(self) -> "MultiRegistryClient":
        for url in self._urls:
            client = RegistryClient(url)
            await client.__aenter__()
            self._clients.append(client)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # Close every client even if one fails on close.
        errors: list[BaseException] = []
        for c in self._clients:
            try:
                await c.__aexit__(exc_type, exc, tb)
            except BaseException as e:
                errors.append(e)
        self._clients = []
        if errors and exc is None:
            raise errors[0]

    def _bound(self, coro):
        """Wrap a coroutine with the configured per-call deadline.

        Falls through unchanged when no timeout is set; otherwise
        ``asyncio.TimeoutError`` is raised by the wrapped task at the
        deadline and gets caught + logged like any other per-registry
        failure.
        """
        if self._timeout is None:
            return coro
        return asyncio.wait_for(coro, timeout=self._timeout)

    # ------------------------------------------------------------------
    # Reads — fan-in
    # ------------------------------------------------------------------

    async def list_listings(self, **kwargs: Any) -> ListingListResponse:
        """Concurrent ``list_listings`` over every registry; merged and
        deduped by ``listing_id``.

        A registry that errors out is logged and skipped — the merge
        proceeds with whatever remaining registries returned. Returns
        an empty response when no registries are configured (matches
        ``enable_registry_discovery=False`` semantics for the caller).
        """
        if not self._clients:
            return ListingListResponse(listings=[])
        results = await asyncio.gather(
            *[self._bound(c.list_listings(**kwargs)) for c in self._clients],
            return_exceptions=True,
        )
        merged: dict[str, ListingSummary] = {}
        for url, result in zip(self._urls, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "[MULTI_REGISTRY] %s list_listings failed: %s", url, result,
                )
                continue
            for listing in result.listings:
                # First-seen wins; registries are queried in config
                # order so the operator's preferred registry can take
                # precedence implicitly.
                merged.setdefault(str(listing.id), listing)
        return ListingListResponse(listings=list(merged.values()))

    async def get_listing(self, listing_id: str) -> ListingSummary:
        """Race every registry; return the first hit. Raises 404 only
        when *every* registry returned 404; other transport errors
        bubble up if no registry produced a hit."""
        if not self._clients:
            raise RegistryClientError(
                "GET", f"/listings/{listing_id}", 404,
                "no registries configured",
            )
        tasks = [
            asyncio.create_task(self._bound(c.get_listing(listing_id)))
            for c in self._clients
        ]
        last_404: RegistryClientError | None = None
        last_other: BaseException | None = None
        try:
            for completed in asyncio.as_completed(tasks):
                try:
                    return await completed
                except RegistryClientError as exc:
                    if getattr(exc, "status_code", None) == 404:
                        last_404 = exc
                    else:
                        last_other = exc
                except BaseException as exc:
                    last_other = exc
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        if last_other is not None:
            raise last_other
        if last_404 is not None:
            raise last_404
        raise RegistryClientError(
            "GET", f"/listings/{listing_id}", 500,
            "all registries failed without a response",
        )

    async def wait_for_agent_indexed(
        self, agent_id: str, *, timeout: float = 60.0,
    ) -> AgentIndexedResponse:
        """Long-poll every registry concurrently; return on the first
        ``indexed=True``. If no registry confirms within the timeout,
        return the first non-error response (so the caller still sees
        an ``indexed=False`` payload to act on)."""
        if not self._clients:
            raise RegistryClientError(
                "GET", "/api/v1/system/sync/wait-for-agent", 404,
                "no registries configured",
            )
        tasks = [
            asyncio.create_task(
                self._bound(c.wait_for_agent_indexed(agent_id, timeout=timeout))
            )
            for c in self._clients
        ]
        first_seen: AgentIndexedResponse | None = None
        last_error: BaseException | None = None
        try:
            for completed in asyncio.as_completed(tasks):
                try:
                    result = await completed
                except BaseException as exc:
                    last_error = exc
                    logger.warning(
                        "[MULTI_REGISTRY] wait_for_agent_indexed errored: %s",
                        exc,
                    )
                    continue
                if getattr(result, "indexed", False):
                    return result
                if first_seen is None:
                    first_seen = result
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        if first_seen is not None:
            return first_seen
        if last_error is not None:
            raise last_error
        raise RegistryClientError(
            "GET", "/api/v1/system/sync/wait-for-agent", 500,
            "all registries failed without a response",
        )

    # ------------------------------------------------------------------
    # Writes — fan-out, best-effort
    # ------------------------------------------------------------------

    async def publish_listing(
        self, agent_id: str, listing: ListingRequest, private_key: str,
    ) -> dict:
        return await self._fanout_write(
            "publish_listing",
            lambda c: c.publish_listing(agent_id, listing, private_key),
        )

    async def update_listing(
        self, listing_id: str, request: UpdateListingRequest,
    ) -> dict:
        return await self._fanout_write(
            "update_listing",
            lambda c: c.update_listing(listing_id, request),
        )

    async def delete_listing(self, listing_id: str, private_key: str) -> None:
        if not self._clients:
            raise RuntimeError("No registries configured")
        results = await asyncio.gather(
            *[self._bound(c.delete_listing(listing_id, private_key)) for c in self._clients],
            return_exceptions=True,
        )
        successes = sum(1 for r in results if not isinstance(r, BaseException))
        for url, r in zip(self._urls, results):
            if isinstance(r, BaseException):
                logger.warning(
                    "[MULTI_REGISTRY] %s delete_listing failed: %s", url, r,
                )
        if successes == 0:
            raise RuntimeError(
                f"delete_listing failed for all {len(self._urls)} registries"
            )

    async def _fanout_write(self, op_name: str, call):
        """Run ``call(client)`` on every client concurrently. Return
        the first registry's successful response. Raises if every
        registry failed."""
        if not self._clients:
            raise RuntimeError("No registries configured")
        results = await asyncio.gather(
            *[self._bound(call(c)) for c in self._clients],
            return_exceptions=True,
        )
        first_ok: dict | None = None
        for url, r in zip(self._urls, results):
            if isinstance(r, BaseException):
                logger.warning(
                    "[MULTI_REGISTRY] %s %s failed: %s", url, op_name, r,
                )
                continue
            if first_ok is None:
                first_ok = r
        if first_ok is None:
            raise RuntimeError(
                f"{op_name} failed for all {len(self._urls)} registries"
            )
        return first_ok
