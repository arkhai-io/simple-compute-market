"""Fan-in/fan-out wrapper over N RegistryClients.

The marketplace treats "registry" as a role rather than a canonical
service: providers may run private registries for their own listings,
public registries may exist alongside them, and a buyer's discovery
is the *union* of every registry it's configured to consult. The
seller side is symmetric — a published listing should appear in every
registry the seller decided to broadcast to, so the union seen by
buyers stays complete even if one registry is offline.

This module exposes ``MultiRegistryClient`` with the same async
context-manager operations as ``registry_client.RegistryClient`` and
keyword-only publication arguments:

  * **Reads** (``list_listings``, ``get_listing``) fan in across every
    configured registry concurrently. Per-registry failures are swallowed
    with a warning so one dead registry doesn't gate the whole discovery
    pass.

  * **Writes** (``publish_listing``, ``update_listing``,
    ``delete_listing``) fan out concurrently. The call succeeds when
    *at least one* registry accepts the write — partial failures are
    logged. Callers that need stricter convergence should layer a
    reconcile loop on top.

Every underlying client receives the storefront signer, the exact ``seller``
caller role, and the separately configured public authority pin for that URL.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

from market_identity import Signer, TrustedIdentitySet


from registry_client import (
    RegistryClient,
    RegistryClientError,
    ListingRequest,
    UpdateListingRequest,
)
from registry_client.models import (
    ListingListResponse,
    ListingSummary,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RegistryAuthorityTrust:
    """Stable registry authority name and its bounded rotation trust set."""

    authority: str
    principals: TrustedIdentitySet

    def __post_init__(self) -> None:
        if not isinstance(self.authority, str) or not self.authority.strip():
            raise ValueError("registry authority name must be non-empty text")
        if not isinstance(self.principals, TrustedIdentitySet):
            raise TypeError("registry authority principals must be a TrustedIdentitySet")


class PublishResult(TypedDict):
    """Per-registry outcome of a fan-out write.

    Returned by the per-registry write methods so callers can persist
    a ``publications`` row reflecting the actual shape of the payload
    sent to each registry. ``payload`` is the exact dict transmitted when
    the wrapper built it from a uniform request.
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
        signer: Signer,
        caller_role: str,
        expected_registries: Mapping[str, RegistryAuthorityTrust],
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
        self._signer = signer
        if caller_role != "seller":
            raise ValueError("storefront registry caller_role must be 'seller'")
        from market_config.registry_url import normalize_registry_url
        if any(not isinstance(url, str) or not url.strip() for url in self._urls):
            raise ValueError("configured registry URLs must be non-empty text")
        normalized_urls = [normalize_registry_url(url) for url in self._urls]
        if len(set(normalized_urls)) != len(normalized_urls):
            raise ValueError("configured registry URLs must be unique after normalization")

        normalized_expected: dict[str, RegistryAuthorityTrust] = {}
        for raw_url, trust in expected_registries.items():
            if not isinstance(raw_url, str) or not raw_url.strip():
                raise ValueError("registry authority URL must be non-empty text")
            if not isinstance(trust, RegistryAuthorityTrust):
                raise TypeError(
                    "expected registry authority must be a RegistryAuthorityTrust"
                )
            normalized_url = normalize_registry_url(raw_url)
            if normalized_url in normalized_expected:
                raise ValueError(
                    f"duplicate expected registry authority for {normalized_url!r}"
                )
            normalized_expected[normalized_url] = trust
        missing = [
            url
            for url in self._urls
            if normalize_registry_url(url) not in normalized_expected
        ]
        if missing:
            raise ValueError(
                f"missing expected registry authority for {missing!r}"
            )
        self._caller_role = caller_role
        self._expected_registries = normalized_expected

    @property
    def urls(self) -> list[str]:
        return list(self._urls)

    async def __aenter__(self) -> "MultiRegistryClient":
        from market_config.registry_url import (
            lookup_registry_auth,
            normalize_registry_url,
        )
        for url in self._urls:
            trust = self._expected_registries[normalize_registry_url(url)]
            client = RegistryClient(
                url,
                api_key=lookup_registry_auth(self._auth, url),
                signer=self._signer,
                caller_role=self._caller_role,
                expected_registries=trust.principals,
                registry_authority=trust.authority,
            )
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

    # ------------------------------------------------------------------
    # Writes — fan-out, best-effort
    # ------------------------------------------------------------------

    async def publish_listing(self, *, listing: ListingRequest) -> dict:
        """Fan out the same signed-principal listing to every registry."""
        payloads = {url: listing for url in self._urls}
        results = await self.publish_listing_per_registry(payloads=payloads)
        return _first_ok_response(results, op="publish_listing")

    async def update_listing(
        self,
        *,
        listing_id: str,
        request: UpdateListingRequest,
    ) -> dict:
        """Fan out the same ``request`` to every configured registry."""
        payloads = {url: request for url in self._urls}
        results = await self.update_listing_per_registry(
            listing_id=listing_id,
            payloads=payloads,
        )
        return _first_ok_response(results, op="update_listing")

    async def delete_listing(self, *, listing_id: str) -> None:
        """Fan out a delete under the injected signer."""
        results = await self.delete_listing_per_registry(
            listing_id=listing_id,
            registry_urls=self._urls,
        )
        if not any(r["success"] for r in results):
            raise RuntimeError(
                f"delete_listing failed for all {len(results)} registries"
            )

    async def publish_listing_per_registry(
        self,
        *,
        payloads: dict[str, ListingRequest],
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
            lambda client, payload: client.publish_listing(listing=payload),
        )

    async def update_listing_per_registry(
        self,
        *,
        listing_id: str,
        payloads: dict[str, UpdateListingRequest],
    ) -> list[PublishResult]:
        """Update a listing with per-registry request payloads. Same
        semantics as :meth:`publish_listing_per_registry`."""
        return await self._fanout_per_registry(
            "update_listing",
            payloads,
            lambda client, payload: client.update_listing(
                listing_id=listing_id,
                request=payload,
            ),
        )

    async def delete_listing_per_registry(
        self,
        *,
        listing_id: str,
        registry_urls: list[str],
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
            lambda client, _payload: client.delete_listing(listing_id=listing_id),
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
    # UpdateListingRequest.to_dict() requires the listing_id it signs over;
    # for audit we keep the update fields, not the signed envelope.
    updates = getattr(payload, "updates", None)
    if isinstance(updates, dict):
        return dict(updates)
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

    Uniform fan-out writes expose the same response shape as one registry;
    callers needing the complete outcome set use the per-registry methods.
    """
    for r in results:
        if r["success"] and r["response"] is not None:
            return r["response"]
    raise RuntimeError(f"{op} failed for all {len(results)} registries")
