"""Declared purchase support, independent of seller-only mechanisms."""

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_core import SettlementStageTable
from market_settlement_runtime import SettlementConfigurationRegistry
from market_arkhai_payments import create_arkhai_payments_registration
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import TermContext
from market_settlement_runtime.buyer_terms import BuyerTermsAdmission, compute_disclosure, lifecycle_disclosure
from market_settlement_runtime.terms_policy import load_buyer_terms_policy

from .settlement_stages import PaymentStage

BUYER_STAGES = SettlementStageTable({ARKHAI_PAYMENTS_MECHANISM: PaymentStage()})


def buyer_term_context(mechanism: str) -> TermContext:
    return TermContext(
        mechanism=mechanism, has_adapter=mechanism == ARKHAI_PAYMENTS_MECHANISM, compute=True,
        dispute_interfaces=frozenset({MEDIATION_INTERFACE}),
    )


def buyer_settlement_registry():
    return SettlementConfigurationRegistry((create_arkhai_payments_registration(),))


def buyer_compute_disclosure(option, **kwargs):
    return compute_disclosure(option, registry=buyer_settlement_registry(), **kwargs)


def buyer_lifecycle_disclosure(option):
    return lifecycle_disclosure(option, context=buyer_term_context(option.settlement_schema))


def validate_authority(option, config) -> None:
    """An explicit option ID does not bypass the buyer's authority or terms policy."""
    BuyerTermsAdmission(AuthoritySelection(config.dispute_authorities_by_registry, contexts={
        ARKHAI_PAYMENTS_MECHANISM: buyer_term_context(ARKHAI_PAYMENTS_MECHANISM),
    }), load_buyer_terms_policy(config.terms_policy)).rank(option, registry_url=config.registry_url)
