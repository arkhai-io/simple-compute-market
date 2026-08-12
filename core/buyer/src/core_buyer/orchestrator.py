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
from registry_client import RegistryClientError, SyncRegistryClient


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


def query_registry_for_matches(
    registry_url: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    *,
    signer: Signer,
    registry_authority: RegistryAuthority,
    filters: Optional[dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Read open listings through a signed, authority-pinned registry client."""

    params = dict(filters or {})
    status = params.pop("status", "open")
    limit = int(params.pop("limit", 100))
    offset = int(params.pop("offset", 0))
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
            response = client.list_listings(
                status=status,
                limit=limit,
                offset=offset,
                **params,
            )
    except Exception as exc:
        raise RuntimeError(
            f"Authenticated registry read failed for {registry_url.rstrip('/')}: {exc}"
        ) from exc
    return [listing.to_dict() for listing in response.listings]


def query_registry_for_matches_multi(
    registry_urls: list[str],
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    *,
    signer: Signer,
    registry_authorities: dict[str, RegistryAuthority],
    filters: Optional[dict[str, Any]] = None,
    api_keys: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    """Fan in signed registry listings and deduplicate by listing identity."""

    urls = [url.rstrip("/") for url in registry_urls]
    if set(registry_authorities) != set(urls):
        raise ValueError("registry authority sets must exactly match registry URLs")
    api_keys = api_keys or {}
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for url in urls:
        try:
            items = query_registry_for_matches(
                url,
                timeout=timeout,
                signer=signer,
                registry_authority=registry_authorities[url],
                filters=filters,
                api_key=api_keys.get(url),
            )
        except RuntimeError as exc:
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
    return list(merged.values())


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
