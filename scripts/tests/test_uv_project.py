"""The shared uv entry point derives internal packages from a project's lock."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "uv_project", Path(__file__).resolve().parents[1] / "uv_project.py"
)
assert _SPEC and _SPEC.loader
uv_project = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(uv_project)


def _repository(tmp_path: Path, python: str | None = "3.13") -> Path:
    root = tmp_path / "repo"
    (root / ".dist").mkdir(parents=True)
    if python is not None:
        (root / ".python-version").write_text(f"{python}\n", "utf-8")
    return root


def _project(root: Path, path: str = "kit/consumer", *, sources: dict[str, dict] | None = None,
             name: str = "arkhai-consumer", version: str = "0.2.0") -> Path:
    project = root / path
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\n', "utf-8"
    )
    entries = [f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {{ editable = "." }}\n']
    for package, source in (sources or {}).items():
        rendered = ", ".join(f'{key} = "{value}"' for key, value in source.items())
        entries.append(f'[[package]]\nname = "{package}"\nversion = "1.0.0"\nsource = {{ {rendered} }}\n')
    (project / "uv.lock").write_text("version = 1\n\n" + "\n".join(entries), "utf-8")
    return project


class _Recorder:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.returncode = returncode

    def __call__(self, command, cwd):
        self.calls.append((list(command), cwd))
        return self.returncode


WHEELHOUSE = {"registry": "../../.dist"}


def test_internal_packages_are_those_resolved_from_the_wheelhouse(tmp_path):
    root = _repository(tmp_path)
    project = _project(root, sources={
        "Arkhai_Kit.Identity": WHEELHOUSE,
        "arkhai-kit-site": WHEELHOUSE,
        "pydantic": {"registry": "https://pypi.org/simple"},
        "arkhai-sibling": {"editable": "../sibling"},
        "arkhai-directory": {"directory": "../directory"},
    })

    assert uv_project.wheelhouse_packages(project, root / ".dist") == [
        "arkhai-kit-identity", "arkhai-kit-site",
    ]


def test_another_local_registry_is_an_error_not_an_internal_package(tmp_path):
    root = _repository(tmp_path)
    (root / "elsewhere").mkdir()
    project = _project(root, sources={"arkhai-kit-site": {"registry": "../../elsewhere"}})

    with pytest.raises(uv_project.DerivationError, match="not the repository wheelhouse"):
        uv_project.wheelhouse_packages(project, root / ".dist")


def test_reinit_upgrades_and_reinstalls_each_internal_package(tmp_path):
    root = _repository(tmp_path)
    project = _project(root, sources={"arkhai-kit-site": WHEELHOUSE, "arkhai-core": WHEELHOUSE})
    run = _Recorder()

    assert uv_project.main(["reinit", "--project", str(project)], root=root, run=run) == 0
    assert run.calls == [([
        "uv", "sync", "--python", "3.13", "--find-links", "../../.dist",
        "--upgrade-package", "arkhai-core", "--reinstall-package", "arkhai-core",
        "--upgrade-package", "arkhai-kit-site", "--reinstall-package", "arkhai-kit-site",
    ], project.resolve())]


def test_reinit_passes_the_wheelhouse_relative_to_the_project(tmp_path):
    root = _repository(tmp_path)
    project = _project(root, "domains/vms/storefront",
                       sources={"arkhai-core": {"registry": "../../../.dist"}})
    run = _Recorder()

    uv_project.main(["reinit", "--project", str(project)], root=root, run=run)
    assert run.calls[0][0][4:6] == ["--find-links", "../../../.dist"]


def test_image_syncs_the_committed_lock_with_the_callers_options(tmp_path):
    root = _repository(tmp_path)
    project = _project(root, sources={"arkhai-core": WHEELHOUSE})
    run = _Recorder()

    argv = ["image", "--project", str(project), "--", "--no-dev", "--no-install-project"]
    assert uv_project.main(argv, root=root, run=run) == 0
    assert run.calls[0][0] == [
        "uv", "sync", "--locked", "--find-links", "../../.dist",
        "--no-dev", "--no-install-project", "--reinstall-package", "arkhai-core",
    ]


def test_install_wheel_uses_the_declared_version_and_no_index(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    project = _project(root, name="arkhai-vms-storefront", version="0.8.0")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/app/.venv")
    run = _Recorder()

    assert uv_project.main(["install-wheel", "--project", str(project)], root=root, run=run) == 0
    assert run.calls[0][0] == [
        "uv", "pip", "install", "--python", "/app/.venv/bin/python",
        "--no-deps", "--no-index", "--reinstall",
        "--find-links", str((root / ".dist").resolve()), "arkhai-vms-storefront==0.8.0",
    ]


def test_lock_upgrades_internal_packages_for_every_locked_project(tmp_path):
    root = _repository(tmp_path)
    first = _project(root, "kit/first", sources={"arkhai-core": WHEELHOUSE})
    second = _project(root, "kit/second", name="arkhai-second")
    (root / "kit" / "not-a-project").mkdir()
    (root / "kit" / "not-a-project" / "uv.lock").write_text("version = 1\n", "utf-8")
    run = _Recorder()

    assert uv_project.main(["lock"], root=root, run=run) == 0
    assert run.calls == [
        (["uv", "lock", "--find-links", "../../.dist",
          "--upgrade-package", "arkhai-core"], first.resolve()),
        (["uv", "lock", "--find-links", "../../.dist"], second.resolve()),
    ]


def test_lock_also_upgrades_repository_distributions_resolved_elsewhere(tmp_path):
    root = _repository(tmp_path)
    _project(root, "kit/config", name="arkhai-kit-config")
    project = _project(root, "domains/consumer", sources={
        "arkhai-kit-config": {"registry": "https://pypi.org/simple"},
        "arkhai-core": WHEELHOUSE,
        "pydantic": {"registry": "https://pypi.org/simple"},
    })
    run = _Recorder()

    uv_project.main(["lock", str(project)], root=root, run=run)
    assert run.calls[0][0] == [
        "uv", "lock", "--find-links", "../../.dist",
        "--upgrade-package", "arkhai-core", "--upgrade-package", "arkhai-kit-config",
    ]


def test_a_failed_command_fails_the_invocation(tmp_path, capsys):
    root = _repository(tmp_path)
    project = _project(root)

    assert uv_project.main(["lock", str(project)], root=root, run=_Recorder(1)) == 1
    assert "lock failed" in capsys.readouterr().err


@pytest.mark.parametrize("breakage", ["no-lock", "bad-lock", "no-python", "no-version"])
def test_a_derivation_failure_runs_nothing(tmp_path, breakage):
    root = _repository(tmp_path, python=None if breakage == "no-python" else "3.13")
    project = _project(root, sources={"arkhai-core": WHEELHOUSE})
    if breakage == "no-lock":
        (project / "uv.lock").unlink()
    elif breakage == "bad-lock":
        (project / "uv.lock").write_text("[[package]\n", "utf-8")
    elif breakage == "no-version":
        (project / "pyproject.toml").write_text('[project]\nname = "x"\n', "utf-8")
    run = _Recorder()

    command = "install-wheel" if breakage == "no-version" else "reinit"
    assert uv_project.main([command, "--project", str(project)], root=root, run=run) == 2
    assert run.calls == []
