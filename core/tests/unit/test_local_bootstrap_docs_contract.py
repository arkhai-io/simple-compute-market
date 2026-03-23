from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ROOT_README = ROOT / "README.md"
REGISTRY_README = ROOT / "erc-8004-registry-py/README.md"
BUYER_QUICKSTART = ROOT / "docs/standup/buyer-quickstart.md"
SELLER_QUICKSTART = ROOT / "docs/standup/seller-quickstart.md"
PLATFORM_QUICKSTART = ROOT / "docs/standup/platform-quickstart.md"


def test_root_readme_uses_canonical_local_bootstrap_contract() -> None:
    text = ROOT_README.read_text(encoding="utf-8")

    for required_token in (
        "git submodule update --init --recursive",
        "python scripts/deploy_local_contracts.py --rpc-url <rpc-url>",
        "market dev deploy-contracts --rpc-url <rpc-url>",
        "ALKAHEST_ADDRESS_CONFIG_PATH",
    ):
        assert required_token in text, (
            "README.md must use the canonical local bootstrap contract token "
            f"{required_token!r}"
        )

    for forbidden_token in (
        "http://localhost:45165",
        "npm run deploy:anvil",
    ):
        assert forbidden_token not in text, (
            "README.md still contains a stale local bootstrap token "
            f"{forbidden_token!r}"
        )


def test_registry_readme_defers_to_root_local_bootstrap_contract() -> None:
    text = REGISTRY_README.read_text(encoding="utf-8")

    assert "scripts/deploy_local_contracts.py" in text
    assert "Navigate to erc-8004-contracts/ and run deployment scripts" not in text


def test_role_quickstarts_stop_advertising_installed_wrapper_paths() -> None:
    for path in (BUYER_QUICKSTART, SELLER_QUICKSTART, PLATFORM_QUICKSTART):
        text = path.read_text(encoding="utf-8")

        assert "## Installed Invocation" not in text
        assert "~/.market/scripts/" not in text
        assert "repo-checkout surface" in text
