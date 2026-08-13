#!/usr/bin/env python3
"""Fail when umbrella and storefront settlement schema fragments diverge."""

from __future__ import annotations

import json
from pathlib import Path


CHART_DIR = Path(__file__).resolve().parents[1]
ROOT_SCHEMA = CHART_DIR / "values.schema.json"
STOREFRONT_SCHEMA = CHART_DIR / "charts" / "storefront" / "values.schema.json"
SETTLEMENT_DEFINITIONS = (
    "stripeSettlement",
    "alkahestSettlement",
    "settlement",
    "wallet",
    "chains",
)


def main() -> int:
    root = json.loads(ROOT_SCHEMA.read_text(encoding="utf-8"))["definitions"]
    storefront = json.loads(STOREFRONT_SCHEMA.read_text(encoding="utf-8"))["definitions"]
    drifted = [
        name
        for name in SETTLEMENT_DEFINITIONS
        if root.get(name) != storefront.get(name)
    ]
    if drifted:
        names = ", ".join(drifted)
        raise SystemExit(f"generated Settlement schema drift: {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
