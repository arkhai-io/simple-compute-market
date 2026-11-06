"""An import a change adds inside a function says why it stays local; module-level
imports and local imports the change did not touch are not read."""

from __future__ import annotations

from pathlib import Path

import pytest

import check_local_imports as checker
from change_diff import merge_base
from change_diff_fixtures import change_repo, commit, write

ALL = set(range(1, 100))


def test_a_local_import_without_a_reason_is_named() -> None:
    source = "def f():\n    import json\n    return json\n"

    assert checker.unexplained(source, ALL) == [2]


@pytest.mark.parametrize("source", [
    "def f():\n    import json  # a lazy load: rarely called\n",
    "def f():\n    # imported here: the module imports this one\n    import json\n",
    "def f():\n    from os import (  # lazy: only the CLI path needs it\n        path,\n    )\n",
    "def f():\n    from os import (\n        path,  # lazy: only the CLI path needs it\n    )\n",
])
def test_a_comment_beside_or_above_gives_the_reason(source: str) -> None:
    assert checker.unexplained(source, ALL) == []


@pytest.mark.parametrize("comment", ["# noqa: F401", "# noqa", "# type: ignore[import]",
                                     "# pragma: no cover", "# noqa: F401  # type: ignore",
                                     "# pylint: disable=import-outside-toplevel",
                                     "# pyright: ignore[reportMissingImports]",
                                     "# isort: skip", "#"])
def test_a_tools_directive_alone_is_no_reason(comment: str) -> None:
    assert checker.unexplained(f"def f():\n    import json  {comment}\n", ALL) == [2]
    assert checker.unexplained(f"def f():\n    {comment}\n    import json\n", ALL) == [3]


def test_a_directive_followed_by_a_reason_gives_it() -> None:
    source = "def f():\n    import json  # noqa: E402 - the module imports this one\n"

    assert checker.unexplained(source, ALL) == []


def test_module_level_imports_pass() -> None:
    source = "import json\nfrom os import path\n\ndef f():\n    return json, path\n"

    assert checker.unexplained(source, ALL) == []


def test_imports_in_nested_and_async_functions_and_methods_are_read() -> None:
    source = ("class C:\n"
              "    def m(self):\n"
              "        def inner():\n"
              "            import json\n"
              "async def g():\n"
              "    if True:\n"
              "        from os import path\n")

    assert checker.unexplained(source, ALL) == [4, 7]


def test_a_local_import_the_change_did_not_touch_is_not_read(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {
        "a.py": "def f():\n    import json\n    return json\n"})
    commit(repo, {"a.py": "def f():\n    import json\n    return json\n\n\n"
                          "def g():\n    import os\n    return os\n"})
    write(repo, "b.py", "def h():\n    import sys  # lazy: rarely called\n")

    assert checker.problems(repo, merge_base(repo)) == [
        "a.py:7: an import inside a function gives no reason to stay local"]


def test_the_command_fails_until_the_reason_is_given(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    repo = change_repo(tmp_path, monkeypatch, {})
    write(repo, "a.py", "def f():\n    import json\n")

    assert checker.main([], root=repo) == 1
    assert "a.py:2:" in capsys.readouterr().out

    write(repo, "a.py", "def f():\n    import json  # lazy: rarely called\n")
    assert checker.main([], root=repo) == 0
