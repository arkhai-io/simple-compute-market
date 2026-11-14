"""The release record check, against real git in a scratch repository where
releases are cut as the release procedure cuts them: a branch at a `main` commit,
one commit adding the bill of materials, and a tag on it."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from check_release_record import check, main
from release_bom import PATH
from release_bom_fixtures import (
    DECLARATION,
    Repository,
    declared_components,
    digest,
    document,
    image,
    npm,
    serialize,
    wheel,
)

TAG = "marketplace-v1.0.0"


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "fixture", "GIT_COMMITTER_NAME": "fixture",
                       "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                       "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return Repository(tmp_path / "repo")


def test_a_well_formed_record_passes(repo: Repository) -> None:
    repo.cut("0.9.0")
    repo.write({"README": "a later change\n"})
    repo.commit("a later change")
    repo.cut("1.0.0")

    assert check(TAG, repo.root) == []


def test_the_command_reports_a_pass_and_each_refusal(repo: Repository, capsys) -> None:
    repo.cut("1.0.0")
    repo.git("branch", "-m", "main", "dev")

    assert main([TAG, "--default-branch", "dev"], root=repo.root) == 0
    assert capsys.readouterr().out.startswith(f"OK: {TAG} records a marketplace release")
    assert main([TAG], root=repo.root) == 1
    assert capsys.readouterr().err == (f"check-release-record: {TAG}:\n"
                                       "  no main branch exists to reach the parent from\n")


def test_a_name_that_is_not_a_marketplace_tag_is_refused(repo: Repository) -> None:
    assert check("market-cli-v1.0.0", repo.root) == [
        "market-cli-v1.0.0 is not a marketplace-v<semver> tag"]
    assert check(TAG, repo.root) == [f"no tag {TAG} exists"]


# 1. The commit is the tip of its release branch, cut from the default branch.


def test_a_merge_commit_is_not_a_release_commit(repo: Repository) -> None:
    repo.git("checkout", "-q", "-b", "side")
    repo.write({"README": "a side change\n"})
    repo.commit("a side change")
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", "merge side", "side")
    repo.git("tag", TAG)

    assert check(TAG, repo.root) == [
        f"{TAG}'s commit has 2 parents; a release commit has exactly one"]


def test_a_record_on_another_branch_is_refused(repo: Repository) -> None:
    repo.git("branch", "releases/1.0.0", "main")
    commit = repo.cut("1.0.0", branch="wip")

    assert check(TAG, repo.root) == [f"releases/1.0.0 is at {repo.head('main')[:9]}, not "
                                     f"{TAG}'s commit {commit[:9]}; a release branch holds "
                                     "only its record"]


def test_a_release_branch_with_a_commit_after_its_record_is_refused(repo: Repository) -> None:
    commit = repo.cut("1.0.0")
    repo.git("checkout", "-q", "releases/1.0.0")
    repo.write({"README": "a fix on the release branch\n"})
    later = repo.commit("a fix on the release branch")
    repo.git("checkout", "-q", "main")

    assert check(TAG, repo.root) == [f"releases/1.0.0 is at {later[:9]}, not {TAG}'s commit "
                                     f"{commit[:9]}; a release branch holds only its record"]


def test_every_remote_release_branch_is_held_to_the_record(repo: Repository) -> None:
    commit = repo.cut("1.0.0")
    repo.git("update-ref", "refs/remotes/origin/releases/1.0.0", commit)
    assert check(TAG, repo.root) == []

    repo.git("update-ref", "refs/remotes/upstream/releases/1.0.0", repo.head("main"))

    assert check(TAG, repo.root) == [
        f"remotes/upstream/releases/1.0.0 is at {repo.head('main')[:9]}, not {TAG}'s commit "
        f"{commit[:9]}; a release branch holds only its record"]


def test_a_record_with_no_release_branch_is_refused(repo: Repository) -> None:
    repo.cut("1.0.0", branch="wip")

    assert check(TAG, repo.root) == ["no branch releases/1.0.0 exists"]


def test_a_branch_point_the_default_branch_cannot_reach_is_refused(repo: Repository) -> None:
    repo.git("checkout", "-q", "-b", "side")
    repo.write({"README": "never merged\n"})
    point = repo.commit("never merged")
    repo.git("checkout", "-q", "main")

    repo.cut("1.0.0", at="side")

    assert check(TAG, repo.root) == [
        f"the release branch's point {point[:9]} is not reachable from main"]


def test_a_remote_default_branch_reaches_the_branch_point(repo: Repository) -> None:
    repo.cut("1.0.0")
    repo.git("update-ref", "refs/remotes/origin/main", repo.head("main"))
    repo.git("branch", "-m", "main", "dev")

    assert check(TAG, repo.root) == []


# 2. The commit adds the bill of materials and changes nothing else.


def test_a_release_commit_changing_another_path_is_refused(repo: Repository) -> None:
    repo.cut("1.0.0", extra={"helm/Chart.yaml": "apiVersion: v2\nname: chart\nversion: 0.2.0\n"})

    assert check(TAG, repo.root) == [
        f"the release commit changes helm/Chart.yaml (M); it may only add {PATH}"]


def test_a_release_commit_that_adds_no_record_is_refused(repo: Repository) -> None:
    repo.git("checkout", "-q", "-b", "releases/1.0.0")
    repo.write({"NOTES": "no record\n"})
    repo.commit("no record")
    repo.git("tag", TAG)
    repo.git("checkout", "-q", "main")

    assert check(TAG, repo.root) == [
        f"the release commit changes NOTES (A); it may only add {PATH}",
        f"the release commit does not add {PATH}"]


# 3. The bill of materials is layout 1, holding content identities only.


def test_a_record_with_a_field_layout_1_does_not_admit_is_refused(repo: Repository) -> None:
    point = repo.head("main")
    record = document("1.0.0", point, declared_components(point))
    record["metadata"]["timestamp"] = "2026-11-13T00:00:00Z"
    repo.cut("1.0.0", bom=serialize(record))

    problems = check(TAG, repo.root)

    assert len(problems) == 1
    assert "metadata has field 'timestamp', which layout 1 does not admit" in problems[0]


def test_a_record_naming_a_registry_is_refused_and_names_the_component(repo: Repository) -> None:
    point = repo.head("main")
    components = declared_components(point)
    components[2]["purl"] += "&repository_url=registry.example.invalid/project"
    repo.cut("1.0.0", components=components)

    problems = check(TAG, repo.root)

    assert len(problems) == 1
    assert "image/registry.purl carries a repository_url" in problems[0]


# 4. It names the branch point and the tag's version.


def test_a_record_naming_another_revision_or_version_is_refused(repo: Repository) -> None:
    point = repo.head("main")
    other = "f" * 40
    repo.cut("1.0.0", bom=serialize(document("1.0.1", other, declared_components(other))))

    assert check(TAG, repo.root) == [
        f"its arkhai:source-revision is {other}, not the branch point {point}",
        "its version is 1.0.1, not the tag's 1.0.0"]


# 5. Its components are exactly the declared release components, each once.


def test_a_record_missing_a_declared_component_names_it(repo: Repository) -> None:
    point = repo.head("main")
    components = [c for c in declared_components(point) if c["bom-ref"] != "binary/market"]
    repo.cut("1.0.0", components=components)

    assert check(TAG, repo.root) == [
        "it does not name binary/market, which the declaration at the branch point declares"]


def test_a_record_naming_an_undeclared_component_or_a_development_image_names_each(
        repo: Repository) -> None:
    point = repo.head("main")
    components = declared_components(point) + [
        image("dev-env", digest("7"), point),
        wheel("arkhai-apicredits-sample-app", "0.1.0", digest("8")),
    ]
    repo.cut("1.0.0", components=components)

    assert check(TAG, repo.root) == [
        "it names image/dev-env, a development image, which is not a release component",
        "it names wheel/arkhai-apicredits-sample-app, which the declaration at the branch "
        "point does not declare"]


def test_a_record_naming_a_component_twice_names_it(repo: Repository) -> None:
    point = repo.head("main")
    components = declared_components(point)
    repo.cut("1.0.0", components=components + [components[2]])

    assert check(TAG, repo.root) == ["it names image/registry 2 times"]


def test_a_declared_npm_package_is_a_component_by_its_unscoped_name(repo: Repository) -> None:
    declared = {**DECLARATION, "npm": [{"path": "middleware"}]}
    repo.write({"manifests/release-components.json": json.dumps(declared, indent=2) + "\n",
                "middleware/package.json": '{"name": "@arkhai/credits-middleware"}\n'})
    repo.commit("declare the npm package")
    repo.cut("0.9.0")
    repo.write({"README": "a later change\n"})
    later = repo.commit("a later change")
    repo.cut("1.0.0", components=declared_components(later) + [
        npm("credits-middleware", "0.2.0", "6" * 128)])

    assert check("marketplace-v0.9.0", repo.root) == [
        "it does not name npm/credits-middleware, which the declaration at the branch point "
        "declares"]
    assert check(TAG, repo.root) == []


def test_a_branch_point_with_no_readable_declaration_or_chart_is_refused(
        repo: Repository) -> None:
    repo.write({"helm/Chart.yaml": "apiVersion: v2\n"})
    repo.commit("a chart with no name")
    repo.cut("0.9.0")
    repo.git("rm", "-q", "manifests/release-components.json")
    repo.commit("no declaration")
    repo.cut("1.0.0")

    assert check("marketplace-v0.9.0", repo.root) == [
        "the parent commit's helm/Chart.yaml names no chart",
        "it names chart/chart, which the declaration at the branch point does not declare"]
    assert check(TAG, repo.root) == [
        "the parent commit has no manifests/release-components.json"]


def test_the_declaration_is_read_at_the_branch_point_not_the_checkout(repo: Repository) -> None:
    repo.cut("1.0.0")
    repo.write({"manifests/release-components.json": "{}\n"})
    repo.commit("a declaration changed after the release")

    assert check(TAG, repo.root) == []


# 6. No version it names was recorded by an earlier release with other contents.


def test_a_record_reusing_an_earlier_version_with_other_bytes_is_refused(
        repo: Repository) -> None:
    repo.cut("0.9.0")
    repo.write({"README": "a later change\n"})
    point = repo.commit("a later change")
    repo.cut("1.0.0", components=declared_components(point, core=("0.1.0", digest("9"))))

    problems = check(TAG, repo.root)

    assert len(problems) == 1
    assert problems[0].startswith(
        f"wheel/arkhai-core 0.1.0: its SHA-256 is {digest('9')}, but marketplace-v0.9.0 "
        f"recorded that version as {digest('1')}")
