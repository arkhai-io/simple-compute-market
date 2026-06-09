"""Compatibility entry point for the VM buyer CLI.

The concrete executable lives under ``domains.vms.buyer``. This module keeps
the historical ``market_buyer.cli:app`` console-script target working while
the package migration is in progress.
"""

from __future__ import annotations

import sys
from pathlib import Path


_repo_root = Path(__file__).resolve().parents[2]
if (_repo_root / "domains" / "vms").exists():
    sys.path.insert(0, str(_repo_root))

from domains.vms.buyer.cli import app


if __name__ == "__main__":
    app()
