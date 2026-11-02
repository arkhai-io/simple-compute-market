#!/usr/bin/env python3
"""Run the installed-resource conformance replay from a source checkout."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_arkhai_payments.fixtures.conformance import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
