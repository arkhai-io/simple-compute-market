"""Declared purchase support, independent of seller-only mechanisms."""

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_core import SettlementStageTable
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import TermContext

from .settlement_stages import PaymentStage

BUYER_STAGES = SettlementStageTable({ARKHAI_PAYMENTS_MECHANISM: PaymentStage()})


def validate_authority(option, config) -> None:
    """An explicit option ID does not bypass the buyer's authority policy."""
    AuthoritySelection(config.dispute_authorities_by_registry, contexts={
        ARKHAI_PAYMENTS_MECHANISM: TermContext(
            mechanism=ARKHAI_PAYMENTS_MECHANISM, has_adapter=True, compute=True,
            dispute_interfaces=frozenset({MEDIATION_INTERFACE}),
        ),
    }).rank(option.settlement_schema, option.lifecycle, registry_url=config.registry_url)
