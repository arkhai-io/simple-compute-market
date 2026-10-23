"""The VM composition root builds the Alkahest chain probe over its client map.

The probe owns the one live map of chain clients every consumer is handed, so a
client it rebuilds reaches them all; it is composed whenever an Alkahest section
is configured, and its interval and timeout are the section's. The root's two
Alkahest boundaries, the SDK's per-chain construction and the chain's JSON-RPC
endpoint, are what a test replaces; everything between them is production's.
Every key and address here is a deterministic development value, never used on
a public network.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from market_alkahest.dev_chain import anvil_address_book_path
from market_config.config_loader import ChainConfig
from market_identity import Ed25519Signer

import market_storefront.container as container
import market_storefront.server as server
from market_storefront import lifecycle_steps
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils import config as storefront_config
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import replaced_setting

_CHAINS = {
    "anvil": ChainConfig(
        name="anvil",
        rpc_url="http://anvil.test",
        chain_id=31337,
        alkahest_address_config_path=str(anvil_address_book_path()),
    )
}
_WALLET = {"address": "0x" + "33" * 20, "private_key": "0x" + "55" * 32}


def _never_called(*_args):
    raise AssertionError("the boundary was not to be reached")


def test_a_configured_section_composes_the_probe_over_the_live_client_map() -> None:
    clients: dict[str, object] = {}
    with replaced_setting(
        "settlement",
        {
            "schema_version": 1,
            "priority": [],
            "alkahest": {
                "enabled": False,
                "probe_interval_seconds": 12,
                "rpc_timeout_seconds": 2,
            },
        },
    ), patch.dict(storefront_config.CHAINS, _CHAINS, clear=True):
        probe = server._build_alkahest_chain_probe(
            clients, constructor=lambda _policy: None, json_rpc=_never_called
        )

    assert probe is not None
    assert probe.clients is clients
    assert probe.chain_names == ("anvil",)
    assert probe.interval_seconds == 12.0
    assert probe.rpc_timeout_seconds == 2.0


def test_no_alkahest_section_composes_no_probe() -> None:
    with replaced_setting("settlement", {"schema_version": 1, "priority": []}):
        assert (
            server._build_alkahest_chain_probe(
                {}, constructor=lambda _policy: None, json_rpc=_never_called
            )
            is None
        )


class _Chain:
    """The chain's JSON-RPC endpoint and the SDK's construction over it: both
    refuse until ``answering`` is set."""

    def __init__(self) -> None:
        self.answering = False

    def rpc(self, rpc_url, method, params, timeout):
        if not self.answering:
            raise ConnectionRefusedError("connection refused")
        return hex(31337) if method == "eth_chainId" else "0x6080"

    def constructor(self, _policy):
        def construct(chain_name: str) -> object:
            if not self.answering:
                raise ConnectionRefusedError("websocket upgrade refused")
            return f"client:{chain_name}"

        return construct


@pytest.mark.asyncio
async def test_the_root_hands_readiness_and_the_loop_one_probe_over_one_client_map(
    tmp_path, monkeypatch
) -> None:
    """The settlement composition reads readiness from the probe the
    ``alkahest-chain-probe`` loop steps, and holds the probe's own map, so a
    stepped probe makes Alkahest ready and its rebuilt client reaches the
    composition without a restart. The map starts empty: the probe's first step
    builds the client, never composition."""
    chain = _Chain()
    domain = build_vm_storefront_domain()
    sqlite_client = SQLiteClient(
        db_path=str(tmp_path / "storefront.db"),
        registry=build_vm_storefront_registry(domain),
    )
    with replaced_setting(
        "settlement",
        {"schema_version": 1, "priority": ["alkahest.v1"], "alkahest": {"enabled": True}},
    ), replaced_setting("wallet", _WALLET), patch.dict(
        storefront_config.CHAINS, _CHAINS, clear=True
    ):
        clients: dict[str, object] = {}
        probe = server._build_alkahest_chain_probe(
            clients, constructor=chain.constructor, json_rpc=chain.rpc
        )
        composition = server._build_settlement_composition(
            domain=domain,
            sqlite_client=sqlite_client,
            alkahest_clients=clients,
            marketplace_signer=Ed25519Signer(b"\x31" * 32),
            chain_probe=probe,
        )
        monkeypatch.setattr(container, "resolved_alkahest_chain_probe", probe)

        def alkahest(statuses):
            (status,) = [item for item in statuses if item.mechanism == "alkahest.v1"]
            return status

        unprobed = alkahest(await composition.readiness())
        await lifecycle_steps.alkahest_chain_probe_step()
        refused = alkahest(await composition.readiness())
        chain.answering = True
        await lifecycle_steps.alkahest_chain_probe_step()
        reached = alkahest(await composition.readiness())

    assert clients == {"anvil": "client:anvil"}
    assert composition.mechanism_resources["clients"] is clients
    assert composition.mechanism_resources["chain_probe"] is probe
    assert [blocker.code for blocker in unprobed.blockers] == ["alkahest.chain_unreachable"]
    assert [blocker.code for blocker in refused.blockers] == ["alkahest.chain_unreachable"]
    assert reached.ready is True
