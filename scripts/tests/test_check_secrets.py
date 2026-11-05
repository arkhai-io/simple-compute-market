"""The private-key check runs the pinned gitleaks with the repository's rule.

The unit cases inject the runner and the version check. The real-scanner cases run
the pinned release over temporary Git repositories, and over the repository's own
tree; they skip where the pinned gitleaks is not on PATH, except under
`GITLEAKS_REQUIRED=1`, which CI's packaging job sets, where a skip is a failure.

No key here is real, and none is written into this file: each test assembles its
header at runtime and fills its body with random bytes, so the check, scanning this
file, finds no block in it.
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Sequence

import pytest

import check_secrets as checker
import install_gitleaks

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = os.environ.get("GITLEAKS_REQUIRED") == "1"
HEADER = "-----BEGIN " + "RSA PRIVATE KEY-----"
FOOTER = "-----END " + "RSA PRIVATE KEY-----"
FIXTURE_HEADER = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
FIXTURE_FOOTER = "-----END " + "OPENSSH PRIVATE KEY-----"


def key_body() -> str:
    """Random base64 the length of an RSA key's body, which no real key shares."""
    return base64.b64encode(os.urandom(1190)).decode()


def wrapped_key(width: int) -> tuple[str, str]:
    """A key block wrapped at `width`, and its body."""
    body = key_body()
    return "\n".join([HEADER, *textwrap.wrap(body, width), FOOTER]) + "\n", body


def fixture(word: str) -> str:
    """A fixture's key block as the repository's tests write it, on one line."""
    return f'"{FIXTURE_HEADER}\\n{word}\\n{FIXTURE_FOOTER}\\n"'


# ---------------------------------------------------------------- unit


class _Runner:
    """Records each command and writes `findings` as gitleaks' JSON report."""

    def __init__(self, findings: list[dict] | None = None, returncode: int | None = None,
                 stderr: str = "") -> None:
        self.findings = findings or []
        self.returncode = (1 if self.findings else 0) if returncode is None else returncode
        self.stderr = stderr
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        report = Path(command[command.index("--report-path") + 1])
        if self.returncode in (0, 1):
            report.write_text(json.dumps(self.findings), "utf-8")
        return subprocess.CompletedProcess(command, self.returncode, "", self.stderr)


def _pinned() -> None:
    return None


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "fixture", "GIT_COMMITTER_NAME": "fixture",
                       "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                       "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}.items():
        monkeypatch.setenv(key, value)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "dev", str(repo)], check=True)
    git(repo, "commit", "--allow-empty", "-qm", "base")
    return repo


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(repo: Path, name: str, text: str, message: str = "change") -> str:
    (repo / name).write_text(text, "utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return _repo(tmp_path, monkeypatch)


def test_a_staged_scan_runs_gitleaks_on_the_index_with_the_repository_rule(
        repo: Path) -> None:
    runner = _Runner()

    assert checker.scan(repo, staged=True, run=runner, version_problem=_pinned) == []

    [command] = runner.commands
    assert command[:3] == ["gitleaks", "git", "--staged"]
    assert command[command.index("--config") + 1] == str(ROOT / ".gitleaks.toml")
    assert {"--redact", "--ignore-gitleaks-allow"} <= set(command)
    assert command[-1] == str(repo)


def test_a_range_scan_reads_every_commit_after_the_base_with_merge_patches(
        repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    tip = commit(repo, "notes.md", "text")
    runner = _Runner()

    checker.scan(repo, base=base, run=runner, version_problem=_pinned)

    [command] = runner.commands
    assert command[1:3] == ["git", f"--log-opts={tip} ^{base} --diff-merges=separate"]


def test_an_outgoing_scan_excludes_every_ref_of_the_target_remote_only(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/public/dev", base)
    tip = commit(repo, "notes.md", "text")
    git(repo, "update-ref", "refs/remotes/private/work", tip)
    runner = _Runner()

    checker.scan(repo, remote="public", run=runner, version_problem=_pinned)

    assert runner.commands[0][2] == f"--log-opts={tip} ^{base} --diff-merges=separate"
    with pytest.raises(checker.SecretsError, match="fetch before publishing"):
        checker.scan(repo, remote="absent", run=runner, version_problem=_pinned)


def test_a_pre_push_scan_reads_each_updated_ref_and_skips_a_deletion(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    tip = commit(repo, "notes.md", "text")
    git(repo, "update-ref", "refs/remotes/public/dev", base)
    runner = _Runner()

    checker.pre_push(repo, "public", [
        f"refs/heads/topic {tip} refs/heads/topic {base}",
        f"refs/heads/new {tip} refs/heads/new {'0' * 40}",
        f"(delete) {'0' * 40} refs/heads/gone {base}",
    ], run=runner, version_problem=_pinned)

    assert [c[2] for c in runner.commands] == [
        f"--log-opts={tip} ^{base} --diff-merges=separate"] * 2
    with pytest.raises(checker.SecretsError, match="Malformed"):
        checker.pre_push(repo, "public", ["refs/heads/topic"], run=runner,
                         version_problem=_pinned)


def test_another_gitleaks_release_is_refused_naming_both_and_nothing_runs(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = _Runner()
    message = install_gitleaks.problem(lambda: "8.29.0\n")

    assert checker.main(["--staged"], root=repo, run=runner,
                        version_problem=lambda: message) == 1

    err = capsys.readouterr().err
    assert "gitleaks 8.30.1 is required and gitleaks 8.29.0 is on PATH" in err
    assert "make install-gitleaks" in err
    assert runner.commands == []


def test_a_finding_is_reported_by_rule_file_line_and_commit_without_its_content(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    finding = {"RuleID": "private-key-block", "File": "keys.py", "StartLine": 7,
               "Commit": "a" * 40, "Secret": "REDACTED", "Match": "REDACTED"}
    runner = _Runner([finding, finding])

    assert checker.main(["--base", "HEAD"], root=repo, run=runner,
                        version_problem=_pinned) == 1

    assert capsys.readouterr().err.splitlines() == [
        f"REFUSED: {'a' * 12}:keys.py:7: private-key-block"]


@pytest.mark.parametrize(("returncode", "findings", "written"), [
    (2, [], False), (1, [], True), (1, None, False)])
def test_a_scan_gitleaks_could_not_complete_is_an_error_not_a_pass(
        repo: Path, returncode: int, findings: list | None, written: bool) -> None:
    runner = _Runner(returncode=returncode, stderr="config: unknown field")

    with pytest.raises(checker.SecretsError, match="could not complete.*unknown field"):
        checker.scan_source(repo, checker.staged_source(), run=runner)


# ---------------------------------------------------------- real gitleaks


@pytest.fixture
def gitleaks() -> None:
    reason = install_gitleaks.problem()
    if reason is not None:
        if REQUIRED:
            pytest.fail(reason)
        pytest.skip(reason)


def stage(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, "utf-8")
    git(repo, "add", name)


def assert_refused_without_echo(findings: list[str], body: str, where: str) -> None:
    assert any(f.endswith(f"{where}: private-key-block") for f in findings), findings
    assert all(body[:40] not in f for f in findings)


@pytest.mark.usefixtures("gitleaks")
def test_a_key_fixture_carries_no_key_material(repo: Path) -> None:
    stage(repo, "test_hosts.py", f"PEM = {fixture('fixture')}\n")

    assert checker.scan(repo, staged=True) == []


@pytest.mark.usefixtures("gitleaks")
def test_two_key_fixtures_share_a_file_staged_and_committed(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    text = (f"FIRST = {fixture('fixture')}\n" + "x = 1\n" * 200
            + f"SECOND = {fixture('legacy-fixture')}\n")
    stage(repo, "test_hosts.py", text)

    assert checker.scan(repo, staged=True) == []
    git(repo, "commit", "-qm", "fixtures")
    assert checker.scan(repo, base=base) == []


@pytest.mark.usefixtures("gitleaks")
@pytest.mark.parametrize("width", [64, 16])
def test_a_real_key_is_staged(repo: Path, capsys: pytest.CaptureFixture[str],
                              width: int) -> None:
    block, body = wrapped_key(width)
    stage(repo, "deploy.pem", "notes\n" + block)

    assert checker.main(["--staged"], root=repo) == 1

    err = capsys.readouterr().err
    assert_refused_without_echo(err.splitlines(), body, "deploy.pem:2")


@pytest.mark.usefixtures("gitleaks")
def test_a_key_is_embedded_as_one_escaped_string(repo: Path) -> None:
    body = key_body()
    escaped = "\\n".join([HEADER, *textwrap.wrap(body, 64), FOOTER]) + "\\n"
    stage(repo, "settings.py", f'import os\nKEY = "{escaped}"\n')

    assert_refused_without_echo(checker.scan(repo, staged=True), body, "settings.py:2")


@pytest.mark.usefixtures("gitleaks")
def test_a_fixture_beside_a_real_key_does_not_hide_it(repo: Path) -> None:
    block, body = wrapped_key(64)
    stage(repo, "keys.py", f"PEM = {fixture('fixture')}\n" + block)

    assert_refused_without_echo(checker.scan(repo, staged=True), body, "keys.py:2")


@pytest.mark.usefixtures("gitleaks")
def test_a_key_marked_gitleaks_allow_is_still_refused(repo: Path) -> None:
    body = key_body()
    escaped = "\\n".join([HEADER, body, FOOTER])
    stage(repo, "settings.py", f'KEY = "{escaped}"  # gitleaks:allow\n')

    assert_refused_without_echo(checker.scan(repo, staged=True), body, "settings.py:1")


@pytest.mark.usefixtures("gitleaks")
def test_a_key_an_intermediate_commit_adds_and_a_later_one_deletes_is_refused(
        repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    block, body = wrapped_key(64)
    added = commit(repo, "deploy.pem", block, "add a key")
    commit(repo, "deploy.pem", "removed\n", "remove it")

    assert_refused_without_echo(checker.scan(repo, base=base), body,
                                f"{added[:12]}:deploy.pem:1")


@pytest.mark.usefixtures("gitleaks")
def test_a_key_added_in_a_merge_resolution_is_refused(repo: Path) -> None:
    base = commit(repo, "settings.py", "VALUE = 1\n", "settings")
    git(repo, "checkout", "-qb", "topic")
    commit(repo, "settings.py", "VALUE = 2\n", "topic edit")
    git(repo, "checkout", "-q", "dev")
    commit(repo, "settings.py", "VALUE = 3\n", "dev edit")
    subprocess.run(["git", "merge", "-q", "topic"], cwd=repo, capture_output=True)
    block, body = wrapped_key(64)
    (repo / "settings.py").write_text("VALUE = 4\n" + block, "utf-8")
    git(repo, "add", "settings.py")
    git(repo, "commit", "-qm", "merge topic")
    merge = git(repo, "rev-parse", "HEAD")
    assert len(git(repo, "show", "-s", "--format=%P", merge).split()) == 2

    assert_refused_without_echo(checker.scan(repo, base=base), body,
                                f"{merge[:12]}:settings.py:2")
    # Without merge patches, git log prints no patch for the merge, and the key the
    # resolution wrote reaches nothing gitleaks reads.
    tip = git(repo, "rev-parse", "HEAD")
    without = checker.scan_source(repo, ["git", f"--log-opts={tip} ^{base}"])
    assert not any("private-key-block" in f for f in without)


@pytest.mark.usefixtures("gitleaks")
def test_the_repositorys_own_tree_holds_no_key_block(tmp_path: Path, monkeypatch) -> None:
    for key, value in {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "fixture", "GIT_COMMITTER_NAME": "fixture",
                       "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                       "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}.items():
        monkeypatch.setenv(key, value)
    clone = tmp_path / "tree"
    git(tmp_path, "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(clone))
    # One parentless commit holding HEAD's tree: its patch adds every tracked file, so
    # the scan reads the whole tree as content about to be published.
    whole = git(clone, "commit-tree", "-m", "the tree", "HEAD^{tree}")

    found = checker.scan_source(clone, checker.range_source([whole, "--root"]))

    assert [f for f in found if f.endswith((": private-key-block", ": private-key"))] == []
