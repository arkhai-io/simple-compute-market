"""A storefront environment composing only the payment stage installs no other mechanism stage or buying distribution.

The environment is this project's own: its lock resolves the selling library
and the payments library with everything they need, and nothing else.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

LOCK = Path(__file__).resolve().parents[2] / "uv.lock"


def test_a_payments_only_environment_installs_no_escrow_stage_or_buying_distribution():
    packages = {package["name"] for package in tomllib.loads(LOCK.read_text())["package"]}

    assert {"arkhai-api-selling", "arkhai-api-selling-arkhai-payments", "arkhai-kit-arkhai-payments"} <= packages
    assert {
        "arkhai-api-selling-alkahest",
        "arkhai-api-buying",
        "arkhai-api-buying-alkahest",
        "arkhai-api-buying-arkhai-payments",
    }.isdisjoint(packages)
