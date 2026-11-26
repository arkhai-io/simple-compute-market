"""What a playbook run recorded of its failed tasks, and the classes a failure takes.

Every playbook the runner starts runs with the notification callback in
``callback_plugins/``, which appends one JSON line per failed or unreachable
task to a file the runner names for that run. Once the process has ended the
runner reads the file into ``FailureRecord``s and attaches them to the run's
result or error; the executor classifies a failed run from them. A record is
Ansible's own account of a task — its host, play, role, name, tags, module,
return code, message and output — so classification depends on neither the
stdout callback an operator configures nor how it prints results.

A failure class is a string from an open set: the generic classes are this
module's constants, a domain's are its codec's. ``FailureClass`` carries one
with whether a retry could succeed, and what a codec read from the record.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The environment variable naming the file the notification callback appends
#: its records to. The runner creates the file before the playbook starts; the
#: callback only appends, so a file the runner has removed is never recreated.
FAILURE_RECORDS_ENV = "ARKHAI_FAILURE_RECORDS_PATH"

#: The directory holding the notification callback, which the runner puts on
#: Ansible's callback plugin path for every playbook it starts.
CALLBACK_PLUGINS_DIR = Path(__file__).with_name("callback_plugins")

#: The tag prefix a role puts on a task to declare the domain class its failure
#: carries, such as ``failure_class:cleanup_refused``. Ansible never selects
#: tasks by it: the runner passes no ``--tags``.
FAILURE_CLASS_TAG_PREFIX = "failure_class:"

# Generic failure classes. Each is raised by the runner or the executor, never
# by a codec; whether it is retried is the executor's.
#: The playbook ran past the job's timeout.
TIMED_OUT = "timed_out"
#: The run was stopped through its cancellation handle.
CANCELLED = "cancelled"
#: The host stopped answering during the run.
UNREACHABLE = "unreachable"
#: The host refused the SSH login.
AUTHENTICATION_REFUSED = "authentication_refused"
#: A task failed and no domain class applies.
TASK_FAILED = "task_failed"
#: The playbook exited non-zero having recorded no failed task.
PLAYBOOK_ERROR = "playbook_error"
#: The executor refused the host's presented key before anything started.
HOST_KEY_REFUSED = "host_key_refused"


@dataclass(frozen=True)
class FailureRecord:
    """One failed or unreachable task, as the notification callback recorded it.

    ``ignored`` is a failure the task's ``ignore_errors`` (or, for an
    unreachable host, ``ignore_unreachable``) absorbed, and ``rescued`` one a
    ``block``'s ``rescue`` took over; neither failed the run. A result under
    ``no_log`` arrives censored, so its ``msg`` says only that it was hidden.
    """

    host: str
    task: str
    msg: str = ""
    play: str | None = None
    role: str | None = None
    tags: tuple[str, ...] = ()
    module: str | None = None
    rc: int | None = None
    stdout: str = ""
    stderr: str = ""
    unreachable: bool = False
    ignored: bool = False
    rescued: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FailureRecord":
        """A record from its JSON form; a field of the wrong type reads empty."""
        rc = value.get("rc")
        tags = value.get("tags")
        return cls(
            host=_text(value.get("host")),
            task=_text(value.get("task")),
            msg=_text(value.get("msg")),
            play=_text(value.get("play")) or None,
            role=_text(value.get("role")) or None,
            tags=tuple(
                tag for tag in tags if isinstance(tag, str)
            ) if isinstance(tags, (list, tuple)) else (),
            module=_text(value.get("module")) or None,
            rc=rc if isinstance(rc, int) and not isinstance(rc, bool) else None,
            stdout=_text(value.get("stdout")),
            stderr=_text(value.get("stderr")),
            unreachable=value.get("unreachable") is True,
            ignored=value.get("ignored") is True,
            rescued=value.get("rescued") is True,
        )

    def to_mapping(self) -> dict[str, Any]:
        """The record's JSON form, as the callback writes it."""
        return {
            "host": self.host,
            "task": self.task,
            "msg": self.msg,
            "play": self.play,
            "role": self.role,
            "tags": list(self.tags),
            "module": self.module,
            "rc": self.rc,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "unreachable": self.unreachable,
            "ignored": self.ignored,
            "rescued": self.rescued,
        }

    @property
    def failure_classes(self) -> tuple[str, ...]:
        """The domain classes the task's tags declare, in tag order."""
        return tuple(
            tag[len(FAILURE_CLASS_TAG_PREFIX):]
            for tag in self.tags
            if tag.startswith(FAILURE_CLASS_TAG_PREFIX) and len(tag) > len(FAILURE_CLASS_TAG_PREFIX)
        )


@dataclass(frozen=True)
class FailureClass:
    """A failure's class, whether running the job again could succeed, and what
    the codec read from the record.

    ``summary``, when set, replaces the record's ``msg`` in the failure's
    message, and ``detail`` is reported as the failure details'
    ``domain_detail``; both leave the service, redacted.
    """

    code: str
    retryable: bool
    summary: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


#: The class of a task failure no domain class applies to: retried, since a
#: task that failed once may pass on a later attempt.
TASK_FAILED_CLASS = FailureClass(TASK_FAILED, retryable=True)


def last_failure(records: Iterable[FailureRecord]) -> FailureRecord | None:
    """The last record that failed the run: neither ignored nor rescued."""
    deciding = None
    for record in records:
        if not record.ignored and not record.rescued:
            deciding = record
    return deciding


def read_failure_records(path: Path) -> tuple[FailureRecord, ...]:
    """The records in a run's file, in the order they were written.

    A line that is not a JSON object, which a process killed mid-write can
    leave, is skipped and counted in the log. A missing file holds none.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ()
    records: list[FailureRecord] = []
    skipped = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if not isinstance(value, dict):
            skipped += 1
            continue
        records.append(FailureRecord.from_mapping(value))
    if skipped:
        logger.warning("Skipped %d unreadable failure record line(s) in %s", skipped, path)
    return tuple(records)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


__all__ = [
    "AUTHENTICATION_REFUSED",
    "CALLBACK_PLUGINS_DIR",
    "CANCELLED",
    "FAILURE_CLASS_TAG_PREFIX",
    "FAILURE_RECORDS_ENV",
    "FailureClass",
    "FailureRecord",
    "HOST_KEY_REFUSED",
    "PLAYBOOK_ERROR",
    "TASK_FAILED",
    "TASK_FAILED_CLASS",
    "TIMED_OUT",
    "UNREACHABLE",
    "last_failure",
    "read_failure_records",
]
