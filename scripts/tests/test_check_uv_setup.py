"""Environment and image installs derive their internal packages from the lock."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_uv_setup", Path(__file__).resolve().parents[1] / "check_uv_setup.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)

REINIT = "reinit: ## Sync\n\tpython3 ../../scripts/uv_project.py reinit\n"


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".dist").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "scripts" / "uv_project.py").write_text("", "utf-8")
    return root


def _project(root: Path, makefile: str | None, *, internal: bool = True, tests: bool = True,
             path: str = "kit/consumer", name: str = "arkhai-consumer") -> Path:
    project = root / path
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\n', "utf-8")
    lock = f'version = 1\n\n[[package]]\nname = "{name}"\nversion = "0.1.0"\nsource = {{ editable = "." }}\n'
    if internal:
        lock += '\n[[package]]\nname = "arkhai-core"\nversion = "0.3.0"\nsource = { registry = "../../.dist" }\n'
    (project / "uv.lock").write_text(lock, "utf-8")
    if tests:
        (project / "tests").mkdir()
    if makefile is not None:
        (project / "Makefile").write_text(makefile, "utf-8")
    return project


def test_a_delegating_reinit_passes(tmp_path):
    root = _repository(tmp_path)
    _project(root, REINIT + "\ninit: reinit\n")

    assert checker.problems(root) == []


def test_a_hand_written_list_is_refused(tmp_path):
    root = _repository(tmp_path)
    _project(root, "reinit:\n\tuv sync --find-links ../../.dist \\\n"
                   "\t\t--upgrade-package arkhai-core --reinstall-package arkhai-core\n")

    found = checker.problems(root)
    assert any("names a package in a flag" in p for p in found)
    assert any("runs uv sync itself" in p for p in found)


def test_text_continued_after_a_help_comment_is_not_recipe(tmp_path):
    rules = checker.makefile_rules(
        "reinit: ## Refresh wheels \\\n"
        "\t\t--upgrade-package arkhai-kit-capability-shape\n"
        "\tpython3 ../../scripts/uv_project.py reinit\n"
    )

    assert rules["reinit"] == ([], ["python3 ../../scripts/uv_project.py reinit"])


def test_an_init_that_syncs_itself_is_refused(tmp_path):
    root = _repository(tmp_path)
    _project(root, REINIT + "\ninit:\n\tuv venv --allow-existing\n\tuv sync --dev\n")

    assert any("`init` runs uv sync itself" in p for p in checker.problems(root))


def test_a_reinit_calling_a_path_that_does_not_resolve_is_refused(tmp_path):
    root = _repository(tmp_path)
    _project(root, "reinit:\n\tpython3 ../scripts/uv_project.py reinit\n")

    assert any("which is not scripts/uv_project.py" in p for p in checker.problems(root))


def test_a_project_with_tests_and_internal_wheels_needs_a_reinit(tmp_path):
    root = _repository(tmp_path)
    _project(root, "test:\n\tuv run pytest\n")
    _project(root, None, internal=False, path="kit/standalone", name="arkhai-standalone")
    _project(root, None, tests=False, path="kit/library", name="arkhai-library")

    found = checker.problems(root)
    assert found == ["kit/consumer: installs arkhai-core from the wheelhouse but has no `reinit` target"]


def _dockerfile(root: Path, text: str) -> None:
    (root / "img").mkdir(exist_ok=True)
    (root / "img" / "Dockerfile").write_text(text, "utf-8")


GOOD_IMAGE = """\
FROM base AS builder
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
RUN python3 /repo/scripts/uv_project.py image --project /repo/kit/consumer -- --no-dev && \\
    python3 /repo/scripts/uv_project.py install-wheel --project /repo/kit/consumer
FROM base AS runtime
COPY --from=builder /app/.venv /app/.venv
"""


def test_an_image_installing_through_the_script_passes(tmp_path):
    root = _repository(tmp_path)
    _project(root, REINIT)
    _dockerfile(root, GOOD_IMAGE)

    assert checker.problems(root) == []


def test_image_hand_lists_rewrites_and_versions_are_refused(tmp_path):
    root = _repository(tmp_path)
    _project(root, REINIT)
    _dockerfile(root, """\
FROM base AS builder
COPY .dist/ /.dist/
RUN sed -E -i 's|registry = "x"|registry = "/.dist"|' uv.lock
RUN uv sync --locked --find-links /.dist \\
        --refresh-package arkhai-core
RUN uv pip install --no-deps --find-links /.dist arkhai-consumer==0.1.0
FROM base AS runtime
COPY .dist/ /.dist/
""")

    found = "\n".join(checker.problems(root))
    for expected in ("rewrites a lock's registry", "names a package in a flag",
                     "installs from the wheelhouse without uv_project.py",
                     "spells the version of arkhai-consumer",
                     "the runtime stage copies the wheelhouse"):
        assert expected in found


def test_a_script_call_needs_the_script_copied_into_that_stage(tmp_path):
    root = _repository(tmp_path)
    _project(root, REINIT)
    _dockerfile(root, GOOD_IMAGE.replace("COPY scripts/uv_project.py /repo/scripts/uv_project.py\n", ""))

    assert any("did not copy there" in p for p in checker.problems(root))


def test_the_current_tree_passes():
    assert checker.problems() == []
