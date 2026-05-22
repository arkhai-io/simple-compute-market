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
from typing import Any, TypedDict

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


class PublishResult(TypedDict):
    """Per-registry outcome of a fan-out write.

    Returned by the per-registry write methods so callers can persist
    a ``publications`` row reflecting the actual shape of the payload
    sent to each registry. ``payload`` is the exact dict transmitted —
    useful when the wrapper built it from a uniform request (back-compat
    fan-out) and the caller wants to record it.
    """
    registry_url: str
    success: bool
    response: dict | None
    error: str | None
    payload: dict | None
    registry_assigned_id: str | None


class MultiRegistryClient:
    """Async context manager that fans calls out over N RegistryClients."""

    def __init__(
        self,
        urls: list[str],
        *,
        timeout: float | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        # Preserve order for log readability and deterministic dedupe
        # tiebreaks (first-seen wins).
        self._urls: list[str] = list(urls)
        self._clients: list[RegistryClient] = []
        # Per-call deadline; ``None`` means no deadline (rely on the
        # underlying httpx client's own timeouts). When set, every
        # fan-in / fan-out call is wrapped in ``asyncio.wait_for`` so
        # one slow registry can't extend the wall time.
        self._timeout = timeout
        # Per-URL bearer tokens. URLs without an entry get no
        # Authorization header on their underlying RegistryClient.
        # Look up via the URL-normalizing helper so trailing-slash and
        # case mismatches between [registry] urls and [registry.auth]
        # keys don't silently drop the token.
        self._auth: dict[str, str] = dict(auth or {})

    @property
    def urls(self) -> list[str]:
        return list(self._urls)

    async def __aenter__(self) -> "MultiRegistryClient":
        from service.registry_url import lookup_registry_auth
        for url in self._urls:
            client = RegistryClient(url, api_key=lookup_registry_auth(self._auth, url))
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
        """Fan out the same ``listing`` payload to every configured
        registry. Back-compat wrapper around
        :meth:`publish_listing_per_registry`. Returns the first
        registry's successful response."""
        payloads = {url: listing for url in self._urls}
        results = await self.publish_listing_per_registry(
            agent_id, payloads, private_key,
        )
        return _first_ok_response(results, op="publish_listing")

    async def update_listing(
        self, listing_id: str, request: UpdateListingRequest,
    ) -> dict:
        """Fan out the same ``request`` to every configured registry.
        Back-compat wrapper around :meth:`update_listing_per_registry`."""
        payloads = {url: request for url in self._urls}
        results = await self.update_listing_per_registry(listing_id, payloads)
        return _first_ok_response(results, op="update_listing")

    async def delete_listing(self, listing_id: str, private_key: str) -> None:
        """Fan out a delete to every configured registry. At least one
        must succeed or the call raises."""
        results = await self.delete_listing_per_registry(
            listing_id, self._urls, private_key,
        )
        if not any(r["success"] for r in results):
            raise RuntimeError(
                f"delete_listing failed for all {len(results)} registries"
            )

    async def publish_listing_per_registry(
        self,
        agent_id: str,
        payloads: dict[str, ListingRequest],
        private_key: str,
    ) -> list[PublishResult]:
        """Publish a (possibly distinct) ``ListingRequest`` payload to each
        registry independently. Returns one :class:`PublishResult` per entry
        in ``payloads`` — including failures, so the caller can record a
        ``publications`` row for every attempt.

        Only registries present in this client's configured URLs are
        contacted; entries in ``payloads`` for unknown URLs are returned
        as failures with ``error="registry not configured"``.
        """
        return await self._fanout_per_registry(
            "publish_listing",
            payloads,
            lambda client, payload: client.publish_listing(
                agent_id, payload, private_key,
            ),
        )

    async def update_listing_per_registry(
        self,
        listing_id: str,
        payloads: dict[str, UpdateListingRequest],
    ) -> list[PublishResult]:
        """Update a listing with per-registry request payloads. Same
        semantics as :meth:`publish_listing_per_registry`."""
        return await self._fanout_per_registry(
            "update_listing",
            payloads,
            lambda client, payload: client.update_listing(listing_id, payload),
        )

    async def delete_listing_per_registry(
        self,
        listing_id: str,
        registry_urls: list[str],
        private_key: str,
    ) -> list[PublishResult]:
        """Delete a listing from a specific subset of registries (typically
        the ones recorded in the ``publications`` table for this listing).
        Returns one :class:`PublishResult` per requested URL."""
        # delete has no payload, but the per-registry contract carries one
        # placeholder per URL so callers see the same result shape.
        synthetic: dict[str, object] = {url: {} for url in registry_urls}
        return await self._fanout_per_registry(
            "delete_listing",
            synthetic,
            lambda client, _payload: client.delete_listing(
                listing_id, private_key,
            ),
        )

    async def _fanout_per_registry(
        self,
        op_name: str,
        payloads: dict[str, Any],
        call,
    ) -> list[PublishResult]:
        """Shared fan-out machinery for the per-registry write methods.

        Builds an ordered :class:`PublishResult` list — one per entry in
        ``payloads`` — preserving the input dict's iteration order so
        callers can match results to inputs positionally. URLs that
        aren't configured on this client are recorded as failures
        without making a network call.
        """
        url_to_client = dict(zip(self._urls, self._clients))
        results: list[PublishResult] = []
        coro_indices: list[int] = []
        coros: list[Any] = []

        for url, payload in payloads.items():
            payload_dict = _payload_to_dict(payload)
            client = url_to_client.get(url)
            if client is None:
                results.append(PublishResult(
                    registry_url=url,
                    success=False,
                    response=None,
                    error="registry not configured",
                    payload=payload_dict,
                    registry_assigned_id=None,
                ))
                continue
            results.append(PublishResult(
                registry_url=url,
                success=False,
                response=None,
                error=None,
                payload=payload_dict,
                registry_assigned_id=None,
            ))
            coro_indices.append(len(results) - 1)
            coros.append(self._bound(call(client, payload)))

        if coros:
            outcomes = await asyncio.gather(*coros, return_exceptions=True)
            for idx, outcome in zip(coro_indices, outcomes):
                url = results[idx]["registry_url"]
                if isinstance(outcome, BaseException):
                    logger.warning(
                        "[MULTI_REGISTRY] %s %s failed: %s", url, op_name, outcome,
                    )
                    results[idx] = PublishResult(
                        registry_url=url,
                        success=False,
                        response=None,
                        error=str(outcome),
                        payload=results[idx]["payload"],
                        registry_assigned_id=None,
                    )
                else:
                    response = outcome if isinstance(outcome, dict) else None
                    assigned_id = None
                    if isinstance(response, dict):
                        for key in ("listing_id", "id", "registry_listing_id"):
                            val = response.get(key)
                            if isinstance(val, str) and val:
                                assigned_id = val
                                break
                    results[idx] = PublishResult(
                        registry_url=url,
                        success=True,
                        response=response,
                        error=None,
                        payload=results[idx]["payload"],
                        registry_assigned_id=assigned_id,
                    )

        return results


def _payload_to_dict(payload: Any) -> dict | None:
    """Best-effort coerce a request payload to a dict for persistence.

    Recognises Pydantic models (``model_dump``), dataclass-style request
    objects from ``registry_client`` (``to_dict``), and plain dicts.
    Returns ``None`` for anything else so the caller can decide whether
    to record a NULL payload or skip the row entirely."""
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:
            try:
                return dump()
            except Exception:
                pass
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
            return result if isinstance(result, dict) else None
        except Exception:
            return None
    return None


def _first_ok_response(results: list[PublishResult], *, op: str) -> dict:
    """Return the first successful response dict or raise if all failed.

    Used by the back-compat fan-out wrappers (``publish_listing`` /
    ``update_listing``) that only surface a single response shape.
    """
    for r in results:
        if r["success"] and r["response"] is not None:
            return r["response"]
    raise RuntimeError(f"{op} failed for all {len(results)} registries")
