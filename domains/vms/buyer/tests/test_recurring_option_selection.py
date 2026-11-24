"""The VM buyer selects a seller's spot and on-demand options, or says why not.

The options are the ones a storefront's preset helper derives, so the buyer's
term context is checked against what sellers publish rather than a copy of it.
"""

from __future__ import annotations

import pytest
from core_buyer.registry_config import RegistryAuthority
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_arkhai_payments.fixtures import dispute_lifecycle, recurring_options
from market_core.schemas import SettlementOption
from market_deal_lifecycle.configuration import DisputeEntry
from typer.testing import CliRunner

from arkhai_vms_buyer.cli import app
from arkhai_vms_buyer.settlement_composition import (
    buyer_compute_disclosure,
    buyer_lifecycle_disclosure,
    resolve_buyer_settlement_policy,
)
from identity_helpers import seller_principals
from test_buy_resume_cli import _RESOLVED

MECHANISM = "arkhai.payments.v1"
# Development accounts, never used on a public network.
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"
REGISTRY = "http://registry"


def _authority(minimum_window: int = 0) -> dict:
    return {
        **dispute_lifecycle(DISPUTE)["adjudication"]["dispute"],
        "interface": MEDIATION_INTERFACE,
        "advertisement": {"mechanisms": [MECHANISM],
                          "minimum_dispute_window_seconds": minimum_window,
                          "minimum_case_hold_seconds": None},
    }


OPTIONS = recurring_options(DisputeEntry.model_validate(_authority()), payee=PAYEE)


def _document(authority: dict) -> dict:
    return {
        "Settlement": {"schema_version": 1, "priority": [MECHANISM],
                       "arkhai_payments": {"enabled": True}},
        "Dispute": [authority],
    }


def _listing() -> dict:
    return {
        "listing_id": "L-recurring", "source_registry_url": REGISTRY,
        "settlement_options": list(OPTIONS.values()),
    }


@pytest.mark.parametrize("kind", ["spot", "on-demand"])
def test_a_recurring_option_is_selected_and_disclosed_by_its_kind(kind):
    policy = resolve_buyer_settlement_policy(_document(_authority()))
    option_id = OPTIONS[kind]["option_id"]

    ((_, selected),) = policy.select_listings(
        [_listing()], expiration_unix=1_900_000_000, clauses=[f"option_id={option_id}"],
    )

    option = SettlementOption.model_validate(OPTIONS[kind])
    assert selected.option == option
    rows = dict(
        buyer_compute_disclosure(option, listing=_listing(), duration_seconds=None)
        + buyer_lifecycle_disclosure(option)
    )
    assert rows["Class"] == kind
    assert rows["Selected price"].startswith("1500 minor units of USD/2 per_period (PT15M")
    assert rows["Seller stop"].startswith(
        "Entitled with 120 seconds' notice" if kind == "spot" else "No entitled payment stop"
    )
    assert "Premature-stop penalty" in rows and "Term end" in rows


def test_buy_says_why_every_advertised_option_was_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_fresh_buyer_identity", lambda: _RESOLVED)
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_registry_authorities", lambda urls: {
        url: RegistryAuthority(authority="registry", principals=seller_principals())
        for url in urls
    })
    monkeypatch.setattr(
        "arkhai_vms_buyer.common.resolve_indexer_urls_for_schema",
        lambda _schema, **kw: list(kw["registry_authorities"]),
    )
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_registry_api_keys", lambda: {})
    # This buyer's authority demands a longer dispute window than either option offers.
    monkeypatch.setattr(
        "arkhai_vms_buyer.settlement_composition.load_user_config",
        lambda: _document(_authority(minimum_window=10 * 604800)),
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.buy_cli.query_registry_for_matches_multi",
        lambda *_args, **_kwargs: [_listing()],
    )

    result = CliRunner().invoke(app, [
        "buy", "--registry-urls", REGISTRY, "--ssh-public-key", "ssh-ed25519 AAAA", "--yes",
        "--settlement", f"mechanism={MECHANISM}",
    ])

    assert result.exit_code == 2, (result.output, result.exception)
    assert "No listings matched" in result.output
    assert "dispute window is below the delivery deadline plus the authority minimum" in result.output
