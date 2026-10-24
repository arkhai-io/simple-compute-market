"""A storefront environment composing only the escrow stage installs no payments or buying distribution.

The environment is this project's own: its lock resolves the selling library
and the escrow library with everything they need, and nothing else.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

LOCK = Path(__file__).resolve().parents[2] / "uv.lock"


def test_an_alkahest_only_environment_installs_no_payments_or_buying_distribution():
    packages = {package["name"] for package in tomllib.loads(LOCK.read_text())["package"]}

    assert {"arkhai-api-selling", "arkhai-api-selling-alkahest", "arkhai-kit-alkahest"} <= packages
    assert {
        "arkhai-kit-arkhai-payments",
        "arkhai-api-selling-arkhai-payments",
        "arkhai-api-buying",
        "arkhai-api-buying-alkahest",
        "arkhai-api-buying-arkhai-payments",
    }.isdisjoint(packages)
