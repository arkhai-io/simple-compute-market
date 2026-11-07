"""A tombstone is recognised in any file it can replace, and nowhere else."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("tombstones", SCRIPTS / "tombstones.py")
assert _SPEC and _SPEC.loader
tombstones = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tombstones)

LINE = "# TOMBSTONE: delete this file — moved to its package directory.\n"


def _write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, "utf-8")
    return path


def test_a_comment_format_tombstone_may_wrap(tmp_path):
    wrapped = LINE + "# and a continuation line.\n"

    assert tombstones.is_tombstone(_write(tmp_path / "module.py", wrapped))
    assert tombstones.is_tombstone(_write(tmp_path / "Makefile", LINE))


def test_live_code_after_the_marker_is_not_a_tombstone(tmp_path):
    assert not tombstones.is_tombstone(_write(tmp_path / "module.py", LINE + "x = 1\n"))


def test_a_fenced_example_in_prose_is_not_a_tombstone(tmp_path):
    prose = "Tombstones look like this:\n\n```\n" + LINE + "```\n"

    assert not tombstones.is_tombstone(_write(tmp_path / "guide.md", prose))


def test_a_moved_data_file_or_binary_artifact_is_a_tombstone(tmp_path):
    assert tombstones.is_tombstone(_write(tmp_path / "evidence.schema.json", LINE))
    assert tombstones.is_tombstone(_write(tmp_path / "models" / "seller.pt", LINE))


def test_other_files_admit_only_the_single_line_form(tmp_path):
    wrapped = LINE + "# and a continuation line.\n"

    assert not tombstones.is_tombstone(_write(tmp_path / "a.json", wrapped))
    assert not tombstones.is_tombstone(_write(tmp_path / "b.json", '{"# TOMBSTONE": 1}\n'))
    assert not tombstones.is_tombstone(_write(tmp_path / "c.txt", "# TOMBSTONE: noted\n"))


def test_a_real_binary_file_is_never_a_tombstone(tmp_path):
    binary = b"\x80\x02}q\x00" + LINE.encode() + b"\xff\xfe"

    assert not tombstones.is_tombstone(_write(tmp_path / "model.pt", binary))


def test_prune_finds_moved_artifacts_of_every_kind(tmp_path):
    sys.modules.setdefault("tombstones", tombstones)
    spec = importlib.util.spec_from_file_location("prune_tombstones", SCRIPTS / "prune_tombstones.py")
    assert spec and spec.loader
    prune = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prune)
    for relative in ("src/old_module.py", "src/schema.json", "models/seller.pt"):
        _write(tmp_path / relative, LINE)
    _write(tmp_path / "models" / "buyer.pt", b"\x80\x02real checkpoint\xff")

    found = {path.relative_to(tmp_path).as_posix() for path in prune.find_tombstones(tmp_path)}

    assert found == {"src/old_module.py", "src/schema.json", "models/seller.pt"}
