"""`change-workflow install` writes the distribution's skills into each supported
harness's user skill directory, stamped with its version beside a manifest of what it
wrote, and a checkout's local configuration where it has none; every other
subcommand of an installed engine refuses while the installed skills are not its
own version's.

Library integration: the command run in-process over a temporary `HOME` and
temporary repositories, the engine an installed distribution laid out in a
temporary directory, its version given as its metadata would give it."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from change_workflow import config, install
from change_workflow.cli import main
from change_workflow.documents import DISTRIBUTION, Distribution
from change_workflow.install import MANIFEST, SKELETON, STAMP, TEMPLATE

CLAUDE, CODEX = ".claude/skills", ".codex/skills"
SKILLS = ("change-design", "change-plan", "guidance-review")


def _distribution(root: Path, version: str, skills=SKILLS) -> Distribution:
    """An installed distribution of `version` shipping `skills`, each a `SKILL.md`
    naming its version."""
    package = root / f"site-{version}" / "change_workflow"
    for name in skills:
        (package / "data/skills" / name).mkdir(parents=True)
        (package / "data/skills" / name / "SKILL.md").write_text(f"# {name} {version}\n",
                                                                 "utf-8")
    return Distribution(package, metadata_version={DISTRIBUTION: version}.__getitem__)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _install(distribution: Distribution, home: Path, root: Path,
             capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    status = main(["install"], root=root, distribution=distribution, home=home)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def test_install_writes_each_skill_stamped_with_a_manifest_into_every_harness(
        tmp_path: Path, home: Path, repository: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    distribution = _distribution(tmp_path, "0.4.1")

    status, out, _ = _install(distribution, home, repository, capsys)

    assert status == 0
    for directory in (home / CLAUDE, home / CODEX):
        assert sorted(path.name for path in directory.iterdir()) == sorted(
            (*SKILLS, MANIFEST))
        for name in SKILLS:
            assert (directory / name / "SKILL.md").read_text("utf-8") == f"# {name} 0.4.1\n"
            assert (directory / name / STAMP).read_text("utf-8") == "0.4.1\n"
        assert json.loads((directory / MANIFEST).read_text("utf-8")) == {
            "version": "0.4.1", "skills": list(SKILLS)}
        assert f"wrote 3 skills of 0.4.1 into {directory}" in out
    assert install.problems(distribution, home) == []


def test_the_engine_is_upgraded_without_its_skills(
        tmp_path: Path, home: Path, repository: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """CW-1rhd's scenario: skills stamped 0.4.1 under an engine at 0.4.2; `next`
    refuses, naming both versions and `change-workflow install`."""
    _install(_distribution(tmp_path, "0.4.1"), home, repository, capsys)

    status = main(["next", "a-change"], root=repository,
                  distribution=_distribution(tmp_path, "0.4.2"), home=home)

    err = capsys.readouterr().err
    assert status == 1
    assert f"{home / CLAUDE / 'change-design'} is stamped 0.4.1, and the engine is 0.4.2" in err
    assert err.rstrip().endswith("run `change-workflow install`")


def test_a_skill_is_missing(tmp_path: Path, home: Path, repository: Path,
                            capsys: pytest.CaptureFixture[str]) -> None:
    """CW-1rhd's scenario: Codex's user skill directory lacks `change-plan`."""
    distribution = _distribution(tmp_path, "0.4.2")
    _install(distribution, home, repository, capsys)
    for path in (home / CODEX / "change-plan").iterdir():
        path.unlink()
    (home / CODEX / "change-plan").rmdir()

    status = main(["next", "a-change"], root=repository, distribution=distribution, home=home)

    err = capsys.readouterr().err
    assert status == 1
    assert f"{home / CODEX / 'change-plan'} is missing, which 0.4.2 ships" in err
    assert "run `change-workflow install`" in err


def test_a_user_skill_directory_without_the_manifest_refuses(
        tmp_path: Path, home: Path, repository: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    distribution = _distribution(tmp_path, "0.4.2")
    _install(distribution, home, repository, capsys)
    (home / CLAUDE / MANIFEST).unlink()

    assert main(["config", "--json"], root=repository, distribution=distribution,
                home=home) == 1
    assert (f"{home / CLAUDE} (claude) has no manifest of the workflow's skills"
            in capsys.readouterr().err)


def test_a_skill_of_the_workflows_name_is_not_the_installers(
        tmp_path: Path, home: Path, repository: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """CW-1rhd's scenario: Claude Code's user skill directory holds a `change-design`
    no manifest records; `install` refuses, naming it, and writes nothing in either
    directory."""
    (home / CLAUDE / "change-design").mkdir(parents=True)
    (home / CLAUDE / "change-design/SKILL.md").write_text("# mine\n", "utf-8")

    status, out, err = _install(_distribution(tmp_path, "0.4.2"), home, repository, capsys)

    assert (status, out) == (1, "")
    assert str(home / CLAUDE / "change-design") in err
    assert sorted(path.name for path in (home / CLAUDE).iterdir()) == ["change-design"]
    assert (home / CLAUDE / "change-design/SKILL.md").read_text("utf-8") == "# mine\n"
    assert not (home / CODEX).exists()
    assert not (repository / config.LOCAL).exists()


def test_a_later_version_retires_a_skill(tmp_path: Path, home: Path, repository: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    """CW-1rhd's scenario: the version that does not ship `change-plan` removes it and
    leaves the skill the owner wrote beside it untouched."""
    _install(_distribution(tmp_path, "0.4.1"), home, repository, capsys)
    (home / CLAUDE / "my-skill").mkdir()
    (home / CLAUDE / "my-skill/SKILL.md").write_text("# mine\n", "utf-8")

    status, out, _ = _install(_distribution(tmp_path, "0.5.0",
                                            ("change-design", "guidance-review")),
                              home, repository, capsys)

    assert status == 0
    assert sorted(path.name for path in (home / CLAUDE).iterdir()) == [
        MANIFEST, "change-design", "guidance-review", "my-skill"]
    assert (home / CLAUDE / "my-skill/SKILL.md").read_text("utf-8") == "# mine\n"
    assert not (home / CODEX / "change-plan").exists()
    assert f"removed {home / CLAUDE / 'change-plan'}, which 0.5.0 does not ship" in out


def test_a_developer_installs_in_a_repository_with_a_template(
        tmp_path: Path, home: Path, repository: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """CW-sv3u's scenario: the local configuration holds the template's content."""
    (repository / TEMPLATE).parent.mkdir(parents=True)
    (repository / TEMPLATE).write_text("[guidance]\nengineering = { none = \"x\" }\n", "utf-8")

    status, out, _ = _install(_distribution(tmp_path, "0.4.2"), home, repository, capsys)

    assert status == 0
    assert (repository / config.LOCAL).read_text("utf-8") == (
        repository / TEMPLATE).read_text("utf-8")
    assert "wrote .agents/workflow.local.toml from .agents/workflow.local.template.toml" in out


@pytest.mark.parametrize("template", [True, False], ids=["template", "no template"])
def test_a_local_configuration_exists(tmp_path: Path, home: Path, repository: Path,
                                      capsys: pytest.CaptureFixture[str],
                                      template: bool) -> None:
    """CW-sv3u's scenario: the file is unchanged, template or none."""
    (repository / TEMPLATE).parent.mkdir(parents=True)
    if template:
        (repository / TEMPLATE).write_text("[models]\n", "utf-8")
    (repository / config.LOCAL).write_text("# mine\n", "utf-8")

    status, out, _ = _install(_distribution(tmp_path, "0.4.2"), home, repository, capsys)

    assert status == 0
    assert (repository / config.LOCAL).read_text("utf-8") == "# mine\n"
    assert "workflow.local.toml" not in out


def test_an_empty_local_configuration_is_written_as_an_absent_one(
        tmp_path: Path, home: Path, repository: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    # The sandbox's empty form of an absent protected file holds no setting.
    (repository / config.LOCAL).parent.mkdir(parents=True)
    (repository / config.LOCAL).write_text("", "utf-8")

    assert _install(_distribution(tmp_path, "0.4.2"), home, repository, capsys)[0] == 0
    assert (repository / config.LOCAL).read_text("utf-8") == SKELETON


def test_without_a_template_the_skeleton_names_each_required_local_field(
        tmp_path: Path, home: Path, repository: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = _install(_distribution(tmp_path, "0.4.2"), home, repository, capsys)

    written = (repository / config.LOCAL).read_text("utf-8")
    assert status == 0
    assert "from the skeleton naming each required local field" in out
    assert "# engineering = { path = " in written
    for field in ("orchestrator", *config.STEPS):
        assert f"\n# {field} = " in written, field
    # The skeleton declares nothing, so every local field is still missing.
    loaded = config.load(repository)
    assert loaded.local_exists and loaded.engineering is None and not loaded.models


def test_outside_a_checkout_no_local_configuration_is_written(
        tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    status = main(["install"], root=outside, distribution=_distribution(tmp_path, "0.4.2"),
                  home=home)

    assert status == 0
    assert not (outside / ".agents").exists()


def test_every_subcommand_but_install_checks_the_skills_check_and_openspec_among_them(
        tmp_path: Path, home: Path, repository: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """CW-d8de's "An installed skill is stale", through the command: `check skills`
    refuses, naming the skill and both versions, as the `openspec` pass-through does
    before it runs anything."""
    _install(_distribution(tmp_path, "0.4.1"), home, repository, capsys)
    stale = _distribution(tmp_path, "0.4.2")

    for command in (["check", "skills"], ["openspec", "--version"]):
        assert main(command, root=repository, distribution=stale, home=home) == 1, command
        err = capsys.readouterr().err
        assert (f"{home / CLAUDE / 'change-plan'} is stamped 0.4.1, and the engine is 0.4.2"
                in err), command


def test_install_is_not_refused_for_the_range_or_the_skills_it_repairs(
        tmp_path: Path, home: Path, repository: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    (repository / config.CONFIGURATION).parent.mkdir(parents=True)
    (repository / config.CONFIGURATION).write_text('[workflow]\nversion = ">=9"\n', "utf-8")
    _install(_distribution(tmp_path, "0.4.1"), home, repository, capsys)

    status, out, err = _install(_distribution(tmp_path, "0.4.2"), home, repository, capsys)

    assert (status, err) == (0, "")
    assert "wrote 3 skills of 0.4.2" in out


def test_the_source_trees_engine_checks_nothing_installed(home: Path) -> None:
    tree = Distribution(Path(__file__).resolve().parents[1] / "change_workflow")

    install.require_installed(tree, home)

    assert not tree.installed
    assert install.problems(tree, home)  # what an installed engine would refuse
