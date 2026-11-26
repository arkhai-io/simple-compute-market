"""Records each failed or unreachable task of a playbook run as one JSON line.

The provisioning service's runner puts this directory on Ansible's callback
plugin path for every playbook it starts, through ``ANSIBLE_CALLBACK_PLUGINS``,
and names the file in ``ARKHAI_FAILURE_RECORDS_PATH``. The callback is not a
stdout callback and needs no enabling, so it runs beside whatever stdout
callback and enabled callbacks an operator's own configuration names. A
playbook run by hand, without that variable, records nothing.

The runner creates the file, owner-only, before the playbook starts; this
callback only appends to it and never creates it, so a file the runner has
removed stays removed. A record's message and output are bounded, since the
whole output is already kept as the job's logs: the message keeps its start,
the output its end, where a failing command reports what failed.

Only the standard library and Ansible are imported: Ansible loads this file by
path, in its own interpreter. The distribution declares that import as its
``ansible`` extra.
"""

from __future__ import annotations

import json
import os

from ansible.plugins.callback import CallbackBase

DOCUMENTATION = """
    name: arkhai_failure_records
    type: notification
    short_description: Record failed and unreachable tasks for the provisioning service
    description:
      - Appends one JSON line per failed or unreachable task to the file named by
        ARKHAI_FAILURE_RECORDS_PATH. Records nothing when the variable is unset.
"""

#: The most characters of a task's ``msg``, ``stdout`` or ``stderr`` a record keeps.
_OUTPUT_LIMIT = 8192


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "notification"
    CALLBACK_NAME = "arkhai_failure_records"
    CALLBACK_NEEDS_ENABLED = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._path = os.environ.get("ARKHAI_FAILURE_RECORDS_PATH") or None
        self._play = None

    def v2_playbook_on_play_start(self, play):
        self._play = play.get_name()

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._record(result, unreachable=False, ignored=bool(ignore_errors))

    def v2_runner_on_unreachable(self, result):
        task = result._task
        self._record(
            result,
            unreachable=True,
            ignored=bool(getattr(task, "ignore_unreachable", False)),
        )

    def _record(self, result, *, unreachable, ignored):
        if self._path is None:
            return
        task = result._task
        values = result._result if isinstance(result._result, dict) else {}
        role = getattr(task, "_role", None)
        rc = values.get("rc")
        record = {
            "host": result._host.get_name(),
            "play": self._play,
            "role": role.get_name(include_role_fqcn=False) if role is not None else None,
            # The task's own name, its role recorded apart; an unnamed task
            # is named by its action.
            "task": task.name or task.get_name(include_role_fqcn=False),
            "tags": [str(tag) for tag in (task.tags or [])],
            "module": _module(task),
            "rc": rc if isinstance(rc, int) and not isinstance(rc, bool) else None,
            # A result under ``no_log`` carries no ``msg``, only Ansible's
            # notice that it was censored.
            "msg": _bounded(values.get("msg") or values.get("censored")),
            "stdout": _bounded(values.get("stdout"), tail=True),
            "stderr": _bounded(values.get("stderr"), tail=True),
            "unreachable": unreachable,
            "ignored": ignored,
            "rescued": not ignored and not unreachable and _rescued(task),
        }
        line = (json.dumps(record, default=str) + "\n").encode("utf-8")
        try:
            descriptor = os.open(self._path, os.O_WRONLY | os.O_APPEND)
        except OSError:
            # The runner has removed the file, or never created it: nothing is
            # waiting for this run's records.
            return
        try:
            os.write(descriptor, line)
        finally:
            os.close(descriptor)


def _module(task):
    """The module the task ran, resolved to its full name where Ansible has it."""
    resolved = getattr(task, "_resolved_action", None)
    return str(resolved or task.action or "") or None


def _bounded(value, tail=False):
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= _OUTPUT_LIMIT:
        return text
    return "…" + text[-_OUTPUT_LIMIT:] if tail else text[:_OUTPUT_LIMIT] + "…"


def _rescued(task):
    """Whether a ``block`` enclosing the task will rescue its failure.

    Walks up from the task through its enclosing blocks and includes: a failure
    is rescued when it sits in the ``block`` section of a block that has a
    ``rescue``. Membership is judged by Ansible's object identity, ``_uuid``,
    which survives the copies Ansible makes of a play's blocks. An enclosing
    block Ansible copied without its task lists reads as having no rescue, so
    a failure only such a block rescues is recorded as not rescued.
    """
    child = task
    parent = getattr(task, "_parent", None)
    while parent is not None:
        rescue = getattr(parent, "rescue", None)
        block = getattr(parent, "block", None)
        if rescue and block and any(
            getattr(item, "_uuid", None) == child._uuid for item in block
        ):
            return True
        child = parent
        parent = getattr(parent, "_parent", None)
    return False
