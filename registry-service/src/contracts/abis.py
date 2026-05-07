"""ERC-8004 ABI loader.

ABI JSONs live in ``registry-service/src/contracts/abi/``, vendored from
the upstream alkahest/contracts/lib/erc-8004-contracts compiled
artifacts. Refresh by re-extracting the ``abi`` field from
``artifacts/contracts/<name>Upgradeable.sol/<name>Upgradeable.json``.

Mirrors the loader pattern in ``service.clients.erc8004.abi`` but kept
local because registry-service is a standalone deployable that doesn't
depend on the market-service package.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ABI_DIR = Path(__file__).resolve().parent / "abi"


def load_erc8004_abi(name: str) -> list[dict[str, Any]]:
    """Load a vendored ERC-8004 ABI by short name.

    Accepts: "IdentityRegistry", "ReputationRegistry", "ValidationRegistry".
    """
    path = _ABI_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"ERC-8004 ABI {name!r} not found at {path}. Vendored ABIs live in "
            f"registry-service/src/contracts/abi/."
        )
    return json.loads(path.read_text())["abi"]


IDENTITY_REGISTRY_ABI = load_erc8004_abi("IdentityRegistry")
