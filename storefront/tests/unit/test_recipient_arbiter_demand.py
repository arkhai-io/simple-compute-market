"""Unit tests for `encode_recipient_demand` + `get_recipient_arbiter`.

The encoder produces the bytes that the escrow contract will pass to
RecipientArbiter.checkObligation as `demand`. The Solidity struct is
`struct DemandData { address recipient; }`, which `abi.encode` lays out
as a single 32-byte address slot (12 zero bytes of padding + 20 address
bytes). We verify shape and round-trip-decode.
"""

from __future__ import annotations

import pytest

from service.clients.alkahest import encode_recipient_demand


_SAMPLE = "0xAaAaaaaaAAaaAAaaAaaaaAAAAAAAAAaaaAaaaAaA"


def test_encode_produces_32_byte_output():
    encoded = encode_recipient_demand(_SAMPLE)
    assert isinstance(encoded, bytes)
    assert len(encoded) == 32


def test_encode_has_correct_address_layout():
    """abi.encode(address) = 12 bytes of zero padding + 20 address bytes."""
    encoded = encode_recipient_demand(_SAMPLE)
    assert encoded[:12] == b"\x00" * 12
    # Last 20 bytes are the address, matched against the lowercased hex.
    expected_addr_bytes = bytes.fromhex(_SAMPLE[2:])
    assert encoded[12:] == expected_addr_bytes


def test_encode_roundtrips_via_abi_decode():
    from eth_abi import decode as _abi_decode
    encoded = encode_recipient_demand(_SAMPLE)
    (decoded,) = _abi_decode(["address"], encoded)
    assert decoded.lower() == _SAMPLE.lower()


@pytest.mark.parametrize("bad", [
    "",
    "0x",
    "not-an-address",
    "0x1234",  # too short
    "0x" + "a" * 41,  # off by one
    "0x" + "z" * 40,  # non-hex
    None,
])
def test_encode_rejects_malformed(bad):
    with pytest.raises((ValueError, TypeError)):
        encode_recipient_demand(bad)
