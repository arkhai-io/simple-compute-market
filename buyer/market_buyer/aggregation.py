"""Pluggable across-seller match aggregation.

A single registry-fanout query usually returns multiple matching listings
from different sellers. The orchestrator (``buy_orchestrator.run_buy``)
walks them in order and tries each one until a negotiation succeeds.
What "in order" means is the across-seller aggregation policy.

Today the default policy is ``cheapest_first`` — sort by the seller's
advertised ``demand.amount`` (per-hour rate). Anyone can register a
different policy that scores or re-orders matches based on whatever
signal they care about (historical settlement success rate, geographic
proximity, attestation/reputation registry lookups, round-robin to
spread load, etc.) without modifying the orchestrator.

Shape:

    @register_aggregation_policy("most_recent")
    def _by_recency(matches: list[dict]) -> list[dict]:
        return sorted(matches, key=lambda m: m.get("created_at") or "", reverse=True)

The orchestrator looks up the policy by name (TOML
``[buyer.aggregation].policy`` or CLI ``--aggregate-by``), defaulting
to ``cheapest_first`` when nothing is set.

A policy that returns an empty list is honored — the orchestrator
treats it as ``no_matches``. A policy that filters out everything is
the right shape for "I refuse to deal with anyone in this batch; ask
the registry again later."
"""
from __future__ import annotations

import json
import random as _random
from typing import Any, Callable

# A policy is a pure function: (matches) -> reordered/filtered matches.
# Stateless so it composes well; per-deal context (constraints, history)
# can be injected via closures at registration time if needed.
AggregationPolicy = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


_REGISTRY: dict[str, AggregationPolicy] = {}

DEFAULT_POLICY_NAME = "cheapest_first"


def register_aggregation_policy(name: str) -> Callable[[AggregationPolicy], AggregationPolicy]:
    """Decorator. Registers a named aggregation policy.

    Names must be unique. Re-registering the same name overwrites the
    previous binding — useful for tests.
    """
    def _decorator(fn: AggregationPolicy) -> AggregationPolicy:
        _REGISTRY[name] = fn
        return fn
    return _decorator


def load_aggregation_policy(name: str | None) -> AggregationPolicy:
    """Look up a registered policy by name. ``None`` returns the default."""
    if not name:
        name = DEFAULT_POLICY_NAME
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown across-seller aggregation policy: {name!r}. "
            f"Registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def list_aggregation_policies() -> list[str]:
    """Names of all registered policies (for CLI help / introspection)."""
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Built-in policies
# ---------------------------------------------------------------------------


def _extract_advertised_price(match: dict[str, Any]) -> int | None:
    """Pull the per-hour advertised price from a match's demand_resource.

    Mirrors ``buy_orchestrator.extract_seller_min_price`` but kept local
    to avoid a circular import. Returns ``None`` for unparseable or
    price-less listings (amount=0 / null).
    """
    demand = match.get("demand_resource") or match.get("demand") or {}
    if isinstance(demand, str):
        try:
            demand = json.loads(demand)
        except (ValueError, TypeError):
            return None
    if not isinstance(demand, dict):
        return None
    amount = demand.get("amount")
    try:
        parsed = int(amount) if amount is not None else None
    except (ValueError, TypeError):
        return None
    if parsed is None or parsed <= 0:
        return None
    return parsed


@register_aggregation_policy("cheapest_first")
def _cheapest_first(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort matches by their advertised per-hour price (low to high).

    Listings with no parseable price (price-less / malformed) sort to
    the end — the buyer's other flags (--initial-price, --max-price)
    handle those, but they shouldn't crowd out priced matches.
    """
    def _key(m: dict[str, Any]) -> tuple[int, int]:
        price = _extract_advertised_price(m)
        if price is None:
            return (1, 0)  # bucket 1: no price, original order within
        return (0, price)
    return sorted(matches, key=_key)


@register_aggregation_policy("registry_order")
def _registry_order(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """No-op: pass matches through in whatever order the registry returned.

    Useful when the registry's own sorting already encodes the operator's
    preference (e.g. a custom registry sorts by reputation), or when
    debugging the registry's response shape.
    """
    return list(matches)


@register_aggregation_policy("random_shuffle")
def _random_shuffle(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shuffle uniformly at random. Useful for load-spreading across
    sellers when the price differences are immaterial."""
    out = list(matches)
    _random.shuffle(out)
    return out


@register_aggregation_policy("priceless_last")
def _priceless_last(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Priced listings first (cheapest first), then price-less listings
    in registry order. Useful when the buyer wants to anchor on
    advertised prices but is willing to make-an-offer if no priced
    listings work out."""
    priced: list[tuple[int, int, dict[str, Any]]] = []
    priceless: list[tuple[int, dict[str, Any]]] = []
    for idx, m in enumerate(matches):
        p = _extract_advertised_price(m)
        if p is None:
            priceless.append((idx, m))
        else:
            priced.append((p, idx, m))
    priced.sort(key=lambda t: (t[0], t[1]))
    priceless.sort(key=lambda t: t[0])
    return [m for _, _, m in priced] + [m for _, m in priceless]
