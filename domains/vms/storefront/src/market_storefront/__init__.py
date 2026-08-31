"""VM storefront executable package."""

from __future__ import annotations

import sys
from pathlib import Path


def _add_checkout_root_to_path() -> None:
    """Support local editable installs after moving under domains/vms.

    Docker sets ``PYTHONPATH=/app`` before importing the storefront. Host-side
    ``uv run market-storefront`` from this package does not, so domain imports
    like ``domains.vms.listings`` need the monorepo root on ``sys.path``.
    """

    for parent in Path(__file__).resolve().parents:
        if (parent / "domains" / "vms").is_dir():
            root = str(parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            return


_add_checkout_root_to_path()
