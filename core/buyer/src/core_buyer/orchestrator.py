"""Core buyer role orchestration.

This module owns the schema-invariant buyer skeleton:

    discover -> negotiate/aggregate -> settle

The listing schema, negotiation policy, settlement mechanism, CLI, and run-log
format are injected by a domain package. Core only owns the control flow and
the generic registry discovery helpers.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


DEFAULT_HTTP_TIMEOUT = 30.0


@dataclass
class BuyConfig:
    """Buyer identity and discovery configuration for one buy attempt."""

    registry_urls: list[str]
    buyer_address: str
    buyer_private_key: str
    discovery_timeout: Optional[float] = None
    indexer_auth: dict[str, str] = field(default_factory=dict)
    aggregation_policy: Optional[str] = None


@dataclass
class BuyConstraints:
    """Domain-interpreted local buyer constraints."""

    max_price: Optional[float] = None
    initial_price: Optional[float] = None
    # Opaque --policy-param key=value pairs for the configured
    # negotiation policy; delivered verbatim to the policy chain's
    # context (design-negotiation-policy-surface.md).
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
    filters: Optional[dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Ask one registry for open seller listings, optionally pre-filtered."""
    base_params: dict[str, Any] = {"status": "open"}
    if filters:
        for key, val in filters.items():
            if val is None:
                continue
            base_params[key] = "true" if val is True else "false" if val is False else val
    url = registry_url.rstrip("/") + "/listings?" + urllib.parse.urlencode(base_params)
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"Registry GET {url} -> HTTP {exc.code}: {detail[:200]}") from exc
    except Exception as exc:
        raise RuntimeError(f"Registry GET {url} failed: {exc}") from exc

    try:
        payload = json.loads(text) if text else []
    except ValueError as exc:
        raise RuntimeError(f"Registry returned non-JSON: {text[:200]!r}") from exc

    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("listings") or payload.get("data") or []
    else:
        items = payload
    if not isinstance(items, list):
        return []

    return items


def query_registry_for_matches_multi(
    registry_urls: list[str],
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    *,
    filters: Optional[dict[str, Any]] = None,
    auth: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    """Fan in registry listings and dedupe by listing id."""
    merged: dict[str, dict[str, Any]] = {}
    auth = auth or {}
    for url in registry_urls:
        try:
            items = query_registry_for_matches(
                url, timeout=timeout, filters=filters, api_key=auth.get(url),
            )
        except RuntimeError as exc:
            print(f"[registry] {url}: {exc}", file=sys.stderr)
            continue
        for item in items:
            lid = item.get("listing_id") or item.get("id")
            if lid is None:
                continue
            merged.setdefault(str(lid), item)
    return list(merged.values())


def fetch_listing_dict(
    registry_url: str,
    listing_id: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    *,
    api_key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Fetch one registry listing by id as a raw dict."""
    url = registry_url.rstrip("/") + "/listings/" + urllib.parse.quote(listing_id, safe="")
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"Registry GET {url} -> HTTP {exc.code}: {detail[:200]}") from exc
    except Exception as exc:
        raise RuntimeError(f"Registry GET {url} failed: {exc}") from exc

    try:
        payload = json.loads(text) if text else None
    except ValueError:
        return None
    if isinstance(payload, dict):
        return payload.get("listing") if "listing" in payload else payload
    return None


def fetch_listing_dict_multi(
    registry_urls: list[str],
    listing_id: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    *,
    auth: Optional[dict[str, str]] = None,
) -> Optional[dict[str, Any]]:
    """Try each registry in order and return the first listing hit."""
    auth = auth or {}
    last_error: Optional[Exception] = None
    for url in registry_urls:
        try:
            result = fetch_listing_dict(url, listing_id, timeout=timeout, api_key=auth.get(url))
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
        if config.indexer_auth:
            kwargs["auth"] = config.indexer_auth
        matches = query_registry_for_matches_multi(config.registry_urls, **kwargs)
    _event("discover", {"match_count": len(matches)})

    if not matches:
        return BuyResult(status="no_matches")

    capped = matches[:max_matches_to_try]
    _event("aggregated", {
        "policy": config.aggregation_policy or "best_price",
        "match_count_after_cap": len(capped),
    })

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
