from __future__ import annotations

from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]


def _toml(path: str) -> dict[str, object]:
    return tomllib.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def _field_paths(value: object, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return set()
    paths: set[str] = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        paths.add(path.lower())
        paths.update(_field_paths(child, path))
    return paths


def test_alkahest_profiles_keep_policy_outside_chains() -> None:
    for relative_path in (
        "domains/vms/storefront/storefront.bob.toml",
        "domains/vms/storefront/storefront.alice.toml",
    ):
        config = _toml(relative_path)
        settlement = config["Settlement"]
        assert settlement["schema_version"] == 1
        assert settlement["priority"] == ["alkahest.v1"]
        assert settlement["alkahest"]["enabled"] is True
        assert "address_config_path" in settlement["alkahest"]
        assert all(
            "alkahest" not in field
            for chain in config["Chains"].values()
            for field in chain
        )


def test_public_deployment_config_examples_exclude_wallet_credentials() -> None:
    for relative_path in (
        "domains/vms/storefront/storefront.bob.toml",
        "domains/vms/storefront/storefront.alice.toml",
    ):
        config = _toml(relative_path)
        assert "wallet.private_key" not in _field_paths(config)
        assert config["Settlement"]["priority"] == ["alkahest.v1"]


#: Every storefront that adopts the hosted mechanism and projects its status.
_HOSTED_PROJECTIONS = (
    "domains/vms/storefront/src/market_storefront/settlement_composition.py",
    "domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py",
    "domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/hosted_lifecycle.py",
)
