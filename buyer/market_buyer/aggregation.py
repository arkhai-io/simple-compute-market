"""Pluggable across-seller aggregation: candidates + negotiate → one deal.

A buyer's "what should I buy?" decision spans several discovered
listings. The aggregation policy is the seam that owns that decision.
It receives the post-discovery candidates *and* a ``negotiate``
callback; it decides how many candidates to negotiate with, in what
order, in parallel or sequence, and which agreed deal to return.

Shape::

    NegotiateFn = Callable[[dict], Awaitable[NegotiationOutcome]]
    AggregationPolicy = Callable[
        [list[dict], NegotiateFn],
        Awaitable[tuple[dict, NegotiationOutcome] | None],
    ]

The policy returns ``(listing, outcome)`` for the winner — or ``None``
to abort settlement (no candidate met its bar). The orchestrator then
settles exactly that one pair. The policy is the only thing that
knows the comparison rule, so the orchestrator stays dumb.

Built-in flavors:

- ``cheapest_first`` — sort by advertised price, negotiate sequentially,
  first agreed wins. The historical default: same effective behavior
  as the pre-callback loop, ported onto the new protocol.
- ``registry_order`` — pass through in registry order, otherwise
  sequential-first-agreed.
- ``random_shuffle`` — shuffle for load spreading, sequential-first-agreed.
- ``priceless_last`` — priced cheapest first, priceless after.
- ``best_price`` — negotiate with *all* candidates in parallel, pick
  the lowest agreed_price. The canonical "comparison shopping" example.

Forward compatibility: returning ``tuple | None`` rather than a list
means today's single-settlement orchestrator can consume the result as
is. When multi-buy lands (plural ``BuyResult`` + plural settlement),
widen this return to ``list[tuple]`` — four built-ins to port, no
deeper structural change.

Failure semantics: ``negotiate`` propagates exceptions. The policy
decides whether to swallow them (see ``gather_outcomes`` helper) or
fail the whole buy. Surfaces all state instead of pre-filtering it.

Registration / discovery:

    @register_aggregation_policy("my_strat")
    async def _my(matches, negotiate):
        ...

Third-party plugins publish entry points in group
``market_buyer.aggregation_policies``; ``load_aggregation_policy``
consults that group as a fallback after the in-process registry.
"""
from __future__ import annotations

import asyncio
import json
import random as _random
from typing import Any, Awaitable, Callable

from .buyer_client import NegotiationOutcome


NegotiateFn = Callable[[dict[str, Any]], Awaitable[NegotiationOutcome]]
"""Per-candidate negotiation callback. Curried by the orchestrator from
``negotiate_with_seller`` — everything except the candidate itself
(buyer keys, ceiling, duration, max_rounds) is already bound.
Returns a ``NegotiationOutcome``; raises on network/signature failure
so the policy sees the actual error."""

AggregationPolicy = Callable[
    [list[dict[str, Any]], NegotiateFn],
    Awaitable[tuple[dict[str, Any], NegotiationOutcome] | None],
]


_REGISTRY: dict[str, AggregationPolicy] = {}

DEFAULT_POLICY_NAME = "cheapest_first"


def register_aggregation_policy(
    name: str,
) -> Callable[[AggregationPolicy], AggregationPolicy]:
    """Decorator. Registers a named aggregation policy.

    Names must be unique within a process. Re-registering overwrites —
    useful for tests and for local override of built-ins.
    """
    def _decorator(fn: AggregationPolicy) -> AggregationPolicy:
        _REGISTRY[name] = fn
        return fn
    return _decorator


def load_aggregation_policy(name: str | None) -> AggregationPolicy:
    """Resolve a policy by name. ``None`` returns the default.

    Lookup order:
    1. In-process registry (built-ins + ``register_aggregation_policy``).
    2. Python entry points in group ``market_buyer.aggregation_policies``.
    """
    if not name:
        name = DEFAULT_POLICY_NAME
    if name in _REGISTRY:
        return _REGISTRY[name]

    try:
        import importlib.metadata as md
        eps = md.entry_points(group="market_buyer.aggregation_policies")
    except Exception:
        eps = []
    for ep in eps:
        if ep.name == name:
            loaded = ep.load()
            _REGISTRY[name] = loaded
            return loaded

    raise ValueError(
        f"Unknown across-seller aggregation policy: {name!r}. "
        f"Registered: {sorted(_REGISTRY)}"
    )


def list_aggregation_policies() -> list[str]:
    """Names of all registered policies (for CLI help / introspection)."""
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Helpers for policy authors
# ---------------------------------------------------------------------------


async def gather_outcomes(
    negotiate: NegotiateFn,
    candidates: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], NegotiationOutcome | BaseException]]:
    """Run ``negotiate`` against every candidate concurrently.

    Each task's exception is captured in the result tuple rather than
    propagated — the policy can then filter / inspect / re-raise as it
    chooses. The orchestrator never silently swallows; this helper is
    opt-in for policies that explicitly want resilient comparison.
    """
    async def _one(
        c: dict[str, Any],
    ) -> tuple[dict[str, Any], NegotiationOutcome | BaseException]:
        try:
            return (c, await negotiate(c))
        except BaseException as exc:  # noqa: BLE001 — policy-author convenience
            return (c, exc)

    return await asyncio.gather(*(_one(c) for c in candidates))


def _extract_advertised_price(match: dict[str, Any]) -> int | None:
    """Pull the per-hour advertised price from a match's demand_resource."""
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


async def _sequential_first_agreed(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Walk candidates in order; first ``status=="agreed"`` wins."""
    for c in candidates:
        outcome = await negotiate(c)
        if outcome.status == "agreed" and outcome.agreed_price is not None:
            return (c, outcome)
    return None


# ---------------------------------------------------------------------------
# Built-in policies
# ---------------------------------------------------------------------------


@register_aggregation_policy("cheapest_first")
async def _cheapest_first(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Sort by advertised price ascending, negotiate sequentially, first agreed wins.

    Priceless listings sort to the end. Same effective behavior as the
    pre-callback loop default — preserves backward compatibility.
    """
    def _key(m: dict[str, Any]) -> tuple[int, int]:
        price = _extract_advertised_price(m)
        if price is None:
            return (1, 0)
        return (0, price)

    return await _sequential_first_agreed(sorted(candidates, key=_key), negotiate)


@register_aggregation_policy("registry_order")
async def _registry_order(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """No-op order: take registry's response order, first agreed wins."""
    return await _sequential_first_agreed(list(candidates), negotiate)


@register_aggregation_policy("random_shuffle")
async def _random_shuffle(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Uniform shuffle for load spreading. First agreed wins."""
    shuffled = list(candidates)
    _random.shuffle(shuffled)
    return await _sequential_first_agreed(shuffled, negotiate)


@register_aggregation_policy("priceless_last")
async def _priceless_last(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Priced cheapest first, then priceless. Sequential-first-agreed."""
    priced: list[tuple[int, int, dict[str, Any]]] = []
    priceless: list[tuple[int, dict[str, Any]]] = []
    for idx, m in enumerate(candidates):
        p = _extract_advertised_price(m)
        if p is None:
            priceless.append((idx, m))
        else:
            priced.append((p, idx, m))
    priced.sort(key=lambda t: (t[0], t[1]))
    priceless.sort(key=lambda t: t[0])
    ordered = [m for _, _, m in priced] + [m for _, m in priceless]
    return await _sequential_first_agreed(ordered, negotiate)


@register_aggregation_policy("best_price")
async def _best_price(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Negotiate with every candidate in parallel; pick the lowest agreed price.

    The canonical "comparison shopping" example. Costs N negotiations
    of wall time at most — bound the candidate list upstream
    (``max_matches_to_try``) to control fan-out. Per-candidate failures
    are skipped, not raised; if you want failures to abort the buy,
    write a policy that doesn't use ``gather_outcomes``.
    """
    results = await gather_outcomes(negotiate, candidates)
    agreed: list[tuple[dict[str, Any], NegotiationOutcome]] = []
    for c, r in results:
        if isinstance(r, NegotiationOutcome) \
                and r.status == "agreed" \
                and r.agreed_price is not None:
            agreed.append((c, r))
    if not agreed:
        return None
    return min(agreed, key=lambda p: p[1].agreed_price or 0)
