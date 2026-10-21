"""The VM composition root builds the Alkahest chain probe over its client map.

The probe owns the one live map of chain clients every consumer is handed, so a
client it rebuilds reaches them all; it is composed whenever an Alkahest section
is configured, and its interval and timeout are the section's.
"""

from __future__ import annotations

from unittest.mock import patch

from market_config.config_loader import ChainConfig

import market_storefront.server as server
from market_storefront.utils import config as storefront_config
from tests._settings_overrides import replaced_setting

_CHAINS = {
    "anvil": ChainConfig(name="anvil", rpc_url="http://anvil.test", chain_id=31337)
}


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
        probe = server._build_alkahest_chain_probe(clients)

    assert probe is not None
    assert probe.clients is clients
    assert probe.chain_names == ("anvil",)
    assert probe.interval_seconds == 12.0
    assert probe.rpc_timeout_seconds == 2.0


def test_no_alkahest_section_composes_no_probe() -> None:
    with replaced_setting("settlement", {"schema_version": 1, "priority": []}):
        assert server._build_alkahest_chain_probe({}) is None
