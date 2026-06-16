"""Generic negotiation middleware framework.

A negotiation policy is expressed as a chain of middlewares. Each
middleware has the signature::

    middleware(history, context) -> (Maybe<NegotiationDecision>, NegotiationContext)

A ``NegotiationDecision`` from a middleware terminates the chain.
``None`` lets the chain continue with the possibly-updated context. The
terminal middleware in any chain must always return a decision; otherwise
the chain runner raises an operator-facing configuration error.

This module is schema-agnostic. It owns only the shared transcript,
decision, context carrier, chain runner, registration/discovery, and config
normalization. Domain-specific middlewares such as scalar bisection,
Alkahest escrow dispatch, escrow-shape guards, and inventory guards live in
domain packages and self-register when those packages are imported.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NegotiationRound:
    """One round's transcript entry.

    ``proposal`` is intentionally opaque to the generic framework. Domain
    packages define the message shape and decide which fields, if any,
    carry negotiated values.
    """

    round_number: int
    sender: Literal["us", "them"]
    action: Literal["initial", "counter", "accept", "exit", "reject"]
    proposal: dict[str, Any] | None = None


@dataclass(frozen=True)
class NegotiationDecision:
    """One round's resulting decision."""

    action: Literal["accept", "counter", "exit", "reject"]
    proposal: dict[str, Any] | None = None
    reason: str | None = None

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

    The generic framework treats this as a carrier. Fields are broad enough
    for the current VM domain, but their concrete meaning is domain/policy
    code's responsibility.
    """

    direction: Literal["minimize", "maximize"]
    our_reference_amount: float
    # Round-0 opening when it differs from the bound (a haggler opens low
    # and concedes toward the bound). None means "open at the bound" —
    # the listed_price default, where the two coincide.
    our_opening_amount: Optional[float] = None
    listing: dict[str, Any] = field(default_factory=dict)
    our_escrow_proposal: dict[str, Any] | None = None
    available_resources: dict[str, Any] = field(default_factory=dict)
    max_rounds: int = 10
    intermediate: dict[str, Any] = field(default_factory=dict)


NegotiationStep = tuple[Optional[NegotiationDecision], NegotiationContext]


class NegotiationChainExhausted(RuntimeError):
    """Every middleware in the chain passed (returned ``None``).

    There is no "terminal" middleware type — any middleware may decide
    or pass, and a chain either produces a decision or it doesn't. A
    chain that can exhaust is misconfigured: its last middleware must be
    one that always decides. Callers should treat this as an error (and
    tell the counterparty the negotiation is over), never silently
    append a fallback decider — that would just be running a different
    chain than the one configured.
    """

NegotiationMiddleware = Callable[
    [list[NegotiationRound], NegotiationContext],
    NegotiationStep,
]


def their_last_proposal(history: list[NegotiationRound]) -> Optional[dict[str, Any]]:
    """Most recent full proposal from the other side. None if not yet."""
    for round_ in reversed(history):
        if round_.sender == "them" and round_.proposal is not None:
            return round_.proposal
    return None


def our_first_proposal(history: list[NegotiationRound]) -> Optional[dict[str, Any]]:
    """Our earliest proposal in the transcript."""
    for round_ in history:
        if round_.sender == "us" and round_.proposal is not None:
            return round_.proposal
    return None


def run_negotiation_chain(
    chain: list[NegotiationMiddleware],
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationDecision:
    """Run the middleware chain and return the first decision produced."""
    decision, _context = run_negotiation_chain_with_context(chain, history, context)
    return decision


def run_negotiation_chain_with_context(
    chain: list[NegotiationMiddleware],
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> tuple[NegotiationDecision, NegotiationContext]:
    """Run the middleware chain and return the decision plus final context."""
    for middleware in chain:
        decision, context = middleware(history, context)
        if decision is not None:
            return decision, context
    raise NegotiationChainExhausted(
        "Negotiation chain produced no decision (every middleware passed). "
        "The chain's last middleware must always decide — check the "
        "[negotiation] policies/policy configuration."
    )


_REGISTRY: dict[str, NegotiationMiddleware] = {}


def register_negotiation_middleware(name: str):
    """Decorator. Registers a middleware function under a stable name."""

    def _decorator(fn: NegotiationMiddleware) -> NegotiationMiddleware:
        _REGISTRY[name] = fn
        return fn

    return _decorator


_FILE_DISCOVERY_TRIGGERED = False


def _discover_file_middlewares() -> None:
    """One-shot hook for local extension discovery.

    File discovery is still a follow-up. Entry points and explicit imports
    cover current in-repo policy packages.
    """

    global _FILE_DISCOVERY_TRIGGERED
    if _FILE_DISCOVERY_TRIGGERED:
        return
    _FILE_DISCOVERY_TRIGGERED = True


def load_negotiation_chain(
    names: list[str] | None,
    *,
    per_middleware_config: dict[str, dict[str, Any]] | None = None,
) -> list[NegotiationMiddleware]:
    """Resolve a list of middleware names to a chain of callables."""
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
                f"For built-ins, ensure the VM policy package is imported."
            )

    return chain


def list_negotiation_middlewares() -> list[str]:
    """Names of all registered middlewares."""
    return sorted(_REGISTRY)


def _plain_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "items"):
        try:
            return {str(k): v for k, v in value.items()}
        except Exception:
            return None
    return None


def normalize_policy_chain_config(value: Any) -> list[str]:
    """Normalize a policy config value into a middleware-name chain."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(name).strip() for name in value if str(name).strip()]
    mapping = _plain_mapping(value)
    if mapping is not None:
        if "chain" in mapping:
            return normalize_policy_chain_config(mapping.get("chain"))
        if "policies" in mapping:
            return normalize_policy_chain_config(mapping.get("policies"))
        if "policy" in mapping:
            return normalize_policy_chain_config(mapping.get("policy"))
    return []


def normalize_policies_by_escrow_kind_config(value: Any) -> dict[str, list[str]] | None:
    """Normalize ``[negotiation.policies]`` table values for dispatch."""
    mapping = _plain_mapping(value)
    if mapping is None:
        return None
    out: dict[str, list[str]] = {}
    for kind, raw_chain in mapping.items():
        chain = normalize_policy_chain_config(raw_chain)
        if chain:
            out[str(kind).strip()] = chain
    return out


@register_negotiation_middleware("max_rounds_guard")
def max_rounds_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Exit when our previous counter count has hit ``context.max_rounds``."""
    counters = [
        round_
        for round_ in history
        if round_.sender == "us" and round_.action == "counter"
    ]
    if len(counters) >= context.max_rounds:
        return (
            NegotiationDecision(action="exit", reason="max_rounds"),
            context,
        )
    return None, context
