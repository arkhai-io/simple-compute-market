"""Lock currency, checked against locks the real `uv` produces.

uv's lock serialisation is the boundary under test: whether a section or an
edge is recorded at all decides what `check_locks` can see. These tests write
wheels directly into a temporary wheelhouse, lock a consumer with the real
`uv` isolated from every package index, rebuild a wheel at the same version,
and run the check on what uv wrote.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="needs the uv executable")

_SPEC = importlib.util.spec_from_file_location(
    "check_locks", Path(__file__).resolve().parents[1] / "check_locks.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


def _wheel(wheelhouse: Path, name: str, version: str, requires: list[str] = (),
           extras: list[str] = ()) -> None:
    stem = name.replace("-", "_")
    for old in wheelhouse.glob(f"{stem}-{version}-*.whl"):
        old.unlink()
    info = f"{stem}-{version}.dist-info"
    metadata = [f"Metadata-Version: 2.3", f"Name: {name}", f"Version: {version}"]
    metadata += [f"Provides-Extra: {extra}" for extra in extras]
    metadata += [f"Requires-Dist: {requirement}" for requirement in requires]
    files = {
        f"{stem}/__init__.py": "",
        f"{info}/METADATA": "\n".join(metadata) + "\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    files[f"{info}/RECORD"] = "".join(f"{path},,\n" for path in files) + f"{info}/RECORD,,\n"
    with zipfile.ZipFile(wheelhouse / f"{stem}-{version}-py3-none-any.whl", "w") as archive:
        for path, text in files.items():
            archive.writestr(path, text)


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("UV_NO_INDEX", "1")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("UV_PYTHON", raising=False)
    root = tmp_path / "repo"
    wheelhouse = root / ".dist"
    wheelhouse.mkdir(parents=True)
    core = root / "kit" / "core"
    core.mkdir(parents=True)
    (core / "pyproject.toml").write_text('[project]\nname = "ex-core"\nversion = "0.3.0"\n', "utf-8")
    for name in ("ex-base", "ex-windows", "ex-client-dep", "ex-other-dep"):
        _wheel(wheelhouse, name, "1.0.0")
    return root


def _core(root: Path, requires: list[str]) -> None:
    _wheel(root / ".dist", "ex-core", "0.3.0", requires, extras=["client", "admin"])


def _consumer(root: Path, requirement: str) -> Path:
    project = root / "domains" / "app"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "ex-app"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
        f'dependencies = ["{requirement}"]\n', "utf-8"
    )
    subprocess.run(["uv", "lock", "--offline", "--find-links", "../../.dist"],
                   cwd=project, check=True, capture_output=True)
    return project


def _uv_lock_check_passes(project: Path) -> bool:
    return subprocess.run(["uv", "lock", "--check", "--offline", "--find-links", "../../.dist"],
                          cwd=project, capture_output=True).returncode == 0


def test_a_current_lock_passes_with_marked_and_extra_scoped_requirements(repository):
    _core(repository, ["ex-base>=1", 'ex-windows>=1; sys_platform == "win32"',
                       'ex-client-dep>=1; extra == "client"'])
    _consumer(repository, "ex-core[client]==0.3.0")

    assert checker.problems(repository) == []


def test_a_same_version_wheel_that_gained_a_requirement_fails(repository):
    _core(repository, [])
    _consumer(repository, "ex-core==0.3.0")
    _core(repository, ["ex-base>=1"])

    assert checker.problems(repository) == [
        "domains/app: ex-core's wheel requires ex-base, which the lock does not record; run `make lock`"
    ]


def test_an_empty_requested_extra_that_gains_a_requirement_fails(repository):
    _core(repository, [])
    project = _consumer(repository, "ex-core[client]==0.3.0")
    _core(repository, ['ex-client-dep>=1; extra == "client"'])

    assert _uv_lock_check_passes(project)
    assert checker.problems(repository) == [
        "domains/app: ex-core[client]'s wheel requires ex-client-dep, which the lock does "
        "not record; run `make lock`"
    ]


def test_an_extra_no_consumer_requests_may_change(repository):
    _core(repository, [])
    _consumer(repository, "ex-core[client]==0.3.0")
    _core(repository, ['ex-other-dep>=1; extra == "admin"'])

    assert checker.problems(repository) == []
