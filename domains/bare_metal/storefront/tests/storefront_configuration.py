"""Storefront configuration files for tests, written where the loader reads them.

The storefront reads its settings only from its configuration files, so a test
that composes it the way the server does writes those files under a temporary
``XDG_CONFIG_HOME``: the public document as ``storefront.json``, as a chart
renders it, and the Secret overlay as ``storefront.secrets.toml``.

Every principal, key, address, and URL here is a development fixture and must
never be used on a public network.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from market_identity import Eip191Signer

# Development keys; never used on any public network.
SELLER = Eip191Signer(bytes.fromhex("11" * 32))
SELLER_CREDENTIAL = "0x" + "11" * 32
ADMIN = Eip191Signer(bytes.fromhex("33" * 32))
SITE = Eip191Signer(bytes.fromhex("44" * 32))
REGISTRY = Eip191Signer(bytes.fromhex("55" * 32))

SITE_ID = "site-a"
REGISTRY_URL = "http://registry.test:8080"

CONTACT_SECTION = {
    "enabled": True,
    "contact_payload": {"email": "seller@bare-metal-test.invalid"},
    "profiles": {"default": {"channel": "email", "terms": "Test introduction."}},
    "retention_seconds": 60,
    "retention_sweep_interval_seconds": 3600,
}


def _principal(signer: Eip191Signer) -> dict[str, str]:
    return signer.identity.model_dump(mode="json")


def publishable_configuration(db_path: Path | str) -> dict[str, Any]:
    """A configuration the storefront starts under: one pinned registry, one
    site bound to one service peer, and contact exchange enabled, which needs
    no chain or wallet."""
    return {
        "base_url": "http://seller:8000",
        "db_path": str(db_path),
        "Identity": {
            "principal": _principal(SELLER),
            "administrators": {"operator": {"principals": [_principal(ADMIN)]}},
            "service_peers": {
                "site_a_authority": {
                    "role": "service",
                    "site_id": SITE_ID,
                    "principals": [_principal(SITE)],
                }
            },
        },
        "capacity": {"sites": {SITE_ID: "http://site-a.test:8081"}},
        "registry": {
            "urls": [REGISTRY_URL],
            "authorities": {
                REGISTRY_URL: {"authority": "registry", "principals": [_principal(REGISTRY)]}
            },
        },
        "Settlement": {
            "schema_version": 1,
            "priority": ["contact-exchange.v1"],
            "contact": CONTACT_SECTION,
        },
    }


def write_configuration(
    monkeypatch: Any,
    tmp_path: Path,
    document: Mapping[str, Any] | None = None,
    *,
    toml: str | None = None,
    secrets: str | None = None,
) -> Path:
    """Write the storefront's configuration files and point the loader at them.

    ``document`` is written as the rendered ``storefront.json``, ``toml`` as an
    operator's ``storefront.toml``, and ``secrets`` as the overlay. Returns the
    configuration directory.
    """
    directory = tmp_path / "xdg" / "arkhai"
    directory.mkdir(parents=True, exist_ok=True)
    if document is not None:
        (directory / "storefront.json").write_text(json.dumps(document), encoding="utf-8")
    if toml is not None:
        (directory / "storefront.toml").write_text(toml, encoding="utf-8")
    if secrets is not None:
        (directory / "storefront.secrets.toml").write_text(secrets, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(directory.parent))
    return directory
