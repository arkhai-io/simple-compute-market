"""Settlement proposal materialization over the Alkahest codec layer.

Turns negotiated ``EscrowProposal``s into the accepted-escrow response
artifacts (settlement plan + legacy flat terms) and builds the buyer's
round-0 proposal from a listing's ``accepted_escrows`` entry. Shared by
every domain that settles through an Alkahest escrow.

A seller settles an Alkahest escrow only under a release condition its listing
authorizes, whatever seller policies ran: ``authorize_escrow_proposal`` and
``escrow_proposal_from_accepted_entry`` give a proposal exactly the condition
the listing authorizes for its chain, refusing a selection it does not
authorize and a listing authorizing none, and materialization uses that
condition and no other. A seller policy such as an escrow-shape guard may
refuse earlier, but nothing here relies on one having run.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from market_alkahest.alkahest import (
    ReleaseConditionError,
    address_to_slot,
    encode_release_condition,
)
from market_alkahest.plans import (
    escrow_terms_from_settlement_plan,
    materialize_settlement_plan_from_proposal,
)
from market_alkahest.schemas import (
    EscrowDemand,
    EscrowProposal,
    accepted_demands,
    accepted_token_address,
)


def _listing_value(listing: Any, key: str) -> Any:
    if isinstance(listing, Mapping):
        return listing.get(key)
    return getattr(listing, key, None)


def _comparable(value: Any) -> Any:
    """A condition's value with address and byte hex compared case-insensitively."""
    if isinstance(value, Mapping):
        return {str(key): _comparable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_comparable(item) for item in value]
    if isinstance(value, str) and value[:2].lower() == "0x":
        return value.lower()
    return value


def authorized_release_conditions(
    listing: Any, *, chain_name: str
) -> list[EscrowDemand]:
    """The release conditions ``listing`` authorizes on ``chain_name``, in order.

    A listing's ``demands`` are its advertised conditions, each an arbiter and
    its demand data, scoped to a chain by ``chain_name`` or to every chain
    without one. Raises ``ReleaseConditionError`` when the listing authorizes
    none on the chain, or states its conditions in a form that cannot be read:
    either way there is no condition a seller may settle under.
    """
    raw = _listing_value(listing, "demands")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise ReleaseConditionError(
                "release_condition_unreadable: the listing's demands are not JSON"
            ) from exc
    if raw is None:
        raw = []
    if not isinstance(raw, (list, tuple)):
        raise ReleaseConditionError(
            "release_condition_unreadable: the listing's demands are not a list"
        )
    authorized: list[EscrowDemand] = []
    for item in raw:
        if hasattr(item, "model_dump"):
            item = item.model_dump(exclude_none=True)
        if not isinstance(item, Mapping):
            raise ReleaseConditionError(
                "release_condition_unreadable: a listing demand is not an object"
            )
        scope = item.get("chain_name")
        if scope is not None and not isinstance(scope, str):
            raise ReleaseConditionError(
                "release_condition_unreadable: a listing demand's chain_name is "
                "not a string"
            )
        if scope and scope != chain_name:
            continue
        arbiter = item.get("arbiter")
        demand_data = item.get("demand_data")
        if not isinstance(arbiter, str) or not arbiter:
            raise ReleaseConditionError(
                "release_condition_unreadable: a listing demand names no arbiter"
            )
        if not isinstance(demand_data, Mapping):
            raise ReleaseConditionError(
                "release_condition_unreadable: a listing demand's demand_data is "
                "not an object"
            )
        authorized.append(
            EscrowDemand(
                chain_name=scope or None,
                arbiter=arbiter,
                demand_data=dict(demand_data),
            )
        )
    if not authorized:
        raise ReleaseConditionError(
            "release_condition_not_advertised: the listing authorizes no release "
            f"condition on chain {chain_name!r}"
        )
    return authorized


def authorized_release_condition(
    listing: Any,
    *,
    chain_name: str,
    selected: Any = None,
) -> EscrowDemand:
    """The condition an escrow on ``chain_name`` settles under for ``listing``.

    ``selected`` is the condition a buyer's proposal names, if any: it must
    equal one the listing authorizes on the chain, arbiter and demand data both,
    and that listing condition is returned. With no selection, the listing's
    first authorized condition on the chain is. Raises
    ``ReleaseConditionError``.
    """
    authorized = authorized_release_conditions(listing, chain_name=chain_name)
    if selected is None:
        return authorized[0]
    if hasattr(selected, "model_dump"):
        selected = selected.model_dump(exclude_none=True)
    if not isinstance(selected, Mapping):
        raise ReleaseConditionError(
            "release_condition_unreadable: the selected release condition is not "
            "an object"
        )
    wanted = (
        _comparable(selected.get("arbiter")),
        _comparable(selected.get("demand_data")),
    )
    for condition in authorized:
        if (
            _comparable(condition.arbiter),
            _comparable(condition.demand_data),
        ) == wanted:
            return condition
    raise ReleaseConditionError(
        "release_condition_not_authorized: the selected release condition is not "
        f"one the listing authorizes on chain {chain_name!r}"
    )


def selected_release_condition(proposal: EscrowProposal | Mapping[str, Any] | None) -> Any:
    """The release condition a proposal selects, or None when it selects none.

    Read from its ``demand``, or the deprecated one-element ``demands`` list.
    Raises ``ReleaseConditionError`` for a proposal selecting several.
    """
    if proposal is None:
        return None
    selected = accepted_demands(proposal)
    if len(selected) > 1:
        raise ReleaseConditionError(
            "release_condition_ambiguous: a proposal selects at most one release "
            "condition"
        )
    return selected[0] if selected else None


def authorize_escrow_proposal(
    proposal: EscrowProposal | Mapping[str, Any],
    *,
    listing: Any,
) -> EscrowProposal:
    """``proposal`` settling under exactly the condition ``listing`` authorizes.

    The proposal's own selection is kept only when the listing authorizes it on
    the proposal's chain, and replaced by the listing's form of it; a proposal
    selecting none takes the listing's authorized condition. Its escrow address
    plays no part, so a proposal that leaves its contract unpinned is held to
    the listing all the same. Raises ``ReleaseConditionError``.
    """
    model = (
        proposal
        if isinstance(proposal, EscrowProposal)
        else EscrowProposal.model_validate(
            proposal.model_dump() if hasattr(proposal, "model_dump") else proposal
        )
    )
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
    condition = authorized_release_condition(listing, chain_name=str(chain or ""))
    arbiter, demand = encode_release_condition(
        str(chain or ""), condition, config_path=addr_config_path
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

    The codec layer owns materialization; the calling domain supplies the
    agreed amount, the lease duration (0 for durationless deals such as
    token credits), and the chain address-config lookup. ``proposal`` is one a
    seller has authorized against its listing (``authorize_escrow_proposal``),
    and the plan is materialized under exactly its selected condition. A
    proposal whose condition cannot be materialized raises
    ``ReleaseConditionError``; any other materialization failure is reported
    as ``accepted_escrow_terms_error`` beside artifacts carrying no plan.
    """
    if proposal is None:
        return {}
    proposal_model = (
        proposal
        if isinstance(proposal, EscrowProposal)
        else (
            EscrowProposal.model_validate(proposal.model_dump())
            if hasattr(proposal, "model_dump")
            else EscrowProposal.model_validate(proposal)
        )
    )
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

    accepted_payload = accepted.model_dump(mode="json")
    if accepted_payload.get("demands") is None:
        accepted_payload.pop("demands", None)
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
            seller_wallet_address=seller_wallet_address,
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
        # No obligation may be accepted without its authorized condition, so a
        # refusal reaches the seller rather than leaving artifacts without a plan.
        raise
    except Exception as exc:
        out["accepted_escrow_terms_error"] = str(exc)
    return out
