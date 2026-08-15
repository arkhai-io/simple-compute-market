from __future__ import annotations

from pathlib import Path

import pytest
from arkhai_bare_metal_buyer.cli import _safe_projection
from arkhai_bare_metal_buyer.config import load_bare_metal_buyer_config
from arkhai_bare_metal_buyer.plugin import domain
from market_core import DomainCapability


PRINCIPAL = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def test_config_is_secret_free_and_strict(tmp_path: Path) -> None:
    path = tmp_path / "buyer.toml"
    path.write_text(
        """
[bare_metal]
registry_url = "https://registry.example"
registry_authority = "registry-prod"
registry_principals = [{scheme = "ed25519", identifier = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}]
default_duration_seconds = 7200
""".strip(),
        encoding="utf-8",
    )
    config = load_bare_metal_buyer_config(path)
    assert config.default_duration_seconds == 7200
    assert config.registry_trust.identities[0].identifier == PRINCIPAL

    path.write_text(
        path.read_text() + '\nprivate_key = "forbidden"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_bare_metal_buyer_config(path)


def test_transient_action_material_is_not_rendered() -> None:
    safe = _safe_projection(
        {
            "status": "awaiting_action",
            "action": {
                "kind": "redirect",
                "expires_at_unix": 123,
                "url": "https://provider.example/secret",
                "bank_instructions": {"account": "123"},
            },
        }
    )
    assert safe == {
        "status": "awaiting_action",
        "action_required": {"kind": "redirect", "expires_at_unix": 123},
    }


def test_plugin_declares_real_buyer_capability() -> None:
    contract = domain
    assert DomainCapability.BUYER in contract.declared_capabilities
    assert contract.buyer is not None
    assert contract.buyer.register_commands is not None
