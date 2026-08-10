"""Ownership and manifest-drift detection, against miniature repositories.

The checker's value is that it fails when someone adds a module and forgets the
manifest, or leaves a namespace unowned. A one-off run against the real tree
proves only that the tree currently passes; these build the failing shapes
deliberately so a later change to the checker cannot silently stop detecting them.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import check_wheel_manifests as checker


def _project(root: Path, rel: str, *, manifest: dict[str, str], only: str | None = None) -> Path:
    project = root / rel
    project.mkdir(parents=True, exist_ok=True)
    entries = "\n".join(f'"{src}" = "{dst}"' for src, dst in manifest.items())
    only_line = f'only-include = ["{only}"]\n' if only else ""
    (project / "pyproject.toml").write_text(
        textwrap.dedent(f"""\
            [project]
            name = "{rel.replace('/', '-')}"
            version = "0.1.0"

            [tool.hatch.build.targets.wheel]
            {only_line}
            [tool.hatch.build.targets.wheel.force-include]
            {entries}
            """),
        encoding="utf-8",
    )
    return project


def test_a_complete_manifest_passes(tmp_path: Path) -> None:
    project = _project(tmp_path, "domains/thing", manifest={"a.py": "pkg/a.py"})
    (project / "a.py").write_text("A = 1\n", encoding="utf-8")

    assert checker.audit(project) == []


def test_a_module_absent_from_the_manifest_fails(tmp_path: Path) -> None:
    project = _project(tmp_path, "domains/thing", manifest={"a.py": "pkg/a.py"})
    (project / "a.py").write_text("A = 1\n", encoding="utf-8")
    (project / "forgotten.py").write_text("B = 2\n", encoding="utf-8")

    findings = checker.audit(project)

    assert any("forgotten.py" in f for f in findings)


def test_a_tombstoned_module_is_not_expected_in_the_manifest(tmp_path: Path) -> None:
    project = _project(tmp_path, "domains/thing", manifest={"a.py": "pkg/a.py"})
    (project / "a.py").write_text("A = 1\n", encoding="utf-8")
    (project / "gone.py").write_text("# TOMBSTONE: moved.\n", encoding="utf-8")

    assert checker.audit(project) == []


def test_a_tombstoned_module_still_in_the_manifest_fails(tmp_path: Path) -> None:
    project = _project(
        tmp_path, "domains/thing", manifest={"a.py": "pkg/a.py", "gone.py": "pkg/gone.py"}
    )
    (project / "a.py").write_text("A = 1\n", encoding="utf-8")
    (project / "gone.py").write_text("# TOMBSTONE: moved.\n", encoding="utf-8")

    findings = checker.audit(project)

    assert any("tombstoned" in f and "gone.py" in f for f in findings)


def test_a_stale_marker_above_live_code_is_still_expected(tmp_path: Path) -> None:
    """The predicate divergence: this module is live and must be in the manifest."""
    project = _project(tmp_path, "domains/thing", manifest={"a.py": "pkg/a.py"})
    (project / "a.py").write_text("A = 1\n", encoding="utf-8")
    (project / "live.py").write_text(
        "# TOMBSTONE: an old reason\n\ndef still_used():\n    return 1\n", encoding="utf-8"
    )

    findings = checker.audit(project)

    assert any("live.py" in f for f in findings)


def test_only_include_exempts_a_module(tmp_path: Path) -> None:
    project = _project(
        tmp_path, "domains/thing", manifest={"a.py": "pkg/a.py"}, only="main.py"
    )
    (project / "a.py").write_text("A = 1\n", encoding="utf-8")
    (project / "main.py").write_text("MAIN = 1\n", encoding="utf-8")

    assert checker.audit(project) == []


# --- ownership ---------------------------------------------------------------


def test_a_package_inside_a_project_is_owned(tmp_path: Path) -> None:
    project = _project(tmp_path, "domains/thing", manifest={"a.py": "pkg/a.py"})
    (project / "a.py").write_text("A = 1\n", encoding="utf-8")
    (project / "sub").mkdir()
    (project / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (project / "sub" / "mod.py").write_text("M = 1\n", encoding="utf-8")

    assert checker.audit_unowned_packages(tmp_path) == []


def test_an_unowned_package_fails(tmp_path: Path) -> None:
    orphan = tmp_path / "domains" / "orphan"
    orphan.mkdir(parents=True)
    (orphan / "__init__.py").write_text("", encoding="utf-8")
    (orphan / "mod.py").write_text("M = 1\n", encoding="utf-8")

    findings = checker.audit_unowned_packages(tmp_path)

    assert any("owned by no distribution" in f for f in findings)


def test_a_namespace_anchor_shipped_by_a_manifest_is_owned(tmp_path: Path) -> None:
    anchor = tmp_path / "domains" / "vms"
    anchor.mkdir(parents=True)
    (anchor / "__init__.py").write_text('"""Namespace."""\n', encoding="utf-8")
    project = _project(
        tmp_path, "domains/vms/buyer", manifest={"../__init__.py": "domains/vms/__init__.py"}
    )
    (project / "__init__.py").write_text("", encoding="utf-8")

    assert checker.audit_unowned_packages(tmp_path) == []


def test_an_unshipped_namespace_anchor_fails(tmp_path: Path) -> None:
    anchor = tmp_path / "domains" / "vms"
    anchor.mkdir(parents=True)
    (anchor / "__init__.py").write_text('"""Namespace."""\n', encoding="utf-8")

    findings = checker.audit_unowned_packages(tmp_path)

    assert any("namespace anchor" in f for f in findings)


def test_a_directory_holding_only_tombstones_is_not_a_package(tmp_path: Path) -> None:
    gone = tmp_path / "domains" / "gone"
    gone.mkdir(parents=True)
    (gone / "__init__.py").write_text("# TOMBSTONE: moved.\n", encoding="utf-8")
    (gone / "mod.py").write_text("# TOMBSTONE: moved.\n", encoding="utf-8")

    assert checker.audit_unowned_packages(tmp_path) == []
