"""Test fixtures for consumers of the Arkhai payments kit.

The receipt fixture shares the kit verifier's framing and is proven against the
published conformance vector, so tests never sign receipts any other way.
"""

from datetime import datetime, timezone

from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.terms import LifecycleTerms
from market_identity import Ed25519Signer
from market_settlement_runtime import SettlementPublicationClause
from market_settlement_runtime.rate_publication import RatePresetRefusal, derive_rate_preset
from market_settlement_runtime.rate_servicing import RateServicing, RateServicingDeclaration

from market_arkhai_payments.fixtures.authority import PaymentsAuthority, sign_snapshot, snapshot_message
from market_arkhai_payments.fixtures.payments_client import FakePaymentsClient
from market_arkhai_payments.fixtures.receipts import (
    build_signed_receipt,
    receipt_parts,
    sign_receipt,
)
from market_arkhai_payments.presets import PaymentsRatePresetHelper, rate_contract_revision
from market_arkhai_payments.settlement_config import ARKHAI_PAYMENTS_MECHANISM

def dispute_lifecycle(account: str) -> dict:
    """Public development terms for controlled payment fixtures, never a live authority."""
    return LifecycleTerms.model_validate({
        "adjudication": {
            "version": 1,
            "dispute": {
                "interface": "example.dispute.v1",
                "origin": "https://dispute.example",
                "account": account,
                "record_key": "ed25519:" + Ed25519Signer(bytes(range(32))).identity.identifier,
                "params": {},
            },
            "dispute_window_seconds": 604800,
            "case_hold_max_seconds": None,
        },
    }).model_dump(mode="json", exclude_none=False, exclude_unset=True)


def recurring_options(authority: DisputeEntry, *, payee: str) -> dict[str, dict]:
    """A seller's spot and on-demand options, derived as a storefront publishes them.

    Both charge USD/2 per 15-minute period through the preset helper, under a
    servicing declaration made only for the fixture; the spot option entitles
    the seller to stop with notice.
    """
    revision = rate_contract_revision()
    servicing = RateServicing(
        required_contracts={ARKHAI_PAYMENTS_MECHANISM: revision},
        declarations={ARKHAI_PAYMENTS_MECHANISM: RateServicingDeclaration(
            ARKHAI_PAYMENTS_MECHANISM, revision, "published",
        )},
    )

    def derive(**recurring: int) -> dict:
        clause = SettlementPublicationClause.model_validate({
            "mechanism": ARKHAI_PAYMENTS_MECHANISM, "asset": "USD/2", "rate": "60", "per": "hour",
            "mechanism_input": {"asset": "USD/2", "payee_account": payee,
                                "approval_window": "PT10M", "dispute_window_seconds": 604800},
            "recurring": {"period": "PT15M", "reserve_ahead_seconds": 1800, **recurring},
        })
        option = derive_rate_preset(
            clause, helper=PaymentsRatePresetHelper(), servicing=servicing,
            authorities=(authority,), max_duration_seconds=86400, available_until_utc=None,
            delivery_deadline_seconds=600, now=datetime(2027, 1, 1, tzinfo=timezone.utc),
            default_penalty_periods=24,
        )
        if isinstance(option, RatePresetRefusal):
            raise ValueError(f"{option.code}: {option.detail}")
        return option.model_dump(mode="json", exclude_none=True)

    return {"spot": derive(payee_notice_seconds=120), "on-demand": derive()}


__all__ = [
    "PaymentsAuthority", "FakePaymentsClient", "build_signed_receipt", "receipt_parts",
    "sign_receipt", "sign_snapshot", "snapshot_message", "dispute_lifecycle", "recurring_options",
]
