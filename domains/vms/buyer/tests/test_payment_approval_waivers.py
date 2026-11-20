"""The VM buyer's payment approval refuses by the same run's terms policy.

Selection and approval read one policy, so a term the run waived is not
refused again once the seller accepts, and an unwaived one still is.
"""

from __future__ import annotations

import pytest
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_arkhai_payments.fixtures import dispute_lifecycle
from market_identity import Ed25519Signer

from arkhai_vms_buyer.arkhai_payments import payment_buyer
from arkhai_vms_buyer.settlement_composition import resolve_buyer_settlement_policy

MECHANISM = "arkhai.payments.v1"
# Development accounts and the all-sevens development key, never used on a
# public network.
PAYER = "11111111-1111-4111-8111-111111111111"
DISPUTE = "33333333-3333-4333-8333-333333333333"
SERVICE = Ed25519Signer(b"\x07" * 32)


def _document() -> dict:
    return {
        "Settlement": {"schema_version": 1, "priority": [MECHANISM], "arkhai_payments": {
            "enabled": True, "service_url": "http://127.0.0.1:9", "fee_bps": 250,
            "service_identity": SERVICE.identity.model_dump(mode="json"), "development_auth": True,
        }},
        "Dispute": [{
            **dispute_lifecycle(DISPUTE)["adjudication"]["dispute"], "interface": MEDIATION_INTERFACE,
            "advertisement": {"mechanisms": [MECHANISM], "minimum_dispute_window_seconds": 0,
                              "minimum_case_hold_seconds": None},
        }],
    }


@pytest.mark.parametrize("waivers", [frozenset(), frozenset({"charged_term_end"})])
def test_payment_approval_takes_the_runs_terms_policy(monkeypatch, waivers):
    monkeypatch.setattr("arkhai_vms_buyer.arkhai_payments.load_user_config",
                        lambda: {"vms": {"payer_account": PAYER}})
    policy = resolve_buyer_settlement_policy(_document(), waivers=waivers)

    approval = payment_buyer(policy)

    # Approval refuses exactly the default refusals these waivers leave, as the
    # payments kit's approval tests prove for each term.
    assert approval.terms_policy is policy.option_preference
    assert approval.terms_policy.waivers == waivers
