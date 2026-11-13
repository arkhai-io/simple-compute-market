"""Environment and image installs derive their internal packages from the lock."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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


def _dockerfile(root: Path, text: str, name: str = "Dockerfile") -> None:
    (root / "img").mkdir(exist_ok=True)
    (root / "img" / name).write_text(text, "utf-8")


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


WHEELHOUSE_INSTALL = "installs from the wheelhouse without uv_project.py"


def _builder(run: str) -> str:
    return f"FROM base AS builder\nCOPY .dist/ /dist/\nRUN {run}\n"


def test_a_dockerfile_named_for_its_image_is_read(tmp_path):
    root = _repository(tmp_path)
    _project(root, REINIT)
    _dockerfile(root, _builder("uv sync --locked"), name="market.Dockerfile")

    assert checker.problems(root) == [f"img/market.Dockerfile: {WHEELHOUSE_INSTALL}"]


def test_an_ignore_file_beside_a_dockerfile_is_not_read(tmp_path):
    """`Dockerfile*` matches `Dockerfile.dockerignore`; text the check would
    refuse in a Dockerfile shows it is skipped."""
    root = _repository(tmp_path)
    _project(root, REINIT)
    _dockerfile(root, _builder("uv sync --locked"), name="Dockerfile.dockerignore")

    assert checker.problems(root) == []


def test_a_wheelhouse_install_in_a_stage_that_does_not_copy_it_is_refused(tmp_path):
    root = _repository(tmp_path)
    _project(root, REINIT)
    _dockerfile(root, GOOD_IMAGE + "RUN --mount=from=builder,source=/repo/.dist,target=/w "
                                   "pip install --find-links /w arkhai-consumer\n")

    assert checker.problems(root) == [f"img/Dockerfile: {WHEELHOUSE_INSTALL}"]


@pytest.mark.parametrize("run", [
    "pip install --find-links /dist arkhai-consumer",
    "python3 -m pip install -f /dist arkhai-consumer",
    "/opt/venv/bin/pip3 install --find-links=/dist arkhai-consumer",
    "uv pip install --find-links /dist arkhai-consumer",
    "pip install /dist/arkhai_consumer-0.1.0-py3-none-any.whl",
    "pip install ./.dist/arkhai_consumer-0.1.0-py3-none-any.whl",
    "python3 -m venv /opt/v && /opt/v/bin/pip install -f/dist arkhai-consumer",
])
def test_a_pip_install_reading_the_wheelhouse_is_refused(tmp_path, run):
    root = _repository(tmp_path)
    _project(root, REINIT)
    _dockerfile(root, _builder(run))

    assert checker.problems(root) == [f"img/Dockerfile: {WHEELHOUSE_INSTALL}"]


def test_the_constrained_install_and_reinstall_from_the_wheelhouse_is_refused(tmp_path):
    root = _repository(tmp_path)
    _project(root, REINIT)
    _dockerfile(root, """\
FROM base AS build
COPY .dist/ /dist/
RUN set -eu; \\
    printf '%s\\n' $CONSTRAINTS > /tmp/constraints.txt; \\
    /opt/market/bin/pip install --find-links /dist --constraint /tmp/constraints.txt $wheels; \\
    /opt/market/bin/pip install --no-index --no-deps --force-reinstall --find-links /dist $installed
""")

    assert checker.problems(root) == [f"img/Dockerfile: {WHEELHOUSE_INSTALL}"]


def test_a_pip_install_that_does_not_read_the_wheelhouse_passes(tmp_path):
    root = _repository(tmp_path)
    _project(root, REINIT)
    _dockerfile(root, GOOD_IMAGE.replace(
        "FROM base AS runtime\n",
        "RUN uv venv /opt/ansible && "
        "uv pip install --python /opt/ansible/bin/python 'ansible-core>=2.17,<2.20'\n"
        "FROM base AS runtime\n"))

    assert checker.problems(root) == []


def test_the_current_tree_passes():
    assert checker.problems() == []
