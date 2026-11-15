"""The version check, against real git in a scratch repository whose releases
carry bills of materials at their tags.

The wheelhouse is a directory of wheel files whose bytes the tests choose; the
chart is packaged by a stub at the check's own chart seam, since its digest is the
reader's concern (`test_release_bom.py`).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from check_release_versions import check, main
from release_bom import PATH, BomError, ChartPackage
from release_bom_fixtures import Repository, declared_components, digest, wheel


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "fixture", "GIT_COMMITTER_NAME": "fixture",
                       "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                       "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}.items():
        monkeypatch.setenv(key, value)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return Repository(tmp_path / "repo")


def _wheelhouse(repo: Repository, core: tuple[str, bytes],
                buyer: tuple[str, bytes] = ("0.1.0", b"buyer-1")) -> Path:
    """`.dist` holding the two declared wheels, each project at its version."""
    dist = repo.root / ".dist"
    dist.mkdir(exist_ok=True)
    for project, dist_name, (version, data) in (("core", "arkhai_core", core),
                                                ("core/buyer", "arkhai_core_buyer", buyer)):
        name = "arkhai-core" if project == "core" else "arkhai-core-buyer"
        repo.write({f"{project}/pyproject.toml":
                    f'[project]\nname = "{name}"\nversion = "{version}"\n'})
        (dist / f"{dist_name}-{version}-py3-none-any.whl").write_bytes(data)
    return dist


def _chart(content_digest: str = digest("3"), version: str = "0.1.0"):
    return lambda chart_dir: ChartPackage("chart", version, content_digest)


def _release(repo: Repository, semver: str, core: tuple[str, bytes],
             buyer: tuple[str, bytes] = ("0.1.0", b"buyer-1"),
             chart: tuple[str, str] = ("0.1.0", digest("3"))) -> None:
    point = repo.head("main")
    repo.cut(semver, components=declared_components(
        point, core=(core[0], _sha(core[1])), buyer=(buyer[0], _sha(buyer[1])),
        chart_identity=chart))


def _load(repo: Repository, chart=None) -> tuple[list[str], str]:
    return check(repo.root, dist_dir=repo.root / ".dist", chart=chart or _chart())


def test_an_unchanged_wheel_passes(repo: Repository) -> None:
    _release(repo, "1.0.0", core=("0.1.0", b"core-1"))
    _wheelhouse(repo, core=("0.1.0", b"core-1"))

    problems, summary = _load(repo)

    assert problems == []
    assert "match every earlier record (marketplace-v1.0.0)" in summary


def test_a_changed_wheel_with_a_bumped_version_passes(repo: Repository) -> None:
    _release(repo, "1.0.0", core=("0.1.0", b"core-1"))
    _wheelhouse(repo, core=("0.2.0", b"core-2"))

    assert _load(repo)[0] == []


def test_a_changed_wheel_at_the_previous_releases_version_fails(repo: Repository) -> None:
    _release(repo, "1.0.0", core=("0.1.0", b"core-1"))
    _wheelhouse(repo, core=("0.1.0", b"core-2"))

    problems, _ = _load(repo)

    assert len(problems) == 1
    assert problems[0].startswith(f"wheel/arkhai-core 0.1.0: its SHA-256 is {_sha(b'core-2')}, "
                                  f"but marketplace-v1.0.0 recorded that version as "
                                  f"{_sha(b'core-1')}")


def test_a_changed_wheel_at_a_version_two_releases_old_fails_and_names_that_release(
        repo: Repository) -> None:
    _release(repo, "1.0.0", core=("0.1.0", b"core-1"))
    _release(repo, "1.1.0", core=("0.2.0", b"core-2"))
    _wheelhouse(repo, core=("0.1.0", b"core-3"))

    problems, _ = _load(repo)

    assert len(problems) == 1
    assert "wheel/arkhai-core 0.1.0" in problems[0]
    assert "marketplace-v1.0.0 recorded that version" in problems[0]


def test_a_changed_chart_digest_at_an_unchanged_chart_version_fails(repo: Repository) -> None:
    _release(repo, "1.0.0", core=("0.1.0", b"core-1"), chart=("0.1.0", digest("3")))
    _wheelhouse(repo, core=("0.1.0", b"core-1"))

    problems, _ = _load(repo, chart=_chart(content_digest=digest("9")))

    assert len(problems) == 1
    assert problems[0].startswith(f"chart/chart 0.1.0: its content digest is {digest('9')}, "
                                  "but marketplace-v1.0.0 recorded that version")


def test_at_the_cut_the_tags_own_record_is_the_subject_and_never_compared_with_itself(
        repo: Repository) -> None:
    _release(repo, "1.0.0", core=("0.1.0", b"core-1"))

    def no_build(chart_dir: Path) -> ChartPackage:
        raise AssertionError("the cut builds nothing")

    problems, summary = check(repo.root, tag="marketplace-v1.0.0",
                              dist_dir=repo.root / "absent", chart=no_build)

    assert problems == []
    assert summary == ("no earlier marketplace release carries a bill of materials, so there "
                       "is nothing to compare marketplace-v1.0.0's record with")


def test_at_the_cut_a_record_reusing_an_earlier_version_with_other_bytes_fails(
        repo: Repository) -> None:
    _release(repo, "1.0.0", core=("0.1.0", b"core-1"))
    repo.write({"README": "a later change\n"})
    repo.commit("a later change")
    _release(repo, "1.1.0", core=("0.1.0", b"core-2"))

    problems, summary = check(repo.root, tag="refs/tags/marketplace-v1.1.0")

    assert len(problems) == 1
    assert "marketplace-v1.0.0 recorded that version" in problems[0]
    assert summary.endswith("every earlier record (marketplace-v1.0.0)")


def test_the_command_reports_a_pass_and_a_refusal(repo: Repository, capsys) -> None:
    _release(repo, "1.0.0", core=("0.1.0", b"core-1"))
    repo.write({"README": "a later change\n"})
    repo.commit("a later change")
    _release(repo, "1.1.0", core=("0.2.0", b"core-2"))

    assert main(["--tag", "marketplace-v1.1.0"], root=repo.root) == 0
    assert capsys.readouterr().out == ("OK: 3 versioned components of marketplace-v1.1.0's "
                                       "record match every earlier record "
                                       "(marketplace-v1.0.0).\n")
    repo.write({"README": "another change\n"})
    repo.commit("another change")
    _release(repo, "1.2.0", core=("0.1.0", b"core-3"))

    assert main(["--tag", "marketplace-v1.2.0"], root=repo.root) == 1
    assert capsys.readouterr().err.startswith("check-release-versions:\n  wheel/arkhai-core 0.1.0")


def test_a_distribution_respelled_is_still_the_project_an_earlier_record_named(
        repo: Repository) -> None:
    point = repo.head("main")
    components = declared_components(point, buyer=("0.1.0", _sha(b"buyer-1")))
    components[0] = wheel("arkhai_core", "0.1.0", _sha(b"core-1"))
    repo.cut("1.0.0", components=components)
    _wheelhouse(repo, core=("0.1.0", b"core-2"))

    problems, _ = _load(repo)

    assert len(problems) == 1
    assert problems[0].startswith("wheel/arkhai-core 0.1.0:")
    assert "marketplace-v1.0.0 recorded that version" in problems[0]


def test_a_tag_carrying_no_record_cannot_be_checked(repo: Repository) -> None:
    repo.git("tag", "-a", "marketplace-v1.0.0", "-m", "no record")

    with pytest.raises(BomError, match=f"marketplace-v1.0.0 carries no {PATH}"):
        check(repo.root, tag="marketplace-v1.0.0")


def test_a_tag_a_branch_of_its_name_shadows_is_still_read(repo: Repository) -> None:
    _release(repo, "1.0.0", core=("0.1.0", b"core-1"))
    repo.git("branch", "marketplace-v1.0.0", "main")
    _wheelhouse(repo, core=("0.1.0", b"core-2"))

    problems, _ = _load(repo)

    assert len(problems) == 1
    assert "marketplace-v1.0.0 recorded that version" in problems[0]


def test_no_earlier_record_passes_and_says_so(repo: Repository) -> None:
    _wheelhouse(repo, core=("0.1.0", b"core-1"))

    problems, summary = _load(repo)

    assert problems == []
    assert summary.startswith("no earlier marketplace release carries a bill of materials")


def test_a_tag_without_a_record_is_not_an_earlier_record(repo: Repository) -> None:
    repo.git("tag", "-a", "marketplace-v0.3.0", "-m", "released before records existed")
    _wheelhouse(repo, core=("0.1.0", b"core-1"))

    assert _load(repo)[1].startswith("no earlier marketplace release carries")


def test_an_earlier_record_in_an_unknown_layout_is_refused_not_skipped(
        repo: Repository) -> None:
    repo.cut("1.0.0", bom=b'{"metadata": {"component": {"properties": '
                          b'[{"name": "arkhai:bom-layout", "value": "2"}]}}}\n')
    _wheelhouse(repo, core=("0.1.0", b"core-1"))

    with pytest.raises(BomError, match=f"marketplace-v1.0.0:{PATH}: arkhai:bom-layout is \"2\""):
        _load(repo)


def test_a_declared_wheel_missing_from_the_wheelhouse_is_refused(repo: Repository) -> None:
    _wheelhouse(repo, core=("0.1.0", b"core-1"))
    (repo.root / ".dist" / "arkhai_core_buyer-0.1.0-py3-none-any.whl").unlink()

    with pytest.raises(BomError, match=r"no wheel for 1 declared distribution.*make dist.*"
                                       r"arkhai_core_buyer-0\.1\.0"):
        _load(repo)
