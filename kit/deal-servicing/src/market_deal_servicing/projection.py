"""The seller projection of a committed deal and its read.

The projection is registered by the seller half (``SellerSession.register``)
in the transaction that records the verified commitment. End service reads it
too, and the seller half imports end service, so the projection sits below
both and imports neither.
"""

from __future__ import annotations

import sqlite3

from market_deal_lifecycle.adapters import DisputeBinding, PaymentSelector
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import Reference, WireModel
from market_identity import Identity
from pydantic import Field, JsonValue


class SellerDeal(WireModel):
    """Immutable projection supplied from the verified committed Agreement.

    ``once_only`` is false unless the registering domain set it, so a
    registration that never stated it reads as a deal with a rate part.
    """

    negotiation_id: Reference
    commitment_ref: Reference
    domain: Reference
    buyer: Identity
    payment: PaymentSelector
    dispute: DisputeAuthority | None = None
    entitlements: dict[str, JsonValue] = Field(default_factory=dict)
    once_only: bool = False

    @property
    def dispute_binding(self) -> DisputeBinding | None:
        return DisputeBinding(self.negotiation_id, self.commitment_ref, self.dispute) if self.dispute else None


def read_seller_deal(conn: sqlite3.Connection, negotiation_id: str) -> SellerDeal | None:
    """The deal's registered projection, or ``None`` where the seller half registered none."""

    row = conn.execute(
        "SELECT deal FROM servicing_seller_deals WHERE negotiation_id=?", (negotiation_id,),
    ).fetchone()
    return SellerDeal.model_validate_json(row[0]) if row else None
