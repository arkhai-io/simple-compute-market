"""A comment or docstring line a change adds may not describe how the code came to
be; code and single-line string values, and lines the change did not add, are not
read."""

from __future__ import annotations

from pathlib import Path

import pytest

import check_history_wording as checker
from change_diff import merge_base
from change_diff_fixtures import change_repo, commit, write


@pytest.mark.parametrize("word", checker.WORDS)
def test_each_listed_phrase_in_an_added_comment_fails(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, word: str) -> None:
    repo = change_repo(tmp_path, monkeypatch, {})
    write(repo, "pool.py", f"x = 1  # {word.upper()} read from the pool\n")

    assert checker.problems(repo, merge_base(repo)) == [
        f'pool.py:1: "{word.upper()}" describes history; say what holds now']


@pytest.mark.parametrize("word", ["now", "legacy"])
def test_now_and_legacy_pass(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, word: str) -> None:
    repo = change_repo(tmp_path, monkeypatch, {})
    write(repo, "pool.py", f"# the {word} fixture value\n")

    assert checker.problems(repo, merge_base(repo)) == []


def test_a_phrase_in_code_or_a_string_value_is_not_a_comment() -> None:
    source = ('previously = "used to"\n'
              'def f():\n'
              '    """Returns the pool."""\n'
              '    return {"no longer": previously}  # the pool\n')

    comments = checker.python_comments(source)

    assert comments == {3: '    """Returns the pool."""', 4: "# the pool"}


def test_every_line_of_a_docstring_is_read() -> None:
    source = 'class C:\n    """One.\n\n    Two.\n    """\n'

    assert sorted(checker.python_comments(source)) == [2, 3, 4, 5]


@pytest.mark.parametrize(("line", "comment"), [
    ("key = 1 # a note", "# a note"),
    ("# a whole line", "# a whole line"),
    ('url = "http://host/#anchor" # note', "# note"),
    ("run: echo don't # note", "# note"),
    ("  - 'a # b'", None),
    ('k = "a \\" # b"', None),
    ("k = 'a\\' # b", "# b"),
    ("color: abc#def", None),
])
def test_a_toml_or_yaml_comment_starts_at_a_hash_outside_a_value(
        line: str, comment: str | None) -> None:
    assert checker.hash_comment(line) == comment


def test_only_lines_the_change_adds_are_read(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {
        "a.py": "# previously in the pool table\nx = 1\n",
        "ci.yml": "jobs: {}  # formerly two jobs\n"})
    commit(repo, {"a.py": "# previously in the pool table\nx = 2  # read from the pool table\n"})
    write(repo, "ci.yml", "jobs: {}  # formerly two jobs\nname: test  # no longer manual\n")
    write(repo, "pkg/pyproject.toml", "[project]\n# originally vendored\nname = 'p'\n")
    write(repo, "notes.md", "previously this said otherwise\n")

    assert checker.problems(repo, merge_base(repo)) == [
        'ci.yml:2: "no longer" describes history; say what holds now',
        'pkg/pyproject.toml:2: "originally" describes history; say what holds now',
    ]


def test_a_hash_line_in_a_block_scalar_or_multi_line_string_is_read_as_a_comment(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Such blocks hold embedded shell or configuration, whose comments the rule covers.
    repo = change_repo(tmp_path, monkeypatch, {})
    write(repo, "ci.yml", "steps:\n  - run: |\n      # previously ran twice\n      make test\n")
    write(repo, "chart.toml", 'config = """\n# formerly in the image\nport = 1\n"""\n')

    assert checker.problems(repo, merge_base(repo)) == [
        'chart.toml:2: "formerly" describes history; say what holds now',
        'ci.yml:3: "previously" describes history; say what holds now',
    ]


def test_the_command_names_the_file_and_line_and_fails(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    repo = change_repo(tmp_path, monkeypatch, {})
    commit(repo, {"pool.py": "x = 1\n# previously read from the pool table\n"})

    assert checker.main([], root=repo) == 1
    assert 'pool.py:2: "previously" describes history' in capsys.readouterr().out

    commit(repo, {"pool.py": "x = 1\n# read from the pool table\n"})
    assert checker.main([], root=repo) == 0


def test_a_python_file_that_does_not_parse_is_named(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {})
    write(repo, "broken.py", "def f(:\n")

    [problem] = checker.problems(repo, merge_base(repo))

    assert problem.startswith("broken.py: cannot be read as Python")


def test_an_unknown_base_is_an_error(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    repo = change_repo(tmp_path, monkeypatch, {})

    assert checker.main(["--base", "release"], root=repo) == 2
    assert "'release'" in capsys.readouterr().err
