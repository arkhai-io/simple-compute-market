"""Every Python version selection reads the root declaration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_python_version", Path(__file__).resolve().parents[1] / "check_python_version.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)

EXPORT = ("export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),"
          "$(error ../../.python-version not found))\n")
CHECKOUT = "      - uses: actions/checkout@v4\n"
STEP = '      - name: Use it\n        run: echo "UV_PYTHON=$(cat .python-version)" >> "$GITHUB_ENV"\n'


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".python-version").write_text("3.13\n", "utf-8")
    return root


def _write(root: Path, path: str, text: str) -> None:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text, "utf-8")


def _conforming(root: Path) -> None:
    _write(root, "kit/site/Makefile", EXPORT + "test:\n\tuv run pytest\n")
    _write(root, "kit/site/Dockerfile", "ARG PYTHON_VERSION=3.13\nFROM python:${PYTHON_VERSION}-slim\n")
    _write(root, ".github/workflows/tests.yml",
           "jobs:\n  python:\n    steps:\n" + CHECKOUT + STEP + "      - run: uv run pytest\n"
           "  node:\n    steps:\n      - run: npm test\n")


def test_a_conforming_tree_passes(tmp_path):
    root = _repository(tmp_path)
    _conforming(root)

    assert checker.problems(root) == []


def test_the_root_declaration_must_exist(tmp_path):
    root = _repository(tmp_path)
    (root / ".python-version").unlink()

    assert checker.problems(root) == [".python-version is missing or is not a MAJOR.MINOR version"]


def test_a_nested_declaration_is_refused(tmp_path):
    root = _repository(tmp_path)
    _conforming(root)
    _write(root, "kit/site/.python-version", "3.12\n")

    assert checker.problems(root) == ["kit/site/.python-version: only the root declares the Python version"]


def test_a_literal_python_flag_is_refused(tmp_path):
    root = _repository(tmp_path)
    _conforming(root)
    _write(root, "scripts/bundle.sh", "uv sync --python 3.12\n")
    _write(root, "tools/finder/config/phases.yaml", "run: uv sync --python=3.13 --extra test\n")

    found = checker.problems(root)
    assert len(found) == 2 and all("names a Python version" in p for p in found)


def test_a_makefile_running_uv_must_export_the_declaration(tmp_path):
    root = _repository(tmp_path)
    _conforming(root)
    _write(root, "kit/other/Makefile", "test:\n\tuv run pytest\n")
    _write(root, "kit/wrong/Makefile", EXPORT.replace("../../", "../") + "test:\n\tuv run pytest\n")
    _write(root, "kit/quiet/Makefile", "# uv run is mentioned only in a comment\nall:\n\techo hi\n")

    assert checker.problems(root) == [
        "kit/other/Makefile: runs uv without exporting UV_PYTHON from .python-version",
        "kit/wrong/Makefile: runs uv without exporting UV_PYTHON from .python-version",
    ]


def test_a_ci_job_running_uv_must_set_the_declaration(tmp_path):
    root = _repository(tmp_path)
    _conforming(root)
    _write(root, ".github/workflows/release.yml",
           "jobs:\n  release:\n    steps:\n      - uses: actions/setup-python@v5\n"
           "        with:\n          python-version: 3.12.4\n      - run: uv build\n")

    assert checker.problems(root) == [
        ".github/workflows/release.yml: sets up Python 3.12; the repository declares 3.13",
        ".github/workflows/release.yml: job `release` runs uv without UV_PYTHON from .python-version",
    ]


def test_image_versions_come_from_the_build_argument(tmp_path):
    root = _repository(tmp_path)
    _conforming(root)
    _write(root, "a/Dockerfile", "FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim\n")
    _write(root, "b/Dockerfile", "ARG PYTHON_VERSION=3.12\nFROM python:${PYTHON_VERSION}-slim\n")

    assert checker.problems(root) == [
        "a/Dockerfile: names a Python version in FROM; use ARG PYTHON_VERSION",
        "b/Dockerfile: PYTHON_VERSION defaults to 3.12; the repository declares 3.13",
    ]


def test_the_current_tree_passes():
    assert checker.problems() == []


def _job(root: Path, steps: str) -> None:
    _write(root, ".github/workflows/tests.yml",
           "jobs:\n  stripe:\n    steps:\n" + steps + "      - run: uv sync\n")


GATED_CHECKOUT = ("      - name: Checkout\n        if: env.SELECTED == 'true'\n"
                  "        uses: actions/checkout@v4\n        with:\n          fetch-depth: 0\n")


def test_a_step_reading_the_declaration_must_share_a_gated_checkouts_condition(tmp_path):
    root = _repository(tmp_path)
    _conforming(root)
    _job(root, GATED_CHECKOUT + STEP)

    assert checker.problems(root) == [
        ".github/workflows/tests.yml: job `stripe` sets UV_PYTHON under no condition but "
        "checks out under `if: env.SELECTED == 'true'`; they must match"
    ]


def test_matching_conditions_pass_including_one_on_the_steps_first_line(tmp_path):
    root = _repository(tmp_path)
    _conforming(root)
    _job(root, GATED_CHECKOUT + "      - if: env.SELECTED   == 'true'\n"
               '        run: echo "UV_PYTHON=$(cat .python-version)" >> "$GITHUB_ENV"\n')

    assert checker.problems(root) == []


def test_a_step_reading_the_declaration_before_checkout_fails(tmp_path):
    root = _repository(tmp_path)
    _conforming(root)
    _job(root, STEP + CHECKOUT)

    assert checker.problems(root) == [
        ".github/workflows/tests.yml: job `stripe` reads .python-version before checking out"
    ]


def test_an_image_variable_needs_a_declared_default(tmp_path):
    root = _repository(tmp_path)
    _conforming(root)
    _write(root, "c/Dockerfile", "FROM python:${PYTHON_VERSION}-slim\nARG PYTHON_VERSION=3.13\n")

    assert checker.problems(root) == [
        "c/Dockerfile: FROM uses PYTHON_VERSION without an `ARG PYTHON_VERSION=` default before it"
    ]
