#!/usr/bin/env python3
"""Validate that the configured chain profile is coherent before a live rollout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NamedTuple
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHARED_SECRETS_DIR = Path("~/.config/web3-ops").expanduser()
DEFAULT_LOCAL_SECRETS_DIR = Path("~/.config/simple-market-service").expanduser()
BASE_SEPOLIA_TOKEN_REGISTRY = ROOT / "core/agent/app/data/token_registry_base_sepolia.json"
ETH_SEPOLIA_TOKEN_REGISTRY = ROOT / "core/agent/app/data/token_registry_eth_sepolia.json"
CHAIN_CONFIG = {
    "base_sepolia": {
        "chain_id": 84532,
        "rpc_env": "ALCHEMY_BASE_SEPOLIA_HTTP_URL",
        "token_registry": BASE_SEPOLIA_TOKEN_REGISTRY,
    },
    "base": {
        "chain_id": 8453,
        "rpc_env": "ALCHEMY_BASE_MAINNET_HTTP_URL",
        "token_registry": None,
    },
    "ethereum_sepolia": {
        "chain_id": 11155111,
        "rpc_env": "ETH_SEPOLIA_HTTP_RPC_URL",
        "token_registry": ETH_SEPOLIA_TOKEN_REGISTRY,
    },
    "ethereum_mainnet": {
        "chain_id": 1,
        "rpc_env": "ETH_MAINNET_HTTP_RPC_URL",
        "token_registry": None,
    },
}
REQUIRED_CONTRACT_KEYS = (
    "IDENTITY_REGISTRY_ADDRESS",
    "REPUTATION_REGISTRY_ADDRESS",
    "VALIDATION_REGISTRY_ADDRESS",
)


class ChainProfile(NamedTuple):
    chain_name: str
    chain_id: int
    rpc_url: str
    registry_addresses: dict[str, str]
    token_registry_path: Path | None


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = _strip_matching_quotes(value.strip())
    return values


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _optional_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return _parse_env_file(path)


def _load_merged_env_file(
    filename: str,
    *,
    shared_secrets_dir: Path,
    local_secrets_dir: Path,
) -> dict[str, str]:
    return {
        **_optional_env_file(shared_secrets_dir / filename),
        **_optional_env_file(local_secrets_dir / filename),
    }


def _require_keys(values: dict[str, str], *, label: str, keys: tuple[str, ...] | list[str]) -> None:
    missing = sorted(key for key in keys if not values.get(key))
    if missing:
        raise SystemExit(f"Missing required {label} keys: {', '.join(missing)}")


def load_chain_profile(
    *,
    shared_secrets_dir: Path = DEFAULT_SHARED_SECRETS_DIR,
    local_secrets_dir: Path = DEFAULT_LOCAL_SECRETS_DIR,
) -> ChainProfile:
    shared = _parse_env_file(local_secrets_dir / "shared.env")
    alchemy = _load_merged_env_file(
        "alchemy.env",
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
    )
    contracts = _parse_env_file(local_secrets_dir / "contracts.env")

    _require_keys(shared, label="shared.env", keys=("CHAIN_NAME",))
    chain_name = shared["CHAIN_NAME"]
    if chain_name not in CHAIN_CONFIG:
        raise SystemExit(
            "shared.env:CHAIN_NAME must be one of "
            + ", ".join(sorted(CHAIN_CONFIG))
            + f", got {chain_name}"
        )
    chain_config = CHAIN_CONFIG[chain_name]

    _require_keys(alchemy, label="alchemy.env", keys=(chain_config["rpc_env"],))
    _require_keys(contracts, label="contracts.env", keys=REQUIRED_CONTRACT_KEYS)

    token_registry_path = chain_config["token_registry"]
    if token_registry_path is not None and not token_registry_path.exists():
        raise SystemExit(f"Token registry path does not exist: {token_registry_path}")

    return ChainProfile(
        chain_name=chain_name,
        chain_id=int(shared.get("CHAIN_ID", chain_config["chain_id"])),
        rpc_url=alchemy[chain_config["rpc_env"]],
        registry_addresses={key: contracts[key] for key in REQUIRED_CONTRACT_KEYS},
        token_registry_path=token_registry_path,
    )


def _rpc_request(url: str, method: str, params: list[object]) -> object:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise SystemExit(f"RPC request failed for {method} against {url}: {exc}") from exc

    if "error" in body:
        raise SystemExit(
            f"RPC request failed for {method} against {url}: {body['error']}"
        )
    return body["result"]


def validate_chain_profile(profile: ChainProfile) -> dict[str, object]:
    reported_chain_id_hex = str(_rpc_request(profile.rpc_url, "eth_chainId", []))
    reported_chain_id = int(reported_chain_id_hex, 16)
    if reported_chain_id != profile.chain_id:
        raise SystemExit(
            f"{profile.chain_name} RPC reported chain id {reported_chain_id}, expected {profile.chain_id}"
        )

    for label, address in profile.registry_addresses.items():
        code = str(_rpc_request(profile.rpc_url, "eth_getCode", [address, "latest"]))
        if code in {"0x", "0x0", ""}:
            raise SystemExit(f"{label} has no bytecode on {profile.chain_name}: {address}")

    result: dict[str, object] = {
        "chain_name": profile.chain_name,
        "chain_id": profile.chain_id,
        "rpc_url": profile.rpc_url,
        "contracts": profile.registry_addresses,
    }
    if profile.token_registry_path is not None:
        result["token_registry_path"] = str(profile.token_registry_path)
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-secrets-dir", type=Path, default=DEFAULT_SHARED_SECRETS_DIR)
    parser.add_argument("--local-secrets-dir", type=Path, default=DEFAULT_LOCAL_SECRETS_DIR)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the successful validation result as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    profile = load_chain_profile(
        shared_secrets_dir=args.shared_secrets_dir.expanduser(),
        local_secrets_dir=args.local_secrets_dir.expanduser(),
    )
    result = validate_chain_profile(profile)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"[ok] validated {profile.chain_name} chain profile against {profile.rpc_url}"
        )
        for label, address in profile.registry_addresses.items():
            print(f"[ok] {label} has bytecode at {address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
