"""The VM buyer resolves its installed terms policy and uses it at approval."""

from __future__ import annotations

import pytest
from market_settlement_runtime.buyer_terms import BuyerTermsAdmission
from market_settlement_runtime.terms_policy import (
    DefaultBuyerTermsPolicy,
    PermissiveBuyerTermsPolicy,
    TermsPolicyError,
    TermsPolicySelection,
)

from arkhai_vms_buyer import arkhai_payments, cli_helpers
from arkhai_vms_buyer.settlement_composition import resolve_buyer_settlement_policy

# Placeholder development identity and account, never for a public network.
SERVICE_IDENTITY = {"scheme": "ed25519", "identifier": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}
PAYER = "11111111-1111-4111-8111-111111111111"


def document(**root):
    return {
        "Settlement": {"schema_version": 1, "priority": ["arkhai.payments.v1"], "arkhai_payments": {
            "enabled": True, "service_url": "http://127.0.0.1",
            "service_identity": SERVICE_IDENTITY, "fee_bps": 250, "development_auth": True,
        }},
        "vms": {"payer_account": PAYER},
        **root,
    }


def selected_policy(policy):
    assert isinstance(policy.option_preference, BuyerTermsAdmission)
    return policy.option_preference.policy


@pytest.mark.parametrize("root,expected", [
    ({}, DefaultBuyerTermsPolicy),
    ({"terms_policy": "default"}, DefaultBuyerTermsPolicy),
    ({"terms_policy": "permissive"}, PermissiveBuyerTermsPolicy),
    ({"terms_policy": {"name": "permissive"}}, PermissiveBuyerTermsPolicy),
])
def test_configuration_selects_the_installed_terms_policy(root, expected):
    assert type(selected_policy(resolve_buyer_settlement_policy(document(**root)))) is expected


def test_a_command_selection_overrides_configuration():
    policy = resolve_buyer_settlement_policy(
        document(), terms_policy=TermsPolicySelection("permissive"),
    )
    assert type(selected_policy(policy)) is PermissiveBuyerTermsPolicy


def test_an_uninstalled_policy_refuses_resolution_rather_than_falling_back():
    with pytest.raises(ValueError, match="'cautious' is not installed"):
        resolve_buyer_settlement_policy(document(terms_policy="cautious"))


def test_the_flag_is_shorthand_for_the_packaged_permissive_policy(monkeypatch):
    configured = {}
    monkeypatch.setattr(cli_helpers, "load_user_config", lambda: configured)
    assert cli_helpers.buyer_terms_selection(allow_unprotected_terms=False).name == "default"
    assert cli_helpers.buyer_terms_selection(allow_unprotected_terms=True).name == "permissive"
    configured["terms_policy"] = {"name": "cautious", "floor": 5}
    kept = cli_helpers.buyer_terms_selection(allow_unprotected_terms=False)
    assert (kept.name, dict(kept.settings)) == ("cautious", {"floor": 5})
    with pytest.raises(TermsPolicyError, match="configuration selects 'cautious'"):
        cli_helpers.buyer_terms_selection(allow_unprotected_terms=True)


@pytest.mark.parametrize("name,expected", [
    ("default", DefaultBuyerTermsPolicy), ("permissive", PermissiveBuyerTermsPolicy),
])
def test_payment_approval_asks_the_policy_that_selected_the_option(monkeypatch, name, expected):
    config = document(terms_policy=name)
    monkeypatch.setattr(arkhai_payments, "load_user_config", lambda: config)
    approval = arkhai_payments.payment_buyer(resolve_buyer_settlement_policy(config))
    assert type(approval.terms_policy) is expected
