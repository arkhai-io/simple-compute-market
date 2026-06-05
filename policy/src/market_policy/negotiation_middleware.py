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
    """One round's transcript entry. Both parties contribute one per round.

    ``proposal`` is the full EscrowProposal-shaped dict for the round
    (``chain_name``, ``escrow_address``, ``fields``, ``expiration_unix``).
    The negotiated scalar — the absolute payment amount in base units of
    the escrow's payment token — lives in ``proposal["fields"]["amount"]``
    for ERC20-style escrows. Per-hour rates are a broadcast-only concept
    on listings; once a negotiation starts, every round carries an
    absolute amount (duration is fixed at round 0).
    """

    round_number: int
    sender: Literal["us", "them"]
    action: Literal["initial", "counter", "accept", "exit", "reject"]
    proposal: dict[str, Any] | None = None  # full EscrowProposal dict


@dataclass(frozen=True)
class NegotiationDecision:
    """One round's resulting decision.

    ``action="reject"`` is reserved for pre-flight guard vetoes (caller
    maps to HTTP 409). Terminal strategies use ``"counter"``, ``"accept"``,
    or ``"exit"``.

    ``proposal`` is the full EscrowProposal dict for ``counter`` / ``accept``
    (with ``fields["amount"]`` carrying the absolute payment amount).
    ``exit`` / ``reject`` decisions leave it None.
    """

    action: Literal["accept", "counter", "exit", "reject"]
    proposal: dict[str, Any] | None = None
    reason: str | None = None  # required for exit / reject; optional otherwise

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"action": self.action}
        if self.proposal is not None:
            d["proposal"] = self.proposal
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
        our_reference_amount: Seller's absolute floor or buyer's absolute
            ceiling (base units of the escrow's payment token). Computed
            at round 0 from a per-hour rate × ``duration_seconds`` / 3600.
        listing: Full listing row (offer_resource, accepted_escrows, status, ...).
            Guards consult this; the terminal strategy typically doesn't.
        our_escrow_proposal: Our own pinned escrow proposal (the seller's
            advertised entry on the seller side; the buyer's first-round
            proposal on the buyer side). Used by shape-guard middlewares
            to detect peer mutations to fields we pinned.
        available_resources: Snapshot of the seller's portfolio at negotiation
            start, for the inventory guard. ``{"resources": [...]}``. Empty
            dict on buyer side.
        max_rounds: Cap on negotiation rounds before the chain exits.
        intermediate: Mutable scratchpad for middleware-computed state.
    """

    direction: Literal["minimize", "maximize"]
    our_reference_amount: float
    listing: dict[str, Any] = field(default_factory=dict)
    our_escrow_proposal: dict[str, Any] | None = None
    available_resources: dict[str, Any] = field(default_factory=dict)
    max_rounds: int = 10
    intermediate: dict[str, Any] = field(default_factory=dict)


# A middleware step: (decision-if-terminal, possibly-updated-context).
NegotiationStep = tuple[Optional[NegotiationDecision], NegotiationContext]

NegotiationMiddleware = Callable[
    [list[NegotiationRound], NegotiationContext],
    NegotiationStep,
]


def _amount_from_proposal(proposal: dict[str, Any] | None) -> Optional[float]:
    """Pull the absolute payment amount out of an EscrowProposal-shaped dict.

    The amount lives in ``fields["amount"]`` for ERC20-style escrows. Coerces
    decimal-digit strings (uint256 wire form) to int. Returns None on a
    missing or unparseable value.
    """
    if not isinstance(proposal, dict):
        return None
    fields = proposal.get("fields") or {}
    if not isinstance(fields, dict):
        return None
    raw = fields.get("amount")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if s.isdigit():
            return float(int(s))
    return None


def their_proposed_amount(history: list[NegotiationRound]) -> Optional[float]:
    """Most recent absolute amount the other side proposed. None if not yet."""
    for round_ in reversed(history):
        if round_.sender == "them":
            amount = _amount_from_proposal(round_.proposal)
            if amount is not None:
                return amount
    return None


def their_last_proposal(history: list[NegotiationRound]) -> Optional[dict[str, Any]]:
    """Most recent full proposal from the other side. None if not yet."""
    for round_ in reversed(history):
        if round_.sender == "them" and round_.proposal is not None:
            return round_.proposal
    return None


def our_previous_counters(history: list[NegotiationRound]) -> list[float]:
    """Absolute amounts we counter-proposed in earlier rounds, oldest first."""
    out: list[float] = []
    for h in history:
        if h.sender == "us" and h.action == "counter":
            amount = _amount_from_proposal(h.proposal)
            if amount is not None:
                out.append(amount)
    return out


def our_first_proposal(history: list[NegotiationRound]) -> Optional[dict[str, Any]]:
    """Our earliest proposal in the transcript — the field shape we pinned.

    Used by ``buyer_escrow_shape_guard`` to detect peer mutations to fields
    we set on opening.
    """
    for h in history:
        if h.sender == "us" and h.proposal is not None:
            return h.proposal
    return None


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


def _set_proposal_amount(proposal: dict[str, Any], amount: float) -> dict[str, Any]:
    """Return a shallow copy of ``proposal`` with ``fields["amount"]``
    updated to the given absolute amount (rounded to int — uint256 wire).
    """
    out = dict(proposal)
    fields = dict(out.get("fields") or {})
    fields["amount"] = int(round(amount))
    out["fields"] = fields
    return out


@register_negotiation_middleware("bisection")
def bisection_middleware(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Amount-midpoint counter-offer with convergence + stale-counter guards.

    The historical default. Rule-based, deterministic, no model files.
    Terminal: always returns Some (never defers).

    Operates on the absolute payment amount carried in
    ``proposal.fields["amount"]``. Counter decisions return a new proposal
    that copies the peer's last proposal (preserving chain / escrow /
    fields shape) with only the amount updated. When the peer has not
    yet proposed (round 0 on our side), opens with our pinned reference
    proposal (``context.our_escrow_proposal``).

    For ``direction="minimize"`` (buyer-shape): accept if peer amount ≤
    our ceiling × (1 + ε); counter at midpoint, clamped to ≤ our ceiling;
    exit if peer amount > our ceiling × 1.5.

    For ``direction="maximize"`` (seller-shape): accept if peer amount ≥
    our floor × (1 - ε); counter at midpoint; exit if peer amount <
    our floor / 1.5.

    Both sides exit after ``context.max_rounds`` rounds or two consecutive
    identical counters (built-in stale-counter guard).
    """
    counters = our_previous_counters(history)

    if len(counters) >= context.max_rounds:
        return NegotiationDecision(action="exit", reason="max_rounds"), context
    if len(counters) >= 2 and counters[-1] == counters[-2]:
        return NegotiationDecision(action="exit", reason="stale_negotiation"), context

    our_amount = context.our_reference_amount
    their_amount = their_proposed_amount(history)
    their_proposal = their_last_proposal(history)

    if their_amount is None:
        # Round 0 on our side: open with our reference amount on our
        # pinned proposal. (Buyer: our_escrow_proposal carries our ask;
        # seller: it carries the listing's accepted_escrows entry.)
        base = context.our_escrow_proposal or {}
        return (
            NegotiationDecision(
                action="counter",
                proposal=_set_proposal_amount(base, our_amount),
            ),
            context,
        )

    conv = DEFAULT_CONVERGENCE_RATIO
    reasonable = DEFAULT_REASONABLE_MULTIPLIER
    # Use the peer's last proposal as the shape skeleton so accept/counter
    # echo the same chain / escrow / fields they sent (only amount differs).
    skeleton = their_proposal or context.our_escrow_proposal or {}

    if context.direction == "minimize":
        if their_amount <= our_amount * (1 + conv):
            return (
                NegotiationDecision(
                    action="accept",
                    proposal=_set_proposal_amount(skeleton, their_amount),
                    reason="convergence",
                ),
                context,
            )
        if their_amount <= our_amount * reasonable:
            proposed = (our_amount + their_amount) / 2
            if proposed > our_amount:
                proposed = our_amount  # never counter above our ceiling
            return (
                NegotiationDecision(
                    action="counter",
                    proposal=_set_proposal_amount(skeleton, proposed),
                ),
                context,
            )
        return NegotiationDecision(action="exit", reason="price_unreasonable"), context

    if context.direction == "maximize":
        if their_amount >= our_amount * (1 - conv):
            return (
                NegotiationDecision(
                    action="accept",
                    proposal=_set_proposal_amount(skeleton, their_amount),
                    reason="convergence",
                ),
                context,
            )
        if their_amount >= our_amount / reasonable:
            proposed = (our_amount + their_amount) / 2
            return (
                NegotiationDecision(
                    action="counter",
                    proposal=_set_proposal_amount(skeleton, proposed),
                ),
                context,
            )
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


def _normalize_exact_value(value: Any) -> Any:
    """Canonicalize JSON-like escrow policy values for exact comparison."""
    if isinstance(value, dict):
        return {str(k): _normalize_exact_value(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize_exact_value(v) for v in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("0x"):
            return stripped.lower()
        if stripped.isdigit():
            return int(stripped)
        return value
    return value


def _normalize_rate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {
            "field": getattr(value, "field", None),
            "per": getattr(value, "per", None),
            "value": getattr(value, "value", None),
        }
    if value.get("field") is None or value.get("value") is None:
        raise ValueError("rate requires field and value")
    return {
        "field": value.get("field"),
        "per": value.get("per", "hour"),
        "value": int(value.get("value")),
    }


def _normalize_demands_for_chain(value: Any, chain_name: Any) -> list[Any]:
    raw = _loads_json_list(value)
    out = []
    for demand in raw:
        if not isinstance(demand, dict):
            continue
        demand_chain = demand.get("chain_name")
        if demand_chain and demand_chain != chain_name:
            continue
        out.append(_normalize_exact_value(demand))
    return out


def _loads_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        import json
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _accepted_escrow_for_proposal(
    listing: dict[str, Any],
    proposal: dict[str, Any],
) -> dict[str, Any] | None:
    accepted = _loads_json_list(listing.get("accepted_escrows"))
    proposal_addr_raw = proposal.get("escrow_address")
    if not isinstance(proposal_addr_raw, str) or not proposal_addr_raw:
        return None
    proposal_addr = proposal_addr_raw.lower()
    if proposal_addr == _ZERO_ADDRESS:
        return None
    proposal_chain = proposal.get("chain_name")
    for entry in accepted:
        if not isinstance(entry, dict):
            continue
        entry_addr = entry.get("escrow_address")
        if (
            entry.get("chain_name") == proposal_chain
            and isinstance(entry_addr, str)
            and entry_addr.lower() == proposal_addr
        ):
            return entry
    return None


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


def _peer_proposal(history: list[NegotiationRound]) -> dict[str, Any] | None:
    """Latest proposal from the *other* side; falls back to None."""
    return their_last_proposal(history)


@register_negotiation_middleware("escrow_shape_guard")
def escrow_shape_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Veto when the buyer's escrow proposal diverges from the seller's
    advertised ``accepted_escrows`` entry on any seller-pinned literal.

    Strict equality: every key the seller set on the matched entry's
    ``literal_fields`` map must equal the buyer's value. Operators wanting
    softer matching (allow arbiter upgrade, swap payment token, etc.)
    drop this guard from ``[negotiation].chain`` and write their own.

    Reads the buyer's latest proposal from history (rounds carry full
    EscrowProposal-shaped dicts; "them" = buyer from the seller's POV).
    """
    proposal = _peer_proposal(history)
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
    proposal_literal = proposal.get("literal_fields") or {}

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

    seller_literal = matched.get("literal_fields") or {}
    if not isinstance(seller_literal, dict):
        return None, context

    for key, seller_value in seller_literal.items():
        buyer_value = proposal_literal.get(key) if isinstance(proposal_literal, dict) else None
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


@register_negotiation_middleware("accept_exact_listing")
def accept_exact_listing_middleware(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Terminal policy: accept only the exact advertised listing escrow.

    This is the packaged no-negotiation fallback for escrow kinds that do
    not have a domain-specific pricing policy. It requires the buyer's
    latest proposal to:

    - select one advertised ``accepted_escrows`` entry by chain + address;
    - exactly mirror that entry's ``literal_fields`` and ``rates``;
    - exactly mirror listing-level demands for the selected chain;
    - offer ``fields.amount == context.our_reference_amount``.

    Any mismatch rejects. No counters are produced.
    """
    proposal = _peer_proposal(history)
    if not isinstance(proposal, dict):
        return (
            NegotiationDecision(action="reject", reason="exact_listing:no_proposal"),
            context,
        )

    listing = context.listing or {}
    matched = _accepted_escrow_for_proposal(listing, proposal)
    if matched is None:
        return (
            NegotiationDecision(
                action="reject",
                reason="exact_listing:escrow_not_in_accepted_set",
            ),
            context,
        )

    expected_literal = _normalize_exact_value(matched.get("literal_fields") or {})
    proposal_literal = _normalize_exact_value(proposal.get("literal_fields") or {})
    if proposal_literal != expected_literal:
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"exact_listing:literal_fields_mismatch:"
                    f"{proposal_literal!r}!={expected_literal!r}"
                ),
            ),
            context,
        )

    proposal_fields = proposal.get("fields") or {}
    if not isinstance(proposal_fields, dict):
        return (
            NegotiationDecision(action="reject", reason="exact_listing:fields_not_object"),
            context,
        )
    expected_amount = int(round(context.our_reference_amount))
    proposed_amount = _amount_from_proposal(proposal)
    if proposed_amount is None or int(proposed_amount) != expected_amount:
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"exact_listing:amount_mismatch:"
                    f"{proposed_amount!r}!={expected_amount!r}"
                ),
            ),
            context,
        )
    for key, value in proposal_fields.items():
        if key == "amount":
            continue
        expected = expected_literal.get(key)
        actual = _normalize_exact_value(value)
        if actual != expected:
            return (
                NegotiationDecision(
                    action="reject",
                    reason=(
                        f"exact_listing:field_mismatch:{key!r}:"
                        f"{actual!r}!={expected!r}"
                    ),
                ),
                context,
            )

    try:
        expected_rates = [
            _normalize_rate(rate) for rate in (matched.get("rates") or [])
        ]
        proposal_rates = [
            _normalize_rate(rate) for rate in (proposal.get("rates") or [])
        ]
    except (TypeError, ValueError) as exc:
        return (
            NegotiationDecision(
                action="reject",
                reason=f"exact_listing:invalid_rates:{exc}",
            ),
            context,
        )
    if proposal_rates != expected_rates:
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"exact_listing:rates_mismatch:"
                    f"{proposal_rates!r}!={expected_rates!r}"
                ),
            ),
            context,
        )

    expected_demands = _normalize_demands_for_chain(
        listing.get("demands"),
        proposal.get("chain_name"),
    )
    proposal_demands = _normalize_demands_for_chain(
        proposal.get("demands"),
        proposal.get("chain_name"),
    )
    if proposal_demands != expected_demands:
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"exact_listing:demands_mismatch:"
                    f"{proposal_demands!r}!={expected_demands!r}"
                ),
            ),
            context,
        )

    return (
        NegotiationDecision(
            action="accept",
            proposal=_set_proposal_amount(proposal, expected_amount),
            reason="exact_listing",
        ),
        context,
    )


@register_negotiation_middleware("buyer_escrow_shape_guard")
def buyer_escrow_shape_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Buyer-side mirror of ``escrow_shape_guard``.

    Veto when the seller's latest reply diverges from a field the buyer
    pinned at round 0. The buyer's pinned proposal lives in
    ``context.our_escrow_proposal`` (every key set there is a buyer
    pin); any value the seller sends back for one of those keys must
    match exactly (case-insensitive for 20-byte hex addresses).

    Pass through when the peer hasn't sent a proposal yet (round 0 on
    our side). Excludes ``fields["amount"]`` from the comparison —
    that's what's being negotiated.
    """
    their_proposal = _peer_proposal(history)
    if not isinstance(their_proposal, dict):
        return None, context

    pinned = context.our_escrow_proposal
    if not isinstance(pinned, dict):
        return None, context

    if pinned.get("chain_name") != their_proposal.get("chain_name"):
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"chain_name_changed:{pinned.get('chain_name')!r}"
                    f"->{their_proposal.get('chain_name')!r}"
                ),
            ),
            context,
        )
    pinned_addr = (pinned.get("escrow_address") or "").lower()
    their_addr = (their_proposal.get("escrow_address") or "").lower()
    if pinned_addr and their_addr and pinned_addr != their_addr:
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"escrow_address_changed:{pinned.get('escrow_address')!r}"
                    f"->{their_proposal.get('escrow_address')!r}"
                ),
            ),
            context,
        )
    if (
        pinned.get("expiration_unix") is not None
        and their_proposal.get("expiration_unix") is not None
        and int(pinned["expiration_unix"]) != int(their_proposal["expiration_unix"])
    ):
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"expiration_unix_changed:{pinned['expiration_unix']}"
                    f"->{their_proposal['expiration_unix']}"
                ),
            ),
            context,
        )

    pinned_fields = pinned.get("fields") or {}
    their_fields = their_proposal.get("fields") or {}
    for key, pinned_value in pinned_fields.items():
        if key == "amount":
            continue  # amount is the negotiated scalar — peer is allowed to counter
        their_value = their_fields.get(key) if isinstance(their_fields, dict) else None
        if _normalize_escrow_field(pinned_value) != _normalize_escrow_field(their_value):
            return (
                NegotiationDecision(
                    action="reject",
                    reason=(
                        f"escrow_field_changed:{key!r}:{pinned_value!r}"
                        f"->{their_value!r}"
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
