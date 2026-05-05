"""ABI alignment integration tests for service.clients.erc8004.

These tests verify that Python data structures passed to web3 contract
function calls are encodable against the vendored IdentityRegistry ABI —
no contract deployment, no external node, and no network required.

Web3's ABI codec raises KeyError during encode_abi() when struct field
names in a Python dict don't match the component names declared in the
ABI. This is the exact failure mode that caused the 'metadataKey'
registration crash when registration.py used 'key'/'value' instead of
the ABI's 'metadataKey'/'metadataValue' field names.

Test strategy
-------------
- Load the vendored IdentityRegistry.json ABI (the single source of truth
  for what the deployed contract expects).
- Instantiate a Web3 contract at a dummy address — no provider, no node.
- Call encode_abi() for each contract function used by registration.py.
- Assert the encoding succeeds (non-empty calldata) and, for struct
  arguments, that the dict field names exactly match the ABI component names.

When to update these tests
--------------------------
If the IdentityRegistry ABI is updated (new struct fields, renamed
components), these tests will fail with a clear message. The fix is to
update _build_metadata_entries() in registration.py to match the new
field names, then re-run the tests to confirm alignment.

See ARCHITECTURE.md — "service package: ABI alignment testing" for the
TODO on Option A (full EthereumTesterProvider + contract deployment tests
for registration logic).
"""
from __future__ import annotations

import pytest
from web3 import Web3

from service.clients.erc8004.abi import load_erc8004_abi
from service.clients.erc8004.registration import _build_metadata_entries

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_DUMMY_ADDRESS = "0x0000000000000000000000000000000000000001"


@pytest.fixture(scope="module")
def identity_abi() -> list[dict]:
    """Vendored IdentityRegistry ABI — single source of truth."""
    return load_erc8004_abi("IdentityRegistry")


@pytest.fixture(scope="module")
def contract(identity_abi):
    """Web3 contract instance for ABI encoding only — no provider, no network.

    Web3() with no arguments creates a provider-less instance. encode_abi()
    works purely from the ABI definition, so no node is required.
    """
    w3 = Web3()
    return w3.eth.contract(address=_DUMMY_ADDRESS, abi=identity_abi)


# ---------------------------------------------------------------------------
# MetadataEntry struct alignment — the primary guard
# ---------------------------------------------------------------------------


class TestMetadataEntryAlignment:
    """Verify _build_metadata_entries() produces ABI-compatible structs.

    The MetadataEntry struct in the IdentityRegistry ABI has two components:
      - metadataKey   (string)
      - metadataValue (bytes)

    If registration.py uses different field names the ABI codec raises
    KeyError before any transaction is broadcast — exactly the production
    bug this test suite guards against.
    """

    def test_metadata_entry_field_names_match_abi_struct(self, identity_abi):
        """Dict keys from _build_metadata_entries exactly match ABI component names.

        This test reads the expected field names from the ABI at runtime so it
        stays correct if the struct is renamed in a future ABI update — the test
        will fail with a clear message rather than silently drifting.
        """
        # Find the two-argument register() overload: register(agentURI, metadata[])
        register_fn = next(
            item for item in identity_abi
            if item.get("name") == "register"
            and item.get("type") == "function"
            and len(item.get("inputs", [])) == 2
        )
        metadata_input = register_fn["inputs"][1]
        expected_fields = {c["name"] for c in metadata_input["components"]}

        entries = _build_metadata_entries(
            agent_name="test-agent",
            agent_card_data={"name": "test-agent"},
        )
        for i, entry in enumerate(entries):
            assert set(entry.keys()) == expected_fields, (
                f"MetadataEntry[{i}] has fields {set(entry.keys())!r} but the ABI "
                f"struct expects {expected_fields!r}.\n"
                f"Update _build_metadata_entries() in registration.py to use the "
                f"correct field names."
            )

    def test_register_with_metadata_encodes_without_error(self, contract):
        """register(agentURI, MetadataEntry[]) calldata encodes without KeyError.

        This is the end-to-end encoding check: it exercises the full ABI codec
        path that production code takes when broadcasting a registration tx.
        """
        metadata = _build_metadata_entries(
            agent_name="test-agent",
            agent_card_data={"name": "test-agent", "version": "1.0"},
        )
        encoded = contract.encode_abi(
            "register",
            args=["http://sell_agent:8001/.well-known/erc-8004-registration.json", metadata],
        )
        assert isinstance(encoded, (bytes, str)) and len(encoded) > 0

    def test_register_without_metadata_encodes_without_error(self, contract):
        """register(agentURI) one-argument overload encodes correctly."""
        encoded = contract.encode_abi(
            "register",
            args=["http://sell_agent:8001/.well-known/erc-8004-registration.json"],
        )
        assert isinstance(encoded, (bytes, str)) and len(encoded) > 0

    def test_metadata_entries_have_correct_value_types(self):
        """All metadataValue fields are hex strings (0x-prefixed), as web3 expects."""
        entries = _build_metadata_entries(
            agent_name="bob",
            agent_card_data={"name": "bob"},
        )
        for entry in entries:
            value = entry["metadataValue"]
            assert isinstance(value, str) and value.startswith("0x"), (
                f"metadataValue for key {entry['metadataKey']!r} must be a "
                f"0x-prefixed hex string for web3 bytes encoding, got {value!r}"
            )

    def test_metadata_entry_keys_are_non_empty_strings(self):
        """All metadataKey fields are non-empty strings."""
        entries = _build_metadata_entries(
            agent_name="bob",
            agent_card_data={"name": "bob"},
        )
        for entry in entries:
            key = entry["metadataKey"]
            assert isinstance(key, str) and key, (
                f"metadataKey must be a non-empty string, got {key!r}"
            )

    def test_custom_labels_are_reflected_in_entries(self):
        """Labels kwarg overrides default category/type values."""
        entries = _build_metadata_entries(
            agent_name="bob",
            agent_card_data={},
            labels={"category": "storage", "type": "provider"},
        )
        entry_map = {e["metadataKey"]: e["metadataValue"] for e in entries}
        assert Web3.to_hex(text="storage") == entry_map["category"]
        assert Web3.to_hex(text="provider") == entry_map["type"]


# ---------------------------------------------------------------------------
# Other contract function encoding guards
# ---------------------------------------------------------------------------


class TestContractFunctionEncoding:
    """Smoke-encode all contract functions used by registration.py.

    Each test confirms the function exists in the ABI under the expected
    signature and that simple valid arguments encode without error.
    A failure here means the ABI was updated and the calling code needs review.
    """

    def test_get_metadata_encodes(self, contract):
        """getMetadata(uint256 agentId, string metadataKey) → bytes."""
        encoded = contract.encode_abi("getMetadata", args=[1, "name"])
        assert isinstance(encoded, (bytes, str)) and len(encoded) > 0

    def test_set_metadata_encodes(self, contract):
        """setMetadata(uint256 agentId, string metadataKey, bytes metadataValue)."""
        encoded = contract.encode_abi(
            "setMetadata",
            args=[1, "name", b"test-agent"],
        )
        assert isinstance(encoded, (bytes, str)) and len(encoded) > 0

    def test_owner_of_encodes(self, contract):
        """ownerOf(uint256 tokenId) → address."""
        encoded = contract.encode_abi("ownerOf", args=[1])
        assert isinstance(encoded, (bytes, str)) and len(encoded) > 0

    def test_set_agent_uri_encodes(self, contract):
        """setAgentURI(uint256 agentId, string agentURI) — used for token URI updates."""
        encoded = contract.encode_abi(
            "setAgentURI",
            args=[1, "http://sell_agent:8001/.well-known/erc-8004-registration.json"],
        )
        assert isinstance(encoded, (bytes, str)) and len(encoded) > 0
