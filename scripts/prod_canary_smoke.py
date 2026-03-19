#!/usr/bin/env python3
"""Production canary smoke test for the deployed full stack."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


CLI_ROOT = Path(__file__).resolve().parents[1] / "cli"
if str(CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(CLI_ROOT))

if "market.canary" in sys.modules:
    _CANARY_MODULE = sys.modules["market.canary"]
else:
    _CANARY_MODULE = importlib.import_module("market.canary")

main = _CANARY_MODULE.main


if __name__ == "__main__":
    raise SystemExit(main())
