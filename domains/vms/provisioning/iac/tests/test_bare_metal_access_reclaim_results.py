"""Reclaim reports success only for steps Ansible performed and read back.

The real bare-metal node-access playbook and role run under the real
``ansible-playbook`` against a local inventory with privilege escalation
disabled. The modules that would change or read a host (``user``, ``group``,
``file``, ``getent``, ``ansible.posix.authorized_key`` and ``slurp``) are
replaced by test-only stand-ins that return scripted results and record their
calls, so nothing on the machine running the test is modified.

Delete verification reads ``/etc/passwd`` through ``slurp``: the account
database the ``user`` module writes to, not a getent lookup whose unsuccessful
result cannot distinguish an absent account from an unavailable NSS backend.
The ``slurp`` stand-in returns exactly the bytes a test supplies, so malformed,
truncated and undecodable databases reach the role as they would from a host.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

IAC = Path(__file__).resolve().parents[1]
PLAYBOOK = IAC / "ansible" / "playbooks" / "bare-metal" / "node-access.yaml"
ANSIBLE_CFG = IAC / "ansible" / "ansible.cfg"
ACCOUNT = "arkhai-70f5f19cca87f7e6"
# The role's own machine-readable result, printed by its debug task.
RESULT_TASK = "Output node_reclaim_access data as parsable JSON"

_STUB = '''#!/usr/bin/python
import json

from ansible.module_utils.basic import AnsibleModule

KIND = {kind!r}
PARAMS = {params!r}
SCENARIO = {scenario!r}
CALLS = {calls!r}


def _operation(params):
    if KIND == "user":
        if params.get("state") == "absent":
            return "user_delete"
        if params.get("password_lock"):
            return "user_lock"
        return "user_ensure"
    if KIND == "getent":
        return "getent_" + str(params.get("database"))
    return KIND + "_" + str(params.get("state") or "present")


def main():
    module = AnsibleModule(
        argument_spec={{name: dict(type="raw") for name in PARAMS}},
        supports_check_mode=True,
    )
    operation = _operation(module.params)
    with open(CALLS, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({{"operation": operation}}) + "\\n")
    outcome = dict(SCENARIO.get(operation, {{"changed": True}}))
    if outcome.pop("failed", False):
        module.fail_json(**outcome)
    module.exit_json(**outcome)


if __name__ == "__main__":
    main()
'''

# slurp is read-back only: it returns the supplied bytes base64-encoded, exactly
# as the real module transports a file, or fails, per scenario.
_SLURP_STUB = '''#!/usr/bin/python
import json

from ansible.module_utils.basic import AnsibleModule

CONTENT = {content!r}
FAIL = {fail!r}
CALLS = {calls!r}


def main():
    module = AnsibleModule(argument_spec={{"src": dict(type="str")}})
    with open(CALLS, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({{"operation": "slurp"}}) + "\\n")
    if FAIL:
        module.fail_json(msg="/etc/passwd is unreadable")
    module.exit_json(content=CONTENT, source="/etc/passwd", encoding="base64")


if __name__ == "__main__":
    main()
'''

_MODULE_PARAMS = {
    "user": ["name", "group", "shell", "create_home", "state", "password_lock", "remove"],
    "group": ["name", "state"],
    "file": ["path", "owner", "group", "mode", "state"],
    "getent": ["database", "key", "fail_key", "split", "service"],
}
_AUTHORIZED_KEY_PARAMS = ["user", "key", "state", "manage_dir", "comment"]

ROOT = b"root:x:0:0:root:/root:/bin/bash\n"
DAEMON = b"daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
TENANT = f"{ACCOUNT}:x:61001:61001::/home/{ACCOUNT}:/bin/bash\n".encode()
PASSWD_ABSENT = ROOT + DAEMON
PASSWD_PRESENT = ROOT + TENANT


def _shadow(password: str) -> dict:
    return {
        "changed": False,
        "ansible_facts": {"getent_shadow": {ACCOUNT: [password, "20000", "0", "99999", "7", "", "", ""]}},
    }


def _passwd_facts(shell: str | None) -> dict:
    entry = None if shell is None else ["x", "61001", "61001", "", "/nonexistent", shell]
    return {"changed": False, "ansible_facts": {"getent_passwd": {ACCOUNT: entry}}}


LOCKED = {"getent_shadow": _shadow("!$6$synthetic"), "getent_passwd": _passwd_facts("/usr/sbin/nologin")}


def _reclaim(
    tmp_path: Path,
    *,
    policy: str,
    scenario: dict,
    key: str | None = None,
    passwd: bytes = PASSWD_ABSENT,
    slurp_fail: bool = False,
):
    library = tmp_path / "library"
    library.mkdir()
    calls = tmp_path / "calls.jsonl"
    for kind, params in _MODULE_PARAMS.items():
        (library / f"{kind}.py").write_text(
            _STUB.format(kind=kind, params=params, scenario=scenario, calls=str(calls)),
            encoding="utf-8",
        )
    (library / "slurp.py").write_text(
        _SLURP_STUB.format(
            content=base64.b64encode(passwd).decode("ascii"),
            fail=slurp_fail,
            calls=str(calls),
        ),
        encoding="utf-8",
    )
    collections = tmp_path / "collections"
    posix = collections / "ansible_collections" / "ansible" / "posix" / "plugins" / "modules"
    posix.mkdir(parents=True)
    (posix / "authorized_key.py").write_text(
        _STUB.format(
            kind="authorized_key",
            params=_AUTHORIZED_KEY_PARAMS,
            scenario=scenario,
            calls=str(calls),
        ),
        encoding="utf-8",
    )
    inventory = tmp_path / "inventory.ini"
    inventory.write_text(
        "[kvm_hosts]\n"
        f"bm1 ansible_connection=local ansible_become=false"
        f" ansible_python_interpreter={sys.executable}\n",
        encoding="utf-8",
    )
    extra_vars = {
        "executor_target": "bm1",
        "executor_action": "node_reclaim_access",
        "bare_metal_ssh_user": ACCOUNT,
        "bare_metal_reclaim_policy": policy,
        "escrow_uid": "escrow-abc",
        "physical_host_id": "host-1",
    }
    if key is not None:
        extra_vars["bare_metal_ssh_public_key"] = key
    env = {
        **os.environ,
        "ANSIBLE_CONFIG": str(ANSIBLE_CFG),
        "ANSIBLE_LIBRARY": str(library),
        "ANSIBLE_COLLECTIONS_PATH": str(collections),
        "ANSIBLE_STDOUT_CALLBACK": "ansible.builtin.default",
        "ANSIBLE_CALLBACK_RESULT_FORMAT": "json",
        "ANSIBLE_LOG_PATH": str(tmp_path / "ansible.log"),
        "ANSIBLE_LOCAL_TEMP": str(tmp_path / "local-tmp"),
        "ANSIBLE_REMOTE_TEMP": str(tmp_path / "remote-tmp"),
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_RETRY_FILES_ENABLED": "0",
    }
    completed = subprocess.run(
        [
            sys.executable, "-m", "ansible.cli.playbook",
            "-i", str(inventory),
            str(PLAYBOOK),
            "--limit", "bm1",
            "-e", json.dumps(extra_vars),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=tmp_path,
    )
    operations = [
        json.loads(line)["operation"]
        for line in (calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [])
    ]
    return completed, operations, _reclaim_result(completed.stdout)


def _reclaim_result(stdout: str) -> dict | None:
    """Return the reclaim result the role printed, or None if it never did."""
    task_at = stdout.find(f"{RESULT_TASK}]")
    if task_at == -1:
        return None
    marker = "ok: [bm1] => "
    result_at = stdout.find(marker, task_at)
    if result_at == -1:
        return None
    printed, _ = json.JSONDecoder().raw_decode(stdout, result_at + len(marker))
    return printed.get("node_reclaim_access_data")


# --- lock -----------------------------------------------------------------

def test_verified_lock_reports_a_locked_account(tmp_path):
    completed, operations, result = _reclaim(tmp_path, policy="lock_user", scenario=LOCKED)

    assert completed.returncode == 0, completed.stdout[-2000:]
    assert result["status"] == "success"
    assert str(result["account_locked"]) == "True"
    assert {"user_lock", "getent_shadow", "getent_passwd"} <= set(operations)


def test_failed_lock_fails_the_reclaim(tmp_path):
    scenario = {**LOCKED, "user_lock": {"failed": True, "msg": "usermod: user is in use"}}

    completed, _, result = _reclaim(tmp_path, policy="lock_user", scenario=scenario)

    assert completed.returncode != 0
    assert result is None, "a failed lock must never produce a reclaim result"


def test_lock_that_cannot_be_read_back_as_locked_fails_the_reclaim(tmp_path):
    scenario = {**LOCKED, "getent_shadow": _shadow("$6$still-usable")}

    completed, _, result = _reclaim(tmp_path, policy="lock_user", scenario=scenario)

    assert completed.returncode != 0
    assert result is None


# --- delete ---------------------------------------------------------------

def test_verified_delete_reports_a_deleted_account(tmp_path):
    completed, operations, result = _reclaim(
        tmp_path, policy="delete_user", scenario={}, passwd=PASSWD_ABSENT
    )

    assert completed.returncode == 0, completed.stdout[-2000:]
    assert result["status"] == "success"
    assert str(result["account_deleted"]) == "True"
    assert {"user_delete", "slurp"} <= set(operations)


def test_verified_delete_accepts_a_realistic_system_database(tmp_path):
    """Ordinary distribution entries must not be mistaken for corruption."""
    passwd = (
        ROOT
        + DAEMON
        + b"_apt:x:42:65534::/nonexistent:/usr/sbin/nologin\n"
        + b"systemd-network:x:998:998:systemd Network Management:/:/usr/sbin/nologin\n"
        + b"nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"
        + b"operator:!:1000:1000:Operator,,,:/home/operator:\n"
    )

    completed, _, result = _reclaim(tmp_path, policy="delete_user", scenario={}, passwd=passwd)

    assert completed.returncode == 0, completed.stdout[-2000:]
    assert str(result["account_deleted"]) == "True"


def test_failed_delete_fails_the_reclaim(tmp_path):
    scenario = {"user_delete": {"failed": True, "msg": "userdel: user is logged in"}}

    completed, _, result = _reclaim(tmp_path, policy="delete_user", scenario=scenario)

    assert completed.returncode != 0
    assert result is None


def test_delete_that_leaves_the_account_in_passwd_fails_the_reclaim(tmp_path):
    completed, _, result = _reclaim(
        tmp_path, policy="delete_user", scenario={}, passwd=PASSWD_PRESENT
    )

    assert completed.returncode != 0
    assert result is None


def test_delete_with_an_unreadable_account_database_fails_closed(tmp_path):
    """An unreadable /etc/passwd is not proof of absence."""
    completed, _, result = _reclaim(
        tmp_path, policy="delete_user", scenario={}, slurp_fail=True
    )

    assert completed.returncode != 0
    assert result is None


@pytest.mark.parametrize(
    "passwd",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"root:\n", id="root-name-only"),
        pytest.param(ROOT + ACCOUNT[:15].encode(), id="truncated-tenant-name"),
        pytest.param(ROOT + b"daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nolo", id="truncated-final-record"),
        pytest.param(ROOT + DAEMON + DAEMON, id="duplicate-account"),
        pytest.param(ROOT + ROOT, id="duplicate-root"),
        pytest.param(ROOT + b"\xff\xfe:x:1:1::/:/bin/sh\n", id="invalid-utf8-after-root"),
        pytest.param(ROOT + b"daemon:x:one:1::/:/bin/sh\n", id="non-numeric-uid"),
        pytest.param(ROOT + b"daemon:x:1::/:/bin/sh\n", id="missing-field"),
        pytest.param(ROOT + b"daemon:x:1:1::/:/bin/sh:extra\n", id="extra-field"),
        pytest.param(ROOT + b"+::::::\n", id="nis-compat-entry"),
        pytest.param(ROOT + b"da\x00emon:x:1:1::/:/bin/sh\n", id="nul-byte"),
        pytest.param(ROOT + b"\n" + DAEMON, id="blank-record"),
        pytest.param(b"root:x:1000:0:root:/root:/bin/bash\n" + DAEMON, id="root-not-uid-0"),
        pytest.param(DAEMON, id="no-root"),
    ],
)
def test_delete_is_not_certified_from_an_invalid_account_database(tmp_path, passwd):
    """A database that is not complete and unambiguous cannot prove absence.

    The tenant account is absent from every one of these, so a reclaim that
    certified deletion here would be trusting content it could not parse.
    """
    completed, _, result = _reclaim(
        tmp_path, policy="delete_user", scenario={}, passwd=passwd
    )

    assert completed.returncode != 0, completed.stdout[-2000:]
    assert result is None


# --- key revocation -------------------------------------------------------

def test_failed_key_revocation_fails_the_reclaim(tmp_path):
    scenario = {"authorized_key_absent": {"failed": True, "msg": "permission denied"}}

    completed, _, result = _reclaim(
        tmp_path,
        policy="remove_lease_key",
        scenario=scenario,
        key="ssh-ed25519 AAAA synthetic",
    )

    assert completed.returncode != 0
    assert result is None
