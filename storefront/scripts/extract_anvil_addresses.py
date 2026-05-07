#!/usr/bin/env python3
"""Generate Anvil Alkahest address config from EnvTestManager.

This script spins up a fresh EnvTestManager (which starts Anvil + deploys contracts),
extracts the deployed address configuration, and writes it to JSON.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from alkahest_py import EnvTestManager


SECTION_FIELDS: dict[str, list[str]] = {
    "arbiters_addresses": [
        "eas",
        "trivial_arbiter",
        "trusted_oracle_arbiter",
        "intrinsics_arbiter",
        "intrinsics_arbiter_2",
        "erc8004_arbiter",
        "any_arbiter",
        "all_arbiter",
        "attester_arbiter",
        "expiration_time_after_arbiter",
        "expiration_time_before_arbiter",
        "expiration_time_equal_arbiter",
        "recipient_arbiter",
        "ref_uid_arbiter",
        "revocable_arbiter",
        "schema_arbiter",
        "time_after_arbiter",
        "time_before_arbiter",
        "time_equal_arbiter",
        "uid_arbiter",
        "exclusive_revocable_confirmation_arbiter",
        "exclusive_unrevocable_confirmation_arbiter",
        "nonexclusive_revocable_confirmation_arbiter",
        "nonexclusive_unrevocable_confirmation_arbiter",
    ],
    "erc20_addresses": [
        "eas",
        "barter_utils",
        "escrow_obligation_nontierable",
        "escrow_obligation_tierable",
        "payment_obligation",
    ],
    "erc721_addresses": [
        "eas",
        "barter_utils",
        "escrow_obligation_nontierable",
        "escrow_obligation_tierable",
        "payment_obligation",
    ],
    "erc1155_addresses": [
        "eas",
        "barter_utils",
        "escrow_obligation_nontierable",
        "escrow_obligation_tierable",
        "payment_obligation",
    ],
    "native_token_addresses": [
        "eas",
        "barter_utils",
        "escrow_obligation_nontierable",
        "escrow_obligation_tierable",
        "payment_obligation",
    ],
    "token_bundle_addresses": [
        "eas",
        "barter_utils",
        "escrow_obligation_nontierable",
        "escrow_obligation_tierable",
        "payment_obligation",
    ],
    "attestation_addresses": [
        "eas",
        "eas_schema_registry",
        "barter_utils",
        "escrow_obligation_nontierable",
        "escrow_obligation_tierable",
        "escrow_obligation_2_nontierable",
        "escrow_obligation_2_tierable",
    ],
    "string_obligation_addresses": [
        "eas",
        "obligation",
    ],
    "commit_reveal_obligation_addresses": [
        "eas",
        "obligation",
    ],
}


def _extract_addresses(env: EnvTestManager) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for section, fields in SECTION_FIELDS.items():
        section_obj = getattr(env.addresses, section)
        out[section] = {field: str(getattr(section_obj, field)) for field in fields}
    return out


def _normalized_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="src/market_storefront/data/alkahest_anvil_addresses.json",
        help="Path to write JSON config",
    )
    args = parser.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Starting EnvTestManager and extracting deployed Anvil addresses...")
    env = EnvTestManager()
    addresses = _extract_addresses(env)
    output_text = _normalized_json(addresses)

    if out_path.exists():
        try:
            existing_obj = json.loads(out_path.read_text(encoding="utf-8"))
            if existing_obj != addresses:
                print(
                    f"WARNING: Existing file differs and will be overwritten: {out_path}"
                )
        except Exception:
            print(f"WARNING: Existing file is not valid JSON and will be overwritten: {out_path}")

    out_path.write_text(output_text, encoding="utf-8")
    print(f"Wrote Anvil address config: {out_path}")
    print("Use with: ALKAHEST_ADDRESS_CONFIG_PATH=" + str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
