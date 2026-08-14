"""Core buyer role orchestration.

This module owns the schema-invariant buyer skeleton:

    discover -> negotiate/aggregate -> settle

The listing schema, negotiation policy, settlement mechanism, CLI, and run-log
format are injected by a domain package. Core only owns the control flow and
the generic registry discovery helpers.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from market_identity import Identity, Signer
from core_buyer.registry_config import RegistryAuthority
from registry_client import (
    CompiledResourceQuery,
    RegistryClientError,
    SyncRegistryClient,
    compile_resource_query,
)


DEFAULT_HTTP_TIMEOUT = 30.0


@dataclass
class BuyConfig:
    """Buyer identity and discovery configuration for one buy attempt."""

    registry_urls: list[str]
    registry_authorities: dict[str, RegistryAuthority]
    principal: Identity
    signer: Signer = field(repr=False)
    discovery_timeout: Optional[float] = None
    registry_api_keys: dict[str, str] = field(default_factory=dict, repr=False)
    aggregation_policy: Optional[str] = None

    def __post_init__(self) -> None:
        if self.signer.identity != self.principal:
            raise ValueError(
                "buyer signer identity does not match configured principal"
            )
        self.registry_urls = [url.rstrip("/") for url in self.registry_urls]
        if len(set(self.registry_urls)) != len(self.registry_urls):
            raise ValueError("buyer registry URLs contain normalized duplicates")
        if set(self.registry_authorities) != set(self.registry_urls):
            raise ValueError(
                "buyer registry authorities must exactly match registry URLs"
            )
        unknown_api_keys = set(self.registry_api_keys) - set(self.registry_urls)
        if unknown_api_keys:
            raise ValueError(
                f"buyer registry API keys contain unknown URLs: "
                f"{sorted(unknown_api_keys)}"
            )


@dataclass
class BuyConstraints:
    """Domain-interpreted local buyer constraints."""

    max_price: Optional[float] = None
    initial_price: Optional[float] = None
    # Opaque --policy-param key=value pairs for the configured
    # negotiation policy; delivered verbatim to the policy chain's
    # context (ARCHITECTURE.md, "Buyer negotiation policy surface").
    policy_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuyResult:
    status: str
    negotiation_id: Optional[str] = None
    seller_url: Optional[str] = None
    agreed_amount: Optional[int] = None
    escrow_uid: Optional[str] = None
    fulfillment_uid: Optional[str] = None
    connection_details: Optional[str] = None
    tenant_credentials: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
    rounds: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "rounds": self.rounds}
        for k in (
            "negotiation_id",
            "seller_url",
            "agreed_amount",
            "escrow_uid",
            "fulfillment_uid",
            "connection_details",
            "tenant_credentials",
            "reason",
        ):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        if self.attempts:
            out["attempts"] = self.attempts
        return out


@dataclass
class NegotiationResult:
    """Result of a domain buyer negotiation/aggregation hook."""

    match: Optional[dict[str, Any]] = None
    outcome: Optional[Any] = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    reason: str = "no_match_agreed_to_terms"


NegotiateFn = Callable[
    [list[dict[str, Any]], Callable[[str, dict], None]],
    NegotiationResult,
]
SettleFn = Callable[
    [NegotiationResult, Callable[[str, dict], None]],
    BuyResult,
]


def _query_registry_for_matches(
    registry_url: str,
    timeout: float,
    *,
    signer: Signer,
    registry_authority: RegistryAuthority,
    resource_query: str | None,
    compiled_query: CompiledResourceQuery | None,
    status: str,
    limit: int,
    offset: int,
    api_key: str | None,
) -> list[dict[str, Any]]:
    normalized_url = registry_url.rstrip("/")
    try:
        with SyncRegistryClient(
            normalized_url,
            signer=signer,
            caller_role="buyer",
            expected_registries=registry_authority.principals,
            registry_authority=registry_authority.authority,
            timeout=timeout,
            api_key=api_key,
        ) as client:
            bound_query = compiled_query
            if resource_query is not None and bound_query is None:
                bound_query = compile_resource_query(
                    resource_query,
                    filter_spec=client.get_filter_spec(),
                    registry_url=normalized_url,
                )
            if bound_query is not None and bound_query.registry_url != normalized_url:
                raise ValueError("compiled resource query is bound to another registry")
            query_params: dict[str, Any] = {
                "status": status,
                "limit": limit,
                "offset": offset,
                "etag": bound_query.etag if bound_query is not None else None,
            }
            if bound_query is not None:
                query_params.update(bound_query.as_params())
            response = client.list_listings(**query_params)
    except Exception as exc:
        raise RuntimeError(
            f"Authenticated registry read failed for {normalized_url}: {exc}"
        ) from exc
    return [listing.to_dict() for listing in response.listings]


def query_registry_for_matches(
    registry_url: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    *,
    signer: Signer,
    registry_authority: RegistryAuthority,
    resource_query: str | None = None,
    status: str = "open",
    limit: int = 100,
    offset: int = 0,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Compile and read listings through one signed, pinned registry client."""

    return _query_registry_for_matches(
        registry_url,
        timeout,
        signer=signer,
        registry_authority=registry_authority,
        resource_query=resource_query,
        compiled_query=None,
        status=status,
        limit=limit,
        offset=offset,
        api_key=api_key,
    )


@dataclass(frozen=True, slots=True)
class RegistryQueryPlan:
    """Authenticated filter contract and semantic pushdown for one registry."""

    registry_url: str
    etag: str
    schema_id: str | None
    filter_spec_version: int
    schema_version: int | None
    canonical_query: str | None
    parameters: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_url": self.registry_url,
            "filter_spec": {
                "etag": self.etag,
                "version": self.filter_spec_version,
                "schema_id": self.schema_id,
                "schema_version": self.schema_version,
            },
            "canonical_resource_query": self.canonical_query,
            "registry_parameters": dict(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class RegistryDiscovery:
    """Listings plus the authenticated query plans that produced them."""

    listings: tuple[dict[str, Any], ...]
    query_plans: tuple[RegistryQueryPlan, ...]


def _prepare_registry_resource_query(
    registry_url: str,
    timeout: float,
    *,
    signer: Signer,
    registry_authority: RegistryAuthority,
    source: str | None,
    api_key: str | None,
) -> tuple[CompiledResourceQuery | None, RegistryQueryPlan]:
    normalized_url = registry_url.rstrip("/")
    try:
        with SyncRegistryClient(
            normalized_url,
            signer=signer,
            caller_role="buyer",
            expected_registries=registry_authority.principals,
            registry_authority=registry_authority.authority,
            timeout=timeout,
            api_key=api_key,
        ) as client:
            filter_spec = client.get_filter_spec()
            compiled = (
                compile_resource_query(
                    source,
                    filter_spec=filter_spec,
                    registry_url=normalized_url,
                )
                if source is not None
                else None
            )
    except Exception as exc:
        raise RuntimeError(
            f"Resource query is not valid for registry {normalized_url}: {exc}"
        ) from exc
    return compiled, RegistryQueryPlan(
        registry_url=normalized_url,
        etag=filter_spec.etag,
        filter_spec_version=filter_spec.version,
        schema_id=filter_spec.schema_id,
        schema_version=filter_spec.schema_version,
        canonical_query=compiled.canonical_query if compiled is not None else None,
        parameters=compiled.parameters if compiled is not None else (),
    )


def _query_registry_for_matches_multi(
    registry_urls: list[str],
    timeout: float,
    *,
    signer: Signer,
    registry_authorities: dict[str, RegistryAuthority],
    resource_query: str | None,
    status: str,
    limit: int,
    offset: int,
    api_keys: dict[str, str],
    explain: bool,
) -> RegistryDiscovery:
    urls = [url.rstrip("/") for url in registry_urls]
    if set(registry_authorities) != set(urls):
        raise ValueError("registry authority sets must exactly match registry URLs")

    # Complete every authenticated filter-spec compilation before the first
    # listing request. A query must never silently weaken to the subset of
    # registries whose vocabularies happen to accept it.
    compiled_by_url: dict[str, CompiledResourceQuery] = {}
    plans: list[RegistryQueryPlan] = []
    if resource_query is not None or explain:
        for url in urls:
            compiled, plan = _prepare_registry_resource_query(
                url,
                timeout,
                signer=signer,
                registry_authority=registry_authorities[url],
                source=resource_query,
                api_key=api_keys.get(url),
            )
            if compiled is not None:
                compiled_by_url[url] = compiled
            plans.append(plan)

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for url in urls:
        try:
            items = _query_registry_for_matches(
                url,
                timeout,
                signer=signer,
                registry_authority=registry_authorities[url],
                resource_query=None,
                compiled_query=compiled_by_url.get(url),
                status=status,
                limit=limit,
                offset=offset,
                api_key=api_keys.get(url),
            )
        except RuntimeError as exc:
            if resource_query is not None or explain:
                raise
            print(f"[registry] {url}: {exc}", file=sys.stderr)
            continue
        for item in items:
            listing_id = item.get("listing_id")
            if listing_id is None:
                continue
            source = dict(item)
            source["source_registry_url"] = url
            source["source_registry_authority"] = registry_authorities[url].authority
            key = (registry_authorities[url].authority, str(listing_id))
            merged.setdefault(key, source)
    return RegistryDiscovery(tuple(merged.values()), tuple(plans))


def query_registry_for_matches_multi(
    registry_urls: list[str],
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    *,
    signer: Signer,
    registry_authorities: dict[str, RegistryAuthority],
    resource_query: str | None = None,
    status: str = "open",
    limit: int = 100,
    offset: int = 0,
    api_keys: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    """Compile for every registry, then fan in and deduplicate listings."""

    return list(
        _query_registry_for_matches_multi(
            registry_urls,
            timeout,
            signer=signer,
            registry_authorities=registry_authorities,
            resource_query=resource_query,
            status=status,
            limit=limit,
            offset=offset,
            api_keys=api_keys or {},
            explain=False,
        ).listings
    )


def explain_registry_query(
    registry_urls: list[str],
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    *,
    signer: Signer,
    registry_authorities: dict[str, RegistryAuthority],
    resource_query: str | None = None,
    status: str = "open",
    limit: int = 100,
    offset: int = 0,
    api_keys: Optional[dict[str, str]] = None,
) -> RegistryDiscovery:
    """Execute authenticated read-only discovery and retain its query evidence."""

    return _query_registry_for_matches_multi(
        registry_urls,
        timeout,
        signer=signer,
        registry_authorities=registry_authorities,
        resource_query=resource_query,
        status=status,
        limit=limit,
        offset=offset,
        api_keys=api_keys or {},
        explain=True,
    )


def fetch_listing_dict(
    registry_url: str,
    listing_id: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    *,
    signer: Signer,
    registry_authority: RegistryAuthority,
    api_key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Fetch one authority-authenticated listing as a schema-opaque dict."""

    try:
        with SyncRegistryClient(
            registry_url,
            signer=signer,
            caller_role="buyer",
            expected_registries=registry_authority.principals,
            registry_authority=registry_authority.authority,
            timeout=timeout,
            api_key=api_key,
        ) as client:
            return client.get_listing(listing_id).to_dict()
    except RegistryClientError as exc:
        if exc.status_code == 404:
            return None
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        raise RuntimeError(
            f"Authenticated registry read failed for {registry_url.rstrip('/')}: {exc}"
        ) from exc


def fetch_listing_dict_multi(
    registry_urls: list[str],
    listing_id: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    *,
    signer: Signer,
    registry_authorities: dict[str, RegistryAuthority],
    api_keys: Optional[dict[str, str]] = None,
) -> Optional[dict[str, Any]]:
    """Try each pinned registry in order and return the first listing hit."""

    urls = [url.rstrip("/") for url in registry_urls]
    if set(registry_authorities) != set(urls):
        raise ValueError("registry authority sets must exactly match registry URLs")
    api_keys = api_keys or {}
    last_error: Optional[Exception] = None
    for url in urls:
        try:
            result = fetch_listing_dict(
                url,
                listing_id,
                timeout=timeout,
                signer=signer,
                registry_authority=registry_authorities[url],
                api_key=api_keys.get(url),
            )
        except RuntimeError as exc:
            print(f"[registry] {url}: {exc}", file=sys.stderr)
            last_error = exc
            continue
        if result is not None:
            return result
    if last_error is not None:
        raise last_error
    return None


def run_buy(
    *,
    config: BuyConfig,
    constraints: BuyConstraints,
    provision: Any,
    negotiate: NegotiateFn,
    settle: SettleFn,
    matches: Optional[list[dict[str, Any]]] = None,
    max_matches_to_try: int = 5,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> BuyResult:
    """Run one buyer attempt end to end over injected domain hooks."""

    def _event(stage: str, payload: dict) -> None:
        if on_event:
            on_event(stage, payload)

    if matches is None:
        kwargs: dict[str, Any] = {}
        if config.discovery_timeout is not None:
            kwargs["timeout"] = config.discovery_timeout
        matches = query_registry_for_matches_multi(
            config.registry_urls,
            signer=config.signer,
            registry_authorities=config.registry_authorities,
            api_keys=config.registry_api_keys,
            **kwargs,
        )
    _event("discover", {"match_count": len(matches)})

    if not matches:
        return BuyResult(status="no_matches")

    capped = matches[:max_matches_to_try]
    from core_buyer.aggregation import DEFAULT_POLICY_NAME

    _event(
        "aggregated",
        {
            "policy": config.aggregation_policy or DEFAULT_POLICY_NAME,
            "match_count_after_cap": len(capped),
        },
    )

    try:
        negotiation = negotiate(capped, _event)
    except RuntimeError as exc:
        return BuyResult(
            status="exited",
            reason=f"policy_error: {exc}",
            attempts=[],
        )

    if negotiation.match is None or negotiation.outcome is None:
        return BuyResult(
            status="exited",
            reason=negotiation.reason,
            attempts=negotiation.attempts,
        )

    return settle(negotiation, _event)
