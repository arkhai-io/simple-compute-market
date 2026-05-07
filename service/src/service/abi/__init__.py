"""Vendored contract ABIs (read-only).

Bundled here so consumers (escrow inspection commands, future
indexers) don't need to depend on a local `~/dev/arkhai/alkahest`
checkout. Refresh by re-extracting from the upstream alkahest build
artifacts under `contracts/out/`.

Files:
  IEAS.json  — Ethereum Attestation Service interface (getAttestation,
               attest, revoke, isAttestationValid, version, …).
               Source: alkahest/contracts/out/IEAS.sol/IEAS.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_ABI_DIR = Path(__file__).resolve().parent


def load_abi(name: str) -> list[dict[str, Any]]:
    """Load a vendored ABI by filename stem (e.g. 'IEAS')."""
    path = _ABI_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"ABI {name!r} not found at {path}. Vendored ABIs live in "
            f"service/src/service/abi/."
        )
    return json.loads(path.read_text())["abi"]
