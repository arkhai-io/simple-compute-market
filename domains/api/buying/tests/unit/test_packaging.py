"""The buying library installs no mechanism kit and no selling or authority distribution.

The environment is this project's own: its lock resolves the library with
everything it needs, and nothing else.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

LOCK = Path(__file__).resolve().parents[2] / "uv.lock"


def test_the_buying_library_installs_no_mechanism_kit_or_other_side():
    packages = {package["name"] for package in tomllib.loads(LOCK.read_text())["package"]}

    assert {"arkhai-api-buying", "arkhai-core-buyer"} <= packages
    assert {
        "arkhai-kit-alkahest",
        "arkhai-kit-arkhai-payments",
        "arkhai-api-selling",
        "arkhai-api-authority",
        "arkhai-api-buying-alkahest",
        "arkhai-api-buying-arkhai-payments",
    }.isdisjoint(packages)
