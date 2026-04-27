"""Pytest configuration for domain/compute tests.

Ensures the repo root is on sys.path so that imports like
``from domain.compute.agent.app.policy.arkhai_common import ...`` and
``from market_storefront...`` resolve correctly from any working
directory.
"""
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
