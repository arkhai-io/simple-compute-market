#!/usr/bin/env python3
"""Generate the test chain's baked Anvil state and Alkahest address book.

Spins up ``EnvTestManager`` (which boots an internal Anvil and deploys the
full Alkahest contract suite + mock tokens), funds Alice and Bob with MOCK,
then captures two artifacts from that one deployment:

  * ``test-env/state/state.json`` — the Anvil state snapshot, loaded at
    container startup via ``anvil --load-state``. Produced by decoding the
    ``anvil_dumpState`` blob (hex-encoded gzip) into the JSON form that
    ``--load-state`` consumes.
  * ``storefront/.../data/alkahest_anvil_addresses.json`` — the deployed
    contract addresses, read by the storefront at runtime.

Both derive from the same deployment, so they cannot drift. Regenerate when
the alkahest_py version changes:

    cd storefront && uv run --find-links ../.dist python ../test-env/generate_state.py
"""

from __future__ import annotations

import gzip
import json
import pathlib
import urllib.request

from alkahest_py import EnvTestManager, MockERC20

# The market's test wallets are the standard deterministic Anvil accounts the
# buyer/seller configs use (integration-tests/config/*, the storefront .toml
# files) — NOT alkahest's env.alice/env.bob, which newer alkahest randomizes.
# The buyer (account #1) escrows MOCK during a deal with no runtime funding, so
# it must hold enough raw base units for bundled 18-decimal dev inventory;
# account #2 is funded likewise.
FUNDING = 1_000 * 10**18
TRANSFER_CHUNK = 9 * 10**18
FUNDED_ACCOUNTS = {
    "anvil #1 (buyer)": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    "anvil #2": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
}

TEST_ENV_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = TEST_ENV_DIR.parent
STATE_PATH = TEST_ENV_DIR / "state" / "state.json"
ADDRESSES_PATH = (
    REPO_ROOT / "storefront" / "src" / "market_storefront" / "data" / "alkahest_anvil_addresses.json"
)

# Fields mirrored from the storefront's address config schema. Each maps to an
# attribute on the corresponding ``env.addresses.<section>`` object.
SECTION_FIELDS: dict[str, list[str]] = {
    "arbiters_addresses": [
        "eas", "trivial_arbiter", "trusted_oracle_arbiter", "intrinsics_arbiter",
        "intrinsics_arbiter_2", "erc8004_arbiter", "any_arbiter", "all_arbiter",
        "attester_arbiter", "expiration_time_after_arbiter", "expiration_time_before_arbiter",
        "expiration_time_equal_arbiter", "recipient_arbiter", "ref_uid_arbiter",
        "revocable_arbiter", "schema_arbiter", "time_after_arbiter", "time_before_arbiter",
        "time_equal_arbiter", "uid_arbiter", "exclusive_revocable_confirmation_arbiter",
        "exclusive_unrevocable_confirmation_arbiter", "nonexclusive_revocable_confirmation_arbiter",
        "nonexclusive_unrevocable_confirmation_arbiter",
    ],
    "erc20_addresses": ["eas", "barter_utils", "escrow_obligation_nontierable", "escrow_obligation_tierable", "payment_obligation"],
    "erc721_addresses": ["eas", "barter_utils", "escrow_obligation_nontierable", "escrow_obligation_tierable", "payment_obligation"],
    "erc1155_addresses": ["eas", "barter_utils", "escrow_obligation_nontierable", "escrow_obligation_tierable", "payment_obligation"],
    "native_token_addresses": ["eas", "barter_utils", "escrow_obligation_nontierable", "escrow_obligation_tierable", "payment_obligation"],
    "token_bundle_addresses": ["eas", "barter_utils", "escrow_obligation_nontierable", "escrow_obligation_tierable", "payment_obligation"],
    "attestation_addresses": ["eas", "eas_schema_registry", "barter_utils", "escrow_obligation_nontierable", "escrow_obligation_tierable", "escrow_obligation_2_nontierable", "escrow_obligation_2_tierable"],
    "string_obligation_addresses": ["eas", "obligation"],
    "commit_reveal_obligation_addresses": ["eas", "obligation"],
}


def rpc(rpc_url: str, method: str, params: list) -> object:
    req = urllib.request.Request(
        rpc_url,
        data=json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    if "error" in result:
        raise RuntimeError(f"RPC error {method}: {result['error']}")
    return result["result"]


def extract_addresses(env: EnvTestManager) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for section, fields in SECTION_FIELDS.items():
        section_obj = getattr(env.addresses, section)
        out[section] = {field: str(getattr(section_obj, field)) for field in fields}
    return out


def transfer_mock_in_chunks(mock: MockERC20, addr: str, amount: int) -> None:
    remaining = amount
    while remaining > 0:
        chunk = min(remaining, TRANSFER_CHUNK)
        mock.transfer(addr, chunk)
        remaining -= chunk


def main() -> int:
    print("Starting EnvTestManager (boots Anvil + deploys Alkahest)...")
    env = EnvTestManager()
    rpc_url = env.rpc_url.replace("ws://", "http://").rstrip("/")

    print(f"  god:   {env.god}")
    print(f"  MOCK:  {env.mock_addresses.erc20_a}")

    mock = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
    for label, addr in FUNDED_ACCOUNTS.items():
        print(f"Funding {label} {addr} with {FUNDING:,} raw MOCK units...")
        transfer_mock_in_chunks(mock, addr, FUNDING)

    # anvil_dumpState returns hex-encoded gzip of the SerializableState JSON;
    # `anvil --load-state` consumes the decompressed JSON form.
    print("Dumping chain state...")
    dump_hex = rpc(rpc_url, "anvil_dumpState", [])
    assert isinstance(dump_hex, str)
    state_json = gzip.decompress(bytes.fromhex(dump_hex[2:] if dump_hex.startswith("0x") else dump_hex))

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_bytes(state_json)
    print(f"Wrote {STATE_PATH} ({len(state_json):,} bytes)")

    addresses = extract_addresses(env)
    ADDRESSES_PATH.write_text(json.dumps(addresses, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {ADDRESSES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
