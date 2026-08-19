"""The delivery event: what a sink receives, and how it reads.

The event is mechanism-neutral. It is constructed from the shape of a reveal
projection rather than by importing the mechanism that produced one, so a role
package can deliver without depending on a settlement mechanism. A second
producer -- a settled charge, a completed escrow -- adds a constructor here and
needs no second delivery system.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field

INTRODUCTION_REVEALED = "introduction.revealed"

Role = Literal["buyer", "seller"]

_CONTEXT_ORDER = ("listing_id", "option_id", "profile", "channel", "terms")


def canonical_principal(identity: Identity | None) -> str | None:
    """Render one marketplace principal in its canonical scheme-tagged form."""

    if identity is None:
        return None
    return f"{identity.scheme.value}:{identity.identifier}"


class DeliveryEvent(BaseModel):
    """One recipient-side event carrying material the recipient already holds.

    ``contact`` is verbatim opaque payload: keys and values the marketplace
    never interprets. ``rendered`` is computed once here so every sink,
    including installed third-party sinks, can be trivial and so output stays
    consistent across destinations.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1)
    obligation_ref: str = Field(min_length=1)
    agreement_ref: str | None = None
    role: Role
    counterparty: str | None = None
    contact: dict[str, str] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    rendered: str = ""

    def payload(self) -> dict[str, Any]:
        """The structured form a sink transmits, with the rendering included."""

        return self.model_dump(mode="json")


def _render(event_fields: Mapping[str, Any]) -> str:
    """Render one event as a stable, readable block.

    Ordering is deterministic -- known context keys first, then the rest
    sorted -- so a sink's output is diffable and a test can pin it.
    """

    role = event_fields["role"]
    lines = [
        "Introduction revealed",
        f"Deal: {event_fields['obligation_ref']}",
    ]
    if event_fields.get("agreement_ref"):
        lines.append(f"Agreement: {event_fields['agreement_ref']}")
    if event_fields.get("counterparty"):
        lines.append(f"Counterparty: {event_fields['counterparty']}")
    lines.append(f"You are the: {role}")

    context = event_fields.get("context") or {}
    known = [key for key in _CONTEXT_ORDER if context.get(key) is not None]
    extra = sorted(key for key in context if key not in _CONTEXT_ORDER)
    if known or extra:
        lines.append("")
        lines.append("Agreed introduction:")
        for key in [*known, *extra]:
            lines.append(f"  {key}: {context[key]}")

    contact = event_fields.get("contact") or {}
    lines.append("")
    lines.append("Counterparty contact:")
    if contact:
        for key in sorted(contact):
            lines.append(f"  {key}: {contact[key]}")
    else:
        lines.append("  (none revealed)")
    return "\n".join(lines)


def introduction_delivery_event(
    projection: Mapping[str, Any],
    *,
    role: Role,
    agreement_ref: str | None = None,
    counterparty: Identity | None = None,
) -> DeliveryEvent:
    """Build the event for one revealed introduction.

    ``projection`` is the reveal's own public shape -- the same mapping the
    seller returns and the buyer receives -- read by shape and never by import.
    The caller supplies what the projection does not carry: which side it is
    delivering for, and who the counterparty is.
    """

    obligation_ref = projection.get("obligation_ref")
    if not isinstance(obligation_ref, str) or not obligation_ref:
        raise ValueError("a delivery event requires the obligation reference")
    if not projection.get("revealed"):
        raise ValueError("only a revealed introduction can be delivered")
    raw_contact = projection.get("counterparty_contact") or {}
    contact = {str(key): str(value) for key, value in dict(raw_contact).items()}
    context = dict(projection.get("introduction") or {})
    fields: dict[str, Any] = {
        "kind": INTRODUCTION_REVEALED,
        "obligation_ref": obligation_ref,
        "agreement_ref": agreement_ref,
        "role": role,
        "counterparty": canonical_principal(counterparty),
        "contact": contact,
        "context": context,
    }
    return DeliveryEvent(**fields, rendered=_render(fields))


__all__ = [
    "INTRODUCTION_REVEALED",
    "DeliveryEvent",
    "Role",
    "canonical_principal",
    "introduction_delivery_event",
]
