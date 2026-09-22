"""A reinit target reinstalls every internal wheel its project's lock installs."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_reinit",
    Path(__file__).resolve().parents[1] / "check_reinit.py",
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)

DIST = "../../.dist"


def _package(root: Path, path: str, name: str) -> None:
    (root / path).mkdir(parents=True, exist_ok=True)
    (root / path / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n', "utf-8"
    )


def _project(
    root: Path,
    *,
    locked: dict[str, str],
    makefile: str | None,
    tests: bool = True,
) -> Path:
    """A consumer project whose lock resolves each package from ``locked``."""
    project = root / "consumer"
    project.mkdir()
    entries = [
        '[[package]]\nname = "consumer"\nversion = "0.1.0"\n'
        'source = { editable = "." }\n'
    ]
    for name, registry in locked.items():
        entries.append(
            f'[[package]]\nname = "{name}"\nversion = "0.1.0"\n'
            f'source = {{ registry = "{registry}" }}\n'
        )
    (project / "uv.lock").write_text("version = 1\n\n" + "\n".join(entries), "utf-8")
    if makefile is not None:
        (project / "Makefile").write_text(makefile, "utf-8")
    if tests:
        (project / "tests").mkdir()
    return project


def _tree(tmp_path: Path) -> Path:
    _package(tmp_path, "kit/site", "arkhai-kit-site")
    _package(tmp_path, "kit/fulfillment", "arkhai-kit-fulfillment")
    return tmp_path


def test_a_complete_reinit_passes(tmp_path):
    root = _tree(tmp_path)
    _project(
        root,
        locked={"arkhai-kit-site": DIST},
        makefile=(
            "reinit:\n\tuv sync --find-links $(DIST_DIR) \\\n"
            "\t\t--upgrade-package arkhai-kit-site --reinstall-package arkhai-kit-site\n"
        ),
    )

    assert checker.problems(root) == []


def test_a_wheel_the_reinit_omits_is_reported(tmp_path):
    root = _tree(tmp_path)
    _project(
        root,
        locked={"arkhai-kit-site": DIST, "arkhai-kit-fulfillment": DIST},
        makefile="reinit:\n\tuv sync --reinstall-package arkhai-kit-site\n",
    )

    assert checker.problems(root) == [
        "consumer: reinit does not reinstall arkhai-kit-fulfillment"
    ]


def test_a_reinstall_in_a_prerequisite_target_counts(tmp_path):
    root = _tree(tmp_path)
    _project(
        root,
        locked={"arkhai-kit-site": DIST},
        makefile=(
            "reinit: sync-internal\n\t@echo done\n\n"
            "sync-internal:\n\tuv sync --reinstall-package arkhai-kit-site\n"
        ),
    )

    assert checker.problems(root) == []


def test_a_comment_inside_the_recipe_does_not_end_it(tmp_path):
    root = _tree(tmp_path)
    _project(
        root,
        locked={"arkhai-kit-site": DIST},
        makefile=(
            "reinit: ## Reinstall\n# A comment between recipe lines.\n"
            "\tuv sync --reinstall-package arkhai-kit-site\n"
        ),
    )

    assert checker.problems(root) == []


def test_packages_not_installed_from_a_local_wheel_are_out_of_scope(tmp_path):
    root = _tree(tmp_path)
    _project(
        root,
        locked={
            "arkhai-kit-site": "https://pypi.org/simple",
            "third-party": DIST,
        },
        makefile="reinit:\n\tuv sync\n",
    )

    assert checker.problems(root) == []


def test_a_project_installing_internal_wheels_needs_a_reinit(tmp_path):
    root = _tree(tmp_path)
    _project(root, locked={"arkhai-kit-site": DIST}, makefile="test:\n\tuv run pytest\n")

    assert checker.problems(root) == [
        "consumer: no reinit target, but its lock installs internal wheels: "
        "arkhai-kit-site"
    ]


def test_a_project_without_tests_is_out_of_scope(tmp_path):
    root = _tree(tmp_path)
    _project(root, locked={"arkhai-kit-site": DIST}, makefile=None, tests=False)

    assert checker.problems(root) == []


def test_package_names_are_compared_normalised(tmp_path):
    root = _tree(tmp_path)
    _project(
        root,
        locked={"arkhai_kit_site": DIST},
        makefile="reinit:\n\tuv sync --reinstall-package Arkhai.Kit.Site\n",
    )

    assert checker.problems(root) == []


def test_the_repository_has_no_reinit_gaps():
    assert checker.problems(checker.ROOT) == []
