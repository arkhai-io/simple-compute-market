"""The shared tombstone predicate.

Both the manifest audit and the prune utility depend on this, and they diverged
once: one treated a file beginning with the marker as deleted while the other
correctly retained it. A file with a stale tombstone above live code is the case
that distinguishes them, so it is tested directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tombstones import is_tombstone, reason


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_whole_file_tombstone_is_recognised(tmp_path: Path) -> None:
    path = _write(tmp_path, "gone.py", "# TOMBSTONE: delete this file — moved.\n")

    assert is_tombstone(path)


def test_leading_blank_lines_do_not_defeat_it(tmp_path: Path) -> None:
    path = _write(tmp_path, "gone.py", "\n\n# TOMBSTONE: moved.\n")

    assert is_tombstone(path)


def test_a_wrapped_reason_is_recognised(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "gone.py", "# TOMBSTONE: moved because the reason\n# wraps onto a second line.\n"
    )

    assert is_tombstone(path)


def test_a_marker_above_live_code_is_not_a_tombstone(tmp_path: Path) -> None:
    """The case the two checks disagreed on."""
    path = _write(
        tmp_path, "live.py", "# TOMBSTONE: an old reason\n\ndef still_used():\n    return 1\n"
    )

    assert not is_tombstone(path)


def test_a_marker_inside_a_fenced_example_is_not_a_tombstone(tmp_path: Path) -> None:
    """AGENTS.md and the prompt documents both contain one."""
    path = _write(
        tmp_path,
        "convention.md",
        "Represent a deletion like this:\n\n```python\n# TOMBSTONE: delete this file — reason\n```\n",
    )

    assert not is_tombstone(path)


def test_a_file_whose_comment_syntax_differs_is_not_a_tombstone(tmp_path: Path) -> None:
    path = _write(tmp_path, "gone.png", "# TOMBSTONE: binary cannot carry one.\n")

    assert not is_tombstone(path)


def test_an_empty_file_is_not_a_tombstone(tmp_path: Path) -> None:
    assert not is_tombstone(_write(tmp_path, "empty.py", "\n\n"))


@pytest.mark.parametrize("name", ["Makefile", "Dockerfile"])
def test_suffixless_hash_comment_files_qualify(tmp_path: Path, name: str) -> None:
    assert is_tombstone(_write(tmp_path, name, "# TOMBSTONE: moved.\n"))


def test_the_reason_is_extracted_without_the_marker(tmp_path: Path) -> None:
    path = _write(tmp_path, "gone.py", "# TOMBSTONE: delete this file — it moved to elsewhere.\n")

    assert reason(path) == "it moved to elsewhere."


def test_a_wrapped_reason_is_joined(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "gone.py", "# TOMBSTONE: delete this file — first part\n# and second part.\n"
    )

    assert reason(path) == "first part and second part."
