"""The time file against the real filesystem it is stored on: read on every call,
replaced whole, never read as wall time.

Library integration: the reader and writer through their public API, over files
in a temporary directory, with no double in between.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from injected_time import InvalidTime, TimeFile, TimeFileError


def test_a_reader_sees_each_write_at_its_next_read(tmp_path: Path) -> None:
    writer = TimeFile(tmp_path / "time.json")
    reader = TimeFile(tmp_path / "time.json")

    writer.write(1794821400)
    assert reader.now() == 1794821400
    writer.write(1794822300)
    assert reader.now() == 1794822300
    assert reader.now() == 1794822300


def test_the_file_holds_exactly_the_time_document(tmp_path: Path) -> None:
    TimeFile(tmp_path / "time.json").write(1794821400)

    assert json.loads((tmp_path / "time.json").read_text()) == {"now": 1794821400}


def test_a_time_file_is_an_injected_source(tmp_path: Path) -> None:
    assert TimeFile(tmp_path / "time.json").name == "injected"


@pytest.mark.parametrize("content", [
    "",
    "not json",
    '{"now": "1794821400"}',
    '{"now": 1794821400.5}',
    '{"now": true}',
    '{"now": 1794821400, "extra": 1}',
    "{}",
])
def test_an_invalid_file_raises_naming_its_path(tmp_path: Path, content: str) -> None:
    path = tmp_path / "time.json"
    path.write_text(content)

    with pytest.raises(TimeFileError) as refused:
        TimeFile(path).now()

    assert str(path) in str(refused.value)
    assert refused.value.path == path


def test_a_missing_file_raises_naming_its_path(tmp_path: Path) -> None:
    path = tmp_path / "absent.json"

    with pytest.raises(TimeFileError) as refused:
        TimeFile(path).now()

    assert str(path) in str(refused.value)


def test_an_unreadable_file_raises_naming_its_path(tmp_path: Path) -> None:
    path = tmp_path / "time.json"
    path.mkdir()

    with pytest.raises(TimeFileError) as refused:
        TimeFile(path).now()

    assert str(path) in str(refused.value)


def test_a_reader_mid_read_keeps_the_whole_previous_document(tmp_path: Path) -> None:
    # The writer renames a complete file over the old one rather than writing into
    # it, so a reader that opened the file before a write reads the old document
    # whole, and one that opens it after reads the new one whole.
    time_file = TimeFile(tmp_path / "time.json")
    time_file.write(1794821400)

    with (tmp_path / "time.json").open("rb") as opened_before:
        time_file.write(1794822300)
        assert json.loads(opened_before.read()) == {"now": 1794821400}
    assert time_file.now() == 1794822300


def test_a_write_leaves_nothing_beside_the_file(tmp_path: Path) -> None:
    time_file = TimeFile(tmp_path / "time.json")

    time_file.write(1794821400)
    time_file.write(1794822300)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["time.json"]


def test_an_invalid_instant_leaves_the_file_as_it_was(tmp_path: Path) -> None:
    time_file = TimeFile(tmp_path / "time.json")
    time_file.write(1794821400)

    with pytest.raises(InvalidTime):
        time_file.write(-1)

    assert time_file.now() == 1794821400
    assert sorted(path.name for path in tmp_path.iterdir()) == ["time.json"]


def test_a_failed_write_leaves_the_file_as_it_was_and_nothing_beside_it(tmp_path: Path) -> None:
    # A directory at the target path makes the final rename fail after the
    # temporary file is complete.
    target = tmp_path / "time.json"
    target.mkdir()
    (target / "keep").write_text("")

    with pytest.raises(OSError):
        TimeFile(target).write(1794821400)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["time.json"]
    assert target.is_dir()
