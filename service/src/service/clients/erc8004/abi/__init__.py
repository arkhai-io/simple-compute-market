"""Vendored ERC-8004 contract ABIs (read-only).

Bundled here so the storefront and any future consumer don't need to
hand-paste ABI constants. Refresh by re-extracting the ``abi`` field
from the upstream ``alkahest/contracts/lib/erc-8004-contracts``
compiled artifacts (the ``Upgradeable`` artifacts under
``artifacts/contracts/<name>Upgradeable.sol/<name>Upgradeable.json``).

JSON files in this package:
  IdentityRegistry.json
  ReputationRegistry.json
  ValidationRegistry.json

The "Upgradeable" suffix is dropped here because consumers refer to the
contract by its functional name (the upgradeable wrapper is a deploy
detail, not a runtime distinction).

For backwards compatibility this module also exposes the legacy
``IDENTITY_REGISTRY_ABI`` / ``IDENTITY_REGISTRY_EVENTS`` /
``FULL_IDENTITY_REGISTRY_ABI`` symbols that used to live in a
hand-pasted ``abi.py`` module.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ABI_DIR = Path(__file__).resolve().parent


def load_erc8004_abi(name: str) -> list[dict[str, Any]]:
    """Load a vendored ERC-8004 ABI by short name.

    Accepts: "IdentityRegistry", "ReputationRegistry", "ValidationRegistry".
    """
    path = _ABI_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"ERC-8004 ABI {name!r} not found at {path}. Vendored ABIs live in "
            f"service/src/service/clients/erc8004/abi/."
        )
    return json.loads(path.read_text())["abi"]


IDENTITY_REGISTRY_ABI = load_erc8004_abi("IdentityRegistry")
IDENTITY_REGISTRY_EVENTS = [
    entry for entry in IDENTITY_REGISTRY_ABI if entry.get("type") == "event"
]
FULL_IDENTITY_REGISTRY_ABI = IDENTITY_REGISTRY_ABI

__all__ = [
    "load_erc8004_abi",
    "IDENTITY_REGISTRY_ABI",
    "IDENTITY_REGISTRY_EVENTS",
    "FULL_IDENTITY_REGISTRY_ABI",
]
