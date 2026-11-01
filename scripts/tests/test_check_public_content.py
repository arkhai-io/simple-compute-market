"""Publication checks exercise real Git additions and intermediate commits."""
from __future__ import annotations

import io
import os
import subprocess
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
