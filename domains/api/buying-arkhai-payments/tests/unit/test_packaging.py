"""A buyer composing only the payment stage installs no escrow or selling distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

LOCK = Path(__file__).resolve().parents[2] / "uv.lock"


def test_a_payments_only_buyer_installs_no_escrow_or_selling_distribution():
    packages = {package["name"] for package in tomllib.loads(LOCK.read_text())["package"]}

    assert {"arkhai-api-buying", "arkhai-api-buying-arkhai-payments", "arkhai-kit-arkhai-payments"} <= packages
    assert {
        "arkhai-api-buying-alkahest",
        "arkhai-kit-alkahest",
        "arkhai-api-selling",
        "arkhai-api-selling-arkhai-payments",
        "arkhai-api-authority",
    }.isdisjoint(packages)
