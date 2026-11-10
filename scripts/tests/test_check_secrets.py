"""The secret gate and audit run the pinned gitleaks with the repository's configurations.

The unit cases inject the runner and the version check. The real-scanner cases run
the pinned release over temporary Git repositories, and over the repository's own
tree; they skip where the pinned gitleaks is not on PATH, except under
`GITLEAKS_REQUIRED=1`, which CI's packaging job sets, where a skip is a failure.

No key or token here is real, and none the gate refuses is written into this file:
each test assembles its key header at runtime and fills the body with random bytes,
and builds its provider token and password from random characters, so the gate,
scanning this file, finds nothing in it.
"""

from __future__ import annotations

import base64
import io
import json
import os
import secrets
import shlex
import string
import subprocess
import sys
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
# Anvil's first published development account key and the address of the first
# contract it deploys: well-known deterministic development values, never to be used
# on a public network.
ANVIL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
ANVIL_CONTRACT = "0x5FbDB2315678afecb367f032d93F642f64180aa3"


def random_text(length: int) -> str:
    """Random letters and digits, the shape of a generated token or password."""
    return "".join(secrets.choice(string.ascii_letters + string.digits)
                   for _ in range(length))


def wordless_password() -> str:
    """40 random characters, each letter followed by a digit.

    `generic-api-key` passes any value holding one of its stop words, common words
    such as `menu` or `boot`; about one 40-character draw of letters and digits in
    eighty holds one. No two letters here are adjacent, so no word of letters can
    form, and no draw has escaped the rule in fifty thousand.
    """
    return "".join(secrets.choice(string.ascii_letters) + secrets.choice(string.digits)
                   for _ in range(20))


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


def test_every_scan_runs_from_the_repository_root_where_the_gate_finds_the_audit(
        repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    tip = commit(repo, "notes.md", "text")
    calls: list[Path] = []
    runner = _Runner()

    def recording(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(cwd)
        return runner(command, cwd)

    checker.scan(repo, staged=True, run=recording, version_problem=_pinned)
    checker.scan(repo, base=base, run=recording, version_problem=_pinned)
    checker.pre_push(repo, "public", [f"refs/heads/topic {tip} refs/heads/topic {base}"],
                     run=recording, version_problem=_pinned)
    checker.audit(repo, run=recording, version_problem=_pinned)

    assert calls == [ROOT] * 4
    assert [c[-1] for c in runner.commands[:3]] == [str(repo)] * 3
    assert runner.commands[3][-1] != str(repo)


def test_the_audit_scans_heads_tree_with_the_audit_configuration_and_exits_0_with_findings(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, "settings.yaml", "value: 1\n")
    (repo / "untracked.yaml").write_text("value: 2\n", "utf-8")
    finding = {"RuleID": "generic-api-key", "File": "settings.yaml", "StartLine": 1,
               "Commit": "b" * 40, "Secret": "REDACTED", "Match": "REDACTED"}
    runner = _Runner([finding])

    assert checker.main(["--audit"], root=repo, run=runner, version_problem=_pinned) == 0

    [command] = runner.commands
    assert command[command.index("--config") + 1] == str(ROOT / "scripts/gitleaks-audit.toml")
    # The scanned repository is the temporary clone holding the tree commit, not `repo`.
    assert Path(command[-1]).name == "tree" and command[-1] != str(repo)
    log_opts = command[2]
    assert log_opts.startswith("--log-opts=") and log_opts.endswith(
        " --root --diff-merges=separate")
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "settings.yaml:1: generic-api-key"
    assert "1 finding(s)" in out[-1]


def test_the_audit_reads_one_parentless_commit_of_heads_tree_and_nothing_untracked(
        repo: Path) -> None:
    commit(repo, "settings.yaml", "value: 1\n")
    (repo / "untracked.yaml").write_text("value: 2\n", "utf-8")

    with checker.tree_commit(repo) as (clone, whole):
        assert git(clone, "show", "-s", "--format=%P", whole) == ""
        assert git(clone, "rev-parse", whole + "^{tree}") == git(repo, "rev-parse",
                                                                 "HEAD^{tree}")
        assert "untracked.yaml" not in git(clone, "ls-tree", "-r", "--name-only", whole)


@pytest.mark.parametrize("returncode", [2, 126])
def test_an_audit_gitleaks_could_not_finish_is_an_error(
        repo: Path, capsys: pytest.CaptureFixture[str], returncode: int) -> None:
    runner = _Runner(returncode=returncode, stderr="config: unknown field")

    assert checker.main(["--audit"], root=repo, run=runner, version_problem=_pinned) == 1

    assert "ERROR: gitleaks could not complete the scan" in capsys.readouterr().err


def test_an_audit_with_another_gitleaks_release_is_an_error_and_runs_nothing(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = _Runner()
    message = install_gitleaks.problem(lambda: "8.29.0\n")

    assert checker.main(["--audit"], root=repo, run=runner,
                        version_problem=lambda: message) == 1

    assert "make install-gitleaks" in capsys.readouterr().err
    assert runner.commands == []


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
def test_a_provider_token_is_staged(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    token = "ghp_" + random_text(36)
    stage(repo, "deploy.env", f"MODE=ci\nGITHUB_TOKEN={token}\n")

    assert checker.main(["--staged"], root=repo) == 1

    err = capsys.readouterr().err.splitlines()
    assert any(f.startswith("REFUSED: deploy.env:2: ") for f in err), err
    assert all(token not in f for f in err)


@pytest.mark.usefixtures("gitleaks")
def test_a_development_fixture_is_added(repo: Path) -> None:
    lines = (f'private_key = "{ANVIL_KEY}"\n'
             f'escrow_address = "{ANVIL_CONTRACT}"\n'
             "    private_key: Ed25519PrivateKey\n")
    stage(repo, "test_settlement.py", lines)

    assert checker.scan(repo, staged=True) == []
    # The audit's `generic-api-key` reports the same lines, so the gate passes them
    # because that rule is off, which this case holds.
    git(repo, "commit", "-qm", "fixtures")
    assert any(f.endswith(": generic-api-key") for f in checker.audit(repo))


@pytest.mark.usefixtures("gitleaks")
def test_the_audit_reports_what_the_gate_passes(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = git(repo, "rev-parse", "HEAD")
    password = wordless_password()
    commit(repo, "build-vars.yaml", f"root_password: {password}\n")

    assert checker.main(["--audit"], root=repo) == 0

    out = capsys.readouterr().out
    assert "build-vars.yaml:1: generic-api-key" in out.splitlines()
    assert password not in out
    assert checker.scan(repo, base=base) == []


@pytest.mark.usefixtures("gitleaks")
def test_the_repositorys_own_tree_passes_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Any rule counts, so a gitleaks release whose new rule the tree trips fails here,
    # when its pin moves, rather than at someone's commit.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    with checker.tree_commit(ROOT) as (clone, whole):
        found = checker.scan_source(clone, checker.tree_source(whole))

    assert found == []


# ---------------------------------------------------------------- the guarded push

# The workflow's command; the guarded push runs the repository's pre-push checks, the
# gate among them, as commands.
COMMAND = ROOT / "scripts/change-workflow"


@pytest.fixture
def branch(repo: Path, tmp_path: Path) -> Path:
    """`repo` with a bare `origin` holding `dev`, on a change branch, its secret gate
    where the guarded push looks for it: a stand-in that runs this repository's gate,
    with its gitleaks configuration, over `repo`."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "dev")
    git(repo, "checkout", "-q", "-b", "feat/change")
    # Its upstream, a branch of its own name on `origin`, as a change's clone sets it.
    git(repo, "config", "branch.feat/change.remote", "origin")
    git(repo, "config", "branch.feat/change.merge", "refs/heads/feat/change")
    return repo


def provide_gate(repo: Path, version_problem: str | None = None) -> None:
    """The stand-in gate, and the workflow configuration whose `pre-push` runs it as
    the guarded push runs a pre-push hook, both ignored so the worktree stays clean;
    `version_problem` stands in for a gitleaks that cannot run."""
    (repo / ".agents").mkdir(exist_ok=True)
    (repo / ".agents/workflow.toml").write_text(
        '[repository]\nprotected-branches = ["main", "dev"]\n[hooks]\n'
        f'pre-push = "{shlex.quote(sys.executable)} scripts/{Path(checker.__file__).name} '
        '--pre-push {remote}"\n', "utf-8")
    with (repo / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("/.agents/\n")
    injected = ("" if version_problem is None
                else f", version_problem=lambda: {version_problem!r}")
    gate = repo / "scripts" / Path(checker.__file__).name
    gate.parent.mkdir(exist_ok=True)
    gate.write_text("import sys\n"
                    "from pathlib import Path\n"
                    f"sys.path.insert(0, {str(Path(checker.__file__).parent)!r})\n"
                    "import check_secrets\n"
                    "sys.exit(check_secrets.main(sys.argv[1:], "
                    f"root=Path(__file__).resolve().parents[1]{injected}))\n", "utf-8")
    with (repo / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write(f"/{gate.relative_to(repo).as_posix()}\n")


def push(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(COMMAND), "push"], cwd=repo, capture_output=True, text=True)


def remote_head(repo: Path) -> str:
    return git(repo, "ls-remote", "origin", "refs/heads/feat/change").split("\t")[0]


def test_a_gate_that_cannot_run_refuses_the_guarded_push(branch: Path) -> None:
    provide_gate(branch, "gitleaks 8.30.1 is required and no gitleaks is on PATH")
    commit(branch, "notes.md", "notes\n")

    pushed = push(branch)

    assert pushed.returncode == 1
    assert "REFUSED: gitleaks 8.30.1 is required" in pushed.stderr
    assert remote_head(branch) == ""


@pytest.mark.usefixtures("gitleaks")
def test_an_outgoing_commit_adding_a_key_refuses_the_guarded_push(branch: Path) -> None:
    provide_gate(branch)
    block, body = wrapped_key(64)
    commit(branch, "deploy.pem", block, "deploy key")

    pushed = push(branch)

    assert pushed.returncode == 1
    assert ":deploy.pem:1: private-key-block" in pushed.stderr
    assert body[:40] not in pushed.stderr + pushed.stdout
    assert remote_head(branch) == ""


@pytest.mark.usefixtures("gitleaks")
def test_an_outgoing_commit_adding_a_key_fixture_is_pushed(branch: Path) -> None:
    provide_gate(branch)
    head = commit(branch, "test_hosts.py", f"PEM = {fixture('fixture')}\n", "fixture")

    pushed = push(branch)

    assert pushed.returncode == 0, pushed.stderr
    assert remote_head(branch) == head


@pytest.mark.usefixtures("gitleaks")
def test_historical_fingerprints_do_not_exempt_staged_or_new_keys(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    block, body = wrapped_key(64)
    historical = commit(repo, "tls.pem", block, "published fixture")
    fingerprint = f"{historical}:tls.pem:private-key-block:1"
    stage(repo, ".gitleaksignore", fingerprint + "\n")
    assert checker.scan(repo, base=base) == []

    commit(repo, "tls.pem", "no key material\n")
    stage(repo, "tls.pem", block)
    assert_refused_without_echo(checker.scan(repo, staged=True), body, "tls.pem:1")
    git(repo, "commit", "-qm", "new key addition")
    findings = checker.scan(repo, base=base)
    assert_refused_without_echo(findings, body, "tls.pem:1")
    assert all(not finding.startswith(historical + ":") for finding in findings)
    assert_refused_without_echo(checker.audit(repo), body, "tls.pem:1")
