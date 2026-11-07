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


def test_the_minimum_is_the_first_release_writing_lock_revision_5() -> None:
    # Measured by locking a fresh project with each release: 0.12.21 writes
    # revision 3 and 0.12.22 writes revision 5.
    assert uv.MINIMUM == (0, 12, 22)


@pytest.mark.parametrize("printed", ["uv 0.12.22", "uv 0.12.24 (x)", "uv 0.13.0", "uv 1.0.0"])
def test_the_minimum_or_newer_passes(printed: str) -> None:
    assert uv.problem(lambda: printed) is None


@pytest.mark.parametrize("printed", ["uv 0.12.21 (x)", "uv 0.12.19", "uv 0.11.17"])
def test_an_older_uv_is_refused_naming_both_versions(printed: str) -> None:
    found = uv.problem(lambda: printed)

    assert found is not None
    assert printed.split()[1] in found and "0.12.22" in found


def test_an_unreadable_version_is_refused() -> None:
    assert "no uv version" in (uv.problem(lambda: "") or "")
