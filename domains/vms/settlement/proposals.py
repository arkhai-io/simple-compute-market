"""VM settlement proposal materialization."""

from __future__ import annotations

from typing import Any

from market_alkahest.schemas import EscrowProposal


def escrow_proposal_from_accepted_entry(
    *,
    listing: dict[str, Any],
    entry: dict[str, Any],
    expiration_unix: int,
) -> EscrowProposal:
    """Build the buyer's negotiation proposal from a selected listing entry."""
    from market_alkahest.schemas import accepted_demands, accepted_token_address

    literal_fields = dict(entry.get("literal_fields") or {})
    token = accepted_token_address(entry)
    if token:
        literal_fields["token"] = token
    selected_chain = entry.get("chain_name")
    demands = [
        demand for demand in accepted_demands(listing)
        if not demand.get("chain_name") or demand.get("chain_name") == selected_chain
    ]
    return EscrowProposal(
        chain_name=selected_chain,
        escrow_address=entry["escrow_address"],
        fields={"token": token},
        literal_fields=literal_fields,
        rates=entry.get("rates") or [],
        demands=demands,
        expiration_unix=expiration_unix,
    )
