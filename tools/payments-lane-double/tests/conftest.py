"""Shared paths and helpers for the double's suite."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "fixtures"


def committed_accounts() -> dict[str, Any]:
    with (FIXTURES / "accounts.toml").open("rb") as handle:
        return tomllib.load(handle)
