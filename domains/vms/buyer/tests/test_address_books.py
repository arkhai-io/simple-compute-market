"""The VM buyer reads each chain's Alkahest address book from its Alkahest section.

The paths are development values; nothing here reads them.
"""

from __future__ import annotations

from arkhai_vms_buyer import common

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
