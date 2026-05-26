"""Negotiation middleware framework.

A negotiation policy is expressed as a chain of middlewares. Each
middleware has the signature::

    middleware(history, context) -> (Maybe<NegotiationDecision>, NegotiationContext)

A ``NegotiationDecision`` from a middleware terminates the chain and
becomes the round's response. ``None`` lets the chain continue with
the (possibly updated) ``NegotiationContext`` threaded into the next
middleware. The terminal middleware in any chain (typically
``bisection`` or ``rl``) must always return Some — otherwise the
chain runner raises.

The framework is symmetric: buyer and seller both build chains and
invoke ``run_negotiation_chain``. The seller's chain typically
includes guards (inventory match, escrow shape) before the terminal
strategy; the buyer's chain is often just the terminal strategy
alone. Operators add custom middlewares by ``@register_negotiation_middleware``
on their own module or by Python entry point.

The composite is wired in TOML::

    [negotiation]
    chain = ["has_matching_inventory_guard", "escrow_shape_guard", "bisection"]

``load_negotiation_chain`` resolves names against the in-process
registry → file-based discovery → entry points (matching the pattern
in ``buyer/market_buyer/aggregation.py``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NegotiationRound:
    """One round's transcript entry. Both parties contribute one per round."""

    round_number: int
    sender: Literal["us", "them"]
    action: Literal["initial", "counter", "accept", "exit", "reject"]
    price: float | None = None  # set for initial / counter / accept; base units per hour


@dataclass(frozen=True)
class NegotiationDecision:
    """One round's resulting decision.

    ``action="reject"`` is reserved for pre-flight guard vetoes (caller
    maps to HTTP 409). Terminal strategies use ``"counter"``, ``"accept"``,
    or ``"exit"``.
    """

    action: Literal["accept", "counter", "exit", "reject"]
    price: float | None = None  # required for counter / accept; base units per hour
    reason: str | None = None  # required for exit / reject; optional otherwise

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"action": self.action}
        if self.price is not None:
            d["price"] = self.price
        if self.reason is not None:
            d["reason"] = self.reason
        return d


@dataclass
class NegotiationContext:
    """State a middleware needs beyond the per-round history.

    Set once at the start of a negotiation by the caller (seller storefront
    on ``POST /negotiate/new``; buyer orchestrator at negotiation start).
    Middlewares may mutate ``intermediate`` to record computed state for
    downstream middlewares to read without recomputing.

    Fields:
        direction: ``"maximize"`` (seller) or ``"minimize"`` (buyer).
        our_reference_price: Seller's floor or buyer's ceiling.
        listing: Full listing row (offer_resource, accepted_escrows, status, ...).
            Guards consult this; the terminal strategy typically doesn't.
        escrow_proposal: Buyer's escrow shape proposal (set by seller side
            on round 0; None on buyer side).
        available_resources: Snapshot of the seller's portfolio at negotiation
            start, for the inventory guard. ``{"resources": [...]}``. Empty
            dict on buyer side.
        max_rounds: Cap on negotiation rounds before the chain exits.
        intermediate: Mutable scratchpad for middleware-computed state.
    """

    direction: Literal["minimize", "maximize"]
    our_reference_price: float
    listing: dict[str, Any] = field(default_factory=dict)
    escrow_proposal: dict[str, Any] | None = None
    available_resources: dict[str, Any] = field(default_factory=dict)
    max_rounds: int = 10
    intermediate: dict[str, Any] = field(default_factory=dict)


# A middleware step: (decision-if-terminal, possibly-updated-context).
NegotiationStep = tuple[Optional[NegotiationDecision], NegotiationContext]

NegotiationMiddleware = Callable[
    [list[NegotiationRound], NegotiationContext],
    NegotiationStep,
]


def their_proposed_price(history: list[NegotiationRound]) -> Optional[float]:
    """Most recent price the other side proposed. None if they haven't yet."""
    for round_ in reversed(history):
        if round_.sender == "them" and round_.price is not None:
            return float(round_.price)
    return None


def our_previous_counters(history: list[NegotiationRound]) -> list[float]:
    """Prices we counter-proposed in earlier rounds, oldest first."""
    return [
        h.price for h in history
        if h.sender == "us" and h.action == "counter" and h.price is not None
    ]


# ---------------------------------------------------------------------------
# Chain runner
# ---------------------------------------------------------------------------


def run_negotiation_chain(
    chain: list[NegotiationMiddleware],
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationDecision:
    """Run the middleware chain and return the first decision produced.

    Each middleware sees the same history and the context threaded by
    upstream middlewares. The first middleware to return Some terminates
    the chain. The terminal middleware MUST always return Some — if the
    chain exhausts without a decision the configuration is broken and we
    raise (operator misconfigured the TOML or omitted the terminal).
    """
    for mw in chain:
        decision, context = mw(history, context)
        if decision is not None:
            return decision
    raise RuntimeError(
        "Negotiation chain exhausted without a decision. The terminal "
        "middleware (typically 'bisection' or 'rl') must always return Some. "
        "Check [negotiation].chain config."
    )


# ---------------------------------------------------------------------------
# Registry + loader
# ---------------------------------------------------------------------------


_REGISTRY: dict[str, NegotiationMiddleware] = {}


def register_negotiation_middleware(name: str):
    """Decorator. Registers a middleware function under a stable name.

    Names must be unique within a process. Re-registering overwrites —
    useful for tests and local override of built-ins.
    """
    def _decorator(fn: NegotiationMiddleware) -> NegotiationMiddleware:
        _REGISTRY[name] = fn
        return fn
    return _decorator


_FILE_DISCOVERY_TRIGGERED = False


def _discover_file_middlewares() -> None:
    """One-shot scan for ``negotiation_middleware`` extension files.

    Mirrors ``buyer/market_buyer/aggregation.py::_discover_file_policies``.
    Operators drop a python file with ``@register_negotiation_middleware``
    decorators into the configured extensions dir; this scanner imports
    them so they end up in ``_REGISTRY`` before ``load_negotiation_chain``
    looks them up.
    """
    global _FILE_DISCOVERY_TRIGGERED
    if _FILE_DISCOVERY_TRIGGERED:
        return
    _FILE_DISCOVERY_TRIGGERED = True
    # Extension discovery via env var is left as a follow-up — the
    # built-ins below + entry points cover today's needs. Operators who
    # need file-based discovery can copy the pattern from
    # buyer/market_buyer/aggregation.py.


def load_negotiation_chain(
    names: list[str] | None,
    *,
    per_middleware_config: dict[str, dict[str, Any]] | None = None,
) -> list[NegotiationMiddleware]:
    """Resolve a list of middleware names to a chain of callables.

    Lookup order for each name:
      1. In-process ``_REGISTRY``.
      2. Python entry points in group ``market_policy.negotiation_middlewares``.

    Raises ``KeyError`` with an actionable message on unknown names so
    operator-typed TOML errors surface at startup, not at request time.

    ``per_middleware_config`` is reserved for parameterized middlewares
    (e.g. ``max_rounds_guard`` taking a custom ``max_rounds`` value); the
    base registry stores configurable middleware factories under names
    when needed. Today's built-ins are config-free callables.
    """
    if not names:
        raise ValueError(
            "load_negotiation_chain requires a non-empty list of middleware names. "
            "Configure [negotiation].chain in your TOML."
        )

    _discover_file_middlewares()

    chain: list[NegotiationMiddleware] = []
    for name in names:
        if name in _REGISTRY:
            chain.append(_REGISTRY[name])
            continue
        try:
            import importlib.metadata as md
            eps = md.entry_points(group="market_policy.negotiation_middlewares")
        except Exception:
            eps = []
        found = False
        for ep in eps:
            if ep.name == name:
                loaded = ep.load()
                _REGISTRY[name] = loaded
                chain.append(loaded)
                found = True
                break
        if not found:
            available = sorted(_REGISTRY.keys())
            raise KeyError(
                f"Unknown negotiation middleware: {name!r}. "
                f"Registered: {available}. "
                f"For built-ins, ensure the policy package is imported (the "
                f"storefront does this at startup)."
            )

    return chain


def list_negotiation_middlewares() -> list[str]:
    """Names of all registered middlewares (for CLI help / introspection)."""
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Built-in: bisection — terminal middleware
# ---------------------------------------------------------------------------


DEFAULT_CONVERGENCE_RATIO = 0.01  # accept when peer is within 1% of our reference
DEFAULT_REASONABLE_MULTIPLIER = 1.5  # exit when peer is more than 1.5× off our reference


@register_negotiation_middleware("bisection")
def bisection_middleware(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Price-midpoint counter-offer with convergence + stale-counter guards.

    The historical default. Rule-based, deterministic, no model files.
    Terminal: always returns Some (never defers).

    For ``direction="minimize"`` (buyer-shape): accept if peer price ≤
    our ceiling × (1 + ε); counter at the midpoint of (our_ceiling,
    their_price), clamped to ≤ our_ceiling; exit if peer price > our
    ceiling × 1.5.

    For ``direction="maximize"`` (seller-shape): accept if peer price ≥
    our floor × (1 - ε); counter at the midpoint of (our_floor, their_price);
    exit if peer price < our_floor / 1.5.

    Both sides exit after ``context.max_rounds`` rounds or two consecutive
    identical counters (built-in stale-counter guard).
    """
    counters = our_previous_counters(history)

    if len(counters) >= context.max_rounds:
        return NegotiationDecision(action="exit", reason="max_rounds"), context
    if len(counters) >= 2 and counters[-1] == counters[-2]:
        return NegotiationDecision(action="exit", reason="stale_negotiation"), context

    our_price = context.our_reference_price
    their_price = their_proposed_price(history)

    if their_price is None:
        # First call: open with our reference (ceiling for minimize, floor for maximize).
        return NegotiationDecision(action="counter", price=our_price), context

    conv = DEFAULT_CONVERGENCE_RATIO
    reasonable = DEFAULT_REASONABLE_MULTIPLIER

    if context.direction == "minimize":
        if their_price <= our_price * (1 + conv):
            return (
                NegotiationDecision(action="accept", price=their_price, reason="convergence"),
                context,
            )
        if their_price <= our_price * reasonable:
            proposed = (our_price + their_price) / 2
            if proposed > our_price:
                proposed = our_price  # never counter above our ceiling
            return NegotiationDecision(action="counter", price=proposed), context
        return NegotiationDecision(action="exit", reason="price_unreasonable"), context

    if context.direction == "maximize":
        if their_price >= our_price * (1 - conv):
            return (
                NegotiationDecision(action="accept", price=their_price, reason="convergence"),
                context,
            )
        if their_price >= our_price / reasonable:
            proposed = (our_price + their_price) / 2
            return NegotiationDecision(action="counter", price=proposed), context
        return NegotiationDecision(action="exit", reason="price_unreasonable"), context

    return (
        NegotiationDecision(action="reject", reason=f"unknown_direction:{context.direction!r}"),
        context,
    )


# ---------------------------------------------------------------------------
# Built-in guards
# ---------------------------------------------------------------------------


_ZERO_ADDRESS = "0x" + "0" * 40


def _coerce_resource_dict(value: Any) -> dict[str, Any]:
    """Listings persist offer_resource as JSON text; normalise to a dict."""
    import json
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalize_escrow_field(value: Any) -> Any:
    """Case-insensitive compare for hex addresses; identity otherwise."""
    if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
        return value.lower()
    return value


@register_negotiation_middleware("has_matching_inventory_guard")
def has_matching_inventory_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Veto a negotiation when no available portfolio resource matches the
    listing's offer (gpu_model + region).

    Designed for the *immediate-deal* seller: capacity must exist now.
    Operators running futures or off-chain-matched flows drop this guard
    from ``[negotiation].chain`` — the seller then accepts threads against
    listings whose inventory will materialise later.

    Reads ``context.available_resources["resources"]`` (populated by the
    seller's request handler from ``db.list_resources()``); never mutates
    state. Listings whose offer isn't compute (token swaps) pass through —
    capacity for those is enforced by the chain.

    This guard is seller-side. Buyer chains should omit it (the buyer's
    context typically has no ``available_resources``).
    """
    offer = _coerce_resource_dict(context.listing.get("offer_resource"))
    if "gpu_model" not in offer:
        return None, context  # not a compute listing — pass through

    required: dict[str, Any] = {}
    for key in ("region", "gpu_model"):
        v = offer.get(key)
        if v is not None:
            required[key] = v

    portfolio_raw = (context.available_resources or {}).get("resources") or []

    import json
    for row in portfolio_raw:
        # ``available_resources`` carries full SQLite rows — only
        # ``state == 'available'`` rows are eligible.
        if (row.get("state") or "").strip() != "available":
            continue
        attrs = row.get("attributes")
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except (ValueError, TypeError):
                continue
        if not isinstance(attrs, dict):
            continue
        if all(attrs.get(k) == v for k, v in required.items()):
            return None, context  # found a match, pass

    return (
        NegotiationDecision(action="reject", reason="no_matching_inventory"),
        context,
    )


@register_negotiation_middleware("escrow_shape_guard")
def escrow_shape_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Veto when the buyer's escrow proposal diverges from the seller's
    advertised ``accepted_escrows`` entry on any seller-pinned field.

    Strict equality: every key the seller set on the matched entry's
    ``fields`` map must equal the buyer's value. Operators wanting softer
    matching (allow arbiter upgrade, swap payment token, etc.) drop this
    guard from ``[negotiation].chain`` and write their own.

    Passes through when:
      * ``context.escrow_proposal`` is None (legacy buyer client),
      * listing has no ``accepted_escrows`` advertised,
      * proposal's ``escrow_address`` is the zero placeholder.

    The structural ``(chain, address)`` lookup against ``accepted_escrows``
    is protocol-fixed shape resolution and lives in ``sync_negotiation``.
    This guard only enforces the *seller's* opinion about which fields
    must match.
    """
    proposal = context.escrow_proposal
    if not isinstance(proposal, dict):
        return None, context

    listing = context.listing or {}
    accepted = listing.get("accepted_escrows")
    if isinstance(accepted, str):
        import json
        try:
            accepted = json.loads(accepted)
        except (ValueError, TypeError):
            return None, context
    if not isinstance(accepted, list) or not accepted:
        return None, context

    proposal_addr_raw = proposal.get("escrow_address")
    if not isinstance(proposal_addr_raw, str) or not proposal_addr_raw:
        return None, context
    proposal_addr = proposal_addr_raw.lower()
    if proposal_addr == _ZERO_ADDRESS:
        return None, context

    proposal_chain = proposal.get("chain_name")
    proposal_fields = proposal.get("fields") or {}

    matched: dict[str, Any] | None = None
    for entry in accepted:
        if not isinstance(entry, dict):
            continue
        entry_addr = entry.get("escrow_address")
        if (
            entry.get("chain_name") == proposal_chain
            and isinstance(entry_addr, str)
            and entry_addr.lower() == proposal_addr
        ):
            matched = entry
            break
    if matched is None:
        # No structural match — protocol layer in sync_negotiation handles
        # "address advertised but not in set". Don't double-report.
        return None, context

    seller_fields = matched.get("fields") or {}
    if not isinstance(seller_fields, dict):
        return None, context

    for key, seller_value in seller_fields.items():
        buyer_value = proposal_fields.get(key) if isinstance(proposal_fields, dict) else None
        if _normalize_escrow_field(buyer_value) != _normalize_escrow_field(seller_value):
            return (
                NegotiationDecision(
                    action="reject",
                    reason=(
                        f"escrow_field_mismatch: field {key!r} — buyer "
                        f"proposed {buyer_value!r}, listing requires "
                        f"{seller_value!r}"
                    ),
                ),
                context,
            )
    return None, context


@register_negotiation_middleware("max_rounds_guard")
def max_rounds_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Exit when our previous counters have hit ``context.max_rounds``.

    Pure round counter — the bisection terminal also enforces this
    internally so it's safe to omit, but having it as a separate
    middleware lets operators run a chain like
    ``[max_rounds_guard, custom_strategy]`` where ``custom_strategy``
    might not check round count itself.
    """
    counters = our_previous_counters(history)
    if len(counters) >= context.max_rounds:
        return (
            NegotiationDecision(action="exit", reason="max_rounds"),
            context,
        )
    return None, context
