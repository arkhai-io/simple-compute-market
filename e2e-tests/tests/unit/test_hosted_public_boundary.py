from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from tests.e2e.roles.scenarios.vms.hosted.boundaries import (
    HostedBoundaryError,
    assert_public_import_boundary,
    assert_wallet_free_config,
    hosted_selection_requested,
)


def test_wallet_free_hosted_config_requires_identity_and_common_settlement(tmp_path: Path) -> None:
    config = tmp_path / "buyer.toml"
    config.write_text(
        """
[Identity]
scheme = "ed25519"
identifier = "buyer-fixture"

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
[Identity]
scheme = "ed25519"
identifier = "buyer-fixture"

[Settlement]
priority = ["fiat.stripe.v1"]
"""
        + field,
        encoding="utf-8",
    )
    with pytest.raises(HostedBoundaryError, match="forbidden"):
        assert_wallet_free_config(config)


def test_public_import_discovery_works_without_private_artifact(monkeypatch) -> None:
    for name in tuple(sys.modules):
        if name == "hosted_settlement_e2e" or name.startswith("hosted_settlement_e2e."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    real_import = importlib.import_module

    def import_without_private(name: str, package: str | None = None):
        if name == "hosted_settlement_e2e" or name.startswith("hosted_settlement_e2e."):
            raise ModuleNotFoundError(name)
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", import_without_private)
    assert_public_import_boundary(
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
        (("tests/e2e/roles/scenarios/vms/hosted",), "", False, True),
        ((), "e2e_hosted_settlement", False, True),
        ((), "", True, True),
    ),
)
def test_hosted_collection_is_explicitly_opt_in(args, marker, enabled, expected) -> None:
    assert hosted_selection_requested(
        invocation_args=args,
        marker_expression=marker,
        environment_enabled=enabled,
    ) is expected
