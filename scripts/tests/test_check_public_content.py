"""Publication checks exercise real Git additions and intermediate commits."""
from __future__ import annotations

import io
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

import check_public_content as checker


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                       'GIT_AUTHOR_NAME': 'fixture', 'GIT_COMMITTER_NAME': 'fixture',
                       'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
                       'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}.items():
        monkeypatch.setenv(key, value)
    subprocess.run(['git', 'init', '-q', '-b', 'dev', str(tmp_path)], check=True)
    git(tmp_path, 'commit', '--allow-empty', '-qm', 'base')
    return tmp_path


def git(repo: Path, *args: str) -> str:
    return subprocess.run(['git', *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def stage(repo: Path, text: str, name: str = 'notes.md') -> None:
    (repo / name).write_text(text)
    git(repo, 'add', name)


def personal_path() -> str:
    # Assemble a synthetic prohibited value so the guard also scans this test.
    return '/home/' + 'fixture-person' + '/work'


ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / 'scripts/change-workflow'


@pytest.fixture
def branch(repo: Path, tmp_path: Path) -> Path:
    """`repo` on a change branch not yet pushed, beside a bare `origin` holding
    `dev`, with this check in its tree and a workflow configuration whose `pre-push`
    runs it as the guarded push runs a pre-push hook; both ignored so the worktree
    stays clean."""
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'push', '-q', '-u', 'origin', 'dev')
    git(repo, 'checkout', '-q', '-b', 'feat/change')
    # Its upstream, a branch of its own name on `origin`, as a change's clone sets it.
    git(repo, 'config', 'branch.feat/change.remote', 'origin')
    git(repo, 'config', 'branch.feat/change.merge', 'refs/heads/feat/change')
    script = repo / 'scripts' / Path(checker.__file__).name
    script.parent.mkdir()
    script.write_text(Path(checker.__file__).read_text('utf-8'), 'utf-8')
    (repo / '.agents').mkdir()
    (repo / '.agents/workflow.toml').write_text(
        '[repository]\nprotected-branches = ["main", "dev"]\n[hooks]\n'
        f'pre-push = "{shlex.quote(sys.executable)} scripts/{script.name} --pre-push '
        '{remote}"\n', 'utf-8')
    with (repo / '.git/info/exclude').open('a', encoding='utf-8') as exclude:
        # The repository is the test's own directory, which holds the remote too.
        exclude.write('/scripts/\n/.agents/\n/remote.git/\n')
    return repo


def push(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(COMMAND), 'push'], cwd=repo, capture_output=True, text=True)


def remote_head(repo: Path) -> str:
    return git(repo, 'ls-remote', 'origin', 'refs/heads/feat/change').split('\t')[0]


def test_the_check_passes_a_clean_guarded_push(branch: Path) -> None:
    (branch / 'notes.md').write_text('notes\n')
    git(branch, 'add', 'notes.md')
    git(branch, 'commit', '-qm', 'notes')

    assert push(branch).returncode == 0
    assert remote_head(branch) == git(branch, 'rev-parse', 'HEAD')


def _pre_push_target() -> str:
    """This repository's `make pre-push`, as its Makefile defines it."""
    text = (ROOT / 'Makefile').read_text('utf-8')
    start = text.index('REMOTE ?=')
    return text[start:text.index('\ncheck-secrets:', start)] + '\n'


@pytest.fixture
def hooked(branch: Path) -> Path:
    """`branch` with this repository's `make pre-push` and Git hook, and, for the
    secret scan, which needs the pinned gitleaks, a stand-in that keeps what it read
    and passes."""
    (branch / 'Makefile').write_text(_pre_push_target(), 'utf-8')
    (branch / 'scripts/check_secrets.py').write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path('.git/secrets-read').write_text(' '.join(sys.argv[1:]) + '|' + sys.stdin.read())\n",
        'utf-8')
    hook = branch / '.git/hooks/pre-push'
    hook.write_text((ROOT / 'scripts/hooks/pre-push').read_text('utf-8'), 'utf-8')
    hook.chmod(0o755)
    with (branch / '.git/info/exclude').open('a', encoding='utf-8') as exclude:
        exclude.write('/Makefile\n')
    return branch


def _without_make_flags() -> dict[str, str]:
    return {key: value for key, value in os.environ.items()
            if key not in ('MAKEFLAGS', 'MFLAGS', 'MAKELEVEL', 'MAKEOVERRIDES')}


def _git_push(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['git', 'push', '-q', 'origin', 'feat/change'], cwd=repo,
                          capture_output=True, text=True, env=_without_make_flags())


def _make_pre_push(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    head = git(repo, 'rev-parse', 'HEAD')
    ref = 'refs/heads/feat/change'
    return subprocess.run(['make', '--no-print-directory', '-s', 'pre-push', *arguments],
                          cwd=repo, input=f'{ref} {head} {ref} {"0" * 40}\n',
                          capture_output=True, text=True, env=_without_make_flags())


def test_the_git_hook_runs_make_pre_push_giving_each_check_the_ref_updates(
        hooked: Path) -> None:
    """MCW-k3vy, library integration: an owner's `git push` runs the repository's
    hook, which runs `make pre-push` with the remote, and each check reads Git's ref
    updates."""
    stage(hooked, 'notes\n')
    git(hooked, 'commit', '-qm', 'notes')

    pushed = _git_push(hooked)

    assert pushed.returncode == 0, pushed.stderr
    assert remote_head(hooked) == git(hooked, 'rev-parse', 'HEAD')
    remote, updates = (hooked / '.git/secrets-read').read_text('utf-8').split('|', 1)
    assert remote == '--pre-push origin'
    assert updates.startswith(f'refs/heads/feat/change {git(hooked, "rev-parse", "HEAD")} ')


def test_the_git_hook_refuses_a_commit_adding_a_private_path(hooked: Path) -> None:
    stage(hooked, personal_path())
    git(hooked, 'commit', '-qm', 'notes')

    pushed = _git_push(hooked)

    assert pushed.returncode != 0
    assert remote_head(hooked) == ''
    assert 'personal home path' in pushed.stderr
    assert personal_path() not in pushed.stderr + pushed.stdout
    # Either refusing, the other still runs.
    assert (hooked / '.git/secrets-read').is_file()


@pytest.mark.parametrize('private', [False, True])
def test_make_pre_push_refuses_a_private_path_and_passes_a_clean_commit(
        hooked: Path, private: bool) -> None:
    stage(hooked, personal_path() if private else 'notes\n')
    git(hooked, 'commit', '-qm', 'notes')

    ran = _make_pre_push(hooked, 'REMOTE=origin')

    # Make exits 2 whenever its recipe fails.
    assert (ran.returncode != 0) is private, ran.stderr
    assert ('personal home path' in ran.stderr) is private


def test_make_pre_push_needs_the_remote(hooked: Path) -> None:
    ran = _make_pre_push(hooked)

    assert ran.returncode != 0
    assert 'pre-push needs REMOTE=<remote>' in ran.stderr


def test_an_up_to_date_push_passes(hooked: Path) -> None:
    """Git runs the hook with no input when every ref is up to date; no blank line
    reaches the checks to be read as a malformed update."""
    assert _git_push(hooked).returncode == 0

    second = _git_push(hooked)

    assert second.returncode == 0, second.stderr
    assert (hooked / '.git/secrets-read').read_text('utf-8') == '--pre-push origin|'


def test_the_secret_scan_refusing_refuses_the_push(hooked: Path) -> None:
    (hooked / 'scripts/check_secrets.py').write_text(
        "import sys\nprint('REFUSED: a key', file=sys.stderr)\nsys.exit(1)\n", 'utf-8')
    stage(hooked, 'notes\n')
    git(hooked, 'commit', '-qm', 'notes')

    ran = _make_pre_push(hooked, 'REMOTE=origin')
    pushed = _git_push(hooked)

    assert ran.returncode != 0 and 'REFUSED: a key' in ran.stderr
    assert pushed.returncode != 0 and remote_head(hooked) == ''


@pytest.mark.parametrize('removed_later', [False, True])
def test_private_content_refuses_the_guarded_push(branch: Path, removed_later: bool) -> None:
    stage(branch, personal_path())
    git(branch, 'commit', '-qm', 'notes')
    if removed_later:
        git(branch, 'rm', '-q', 'notes.md')
        git(branch, 'commit', '-qm', 'remove notes')

    pushed = push(branch)

    assert pushed.returncode == 1
    assert remote_head(branch) == ''
    assert 'personal home path' in pushed.stderr
    assert personal_path() not in pushed.stderr + pushed.stdout


def test_staged_scan_uses_index_and_redacts_values(repo: Path, capsys) -> None:
    stage(repo, personal_path())
    (repo / 'notes.md').write_text('safe unstaged replacement')
    assert checker.main(['--staged'], root=repo) == 1
    output = capsys.readouterr().err
    assert 'notes.md:1: personal home path' in output
    assert personal_path() not in output


def test_unstaged_private_content_is_not_part_of_a_commit(repo: Path) -> None:
    stage(repo, 'safe staged text')
    (repo / 'notes.md').write_text(personal_path())
    assert checker.scan(repo, staged=True) == []


def test_safe_fixtures_and_runtime_accounts(repo: Path) -> None:
    stage(repo, '/home/example-user/work\n/home/appuser/.venv\n'
                '/home/ubuntu/work\n/home/<user>/work\n/home/{{ tenant }}/work')
    assert checker.scan(repo, staged=True) == []


def test_intermediate_leak_still_blocks_after_deletion(repo: Path) -> None:
    base = git(repo, 'rev-parse', 'HEAD')
    stage(repo, personal_path())
    git(repo, 'commit', '-qm', 'unsafe')
    stage(repo, 'now removed')
    git(repo, 'commit', '-qm', 'cleanup')
    assert checker.scan(repo, base=base)


def test_commit_message_is_checked(repo: Path) -> None:
    base = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'commit', '--allow-empty', '-qm', personal_path())
    assert any('<commit message>' in f for f in checker.scan(repo, base=base))


def test_local_denylist_and_unreadable_configuration_fail_closed(repo: Path, tmp_path: Path) -> None:
    deny = tmp_path.parent / 'private-identifiers.txt'
    deny.write_text('fixture-host.example.invalid\n')
    git(repo, 'config', 'scm.publicContentDenyFile', str(deny))
    stage(repo, 'FIXTURE-HOST.EXAMPLE.INVALID')
    assert 'locally denied identifier' in checker.scan(repo, staged=True)[0]
    deny.unlink()
    with pytest.raises(ValueError, match='unreadable'):
        checker.scan(repo, staged=True)


def test_binary_addition_is_not_silently_accepted(repo: Path) -> None:
    (repo / 'blob').write_bytes(b'\x00' + personal_path().encode())
    git(repo, 'add', 'blob')
    assert any('binary' in f for f in checker.scan(repo, staged=True))


def test_suspicious_filename_is_not_echoed(repo: Path, tmp_path: Path) -> None:
    deny = tmp_path.parent / 'private-identifiers.txt'
    deny.write_text('fixture-machine\n')
    git(repo, 'config', 'scm.publicContentDenyFile', str(deny))
    stage(repo, 'safe', 'fixture-machine.txt')
    findings = checker.scan(repo, staged=True)
    assert findings and all('fixture-machine' not in f for f in findings)


def test_missing_base_ref_is_an_error(repo: Path) -> None:
    with pytest.raises(ValueError, match='Git inspection failed'):
        checker.scan(repo, base='not-a-ref')


def test_outgoing_commits_respect_only_target_remote(repo: Path) -> None:
    base = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'update-ref', 'refs/remotes/public/dev', base)
    stage(repo, personal_path())
    git(repo, 'commit', '-qm', 'unsafe')
    git(repo, 'update-ref', 'refs/remotes/private/work', 'HEAD')
    assert checker.scan(repo, remote='public')
    assert checker.scan(repo, remote='private') == []


def test_pre_push_checks_the_supplied_tip_instead_of_head(repo: Path, monkeypatch, capsys) -> None:
    base = git(repo, 'rev-parse', 'HEAD')
    stage(repo, personal_path())
    git(repo, 'commit', '-qm', 'unsafe topic')
    tip = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '--detach', base)
    monkeypatch.setattr('sys.stdin', io.StringIO(f'refs/heads/topic {tip} refs/heads/topic {base}\n'))
    assert checker.main(['--pre-push', 'public'], root=repo) == 1
    assert personal_path() not in capsys.readouterr().err


def test_added_text_starting_with_plus_signs_is_not_a_file_header(repo: Path) -> None:
    stage(repo, "++ " + personal_path())
    assert checker.scan(repo, staged=True)


@pytest.mark.parametrize("prefix,name", [("/Users/", "fixture-person"),
    ("/home/", "fixture-pérson"), ("C:" + chr(92) + "Users" + chr(92), "fixture-person")])
def test_home_path_variants_are_checked(repo: Path, prefix: str, name: str) -> None:
    stage(repo, prefix + name + "/work")
    assert checker.scan(repo, staged=True)


def test_added_patch_header_lookalike_cannot_hide_private_content(repo: Path) -> None:
    stage(repo, "++ b/notes " + personal_path())
    assert checker.scan(repo, staged=True)


def test_unicode_private_filename_is_checked(repo: Path, tmp_path: Path) -> None:
    deny = tmp_path.parent / "private-identifiers.txt"
    deny.write_text("fixture-máchine")
    git(repo, "config", "scm.publicContentDenyFile", str(deny))
    stage(repo, "safe", "fixture-máchine.txt")
    findings = checker.scan(repo, staged=True)
    assert findings and all("fixture-máchine" not in f for f in findings)


def test_private_ref_name_is_refused(repo: Path, tmp_path: Path, monkeypatch) -> None:
    deny = tmp_path.parent / "private-identifiers.txt"
    deny.write_text("fixture-machine")
    git(repo, "config", "scm.publicContentDenyFile", str(deny))
    head = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr("sys.stdin", io.StringIO(
        f"refs/heads/fixture-machine {head} refs/heads/fixture-machine {head}\n"))
    assert checker.main(["--pre-push", "public"], root=repo) == 1


def test_annotated_tag_message_is_checked(repo: Path, monkeypatch) -> None:
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/public/dev", head)
    git(repo, "tag", "-a", "fixture-tag", "-m", personal_path())
    tag = git(repo, "rev-parse", "fixture-tag")
    monkeypatch.setattr("sys.stdin", io.StringIO(
        f"refs/tags/fixture-tag {tag} refs/tags/fixture-tag {'0' * 40}\n"))
    assert checker.main(["--pre-push", "public"], root=repo) == 1
