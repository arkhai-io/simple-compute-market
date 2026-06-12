"""Seller-round hook result carrier.

Every domain storefront drives negotiation through a seller round hook
— an async callable the sync-negotiation engine invokes once per buyer
message. The hook's result shape is domain-invariant: the decision the
policy chain produced plus the labels the storefront persists for the
stage log. Domain modules implement the hook itself (the VM hook
captures inventory snapshots, the API-tokens hook quota + key records);
this module owns only the carrier.

History: extracted from ``domains.vms.negotiation.storefront_round``
(design-api-tokens-domain.md, work item 5); the VM module re-exports
both names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from market_policy.negotiation_middleware import (
    NegotiationDecision,
    NegotiationRound,
)


@dataclass(frozen=True)
class SellerRoundResult:
    our_amount: int
    strategy_label: str
    direction: str
    chain_label: str
    decision: NegotiationDecision
    intermediate: dict[str, Any] | None = None


class SellerRoundHook(Protocol):
    async def __call__(
        self,
        *,
        listing: Any,
        history: list[NegotiationRound],
        requested_duration_seconds: int | None = None,
        strategy_label: str | None = None,
    ) -> SellerRoundResult:
        ...
