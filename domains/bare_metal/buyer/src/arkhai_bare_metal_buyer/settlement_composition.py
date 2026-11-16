"""Declared purchase support, independent of seller-only mechanisms."""

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_core import SettlementStageTable
from market_settlement_runtime import SettlementConfigurationRegistry
from market_arkhai_payments import create_arkhai_payments_registration
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import TermContext
from market_settlement_runtime.buyer_terms import (
    BuyerTermsPolicy, allows_missing_delivery_deadline, compute_disclosure, lifecycle_disclosure,
)
from market_settlement_runtime.rate_publication import DefaultRefusal

from .settlement_stages import PaymentStage

BUYER_STAGES = SettlementStageTable({ARKHAI_PAYMENTS_MECHANISM: PaymentStage()})


def buyer_term_context(
    mechanism: str, *, waivers: frozenset[DefaultRefusal] = frozenset(),
) -> TermContext:
    return TermContext(
        mechanism=mechanism, has_adapter=mechanism == ARKHAI_PAYMENTS_MECHANISM, compute=True,
        dispute_interfaces=frozenset({MEDIATION_INTERFACE}),
        allow_missing_delivery_deadline=allows_missing_delivery_deadline(waivers),
    )


def buyer_settlement_registry():
    return SettlementConfigurationRegistry((create_arkhai_payments_registration(),))


def buyer_compute_disclosure(option, **kwargs):
    return compute_disclosure(option, registry=buyer_settlement_registry(), **kwargs)


def buyer_lifecycle_disclosure(option, *, waivers: frozenset[DefaultRefusal] = frozenset()):
    return lifecycle_disclosure(
        option, context=buyer_term_context(option.settlement_schema), waivers=waivers,
    )


def validate_authority(option, config, *, waivers: frozenset[DefaultRefusal] = frozenset()) -> None:
    """An explicit option ID does not bypass the buyer's authority or rights policy."""
    BuyerTermsPolicy(AuthoritySelection(config.dispute_authorities_by_registry, contexts={
        ARKHAI_PAYMENTS_MECHANISM: buyer_term_context(ARKHAI_PAYMENTS_MECHANISM, waivers=waivers),
    }), waivers=waivers).rank(option, registry_url=config.registry_url)
