"""Buyer-side seller-counter response policy.

When the buyer sends an ``EscrowProposal`` and the seller returns a
potentially-modified version (the ``accepted_escrow_proposal`` on the
negotiation outcome), this is where the buyer decides whether the
counter is acceptable.

Mirror of the seller's ``negotiate.guard.escrow_fields_strict_match``
in the storefront: the default policy ``strict_echo`` rejects any
change to a buyer-set field. Operators that want softer matching
(allow the seller to swap arbiter, push expiration, etc.) swap the
policy via ``BuyConfig.counter_policy`` or by registering a custom
one through entry points.

Shape::

    CounterPolicy = Callable[
        [EscrowProposal, Optional[EscrowProposal]],
        CounterDecision,
    ]

``reject`` short-circuits settlement: the orchestrator rewrites the
``NegotiationOutcome`` to ``status="exited"`` with
``reason=f"counter_rejected:{decision.reason}"`` and skips the
on-chain escrow + ``/settle`` round-trip.

Registration mirrors ``aggregation.py``: in-process registry +
``@register_counter_policy`` decorator + entry-point lookup. No
file-discovery layer — add one when somebody asks for ad-hoc local
policies.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from service.schemas import EscrowProposal

logger = logging.getLogger(__name__)


@dataclass
class CounterDecision:
    action: Literal["accept", "reject"]
    reason: Optional[str] = None


CounterPolicy = Callable[
    [EscrowProposal, Optional[EscrowProposal]],
    CounterDecision,
]


_REGISTRY: dict[str, CounterPolicy] = {}

DEFAULT_POLICY_NAME = "strict_echo"


def register_counter_policy(
    name: str,
) -> Callable[[CounterPolicy], CounterPolicy]:
    """Decorator. Registers a named counter policy.

    Names must be unique within a process; re-registering overwrites —
    useful for tests and local overrides.
    """
    def _decorator(fn: CounterPolicy) -> CounterPolicy:
        _REGISTRY[name] = fn
        return fn
    return _decorator


def _normalize(value: Any) -> Any:
    """Case-insensitive compare for hex addresses; identity otherwise.

    Matches the seller's strict-match guard so both sides converge on
    the same equality decision when the buyer asks for a checksummed
    address and the seller stores it lowercase (or vice versa).
    """
    if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
        return value.lower()
    return value


@register_counter_policy("strict_echo")
def _strict_echo(
    sent: EscrowProposal,
    returned: Optional[EscrowProposal],
) -> CounterDecision:
    """Accept iff the seller didn't change any field the buyer pinned.

    Rejects:
      * missing echo (seller dropped the proposal entirely)
      * different ``(chain_name, escrow_address)`` than the buyer asked
        for (seller swapped to a different accepted_escrows entry)
      * different ``expiration_unix`` than the buyer asked for
      * any buyer-set field whose value differs from the returned value

    Accepts a returned proposal that *adds* keys the buyer didn't set
    (e.g. the seller populates an ``arbiter`` default). The buyer's
    ``build_escrow_terms`` reads from the accepted proposal at
    settlement time, so picking up seller-supplied defaults is correct
    — the buyer was silent about them, not opposed to them.
    """
    if returned is None:
        return CounterDecision(action="reject", reason="seller_did_not_echo")
    if returned.chain_name != sent.chain_name:
        return CounterDecision(
            action="reject",
            reason=(
                f"chain_name_changed:{sent.chain_name}->{returned.chain_name}"
            ),
        )
    if returned.escrow_address.lower() != sent.escrow_address.lower():
        return CounterDecision(
            action="reject",
            reason=(
                f"escrow_address_changed:{sent.escrow_address}"
                f"->{returned.escrow_address}"
            ),
        )
    if int(returned.expiration_unix) != int(sent.expiration_unix):
        return CounterDecision(
            action="reject",
            reason=(
                f"expiration_unix_changed:{sent.expiration_unix}"
                f"->{returned.expiration_unix}"
            ),
        )
    for key, sent_value in sent.fields.items():
        returned_value = returned.fields.get(key)
        if _normalize(sent_value) != _normalize(returned_value):
            return CounterDecision(
                action="reject",
                reason=(
                    f"field_changed:{key}:"
                    f"{sent_value!r}->{returned_value!r}"
                ),
            )
    return CounterDecision(action="accept")


@register_counter_policy("always_accept")
def _always_accept(
    sent: EscrowProposal,
    returned: Optional[EscrowProposal],
) -> CounterDecision:
    """Accept whatever the seller returned, including missing echo.

    For operators who explicitly want to take seller counter-proposals,
    and for tests. Settlement-time ``build_escrow_terms`` still errors
    on a structurally broken proposal — this policy only opts out of
    the field-equality check.
    """
    return CounterDecision(action="accept")


def load_counter_policy(name: Optional[str]) -> CounterPolicy:
    """Resolve a counter policy by name. ``None`` returns the default.

    Lookup order: in-process registry → Python entry points in group
    ``market_buyer.counter_policies``. Raises ``ValueError`` if not
    found.
    """
    if not name:
        name = DEFAULT_POLICY_NAME
    if name in _REGISTRY:
        return _REGISTRY[name]

    try:
        import importlib.metadata as md
        eps = md.entry_points(group="market_buyer.counter_policies")
    except Exception:
        eps = []
    for ep in eps:
        if ep.name == name:
            loaded = ep.load()
            _REGISTRY[name] = loaded
            return loaded

    raise ValueError(
        f"Unknown counter policy: {name!r}. "
        f"Registered: {sorted(_REGISTRY)}"
    )


def list_counter_policies() -> list[str]:
    """Names of all registered policies (for CLI help / introspection)."""
    return sorted(_REGISTRY)
