from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from tests.e2e.roles.scenarios.vms.hosted.boundaries import (
    HostedBoundaryError,
    assert_import_boundary,
    assert_wallet_free_config,
    hosted_selection_requested,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_wallet_free_hosted_config_requires_profile_store_and_common_settlement(tmp_path: Path) -> None:
    config = tmp_path / "buyer.toml"
    config.write_text(
        """
[BuyerProfile]
store_path = "/var/lib/arkhai/buyer/profiles.json"

[Settlement]
priority = ["fiat.stripe.v1"]

[Settlement.stripe]
enabled = true
currency = "usd"
""",
        encoding="utf-8",
    )
    assert assert_wallet_free_config(config)["Settlement"]["stripe"]["enabled"] is True


@pytest.mark.parametrize(
    "field",
    (
        "[Wallet]\nprivate_key = 'secret'",
        "[Chains.anvil]\nrpc_url = 'http://anvil:8545'",
        "[Settlement.stripe]\ncontrol_url = 'http://control:8083'",
        "[Settlement.stripe]\nprovider = 'simulator'",
        "[Settlement.stripe]\nwebhook_secret = 'secret'",
    ),
)
def test_wallet_free_config_rejects_wallet_chain_rpc_provider_and_control(
    tmp_path: Path, field: str
) -> None:
    config = tmp_path / "buyer.toml"
    config.write_text(
        """
[BuyerProfile]
store_path = "/var/lib/arkhai/buyer/profiles.json"

[Settlement]
priority = ["fiat.stripe.v1"]
"""
        + field,
        encoding="utf-8",
    )
    with pytest.raises(HostedBoundaryError, match="forbidden"):
        assert_wallet_free_config(config)


def test_wallet_free_config_rejects_legacy_identity(tmp_path: Path) -> None:
    config = tmp_path / "buyer.toml"
    config.write_text(
        """
[Identity]
scheme = "ed25519"
identifier = "legacy"
[Settlement]
priority = ["fiat.stripe.v1"]
[Settlement.stripe]
enabled = true
""",
        encoding="utf-8",
    )
    with pytest.raises(HostedBoundaryError, match="BuyerProfile"):
        assert_wallet_free_config(config)



def test_buyer_deployment_mounts_separate_profile_state_and_credential() -> None:
    for relative in ("compose.vms.yml", "compose.apicredits.yml"):
        rendered = (_REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "XDG_DATA_HOME" in rendered
        assert "XDG_STATE_HOME" in rendered
        assert "PROFILE_DIR" in rendered
        assert "CREDENTIAL_FILE" in rendered
        assert "ARKHAI_IDENTITY_CREDENTIAL" not in rendered

    helm_job = (
        _REPO_ROOT
        / "helm/charts/e2e-tests/templates/tests/e2e-deal-test.yaml"
    ).read_text(encoding="utf-8")
    assert "buyer-profile-store" in helm_job
    assert "buyer-credential" in helm_job
    assert "persistentVolumeClaim" in helm_job
    assert "secretKeyRef" not in helm_job


def test_hosted_public_config_has_no_legacy_identity_or_secret_canary() -> None:
    rendered = (_REPO_ROOT / "e2e-tests/config/hosted-buyer.toml").read_text(
        encoding="utf-8"
    )
    assert "[BuyerProfile]" in rendered
    assert "[Identity" not in rendered
    assert "PRIVATE-SEED-CANARY" not in rendered

def test_public_import_discovery_works_without_fixture_distribution(monkeypatch) -> None:
    for name in tuple(sys.modules):
        if name == "hosted_settlement_e2e" or name.startswith("hosted_settlement_e2e."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    real_import = importlib.import_module

    def import_without_private(name: str, package: str | None = None):
        if name == "hosted_settlement_e2e" or name.startswith("hosted_settlement_e2e."):
            raise ModuleNotFoundError(name)
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", import_without_private)
    assert_import_boundary(
        (
            "market_hosted_settlement",
            "market_storefront.settlement_composition",
            "domains.vms.buyer.settlement_composition",
        )
    )


@pytest.mark.parametrize(
    ("args", "marker", "enabled", "expected"),
    (
        ((), "", False, False),
        (("hosted-stripe-test",), "", False, True),
        ((), "e2e_hosted_stripe_test", False, True),
        ((), "", True, True),
    ),
)
def test_hosted_stripe_collection_is_explicitly_opt_in(args, marker, enabled, expected) -> None:
    assert (
        hosted_selection_requested(
            invocation_args=args,
            marker_expression=marker,
            environment_enabled=enabled,
        )
        is expected
    )
