"""The wheelhouse digest, over a synthetic declaration and wheelhouse."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from release_bom import files_digest
from wheelhouse_digest import main, wheelhouse_digest

DECLARATION = {
    "distributions": [{"key": "core", "path": "core", "dist": "arkhai-core"},
                      {"key": "kit-site", "path": "kit/site", "dist": "arkhai-kit-site"}],
    "images": [{"name": "registry", "local": "registry"}],
    "chart": {"path": "helm"},
    "binaries": [{"name": "market", "target": "build-market-binary", "path": ".dist/bin/market"}],
    "development_images": [],
}
WHEELS = ("arkhai_core-1.0.0-py3-none-any.whl", "arkhai_kit_site-2.0.0-py3-none-any.whl")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "release-components.json").write_text(
        json.dumps(DECLARATION), encoding="utf-8")
    for entry, version in zip(DECLARATION["distributions"], ("1.0.0", "2.0.0")):
        (tmp_path / entry["path"]).mkdir(parents=True)
        (tmp_path / entry["path"] / "pyproject.toml").write_text(
            f'[project]\nname = "{entry["dist"]}"\nversion = "{version}"\n', encoding="utf-8")
    (tmp_path / ".dist").mkdir()
    for wheel in WHEELS:
        (tmp_path / ".dist" / wheel).write_bytes(wheel.encode())
    return tmp_path


def test_the_digest_is_the_dirhash_of_the_declared_wheels_alone(root: Path) -> None:
    (root / ".dist" / "lane_double_controls-0.1.0-py3-none-any.whl").write_bytes(b"test")
    (root / ".dist" / "arkhai_core-0.9.0-py3-none-any.whl").write_bytes(b"older")

    assert wheelhouse_digest(root) == files_digest(root / ".dist" / wheel for wheel in WHEELS)


def test_a_changed_wheel_changes_the_digest(root: Path) -> None:
    before = wheelhouse_digest(root)
    (root / ".dist" / WHEELS[1]).write_bytes(b"rebuilt")

    assert wheelhouse_digest(root) != before


def test_a_missing_declared_wheel_is_refused_naming_make_dist(
        root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (root / ".dist" / WHEELS[0]).unlink()

    assert main([], root=root) == 1

    error = capsys.readouterr().err
    assert "holds no wheel for 1 declared distribution(s)" in error
    assert "make dist" in error and WHEELS[0] in error


def test_the_command_prints_the_digest(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([], root=root) == 0

    assert capsys.readouterr().out == wheelhouse_digest(root) + "\n"
