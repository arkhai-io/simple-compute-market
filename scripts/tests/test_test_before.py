"""`test_before.py` runs a test file in the environment of the project that owns it,
rebuilding only the wheels its caller names."""

from __future__ import annotations

from pathlib import Path

import pytest

import test_before


def _project(root: Path, path: str) -> Path:
    project = root / path
    project.mkdir(parents=True, exist_ok=True)
    (project / "pyproject.toml").write_text('[project]\nname = "p"\n', "utf-8")
    return project


def _test(root: Path, path: str) -> Path:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text("def test_it(): pass\n", "utf-8")
    return Path(path)


def _worktree(tmp_path: Path) -> tuple[Path, Path]:
    checkout, root = tmp_path / "checkout", tmp_path / "tree"
    (checkout / ".dist").mkdir(parents=True)
    (checkout / ".dist" / "arkhai_x-0.1.0-py3-none-any.whl").write_text("wheel", "utf-8")
    root.mkdir()
    return checkout, root


def test_a_test_is_owned_by_the_nearest_project_above_it(tmp_path: Path) -> None:
    _project(tmp_path, "provisioning/compute")
    service = _project(tmp_path, "provisioning/compute/service")
    test = _test(tmp_path, "provisioning/compute/service/tests/integration/test_x.py")

    assert test_before.owning_project(tmp_path, test) == service


def test_a_scripts_test_has_no_owning_project(tmp_path: Path) -> None:
    assert test_before.owning_project(tmp_path, _test(tmp_path, "scripts/tests/test_x.py")) is None


def test_the_named_dist_targets_are_read_and_anything_else_is_refused() -> None:
    assert test_before.dist_targets(None) == []
    assert test_before.dist_targets("dist-compute-provisioning, dist-kits") == [
        "dist-compute-provisioning", "dist-kits"]
    assert test_before.dist_targets("dist") == ["dist"]
    with pytest.raises(ValueError):
        test_before.dist_targets("dist; rm -rf /")
    with pytest.raises(ValueError):
        test_before.dist_targets("test")


def test_a_scripts_test_runs_as_before_with_no_wheelhouse(tmp_path: Path) -> None:
    checkout, root = _worktree(tmp_path)
    test = _test(root, "scripts/tests/test_x.py")
    ran: list[tuple[list[str], Path]] = []

    status = test_before.main([str(test)], root=root, checkout=checkout, environ={},
                              run=lambda command, cwd: ran.append((list(command), cwd)) or 0)

    assert status == 0
    assert ran == [([*test_before.UNOWNED, "scripts/tests/test_x.py"], root)]
    assert not (root / ".dist").exists()


def test_a_project_test_rebuilds_only_the_named_wheels_then_runs_the_one_file(tmp_path: Path) -> None:
    checkout, root = _worktree(tmp_path)
    project = _project(root, "kit/storefront")
    test = _test(root, "kit/storefront/tests/unit/test_x.py")
    ran: list[tuple[list[str], Path]] = []

    status = test_before.main([str(test)], root=root, checkout=checkout,
                              environ={"TEST_BEFORE_DIST": "dist-kits"},
                              run=lambda command, cwd: ran.append((list(command), cwd)) or 0)

    assert status == 0
    assert (root / ".dist" / "arkhai_x-0.1.0-py3-none-any.whl").read_text("utf-8") == "wheel"
    assert ran == [
        (["make", "dist-kits", f"DIST_DIR={root / '.dist'}"], root),
        (["python3", str(root / "scripts/uv_project.py"), "reinit", "--project", str(project)], root),
        (["uv", "run", "--no-sync", "pytest", "-q", "tests/unit/test_x.py"], project),
    ]


def test_with_no_targets_named_nothing_is_rebuilt(tmp_path: Path) -> None:
    checkout, root = _worktree(tmp_path)
    _project(root, "kit/storefront")
    test = _test(root, "kit/storefront/tests/unit/test_x.py")
    ran: list[list[str]] = []

    test_before.main([str(test)], root=root, checkout=checkout, environ={},
                     run=lambda command, cwd: ran.append(list(command)) or 0)

    assert [command[0] for command in ran] == ["python3", "uv"]


def test_a_failed_rebuild_stops_before_the_test(tmp_path: Path) -> None:
    checkout, root = _worktree(tmp_path)
    _project(root, "kit/storefront")
    test = _test(root, "kit/storefront/tests/unit/test_x.py")
    ran: list[list[str]] = []

    status = test_before.main([str(test)], root=root, checkout=checkout,
                              environ={"TEST_BEFORE_DIST": "dist-kits"},
                              run=lambda command, cwd: ran.append(list(command)) or 1)

    assert status == 2
    assert ran == [["make", "dist-kits", f"DIST_DIR={root / '.dist'}"]]


def test_the_tests_result_is_the_scripts_exit_status(tmp_path: Path) -> None:
    checkout, root = _worktree(tmp_path)
    _project(root, "kit/storefront")
    test = _test(root, "kit/storefront/tests/unit/test_x.py")

    status = test_before.main([str(test)], root=root, checkout=checkout, environ={},
                              run=lambda command, cwd: 1 if command[0] == "uv" else 0)

    assert status == 1
