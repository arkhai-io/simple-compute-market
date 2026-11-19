from __future__ import annotations

import io
import os
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "package-review-wheelhouse.sh"
IDENTITY_PROJECT = Path("kit") / "identity" / "pyproject.toml"
# The identity kit's version, which the script reads from the same project.
IDENTITY_VERSION = tomllib.loads((REPO_ROOT / IDENTITY_PROJECT).read_text())["project"]["version"]
IDENTITY_WHEEL = f"arkhai_kit_identity-{IDENTITY_VERSION}-py3-none-any.whl"


def _write_wheel_member(
    archive: zipfile.ZipFile,
    filename: str,
    content: str,
) -> None:
    member = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
    member.create_system = 3
    member.external_attr = 0o100644 << 16
    archive.writestr(member, content.encode("utf-8"))


def _identity_wheel() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        _write_wheel_member(archive, "market_identity/__init__.py", "")
        _write_wheel_member(
            archive,
            f"arkhai_kit_identity-{IDENTITY_VERSION}.dist-info/METADATA",
            f"Name: arkhai-kit-identity\nVersion: {IDENTITY_VERSION}\n",
        )
    return buffer.getvalue()


def _fake_uv(bin_dir: Path) -> None:
    executable = bin_dir / "uv"
    executable.write_text(
        """#!/usr/bin/env python3
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args and args[0] == "run":
    python_index = max(index for index, value in enumerate(args) if value == "python")
    os.execv(sys.executable, [sys.executable, *args[python_index + 1:]])
if args and args[0] == "sync":
    environment = Path(os.environ["UV_PROJECT_ENVIRONMENT"])
    target = environment / "bin" / "python"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'#!/bin/sh\\nexec "{sys.executable}" "$@"\\n')
    target.chmod(0o755)
    raise SystemExit(0)
raise SystemExit(f"unsupported fake uv invocation: {args}")
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)


def _stage_root(
    tmp_path: Path,
    *,
    lock_extra: str = "",
) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / ".dist").mkdir()
    (root / "project").mkdir()
    shutil.copy2(SCRIPT, root / "scripts" / SCRIPT.name)
    (root / IDENTITY_PROJECT).parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / IDENTITY_PROJECT, root / IDENTITY_PROJECT)

    (root / ".dist" / IDENTITY_WHEEL).write_bytes(_identity_wheel())
    (root / "project" / "pyproject.toml").write_text(
        """[project]
name = "fixture-project"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = []
""",
        encoding="utf-8",
    )
    (root / "project" / "uv.lock").write_text(
        """version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "fixture-project"
version = "1.0.0"
source = { editable = "." }
"""
        + lock_extra,
        encoding="utf-8",
    )
    bin_dir = root / "bin"
    bin_dir.mkdir()
    _fake_uv(bin_dir)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "REVIEW_PROJECTS": "project",
        "REVIEW_PYTHON": "3.13",
        "REVIEW_SOURCE_COMMIT": "34" * 20,
    }
    return root, env


def _run(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(root / "scripts" / SCRIPT.name), str(root / "bundle.tar.gz")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_wheelhouse_requires_exact_identity_release_filename(tmp_path: Path) -> None:
    root, env = _stage_root(tmp_path)
    exact = root / ".dist" / IDENTITY_WHEEL
    exact.rename(root / ".dist" / "arkhai_kit_identity-0.1.0-py3-none-any.whl")

    result = _run(root, env)

    assert result.returncode == 2
    assert IDENTITY_WHEEL in result.stderr


def test_wheelhouse_requires_the_wheel_of_the_version_the_kit_states(tmp_path: Path) -> None:
    root, env = _stage_root(tmp_path)
    project = root / IDENTITY_PROJECT
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            f'version = "{IDENTITY_VERSION}"', 'version = "9.9.9"'),
        encoding="utf-8",
    )

    result = _run(root, env)

    assert result.returncode == 2
    assert "arkhai_kit_identity-9.9.9-py3-none-any.whl" in result.stderr


def test_wheelhouse_refuses_an_identity_kit_stating_no_version(tmp_path: Path) -> None:
    root, env = _stage_root(tmp_path)
    (root / IDENTITY_PROJECT).unlink()

    result = _run(root, env)

    assert result.returncode == 2
    assert "states no version" in result.stderr


def test_wheelhouse_rejects_portable_lock_source_leakage(tmp_path: Path) -> None:
    root, env = _stage_root(
        tmp_path,
        lock_extra="""

[[package]]
name = "sibling-package"
version = "1.0.0"
source = { directory = "../sibling" }
""",
    )

    result = _run(root, env)

    assert result.returncode != 0
    assert "portable review lock retains repository source paths" in result.stderr


def test_wheelhouse_does_not_treat_project_name_as_dependency_pin(
    tmp_path: Path,
) -> None:
    root, env = _stage_root(tmp_path)
    pyproject = root / "project" / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'name = "fixture-project"',
            'name = "arkhai-kit-identity"',
        ),
        encoding="utf-8",
    )
    lockfile = root / "project" / "uv.lock"
    lockfile.write_text(
        lockfile.read_text(encoding="utf-8").replace(
            'name = "fixture-project"',
            'name = "arkhai-kit-identity"',
        ),
        encoding="utf-8",
    )

    result = _run(root, env)

    assert result.returncode == 0, result.stderr


def test_wheelhouse_checks_identity_package_record_not_dependency_reference(
    tmp_path: Path,
) -> None:
    root, env = _stage_root(
        tmp_path,
        lock_extra=f"""

[[package]]
name = "arkhai-kit-identity"
version = "{IDENTITY_VERSION}"
source = {{ registry = "../.dist" }}
wheels = [
    {{ path = "../.dist/{IDENTITY_WHEEL}" }},
]
""",
    )
    lockfile = root / "project" / "uv.lock"
    lockfile.write_text(
        lockfile.read_text(encoding="utf-8").replace(
            'source = { editable = "." }',
            'source = { editable = "." }\n'
            'dependencies = [{ name = "arkhai-kit-identity" }]',
        ),
        encoding="utf-8",
    )

    result = _run(root, env)

    assert result.returncode == 0, result.stderr
