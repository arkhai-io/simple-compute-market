"""A committed lock matches its project, the wheels the tree builds, and the wheelhouse."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_locks", Path(__file__).resolve().parents[1] / "check_locks.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


def _current(project, wheelhouse):
    return None


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".dist").mkdir(parents=True)
    _declare(root, "kit/core", "arkhai-core", "0.3.0")
    return root


def _declare(root: Path, path: str, name: str, version: str) -> Path:
    project = root / path
    project.mkdir(parents=True, exist_ok=True)
    (project / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "{version}"\n', "utf-8")
    return project


def _wheel(root: Path, name: str, version: str, requires: list[str]) -> None:
    stem = name.replace("-", "_")
    with zipfile.ZipFile(root / ".dist" / f"{stem}-{version}-py3-none-any.whl", "w") as archive:
        lines = [f"Metadata-Version: 2.3", f"Name: {name}", f"Version: {version}"]
        lines += [f"Requires-Dist: {r}" for r in requires]
        archive.writestr(f"{stem}-{version}.dist-info/METADATA", "\n".join(lines) + "\n")


def _consumer(root: Path, packages: str) -> Path:
    project = _declare(root, "domains/consumer", "arkhai-consumer", "0.1.0")
    (project / "uv.lock").write_text(
        'version = 1\n\n[[package]]\nname = "arkhai-consumer"\nversion = "0.1.0"\n'
        'source = { editable = "." }\n\n' + packages, "utf-8"
    )
    return project


CORE = '''[[package]]
name = "arkhai-core"
version = "0.3.0"
source = { registry = "../../.dist" }
dependencies = [
    { name = "pydantic" },
]

[[package]]
name = "pydantic"
version = "2.9.0"
source = { registry = "https://pypi.org/simple" }
'''


def _problems(root: Path, lock_check=_current) -> list[str]:
    return checker.problems(root, lock_check=lock_check)


def test_a_current_lock_passes(tmp_path):
    root = _repository(tmp_path)
    _wheel(root, "arkhai-core", "0.3.0", ["pydantic>=2", 'tomli; python_version < "3.11"'])
    _consumer(root, CORE)

    assert _problems(root) == []


def test_a_lock_that_no_longer_matches_its_project_fails(tmp_path):
    root = _repository(tmp_path)
    _wheel(root, "arkhai-core", "0.3.0", ["pydantic>=2"])
    _consumer(root, CORE)

    found = _problems(root, lambda project, wheelhouse: "lockfile needs to be updated")
    assert found == ["domains/consumer: lock does not match the project (lockfile needs to be updated); run `make lock`"]


def test_a_superseded_internal_version_fails(tmp_path):
    root = _repository(tmp_path)
    _declare(root, "kit/core", "arkhai-core", "0.4.0")
    _consumer(root, CORE)

    assert _problems(root) == ["domains/consumer: pins arkhai-core==0.3.0; the tree builds 0.4.0"]


def test_a_same_version_wheel_that_gained_a_requirement_fails(tmp_path):
    root = _repository(tmp_path)
    _wheel(root, "arkhai-core", "0.3.0", ["pydantic>=2", "six"])
    _consumer(root, CORE)

    assert _problems(root) == [
        "domains/consumer: arkhai-core's wheel requires six, which the lock does not record; run `make lock`"
    ]


def test_a_same_version_wheel_that_dropped_a_requirement_fails(tmp_path):
    root = _repository(tmp_path)
    _wheel(root, "arkhai-core", "0.3.0", [])
    _consumer(root, CORE)

    assert _problems(root) == [
        "domains/consumer: the lock records pydantic for arkhai-core, which its wheel no longer requires; run `make lock`"
    ]


def test_an_extra_requested_only_through_requires_dist_is_compared(tmp_path):
    """uv records neither a section nor an edge extra for an empty extra."""
    root = _repository(tmp_path)
    _wheel(root, "arkhai-core", "0.3.0", ["pydantic>=2", 'httpx; extra == "client"'])
    project = _consumer(root, CORE)
    lock = (project / "uv.lock").read_text("utf-8")
    (project / "uv.lock").write_text(lock.replace(
        'source = { editable = "." }\n',
        'source = { editable = "." }\n\n[package.metadata]\n'
        'requires-dist = [{ name = "arkhai-core", extras = ["client"] }]\n', 1), "utf-8")

    assert _problems(root) == [
        "domains/consumer: arkhai-core[client]'s wheel requires httpx, which the lock does not record; run `make lock`"
    ]


def test_an_extra_requested_by_another_internal_wheel_is_compared(tmp_path):
    root = _repository(tmp_path)
    _declare(root, "kit/site", "arkhai-site", "0.1.0")
    _wheel(root, "arkhai-core", "0.3.0", ["pydantic>=2", 'httpx; extra == "client"'])
    _wheel(root, "arkhai-site", "0.1.0", ["arkhai-core[client]"])
    _consumer(root, CORE + '''
[[package]]
name = "arkhai-site"
version = "0.1.0"
source = { registry = "../../.dist" }
dependencies = [
    { name = "arkhai-core" },
]
''')

    assert _problems(root) == [
        "domains/consumer: arkhai-core[client]'s wheel requires httpx, which the lock does not record; run `make lock`"
    ]


def test_a_locked_version_the_wheel_no_longer_admits_fails(tmp_path):
    root = _repository(tmp_path)
    _wheel(root, "arkhai-core", "0.3.0", ["pydantic>=2.10"])
    _consumer(root, CORE)

    assert _problems(root) == [
        "domains/consumer: arkhai-core requires pydantic>=2.10, but the lock pins 2.9.0; run `make lock`"
    ]


def test_a_repository_distribution_from_an_index_fails(tmp_path):
    root = _repository(tmp_path)
    _consumer(root, CORE.replace('registry = "../../.dist"', 'registry = "https://pypi.org/simple"'))

    assert _problems(root) == [
        "domains/consumer: resolves repository distribution arkhai-core from https://pypi.org/simple"
    ]


def test_another_local_registry_fails(tmp_path):
    root = _repository(tmp_path)
    (root / "elsewhere").mkdir()
    _consumer(root, CORE.replace('registry = "../../.dist"', 'registry = "../../elsewhere"'))

    assert _problems(root) == [
        "domains/consumer: resolves arkhai-core from ../../elsewhere, not the repository wheelhouse"
    ]


def test_a_missing_wheel_asks_for_the_wheelhouse_to_be_built(tmp_path):
    root = _repository(tmp_path)
    _consumer(root, CORE)

    assert _problems(root) == [
        "domains/consumer: the wheelhouse holds no arkhai-core==0.3.0; run `make dist`"
    ]


@pytest.mark.parametrize(("version", "specifier", "expected"), [
    ("2.9.0", ">=2", True), ("2.9.0", ">=2.10", False), ("2.9.0", ">=2,<3", True),
    ("1.4.2", "~=1.4", True), ("2.0.0", "~=1.4", False), ("1.4.2", "==1.4.*", True),
    ("1.5.0", "==1.4.*", False), ("1.0.0rc1", ">=1", None), ("1.0.0", "===1.0.0", None),
])
def test_specifier_matching(version, specifier, expected):
    assert checker.satisfies(version, specifier) is expected


def test_an_unevaluable_version_fails_rather_than_passes(tmp_path):
    root = _repository(tmp_path)
    _wheel(root, "arkhai-core", "0.3.0", ["pydantic>=2"])
    _consumer(root, CORE.replace('version = "2.9.0"', 'version = "2.9.0rc1"'))

    assert _problems(root) == [
        "domains/consumer: cannot verify that the lock's pydantic (2.9.0rc1) meets arkhai-core's requirement >=2"
    ]


FORKED = CORE.replace('    { name = "pydantic" },', '    { name = "pydantic", version = "2.9.0", marker = "python_full_version >= \'3.13\'" },') + '''
[[package]]
name = "pydantic"
version = "1.10.0"
source = { registry = "https://pypi.org/simple" }
'''


def test_a_forked_lock_is_checked_against_the_edge_version(tmp_path):
    root = _repository(tmp_path)
    _wheel(root, "arkhai-core", "0.3.0", ["pydantic>=2"])
    _consumer(root, FORKED)

    assert _problems(root) == []


def test_several_locked_versions_with_no_edge_version_cannot_be_verified(tmp_path):
    root = _repository(tmp_path)
    _wheel(root, "arkhai-core", "0.3.0", ["pydantic>=2"])
    _consumer(root, FORKED.replace(', version = "2.9.0", marker = "python_full_version >= \'3.13\'"', ""))

    assert _problems(root) == [
        "domains/consumer: cannot verify that the lock's pydantic (1.10.0, 2.9.0) meets arkhai-core's requirement >=2"
    ]
