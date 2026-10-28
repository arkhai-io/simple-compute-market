"""A seller trading on two chains reads each chain's book from the Alkahest section.

The real app and lifespan compose the storefront from configuration naming
``anvil`` and ``base_sepolia``, with ``[Settlement.alkahest.address_books]``
naming a book for ``anvil`` alone. The chain is reached only through the two
Alkahest boundaries the composition root takes as seams, the SDK's per-chain
client construction and the chain's JSON-RPC endpoint, which a double replaces.

Every key, address, and principal here is a deterministic development value,
never used on a public network.
"""

from __future__ import annotations

import base64
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from market_alkahest.dev_chain import anvil_address_book_path
from market_config.config_loader import ChainConfig

import market_storefront.server as server
from market_storefront import lifecycle
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils import config as storefront_config
from market_storefront.utils import sqlite_client as sqlite_module
from tests._settings_overrides import replaced_setting
from tests.integration.test_degraded_startup import (
    _CONFIGURATION,
    _SEED,
    _admin,
    _alkahest,
)

pytestmark = pytest.mark.asyncio

_BOOK = str(anvil_address_book_path())
_CHAINS = {
    "anvil": ChainConfig(name="anvil", rpc_url="http://anvil.test", chain_id=31337),
    "base_sepolia": ChainConfig(name="base_sepolia", rpc_url="http://base.test", chain_id=84532),
}


class _Chains:
    """Both chains answering: each JSON-RPC call returns its chain's identity
    and code at every address, and the SDK's construction records the policy
    the storefront builds its clients from."""

    def __init__(self) -> None:
        self.policies: list = []

    def rpc(self, rpc_url, method, params, timeout):
        if method == "eth_chainId":
            return hex(31337 if rpc_url == "http://anvil.test" else 84532)
        return "0x6080"

    def constructor(self, policy):
        self.policies.append(policy)
        return lambda chain_name: f"client:{chain_name}"


@pytest.fixture
async def lifecycle_registry():
    """A clean loop registry and pause flag, as a fresh process has."""
    await lifecycle.reset_for_tests()
    yield
    await lifecycle.reset_for_tests()


async def test_a_seller_trading_on_two_chains_uses_each_chains_own_book(
    tmp_path, monkeypatch, lifecycle_registry
):
    """Spec scenario "A seller trades on two chains", for client construction
    and the chain probe: ``anvil``'s client and probe read its book, and
    ``base_sepolia``'s read the SDK's built-in addresses, so both are reached
    and Alkahest is ready."""
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(_SEED).rstrip(b"=").decode()
    )
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)
    chains = _Chains()
    app = server.build_vm_storefront_app(
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
        seams=server.VmCompositionSeams(
            alkahest_client_constructor=chains.constructor,
            alkahest_json_rpc=chains.rpc,
        ),
    )
    configuration = {
        **_CONFIGURATION,
        "settlement": {
            "schema_version": 1,
            "priority": ["alkahest.v1"],
            "alkahest": {"enabled": True, "address_books": {"anvil": _BOOK}},
        },
        "db_path": str(tmp_path / "storefront.db"),
    }
    with ExitStack() as stack:
        for key, value in configuration.items():
            stack.enter_context(replaced_setting(key, value))
        stack.enter_context(patch.dict(storefront_config.CHAINS, _CHAINS, clear=True))
        async with app.router.lifespan_context(app):
            async with _admin(app) as admin:
                await admin.admin_pause_lifecycle_loops()
                probed = await admin.admin_run_lifecycle_cycle("alkahest-chain-probe")
                status = await admin.get_system_status()

    (policy,) = chains.policies
    assert {chain.name: chain.address_config_path for chain in policy.chains} == {
        "anvil": _BOOK,
        "base_sepolia": None,
    }
    assert sorted(probed["probed"]) == ["anvil", "base_sepolia"]
    alkahest = _alkahest(status)
    assert alkahest["ready"] is True, alkahest
    assert {
        name: result["result"]
        for name, result in alkahest["public_details"]["chain_probe"].items()
    } == {"anvil": "reachable", "base_sepolia": "reachable"}
