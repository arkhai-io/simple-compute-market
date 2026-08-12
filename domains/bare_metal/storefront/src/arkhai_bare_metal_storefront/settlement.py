"""Bare-metal settlement verification and plan-construction hooks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_alkahest.proposals import accepted_escrow_artifacts_from_proposal
from market_alkahest.schemas import EscrowProposal
from market_core.schemas import SettlementPlan
from market_identity import Identity


class BareMetalSettlementPlanError(ValueError):
    """The accepted escrow could not produce a valid settlement plan."""


def build_bare_metal_settlement_plan(
    *,
    proposal: EscrowProposal | dict[str, Any] | None,
    agreed_amount: int,
    duration_seconds: int,
    buyer_principal: Identity,
    seller_principal: Identity,
    uses_scalar_amount: bool = True,
    seller_wallet_address: str | None = None,
    chain_config_paths: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """Materialize a fail-closed mechanism-neutral plan for agreed terms."""
    if duration_seconds < 1:
        raise BareMetalSettlementPlanError(
            "duration_seconds must be positive",
        )
    if proposal is None:
        return {}

    artifacts = accepted_escrow_artifacts_from_proposal(
        proposal=proposal,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        uses_scalar_amount=uses_scalar_amount,
        seller_wallet_address=seller_wallet_address,
        chain_config_paths=dict(chain_config_paths or {}),
        heartbeat_interval_seconds=None,
    )
    error = artifacts.pop("accepted_escrow_terms_error", None)
    if error:
        raise BareMetalSettlementPlanError(
            f"accepted escrow could not be materialized: {error}",
        )

    raw_plan = artifacts.get("settlement_plan")
    if raw_plan is None:
        raise BareMetalSettlementPlanError(
            "accepted escrow produced no settlement_plan",
        )
    try:
        plan = SettlementPlan.model_validate(raw_plan)
    except Exception as exc:
        raise BareMetalSettlementPlanError(
            "accepted escrow produced an invalid settlement_plan",
        ) from exc
    canonical_plan = plan.model_dump(mode="json")
    for obligation in canonical_plan["obligations"]:
        obligation["payer_principal"] = buyer_principal.model_dump(mode="json")
        obligation["claimant_principal"] = seller_principal.model_dump(mode="json")
    artifacts["settlement_plan"] = canonical_plan
    return artifacts
