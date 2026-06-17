"""VM shim over the core buyer orchestration stages.

The discover → negotiate → settle plumbing moved to
``core_buyer.orchestration`` when the API-tokens domain became the
second schema plugin. This module keeps the VM instantiation: the
legacy hook factories translate ``VmProvisionTerms`` into the core
seams — ``unit_count`` (lease hours, ``duration_seconds / 3600``),
``duration_seconds`` for escrow-terms materialization, and the SSH
public key riding the settle request — and adapt the confirmation
callback to the VM-flavoured :class:`AgreedTerms`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from core_buyer import (  # noqa: F401 — re-exports for existing callers
    DEFAULT_HTTP_TIMEOUT,
    BuyConfig,
    BuyConstraints,
    BuyResult,
    NegotiationResult,
    NegotiateFn,
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
    _looks_like_propagation_lag,
    _signed_json,
    poll_settlement_status,
    submit_settlement,
    wait_for_settlement,
)
from core_buyer.orchestration import AgreedTerms as CoreAgreedTerms
from core_buyer.orchestration import (
    make_negotiate_hook as _core_make_negotiate_hook,
    make_settle_hook as _core_make_settle_hook,
)
from core_buyer.policy_surface import extract_seller_min_price  # noqa: F401
from arkhai_vms_common import VmProvisionTerms
from core_buyer.escrow_client import BuildEscrowTermsFn, CreateEscrowFn

from .buyer_client import _sign  # noqa: F401 — re-export for service_cli/tests


@dataclass
class AgreedTerms:
    """Human-facing summary of a finalized negotiation (VM reading).

    Passed to the optional ``confirm_settlement`` callback so the user
    can review what they're about to commit to before any chain write.
    """
    seller_url: str
    seller_wallet_address: str
    negotiation_id: str
    listing_id: str
    agreed_amount: int                # base units, absolute payment total
    duration_seconds: int           # buyer's lease ask (negotiation init)


def make_legacy_negotiate_hook(
    *,
    config: BuyConfig,
    constraints: BuyConstraints,
    provision: VmProvisionTerms,
    build_escrow_proposal: BuildEscrowProposalFn,
    max_negotiation_rounds: int,
    derive_prices: Optional[Callable[[dict[str, Any]], tuple[int, int]]],
    chain: Optional[list[Any]],
) -> NegotiateFn:
    """Build the compute-instantiated negotiate hook over the core stage."""
    return _core_make_negotiate_hook(
        config=config,
        constraints=constraints,
        provision=provision,
        unit_count=float(provision.duration_seconds) / 3600.0,
        build_escrow_proposal=build_escrow_proposal,
        max_negotiation_rounds=max_negotiation_rounds,
        derive_prices=derive_prices,
        chain=chain,
    )


def make_legacy_settle_hook(
    *,
    config: "BuyConfig",
    provision: VmProvisionTerms,
    build_escrow_terms: BuildEscrowTermsFn,
    create_escrow: CreateEscrowFn,
    confirm_settlement: Optional[Callable[["AgreedTerms", dict[str, Any]], bool]],
    settlement_poll_interval: float,
    settlement_total_timeout: float,
    sleep: Callable[[float], None],
) -> SettleFn:
    """Build the compute-instantiated settlement hook over the core stage."""
    adapted_confirm: Optional[Callable[[CoreAgreedTerms, dict[str, Any]], bool]] = None
    if confirm_settlement is not None:
        def adapted_confirm(core_terms: CoreAgreedTerms, match: dict[str, Any]) -> bool:
            return confirm_settlement(
                AgreedTerms(
                    seller_url=core_terms.seller_url,
                    seller_wallet_address=core_terms.seller_wallet_address,
                    negotiation_id=core_terms.negotiation_id,
                    listing_id=core_terms.listing_id,
                    agreed_amount=core_terms.agreed_amount,
                    duration_seconds=provision.duration_seconds,
                ),
                match,
            )

    return _core_make_settle_hook(
        config=config,
        unit_count=float(provision.duration_seconds) / 3600.0,
        duration_seconds=provision.duration_seconds,
        ssh_public_key=provision.ssh_public_key,
        build_escrow_terms=build_escrow_terms,
        create_escrow=create_escrow,
        confirm_settlement=adapted_confirm,
        settlement_poll_interval=settlement_poll_interval,
        settlement_total_timeout=settlement_total_timeout,
        sleep=sleep,
    )
