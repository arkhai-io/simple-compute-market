"""VM composition of discovery, negotiation and declared settlement stages.

VM lease hours supply the core priced-unit count. The selected buyer entry
owns accepted-artifact validation, resource resolution and settlement effects.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from arkhai_vms import VmProvisionTerms
from core_buyer import (  # noqa: F401 — re-exports for existing callers
    DEFAULT_HTTP_TIMEOUT,
    BuyConfig,
    BuyConstraints,
    BuyResult,
    NegotiateFn,
    NegotiationResult,
    SettleFn,
    fetch_listing_dict,
    fetch_listing_dict_multi,
    query_registry_for_matches,
    query_registry_for_matches_multi,
    run_buy,
)
from core_buyer.orchestration import (  # noqa: F401 — re-exports
    DEFAULT_SETTLEMENT_POLL_INTERVAL,
    DEFAULT_SETTLEMENT_TIMEOUT,
    BuildEscrowProposalFn,
    RevalidateSettlementFn,
    _signed_json,
    poll_settlement_status,
    submit_settlement_request,
    wait_for_settlement,
)
from core_buyer.orchestration import (
    make_negotiate_hook as _core_make_negotiate_hook,
)
from core_buyer.orchestration import (
    make_settle_hook as _core_make_settle_hook,
)
from core_buyer.policy_surface import extract_seller_min_price  # noqa: F401
from market_alkahest.schemas import EscrowProposal, EscrowTerms

from .arkhai_payments import AgreedTerms  # noqa: F401 — public VM summary
from .escrow_client import BuildEscrowTermsFn, CreateEscrowFn, encode_escrow_proposal
from .settlement_composition import (
    buyer_settlement_stages,
    resolve_buyer_settlement_policy,
    validate_buyer_acceptance,
)
from .settlement_stages import BuyerStageContext


def make_legacy_negotiate_hook(
    *,
    config: BuyConfig,
    constraints: BuyConstraints,
    provision: VmProvisionTerms,
    build_escrow_proposal: BuildEscrowProposalFn,
    max_negotiation_rounds: int,
    derive_prices: Optional[Callable[[dict[str, Any]], tuple[int, int]]],
    chain: Optional[list[Any]],
    revalidate_settlement: RevalidateSettlementFn | None = None,
) -> NegotiateFn:
    """Build the compute-instantiated negotiate hook over the core stage."""
    return _core_make_negotiate_hook(
        config=config,
        constraints=constraints,
        provision=provision,
        unit_count=float(provision.duration_seconds) / 3600.0,
        build_escrow_proposal=build_escrow_proposal,
        encode_escrow_proposal=encode_escrow_proposal,
        decode_provision_terms=VmProvisionTerms.model_validate,
        decode_escrow_proposal=EscrowProposal.model_validate,
        decode_escrow_terms=EscrowTerms.model_validate,
        max_negotiation_rounds=max_negotiation_rounds,
        derive_prices=derive_prices,
        chain=chain,
        revalidate_settlement=revalidate_settlement,
        validate_acceptance=validate_buyer_acceptance,
    )


def make_legacy_settle_hook(
    *,
    config: "BuyConfig",
    provision: VmProvisionTerms,
    buyer_evm_address: str = "",
    build_escrow_terms: BuildEscrowTermsFn | None = None,
    create_escrow: CreateEscrowFn | None = None,
    confirm_settlement: Optional[Callable[["AgreedTerms", dict[str, Any]], bool]],
    settlement_poll_interval: float,
    settlement_total_timeout: float,
    sleep: Callable[[float], None],
    settlement_policy=None,
) -> SettleFn:
    """Bind VM stage invocation without constructing unselected resources."""
    context = BuyerStageContext(
        config=config, provision=provision,
        resolve_policy=lambda: settlement_policy or resolve_buyer_settlement_policy(),
        poll_interval=settlement_poll_interval, timeout=settlement_total_timeout,
        sleep=sleep, confirm=confirm_settlement,
        buyer_evm_address=buyer_evm_address,
        build_escrow_terms=build_escrow_terms, create_escrow=create_escrow,
    )
    return _core_make_settle_hook(
        stages=buyer_settlement_stages(),
        invoke=lambda stage, negotiation, on_event: stage.settle(
            context, negotiation, on_event,
        ),
    )
