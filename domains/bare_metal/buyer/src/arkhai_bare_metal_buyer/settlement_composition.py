"""Declared purchase support, independent of seller-only mechanisms."""

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_core import SettlementStageTable

from .settlement_stages import PaymentStage

BUYER_STAGES = SettlementStageTable({ARKHAI_PAYMENTS_MECHANISM: PaymentStage()})
