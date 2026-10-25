"""A buyer environment installs the buying libraries and no selling or authority distribution.

The environment is this project's own: its lock resolves the plugin with
everything it needs.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

LOCK = Path(__file__).resolve().parents[1] / "uv.lock"


def test_a_buyer_environment_installs_no_selling_or_authority_distribution():
    packages = {package["name"] for package in tomllib.loads(LOCK.read_text())["package"]}

    assert {
        "arkhai-api-buying",
        "arkhai-api-buying-alkahest",
        "arkhai-api-buying-arkhai-payments",
    } <= packages
    assert {
        "arkhai-api-selling",
        "arkhai-api-selling-alkahest",
        "arkhai-api-selling-arkhai-payments",
        "arkhai-api-authority",
        "arkhai-core-storefront",
        "arkhai-kit-capacity-publication",
        "arkhai-kit-storefront",
        "sqlalchemy",
    }.isdisjoint(packages)
