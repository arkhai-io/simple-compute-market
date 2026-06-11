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


def proposal_is_oracle_gated(
    proposal: EscrowProposal | dict[str, Any],
    *,
    chain_config_paths: dict[str, str | None] | None = None,
) -> bool:
    """True when the proposal's demand tree gates collection on a
    trusted oracle (directly or inside an AllArbiter conjunction)."""
    from market_alkahest.alkahest import address_to_slot
    from market_alkahest.schemas import accepted_demands

    chain = (
        proposal.chain_name
        if isinstance(proposal, EscrowProposal)
        else proposal.get("chain_name")
    )
    config_path = (chain_config_paths or {}).get(chain)
    for demand in accepted_demands(proposal):
        arbiter = demand.get("arbiter")
        if not arbiter:
            continue
        try:
            slot = address_to_slot(chain, arbiter, config_path=config_path)
        except Exception:
            continue
        if slot == "trusted_oracle_arbiter":
            return True
        if slot == "all_arbiter":
            children = (demand.get("demand_data") or {}).get("arbiters") or []
            for child in children:
                try:
                    if address_to_slot(
                        chain, child, config_path=config_path
                    ) == "trusted_oracle_arbiter":
                        return True
                except Exception:
                    continue
    return False


def accepted_escrow_artifacts_from_proposal(
    *,
    proposal: EscrowProposal | dict[str, Any] | None,
    agreed_amount: int,
    duration_seconds: int,
    uses_scalar_amount: bool = True,
    seller_wallet_address: str | None = None,
    chain_config_paths: dict[str, str | None] | None = None,
    heartbeat_interval_seconds: int | None = None,
) -> dict[str, Any]:
    """Build accepted escrow response artifacts from a negotiated proposal.

    The Alkahest kit owns codec materialization. The VM domain supplies the
    negotiated lease duration and chain address-config lookup.
    """
    if proposal is None:
        return {}
    proposal_model = proposal if isinstance(proposal, EscrowProposal) else (
        EscrowProposal.model_validate(proposal.model_dump())
        if hasattr(proposal, "model_dump")
        else EscrowProposal.model_validate(proposal)
    )
    fields = dict(proposal_model.fields or {})
    if uses_scalar_amount:
        fields["amount"] = int(agreed_amount)
    accepted = EscrowProposal(
        chain_name=proposal_model.chain_name,
        escrow_address=proposal_model.escrow_address,
        fields=fields,
        literal_fields=proposal_model.literal_fields,
        rates=proposal_model.rates,
        demands=proposal_model.demands,
        expiration_unix=proposal_model.expiration_unix,
    )

    out: dict[str, Any] = {
        "proposal": accepted.model_dump(),
        "accepted_escrow_proposal": accepted.model_dump(),
    }
    try:
        from market_alkahest.plans import (
            escrow_terms_from_settlement_plan,
            materialize_settlement_plan_from_proposal,
        )

        service_terms: dict[str, Any] = {}
        if heartbeat_interval_seconds and proposal_is_oracle_gated(
            accepted, chain_config_paths=chain_config_paths
        ):
            # Oracle-gated collection: the buyer's off-chain duty is the
            # heartbeat cadence the oracle's evidence window assumes.
            service_terms["heartbeat"] = {
                "schema": "vms.heartbeat.v1",
                "interval_seconds": int(heartbeat_interval_seconds),
            }
        plan = materialize_settlement_plan_from_proposal(
            proposal=accepted,
            seller_wallet_address=seller_wallet_address,
            agreed_amount=int(agreed_amount),
            duration_seconds=int(duration_seconds),
            addr_config_path=(chain_config_paths or {}).get(accepted.chain_name),
            service_terms=service_terms,
        )
        out["settlement_plan"] = plan.model_dump()
        # LEGACY mirror of the plan's alkahest obligations, kept for
        # buyers that predate the settlement-plan carrier. Leaves with
        # the client-wheel wire bump.
        out["accepted_escrow_terms"] = [
            terms.model_dump()
            for terms in escrow_terms_from_settlement_plan(plan)
        ]
    except Exception as exc:
        out["accepted_escrow_terms_error"] = str(exc)
    return out
