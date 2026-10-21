"""Settlement proposal materialization over the Alkahest codec layer.

Turns negotiated ``EscrowProposal``s into the accepted-escrow response
artifacts (settlement plan + legacy flat terms) and builds the buyer's
round-0 proposal from a listing's ``accepted_escrows`` entry. Shared by
every domain that settles through an Alkahest escrow.

An escrow settles only under a release condition its listing authorizes,
whatever seller policies ran: every function here that builds a proposal or
materializes an obligation takes the listing and authorizes the condition
itself (``market_alkahest.release_authorization``), refusing a selection the
listing does not authorize and a listing authorizing none. A seller policy
such as an escrow-shape guard may refuse earlier, but nothing here relies on
one having run, and no caller can reach a materialized condition its listing
does not authorize.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_alkahest.alkahest import (
    address_to_slot,
    encode_authorized_release_condition,
)
from market_alkahest.plans import (
    escrow_terms_from_settlement_plan,
    materialize_settlement_plan_from_proposal,
)
from market_alkahest.release_authorization import (
    ReleaseConditionError,
    UnpinnedEscrowError,
    authorized_release_condition,
    authorized_release_conditions,
    require_pinned_escrow,
    selected_release_condition,
)
from market_alkahest.schemas import (
    EscrowProposal,
    accepted_demands,
    accepted_token_address,
)

__all__ = [
    "ReleaseConditionError",
    "SettlementPlanMaterializationError",
    "UnpinnedEscrowError",
    "accepted_escrow_artifacts_from_proposal",
    "authorize_escrow_proposal",
    "authorized_escrow_proposal_at_amount",
    "authorized_release_condition",
    "authorized_release_conditions",
    "escrow_proposal_from_accepted_entry",
    "proposal_is_oracle_gated",
    "proposal_is_splitter_gated",
    "selected_release_condition",
    "validate_selected_escrow_plan",
]


class SettlementPlanMaterializationError(ValueError):
    """An accepted escrow cannot be materialized as its settlement plan.

    An Alkahest deal is accepted only with the plan its settlement is verified
    against, so any failure to build that plan from an authorized proposal
    refuses the acceptance rather than leaving artifacts without one. A
    release condition the listing does not authorize, or cannot be encoded, is
    refused separately with ``ReleaseConditionError``. The message starts with
    ``settlement_plan_unmaterializable``.
    """


def _escrow_proposal(proposal: EscrowProposal | Mapping[str, Any] | Any) -> EscrowProposal:
    if isinstance(proposal, EscrowProposal):
        return proposal
    return EscrowProposal.model_validate(
        proposal.model_dump() if hasattr(proposal, "model_dump") else proposal
    )


def authorize_escrow_proposal(
    proposal: EscrowProposal | Mapping[str, Any],
    *,
    listing: Any,
) -> EscrowProposal:
    """``proposal`` settling under exactly the condition ``listing`` authorizes.

    The proposal's own selection is kept only when the listing authorizes it on
    the proposal's chain, and replaced by the listing's form of it; a proposal
    selecting none takes the listing's authorized condition. A proposal naming
    no escrow contract is refused (``UnpinnedEscrowError``), whatever condition
    it selects. Raises ``ReleaseConditionError``.
    """
    model = _escrow_proposal(proposal)
    require_pinned_escrow(model)
    condition = authorized_release_condition(
        listing,
        chain_name=model.chain_name,
        selected=selected_release_condition(model),
    )
    return model.model_copy(update={"demand": condition, "demands": None})


def escrow_proposal_from_accepted_entry(
    *,
    listing: dict[str, Any],
    entry: dict[str, Any],
    expiration_unix: int,
    demand: Any = None,
) -> EscrowProposal:
    """Build the proposal for a selected listing entry, under its authorized condition.

    ``demand`` is a condition the caller selected; it must be one the listing
    authorizes on the entry's chain. Without it the listing's authorized
    condition on that chain is used. Raises ``ReleaseConditionError`` when the
    listing authorizes none, or not the one selected.
    """
    literal_fields = dict(entry.get("literal_fields") or {})
    token = accepted_token_address(entry)
    if token:
        literal_fields["token"] = token
    selected_chain = entry.get("chain_name")
    condition = authorized_release_condition(
        listing, chain_name=str(selected_chain or ""), selected=demand
    )
    # A native-token escrow has no token. Naming one as None would put a
    # ``token`` key into the materialized obligation data that the chain's
    # obligation never carries, so the escrow could never verify.
    return EscrowProposal(
        chain_name=selected_chain,
        escrow_address=entry["escrow_address"],
        fields={"token": token} if token else {},
        literal_fields=literal_fields,
        rates=entry.get("rates") or [],
        demand=condition,
        expiration_unix=expiration_unix,
    )


def validate_selected_escrow_plan(
    plan: Any,
    *,
    listing: dict[str, Any],
    entry: dict[str, Any],
    addr_config_path: str | None = None,
) -> None:
    """Check an accepted plan funds the escrow a buyer's selection names.

    A selection names a listing's accepted-escrow entry rather than carrying
    escrow terms, and the seller materializes it into one concrete
    ``alkahest.v1`` obligation. That obligation must be on the entry's chain
    and escrow contract, in its token, and released under the condition the
    listing authorizes on that chain: its arbiter, and its demand data encoded
    through that arbiter's codec, which ``addr_config_path`` (the chain's
    address book) resolves. A listing authorizing no condition fails. Amount and
    expiry are the negotiation's and are checked by its caller. Raises
    ``ValueError``.
    """
    # Read through the wire form: the plan may be any model of the shared
    # settlement-plan contract, not only this codec's.
    terms = escrow_terms_from_settlement_plan(
        plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
    )
    if len(terms) != 1:
        raise ValueError("selected Alkahest plan is not a single escrow obligation")
    (term,) = terms
    chain = entry.get("chain_name")
    if term.chain_name != chain:
        raise ValueError("selected Alkahest plan is on another chain")
    if term.escrow_contract.lower() != str(entry.get("escrow_address", "")).lower():
        raise ValueError("selected Alkahest plan names another escrow contract")
    token = accepted_token_address(entry)
    if token and str(term.obligation_data.get("token", "")).lower() != token.lower():
        raise ValueError("selected Alkahest plan escrows another token")
    arbiter, demand = encode_authorized_release_condition(
        listing, chain_name=str(chain or ""), config_path=addr_config_path
    )
    if str(term.obligation_data.get("arbiter", "")).lower() != arbiter.lower():
        raise ValueError("selected Alkahest plan names another arbiter")
    if str(term.obligation_data.get("demand", "")).lower() != demand.lower():
        raise ValueError(
            "selected Alkahest plan names another demand than the listing authorizes"
        )


def proposal_is_oracle_gated(
    proposal: EscrowProposal | dict[str, Any],
    *,
    chain_config_paths: dict[str, str | None] | None = None,
) -> bool:
    """True when the proposal's demand tree gates collection on a
    trusted oracle (directly or inside an AllArbiter conjunction)."""

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
                    if (
                        address_to_slot(chain, child, config_path=config_path)
                        == "trusted_oracle_arbiter"
                    ):
                        return True
                except Exception:
                    continue
    return False


def proposal_is_splitter_gated(
    proposal: EscrowProposal | dict[str, Any],
    *,
    chain_config_paths: dict[str, str | None] | None = None,
) -> bool:
    """True when collection routes through a splitter arbiter."""

    chain = (
        proposal.chain_name
        if isinstance(proposal, EscrowProposal)
        else proposal.get("chain_name")
    )
    config_path = (chain_config_paths or {}).get(chain)
    splitter_slots = {"erc20_splitter", "native_token_splitter"}
    for demand in accepted_demands(proposal):
        arbiter = demand.get("arbiter")
        if not arbiter:
            continue
        try:
            slot = address_to_slot(chain, arbiter, config_path=config_path)
        except Exception:
            continue
        if slot in splitter_slots:
            return True
        if slot == "all_arbiter":
            children = (demand.get("demand_data") or {}).get("arbiters") or []
            for child in children:
                try:
                    if (
                        address_to_slot(chain, child, config_path=config_path)
                        in splitter_slots
                    ):
                        return True
                except Exception:
                    continue
    return False


def authorized_escrow_proposal_at_amount(
    *,
    proposal: EscrowProposal | dict[str, Any],
    listing: Any,
    agreed_amount: int,
    uses_scalar_amount: bool = True,
) -> dict[str, Any]:
    """The proposal as accepted at ``agreed_amount``, without materializing a plan.

    The proposal is authorized against ``listing`` (``authorize_escrow_proposal``),
    so it names the listing's form of its release condition, and carries the
    agreed amount when the escrow bargains over one. This is what a seller
    offers back in a round that does not accept; an acceptance takes
    ``accepted_escrow_artifacts_from_proposal``, which also builds the plan.
    Raises ``ReleaseConditionError``.
    """
    proposal_model = authorize_escrow_proposal(proposal, listing=listing)
    fields = dict(proposal_model.fields or {})
    if uses_scalar_amount:
        fields["amount"] = str(agreed_amount)
    accepted = EscrowProposal(
        chain_name=proposal_model.chain_name,
        escrow_address=proposal_model.escrow_address,
        fields=fields,
        literal_fields=proposal_model.literal_fields,
        rates=proposal_model.rates,
        demand=proposal_model.demand,
        expiration_unix=proposal_model.expiration_unix,
    )
    payload = accepted.model_dump(mode="json")
    if payload.get("demands") is None:
        payload.pop("demands", None)
    return payload


def accepted_escrow_artifacts_from_proposal(
    *,
    proposal: EscrowProposal | dict[str, Any] | None,
    listing: Any,
    agreed_amount: int,
    duration_seconds: int,
    uses_scalar_amount: bool = True,
    chain_config_paths: dict[str, str | None] | None = None,
    heartbeat_interval_seconds: int | None = None,
) -> dict[str, Any]:
    """Build accepted escrow response artifacts from a negotiated proposal.

    The codec layer owns materialization; the calling domain supplies the
    listing the proposal was negotiated against, the agreed amount, the lease
    duration (0 for durationless deals such as token credits), and the chain
    address-config lookup. The proposal is first authorized against
    ``listing`` (``authorized_escrow_proposal_at_amount``), so the recorded
    accepted proposal names the listing's form of its condition and the plan is
    materialized under exactly that condition.

    Artifacts for a proposal always carry its settlement plan: a condition the
    listing does not authorize, or that cannot be encoded, raises
    ``ReleaseConditionError``, and any other failure to materialize the plan
    raises ``SettlementPlanMaterializationError``, so no caller can accept an
    escrow without the plan its settlement is verified against. With no
    proposal there is no escrow, and the artifacts are empty.
    """
    if proposal is None:
        return {}
    accepted_payload = authorized_escrow_proposal_at_amount(
        proposal=proposal,
        listing=listing,
        agreed_amount=agreed_amount,
        uses_scalar_amount=uses_scalar_amount,
    )
    accepted = EscrowProposal.model_validate(accepted_payload)
    out: dict[str, Any] = {
        "proposal": dict(accepted_payload),
        "accepted_escrow_proposal": dict(accepted_payload),
    }
    try:
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
        if proposal_is_splitter_gated(accepted, chain_config_paths=chain_config_paths):
            service_terms["interruptible"] = {
                "schema": "vms.interruptible.v1",
                "refund_authority": "seller_declared",
            }
        plan = materialize_settlement_plan_from_proposal(
            proposal=accepted,
            listing=listing,
            agreed_amount=int(agreed_amount),
            duration_seconds=int(duration_seconds),
            addr_config_path=(chain_config_paths or {}).get(accepted.chain_name),
            service_terms=service_terms,
        )
        out["settlement_plan"] = plan.model_dump(mode="json")
        # Legacy escrow terms remain part of the signed JSON response until
        # the client wire carrier is retired. Keep uint256 fields in their
        # canonical decimal-string form at that boundary.
        accepted_terms: list[dict[str, Any]] = []
        for terms in escrow_terms_from_settlement_plan(plan):
            payload = terms.model_dump(mode="json")
            obligation_data = dict(payload.get("obligation_data") or {})
            amount = obligation_data.get("amount")
            if isinstance(amount, int) and not isinstance(amount, bool):
                obligation_data["amount"] = str(amount)
            payload["obligation_data"] = obligation_data
            accepted_terms.append(payload)
        out["accepted_escrow_terms"] = accepted_terms
    except ReleaseConditionError:
        # A condition the listing does not authorize keeps its own reason.
        raise
    except Exception as exc:
        raise SettlementPlanMaterializationError(
            f"settlement_plan_unmaterializable: {exc}"
        ) from exc
    return out
