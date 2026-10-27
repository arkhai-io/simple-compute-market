"""An older uv is refused before it writes or judges the repository's locks."""

from __future__ import annotations

import pytest

import check_uv_version as uv


@pytest.mark.parametrize("printed,expected", [
    ("uv 0.12.19 (a1b2c3d 2026-10-01)\n", (0, 12, 19)),
    ("uv 0.12.0", (0, 12, 0)),
    ("uv 1.0", (1, 0)),
    ("", None),
    ("command not found", None),
])
def test_the_installed_version_is_read_from_uv(printed: str, expected) -> None:
    assert uv.installed(lambda: printed) == expected


@pytest.mark.parametrize("printed", ["uv 0.12.0", "uv 0.12.19 (x)", "uv 0.13.1", "uv 1.0.0"])
def test_the_minimum_or_newer_passes(printed: str) -> None:
    assert uv.problem(lambda: printed) is None


def test_an_older_uv_is_refused_naming_both_versions() -> None:
    found = uv.problem(lambda: "uv 0.11.17 (x)")

    assert found is not None and "0.11.17" in found and "0.12" in found


def test_an_unreadable_version_is_refused() -> None:
    assert "no uv version" in (uv.problem(lambda: "") or "")
