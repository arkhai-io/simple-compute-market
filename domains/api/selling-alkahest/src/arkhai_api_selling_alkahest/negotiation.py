"""The Alkahest escrow in negotiation: the opening's proposal step and the escrow path of an acceptance."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from market_alkahest import ALKAHEST_MECHANISM_ID
from market_alkahest.proposals import (
    ReleaseConditionError,
    SettlementPlanMaterializationError,
    accepted_escrow_artifacts_from_proposal,
    authorized_escrow_proposal_at_amount,
)
from market_alkahest.schemas import (
    EscrowProposal,
    normalize_proposal_against_accepted_escrows,
)
from market_core.schemas import SettlementOption, SettlementSelection, derive_settlement_option_id
from market_identity import Identity
from market_negotiation_runtime import OfferUnfulfillableError

ChainConfigPaths = Callable[[], Mapping[str, str | None]]


def accepted_escrow_proposal(
    proposal: Mapping[str, Any], accepted_escrows: list[Any] | None
) -> dict[str, Any]:
    """The buyer's escrow proposal canonicalized against the listing's accepted escrows."""
    return normalize_proposal_against_accepted_escrows(
        proposal=EscrowProposal.model_validate(proposal),
        accepted_escrows=accepted_escrows,
    ).model_dump()


def accepted_escrow_artifacts(
    *,
    buyer_principal: Identity,
    seller_principal: Identity,
    proposal: Any,
    listing: Mapping[str, Any],
    agreed_amount: int,
    chain_config_paths: Mapping[str, str | None],
    uses_scalar_amount: bool = True,
    duration_seconds: int = 0,
) -> dict[str, Any]:
    """The durationless accepted settlement artifacts of an escrow deal.

    The escrow settles under the release condition ``listing`` authorizes on
    its chain, which a condition the proposal selects must be; the kit refuses
    any other, and a listing authorizing none, with ``ReleaseConditionError``,
    and an escrow whose plan cannot be materialized with
    ``SettlementPlanMaterializationError``.
    """
    artifacts = accepted_escrow_artifacts_from_proposal(
        proposal=proposal,
        listing=listing,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        uses_scalar_amount=uses_scalar_amount,
        chain_config_paths=dict(chain_config_paths),
        heartbeat_interval_seconds=None,
    )
    plan = artifacts.get("settlement_plan")
    if isinstance(plan, dict):
        buyer_wire = buyer_principal.model_dump(mode="json")
        seller_wire = seller_principal.model_dump(mode="json")
        plan["buyer_principal"] = buyer_wire
        plan["seller_principal"] = seller_wire
        for obligation in plan.get("obligations") or []:
            if isinstance(obligation, dict):
                obligation["payer_principal"] = buyer_wire
                obligation["claimant_principal"] = seller_wire
    accepted = artifacts.get("accepted_escrow_proposal")
    if isinstance(accepted, Mapping):
        params = {"accepted_escrow": dict(accepted)}
        asset = str((accepted.get("fields") or {}).get("token") or "")
        option = SettlementOption(
            option_id=derive_settlement_option_id(
                mechanism=ALKAHEST_MECHANISM_ID, asset=asset, rates=[], params=params
            ),
            mechanism=ALKAHEST_MECHANISM_ID, asset=asset, rates=[], params=params,
        )
        artifacts["_agreement_settlement_option"] = option.model_dump(mode="json")
        artifacts["settlement_selection"] = SettlementSelection(
            mechanism=option.mechanism, option_id=option.option_id,
            expiration_unix=accepted.get("expiration_unix"),
        ).model_dump(mode="json", exclude_none=True)
    return artifacts


class AlkahestEscrowAcceptance:
    """The escrow path of an acceptance, under the release condition the listing authorizes."""

    def __init__(self, chain_config_paths: ChainConfigPaths) -> None:
        self._chain_config_paths = chain_config_paths

    def offer(self, acceptance: Any) -> dict[str, Any]:
        try:
            return authorized_escrow_proposal_at_amount(
                proposal=acceptance.pinned_proposal,
                listing=acceptance.listing_record,
                agreed_amount=acceptance.agreed_amount,
                uses_scalar_amount=acceptance.uses_scalar_amount,
            )
        except ReleaseConditionError as exc:
            raise OfferUnfulfillableError(str(exc)) from exc

    def accept(self, acceptance: Any) -> dict[str, Any]:
        try:
            return accepted_escrow_artifacts(
                buyer_principal=acceptance.buyer_principal,
                seller_principal=acceptance.seller_principal,
                proposal=acceptance.pinned_proposal,
                agreed_amount=acceptance.agreed_amount,
                uses_scalar_amount=acceptance.uses_scalar_amount,
                listing=acceptance.listing_record,
                chain_config_paths=self._chain_config_paths(),
            )
        except (ReleaseConditionError, SettlementPlanMaterializationError) as exc:
            raise OfferUnfulfillableError(str(exc)) from exc


__all__ = [
    "AlkahestEscrowAcceptance",
    "accepted_escrow_artifacts",
    "accepted_escrow_proposal",
]
