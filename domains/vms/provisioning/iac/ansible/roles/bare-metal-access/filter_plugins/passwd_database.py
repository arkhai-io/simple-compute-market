"""Authoritative absence of an account from a slurped ``/etc/passwd``.

A deleted account is proven gone by reading the local account database itself.
That proof holds only when the bytes read are a well-formed and unambiguous
database: a corrupted record or a duplicated name can leave an account unlisted
without the account being gone. The whole database is therefore validated before
absence is reported, and anything that does not validate raises instead of
answering, which fails the task.

Scope of the guarantee
----------------------
This establishes that the snapshot read is a *valid authoritative current*
account database that does not contain the account. It cannot establish that the
snapshot is historically complete: a file truncated exactly after a complete
record is indistinguishable from a database that legitimately ends there, so a
syntactically valid root-only snapshot is accepted as valid. Preservation of the
host's other accounts is a property of the reclaim action itself — the role
mutates only the named tenant account — and of the host preservation gates
around it, not of this reader. Do not read a pass here as proof that nothing
else was removed.

This is deliberately not a general NSS reader or an integrity framework. It
accepts only what the local ``files`` database the ``user`` module writes looks
like.
"""

from __future__ import annotations

import base64
import binascii
import re

from ansible.errors import AnsibleFilterError

# Portable name characters only. This excludes NSS compatibility entries
# (``+name``/``-name``), whitespace and separators; purely numeric names are
# rejected separately because they read as a UID.
_ACCOUNT_NAME = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*\$?")
_ID = re.compile(r"0|[1-9][0-9]*")
# (uid_t)-1 means "no id" to the tools that write this file.
_MAX_ID = 4294967294
_FIELDS = 7


def _valid_name(name: str) -> bool:
    return (
        bool(_ACCOUNT_NAME.fullmatch(name))
        and not name.isdigit()
        and name not in (".", "..")
    )


def _parse(data: bytes) -> dict[str, tuple[int, int]]:
    """Map each account name to its (uid, gid), or raise if the file is invalid."""
    if not data:
        raise AnsibleFilterError("account database is empty")
    # Every record is newline-terminated, so a read that stops mid-record is
    # detectable here rather than parsing as a shorter, valid-looking file.
    if not data.endswith(b"\n"):
        raise AnsibleFilterError("account database does not end with a complete record")
    if b"\x00" in data or b"\r" in data:
        raise AnsibleFilterError("account database contains control characters")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise AnsibleFilterError(
            f"account database is not valid UTF-8 at byte {error.start}"
        ) from None

    records: dict[str, tuple[int, int]] = {}
    for number, line in enumerate(text[:-1].split("\n"), start=1):
        fields = line.split(":")
        if len(fields) != _FIELDS:
            raise AnsibleFilterError(
                f"account database record {number} has {len(fields)} fields, not {_FIELDS}"
            )
        name, _password, uid, gid = fields[:4]
        if not _valid_name(name):
            raise AnsibleFilterError(f"account database record {number} has an ambiguous name")
        ids = []
        for value in (uid, gid):
            if not _ID.fullmatch(value) or int(value) > _MAX_ID:
                raise AnsibleFilterError(
                    f"account database record {number} has an invalid numeric id"
                )
            ids.append(int(value))
        if name in records:
            raise AnsibleFilterError(f"account database lists {name!r} more than once")
        records[name] = (ids[0], ids[1])

    if records.get("root") != (0, 0):
        raise AnsibleFilterError("account database has no valid root record")
    return records


def account_absent_from_passwd(content, account) -> bool:
    """Whether *account* is absent from the base64 ``/etc/passwd`` in *content*.

    Raises instead of answering when the account name is ambiguous, or when the
    database cannot be decoded or is not complete and well-formed.
    """
    if not isinstance(account, str) or not _valid_name(account):
        raise AnsibleFilterError("account name is ambiguous")
    if not isinstance(content, str):
        raise AnsibleFilterError("account database was not read")
    try:
        data = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError):
        raise AnsibleFilterError("account database transport is not valid base64") from None
    return account not in _parse(data)


class FilterModule:
    def filters(self):
        return {"bare_metal_account_absent_from_passwd": account_absent_from_passwd}
