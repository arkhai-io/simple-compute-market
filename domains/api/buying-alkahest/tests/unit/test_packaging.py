"""A buyer composing only the escrow stage installs no payments or selling distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

LOCK = Path(__file__).resolve().parents[2] / "uv.lock"


def test_an_alkahest_only_buyer_installs_no_payments_or_selling_distribution():
    packages = {package["name"] for package in tomllib.loads(LOCK.read_text())["package"]}

    assert {"arkhai-api-buying", "arkhai-api-buying-alkahest", "arkhai-kit-alkahest"} <= packages
    assert {
        "arkhai-api-buying-arkhai-payments",
        "arkhai-api-selling",
        "arkhai-api-selling-alkahest",
        "arkhai-api-authority",
    }.isdisjoint(packages)
