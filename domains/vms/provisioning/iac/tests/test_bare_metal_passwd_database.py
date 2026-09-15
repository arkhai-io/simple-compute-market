"""The account-database reader certifies absence only from a valid database.

The bare-metal access role proves a deleted account is gone by reading
``/etc/passwd`` itself. That proof is only as good as the parse: a truncated,
corrupted or ambiguous file can omit an account without the account being
gone. These cases feed the role's filter the exact bytes a host could return,
base64-encoded as ``slurp`` delivers them.
"""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

import pytest
from ansible.errors import AnsibleFilterError

FILTER = (
    Path(__file__).resolve().parents[1]
    / "ansible" / "roles" / "bare-metal-access" / "filter_plugins" / "passwd_database.py"
)
_spec = importlib.util.spec_from_file_location("bare_metal_passwd_database", FILTER)
passwd_database = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(passwd_database)

ACCOUNT = "arkhai-70f5f19cca87f7e6"
ROOT = b"root:x:0:0:root:/root:/bin/bash\n"
DAEMON = b"daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"


def _absent(raw: bytes, account: str = ACCOUNT) -> bool:
    return passwd_database.account_absent_from_passwd(
        base64.b64encode(raw).decode("ascii"), account
    )


def test_the_role_can_find_the_filter():
    assert (
        passwd_database.FilterModule().filters()["bare_metal_account_absent_from_passwd"]
        is passwd_database.account_absent_from_passwd
    )


def test_a_valid_database_without_the_account_proves_absence():
    assert _absent(ROOT + DAEMON) is True


def test_a_valid_database_with_the_account_does_not():
    tenant = f"{ACCOUNT}:x:61001:61001::/home/{ACCOUNT}:/bin/bash\n".encode()

    assert _absent(ROOT + tenant + DAEMON) is False


def test_a_prefix_of_the_account_name_is_a_different_account():
    shorter = f"{ACCOUNT[:-1]}:x:61001:61001::/home/x:/bin/bash\n".encode()

    assert _absent(ROOT + shorter) is True


def test_ordinary_distribution_entries_are_valid():
    raw = (
        ROOT
        + DAEMON
        + b"_apt:x:42:65534::/nonexistent:/usr/sbin/nologin\n"
        + b"systemd-network:x:998:998:systemd Network Management:/:/usr/sbin/nologin\n"
        + b"nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"
        + b"toor:x:0:0:second root-uid account:/root:/bin/sh\n"
        + "operator:!:1000:1000:Opérateur,,,:/home/operator:\n".encode("utf-8")
    )

    assert _absent(raw) is True


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"root:\n", id="root-name-only"),
        pytest.param(ROOT + b"arkhai-70f5f19c", id="truncated-tenant-name"),
        pytest.param(ROOT + b"daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nolo", id="no-final-newline"),
        pytest.param(ROOT + DAEMON + DAEMON, id="duplicate-account"),
        pytest.param(ROOT + ROOT, id="duplicate-root"),
        pytest.param(ROOT + b"\xff\xfe:x:1:1::/:/bin/sh\n", id="invalid-utf8"),
        pytest.param(ROOT + b"daemon:x:1:1:caf\xe9:/:/bin/sh\n", id="latin1-gecos"),
        pytest.param(ROOT + b"daemon:x:one:1::/:/bin/sh\n", id="non-numeric-uid"),
        pytest.param(ROOT + b"daemon:x:1:-1::/:/bin/sh\n", id="negative-gid"),
        pytest.param(ROOT + b"daemon:x:01:1::/:/bin/sh\n", id="leading-zero-uid"),
        pytest.param(ROOT + b"daemon:x:4294967295:1::/:/bin/sh\n", id="uid-out-of-range"),
        pytest.param(ROOT + b"daemon:x:1::/:/bin/sh\n", id="missing-field"),
        pytest.param(ROOT + b"daemon:x:1:1::/:/bin/sh:extra\n", id="extra-field"),
        pytest.param(ROOT + b"+::::::\n", id="nis-compat-include"),
        pytest.param(ROOT + b"-daemon::::::\n", id="nis-compat-exclude"),
        pytest.param(ROOT + b" daemon:x:1:1::/:/bin/sh\n", id="leading-space-name"),
        pytest.param(ROOT + b"1234:x:1:1::/:/bin/sh\n", id="numeric-name"),
        pytest.param(ROOT + b":x:1:1::/:/bin/sh\n", id="empty-name"),
        pytest.param(ROOT + b"da\x00emon:x:1:1::/:/bin/sh\n", id="nul-byte"),
        pytest.param(ROOT + b"daemon:x:1:1::/:/bin/sh\r\n", id="carriage-return"),
        pytest.param(ROOT + b"\n" + DAEMON, id="blank-record"),
        pytest.param(b"root:x:1000:0:root:/root:/bin/bash\n", id="root-not-uid-0"),
        pytest.param(b"root:x:0:1000:root:/root:/bin/bash\n", id="root-not-gid-0"),
        pytest.param(DAEMON, id="no-root"),
    ],
)
def test_an_invalid_database_refuses_rather_than_proving_absence(raw):
    with pytest.raises(AnsibleFilterError):
        _absent(raw)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("not base64!", id="not-base64"),
        pytest.param(base64.b64encode(ROOT).decode()[:-2], id="truncated-base64"),
        pytest.param(None, id="missing"),
    ],
)
def test_undecodable_transport_refuses(content):
    with pytest.raises(AnsibleFilterError):
        passwd_database.account_absent_from_passwd(content, ACCOUNT)


@pytest.mark.parametrize("account", ["", "root:", "arkhai tenant", "+arkhai", "1234"])
def test_an_ambiguous_account_name_is_refused(account):
    with pytest.raises(AnsibleFilterError):
        _absent(ROOT + DAEMON, account)
