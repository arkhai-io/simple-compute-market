"""The VM buyer reads each chain's Alkahest address book from its Alkahest section.

The paths are development values; nothing here reads them.
"""

from __future__ import annotations

import pytest

from arkhai_vms_buyer import common
from arkhai_vms_buyer.settlement_composition import resolve_buyer_settlement_policy

_CONFIG = {
    "Settlement": {
        "schema_version": 1,
        "priority": ["alkahest.v1"],
        "alkahest": {
            "enabled": True,
            "address_books": {"anvil": "/etc/arkhai/alkahest/anvil.json"},
        },
    },
    "chains": {
        "anvil": {"rpc_url": "http://anvil.test", "chain_id": 31337},
        "base_sepolia": {"rpc_url": "http://base.test", "chain_id": 84532},
    },
}


def test_a_buyer_configuration_with_the_table_resolves_anvils_book() -> None:
    assert common.chain_address_book("anvil", _CONFIG) == "/etc/arkhai/alkahest/anvil.json"


def test_a_chain_the_table_does_not_name_uses_the_built_in_addresses() -> None:
    assert common.chain_address_book("base_sepolia", _CONFIG) is None
    assert common.chain_address_books(_CONFIG) == {
        "anvil": "/etc/arkhai/alkahest/anvil.json",
        "base_sepolia": None,
    }


def test_a_buyer_with_no_alkahest_section_names_no_book() -> None:
    assert common.chain_address_book("anvil", {"chains": _CONFIG["chains"]}) is None


_RETIRED = [
    (
        {"chains": {"anvil": {"rpc_url": "http://anvil.test",
                              "alkahest_address_config_path": "/book.json"}}},
        "[Chains.anvil].alkahest_address_config_path",
    ),
    (
        {"Settlement": {"schema_version": 1, "priority": [],
                        "alkahest": {"address_config_path": "/book.json"}}},
        "[Settlement.alkahest].address_config_path",
    ),
]


@pytest.mark.parametrize(("config", "path"), _RETIRED, ids=["chain-key", "section-key"])
def test_a_retired_key_is_refused_naming_the_table(config, path) -> None:
    """Spec scenario "A retired key is stated", for the VM buyer: both its
    book resolution and its settlement policy refuse it."""
    for resolve in (
        lambda: common.chain_address_book("anvil", config),
        lambda: resolve_buyer_settlement_policy(config),
    ):
        with pytest.raises(ValueError) as refused:
            resolve()
        assert f"{path} is retired" in str(refused.value)
        assert "[Settlement.alkahest.address_books]" in str(refused.value)
