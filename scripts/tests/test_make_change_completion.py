"""Complete workflow arguments through Bash's real word-reassembly helper."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPLETION = ROOT / "scripts/completions/make-change.bash"
BASH_COMPLETION = Path("/usr/share/bash-completion/bash_completion")
MAKE_COMPLETION = BASH_COMPLETION.parent / "completions/make"
pytestmark = pytest.mark.skipif(
    not shutil.which("bash") or not BASH_COMPLETION.is_file() or not MAKE_COMPLETION.is_file(),
    reason="Bash and bash-completion's make completion are required",
)


def _complete(root: Path, line: str, words: list[str], *, legacy: bool = False,
              preload: bool = True) -> list[str]:
    script = f"""
source {shlex.quote(str(BASH_COMPLETION))}
{('source ' + shlex.quote(str(MAKE_COMPLETION))) if preload else ':'}
if {str(legacy).lower()} && ! declare -F _make >/dev/null; then
    _make() {{ _comp_cmd_make "$@"; }}
fi
source {shlex.quote(str(COMPLETION))}
COMP_LINE={shlex.quote(line)}
COMP_POINT=${{#COMP_LINE}}
COMP_WORDS=({shlex.join(words)})
COMP_CWORD=$((${{#COMP_WORDS[@]}} - 1))
_arkhai_make_change make "${{COMP_WORDS[COMP_CWORD]}}" "${{COMP_WORDS[COMP_CWORD-1]}}"
if ((${{#COMPREPLY[@]}})); then
    printf '%s\\n' "${{COMPREPLY[@]}}"
fi
"""
    result = subprocess.run(["bash", "--noprofile", "--norc", "-c", script], cwd=root,
                            capture_output=True, text=True, check=True)
    assert not result.stderr
    return sorted(result.stdout.splitlines())


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    for name in ("orch-one", "orch-two", "other", "archive/2026-10-16-old-change",
                 "archive/2026-10-15-older-change"):
        (tmp_path / "openspec/changes" / name).mkdir(parents=True)
    (tmp_path / "openspec/changes/README.md").write_text("index\n")
    (tmp_path / "Makefile").write_text("triage:\n\t@true\nreview:\n\t@true\n")
    return tmp_path


@pytest.mark.parametrize("legacy", [False, True])
def test_complete_active_names_with_equals_word_break(repository: Path, legacy: bool) -> None:
    assert _complete(repository, "make triage CHANGE=orch",
                     ["make", "triage", "CHANGE", "=", "orch"], legacy=legacy) == [
                         "orch-one", "orch-two"]


def test_complete_empty_value_excludes_archive_and_files(repository: Path) -> None:
    assert _complete(repository, "make triage CHANGE=",
                     ["make", "triage", "CHANGE", "=", ""]) == [
                         "orch-one", "orch-two", "other"]


def test_no_matching_change(repository: Path) -> None:
    assert _complete(repository, "make triage CHANGE=missing",
                     ["make", "triage", "CHANGE", "=", "missing"]) == []


def test_archive_cleanup_strips_date_prefix(repository: Path) -> None:
    assert _complete(repository, "make archive-cleanup CHANGE=old",
                     ["make", "archive-cleanup", "CHANGE", "=", "old"]) == [
                         "old-change", "older-change"]


def test_archive_cleanup_after_assignment(repository: Path) -> None:
    assert _complete(repository, "make CHANGE=old archive-cleanup CHANGE=old",
                     ["make", "CHANGE", "=", "old", "archive-cleanup", "CHANGE", "=", "old"]) == [
                         "old-change", "older-change"]


def test_review_kinds(repository: Path) -> None:
    assert _complete(repository, "make review KIND=",
                     ["make", "review", "KIND", "=", ""]) == [
                         "closeout", "design", "implementation", "pre-closeout"]
    assert _complete(repository, "make review KIND=pre",
                     ["make", "review", "KIND", "=", "pre"]) == ["pre-closeout"]


@pytest.mark.parametrize("legacy", [False, True])
def test_other_words_use_make_completion(repository: Path, legacy: bool) -> None:
    assert _complete(repository, "make tri", ["make", "tri"], legacy=legacy) == ["triage"]


def test_loads_lazy_make_completion(repository: Path) -> None:
    assert _complete(repository, "make tri", ["make", "tri"], preload=False) == ["triage"]


def test_missing_changes_directory(tmp_path: Path) -> None:
    assert _complete(tmp_path, "make triage CHANGE=",
                     ["make", "triage", "CHANGE", "=", ""]) == []
