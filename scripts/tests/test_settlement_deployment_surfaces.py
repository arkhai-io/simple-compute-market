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
        # A profile may offer other mechanisms beside Alkahest (Bob also offers
        # contact exchange); what matters here is that Alkahest is configured.
        assert "alkahest.v1" in settlement["priority"]
        assert settlement["alkahest"]["enabled"] is True
        assert "address_config_path" in settlement["alkahest"]
        # Each chain names the address book its Alkahest client is built from;
        # Alkahest policy itself stays in `Settlement.alkahest`.
        assert all(
            field == "alkahest_address_config_path"
            for chain in config["Chains"].values()
            for field in chain
            if "alkahest" in field
        )


def test_public_deployment_config_examples_exclude_wallet_credentials() -> None:
    for relative_path in (
        "domains/vms/storefront/storefront.bob.toml",
        "domains/vms/storefront/storefront.alice.toml",
    ):
        config = _toml(relative_path)
        assert "wallet.private_key" not in _field_paths(config)
        assert "alkahest.v1" in config["Settlement"]["priority"]
