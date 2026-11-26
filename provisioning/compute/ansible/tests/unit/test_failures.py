"""Failure records as the runner reads them, and the record that decides a run."""

from __future__ import annotations

import json
import logging

from compute_provisioning_ansible import FailureRecord
from compute_provisioning_ansible.failures import last_failure, read_failure_records


def test_a_record_reads_every_field_the_callback_writes() -> None:
    written = {
        "host": "node-1", "play": "Operate", "role": "access", "task": "Clean up",
        "tags": ["cleanup", "failure_class:cleanup_refused"], "module": "ansible.builtin.command",
        "rc": 1, "msg": "non-zero return code", "stdout": "out", "stderr": "err",
        "unreachable": False, "ignored": False, "rescued": True,
    }

    record = FailureRecord.from_mapping(written)

    assert record.to_mapping() == written
    assert record.failure_classes == ("cleanup_refused",)


def test_a_field_of_the_wrong_type_reads_empty() -> None:
    record = FailureRecord.from_mapping({
        "host": 7, "task": None, "msg": ["x"], "role": 3, "tags": "failure_class:x",
        "rc": True, "unreachable": "yes", "ignored": 1, "rescued": "true",
    })

    assert (record.host, record.task, record.msg, record.role) == ("", "", "", None)
    assert record.tags == ()
    assert record.rc is None
    assert (record.unreachable, record.ignored, record.rescued) == (False, False, False)


def test_a_bare_class_tag_declares_nothing() -> None:
    assert FailureRecord(host="h", task="t", tags=("failure_class:",)).failure_classes == ()


def test_the_records_file_is_read_in_order_skipping_lines_that_are_not_objects(
    tmp_path, caplog
) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(
        json.dumps({"host": "h", "task": "first"}) + "\n"
        "\n"
        "[1, 2]\n"
        '{"host": "h", "task": "cut short\n'
        + json.dumps({"host": "h", "task": "second"}) + "\n"
    )

    with caplog.at_level(logging.WARNING):
        records = read_failure_records(path)

    assert [record.task for record in records] == ["first", "second"]
    assert "Skipped 2 unreadable failure record line(s)" in caplog.text


def test_a_missing_records_file_holds_none(tmp_path) -> None:
    assert read_failure_records(tmp_path / "absent.jsonl") == ()


def test_the_deciding_record_is_the_last_neither_ignored_nor_rescued() -> None:
    first = FailureRecord(host="h", task="first")
    records = (
        first,
        FailureRecord(host="h", task="ignored", ignored=True),
        FailureRecord(host="h", task="rescued", rescued=True),
    )

    assert last_failure(records) is first
    assert last_failure(records[1:]) is None
