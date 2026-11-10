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


class Clock:
    """An injected clock a test moves by hand."""

    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now
