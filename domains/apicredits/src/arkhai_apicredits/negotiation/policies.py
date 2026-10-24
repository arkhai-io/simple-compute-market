"""The API-credits storefront's escrow proposal step, run by the opening guard."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_alkahest.schemas import (
    EscrowProposal,
    normalize_proposal_against_accepted_escrows,
)


def accepted_escrow_proposal(
    proposal: Mapping[str, Any], accepted_escrows: list[Any] | None
) -> dict[str, Any]:
    """The buyer's escrow proposal canonicalized against the listing's accepted escrows."""
    return normalize_proposal_against_accepted_escrows(
        proposal=EscrowProposal.model_validate(proposal),
        accepted_escrows=accepted_escrows,
    ).model_dump()


__all__ = ["accepted_escrow_proposal"]
