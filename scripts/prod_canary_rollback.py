#!/usr/bin/env python3
"""Production canary rollback helper."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterable


if "market.canary_rollback" in sys.modules:
    _ROLLBACK_MODULE = sys.modules["market.canary_rollback"]
else:
    _ROLLBACK_MODULE = importlib.import_module("market.canary_rollback")


def main(argv: Iterable[str] | None = None) -> int:
    return _ROLLBACK_MODULE.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
