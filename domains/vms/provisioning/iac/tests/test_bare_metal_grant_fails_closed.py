"""Grant refuses until the host itself shows the lease environment is ready.

The real bare-metal node-access playbook and role run under the real
``ansible-playbook`` against a local inventory with privilege escalation
disabled. Every module that would change or read a host is replaced by a
test-only stand-in that records its calls, so nothing on the machine running
the test is modified and no privileged operation is performed.

Two properties matter here and neither is about rendering:

* A grant proceeds only when the host shows the lease volume, network
  namespace and runtime view exist. A caller cannot assert readiness: the role
  reads it from the host. While M2.2-2.5 are unimplemented no host supplies
  that state, so grant refuses and issues no receipt.
* The tenant account is never created, adopted or altered on the host. An
  account already present under the lease name stops the grant before any
  mutation.
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
GENERATION = "g-7f3a9c21"

ROOT_LINE = b"root:x:0:0:root:/root:/bin/bash\n"
DAEMON_LINE = b"daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
TENANT_LINE = f"{ACCOUNT}:x:61001:61001::/home/{ACCOUNT}:/bin/bash\n".encode()

# Records every invocation, so "the role never created an account" is a
# statement about what ran, not about what the play said it would do.
_STUB = '''#!/usr/bin/python
import json

from ansible.module_utils.basic import AnsibleModule

KIND = {kind!r}
PARAMS = {params!r}
CALLS = {calls!r}
RESULTS = {results!r}


def main():
    module = AnsibleModule(
        argument_spec={{name: dict(type="raw") for name in PARAMS}},
        supports_check_mode=True,
    )
    with open(CALLS, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({{"module": KIND, "args": {{
            name: module.params.get(name) for name in PARAMS
        }}}}) + "\\n")
    outcome = dict(RESULTS.get(KIND, {{"changed": False}}))
    if outcome.pop("failed", False):
        module.fail_json(**outcome)
    module.exit_json(**outcome)


if __name__ == "__main__":
    main()
'''

_SLURP_STUB = '''#!/usr/bin/python
import json

from ansible.module_utils.basic import AnsibleModule

CONTENT = {content!r}
CALLS = {calls!r}


def main():
    module = AnsibleModule(argument_spec={{"src": dict(type="str")}})
    with open(CALLS, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({{"module": "slurp", "args": {{
            "src": module.params.get("src")
        }}}}) + "\\n")
    module.exit_json(content=CONTENT, source=module.params.get("src"),
                     encoding="base64")


if __name__ == "__main__":
    main()
'''

_MODULE_PARAMS = {
    "user": ["name", "group", "shell", "create_home", "state", "password_lock", "remove"],
    "group": ["name", "state"],
    "file": ["path", "owner", "group", "mode", "state"],
    "getent": ["database", "key", "fail_key", "split", "service"],
    "stat": ["path", "follow", "get_checksum"],
    "command": ["_raw_params", "argv", "chdir", "creates", "removes"],
    "template": ["src", "dest", "owner", "group", "mode"],
    "copy": ["src", "dest", "content", "owner", "group", "mode"],
    "systemd": ["name", "state", "enabled", "daemon_reload", "scope"],
}
_AUTHORIZED_KEY_PARAMS = ["user", "key", "state", "manage_dir", "comment"]

# Modules that would create, adopt or alter a host account.
ACCOUNT_MUTATING = {"user", "group", "authorized_key"}


def _grant(
    tmp_path: Path,
    *,
    passwd: bytes = ROOT_LINE + DAEMON_LINE,
    stat_results: dict | None = None,
    results: dict | None = None,
    extra: dict | None = None,
):
    library = tmp_path / "library"
    library.mkdir()
    calls = tmp_path / "calls.jsonl"
    scripted = dict(results or {})
    # `stat` answers the readiness questions. By default nothing the lease
    # needs exists, which is the state of every host until M2.2-2.5 land.
    scripted.setdefault("stat", stat_results or {"stat": {"exists": False}})
    for kind, params in _MODULE_PARAMS.items():
        (library / f"{kind}.py").write_text(
            _STUB.format(kind=kind, params=params, calls=str(calls), results=scripted),
            encoding="utf-8",
        )
    (library / "slurp.py").write_text(
        _SLURP_STUB.format(
            content=base64.b64encode(passwd).decode("ascii"), calls=str(calls)
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
            calls=str(calls),
            results=scripted,
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
        "executor_action": "node_grant_access",
        "bare_metal_ssh_user": ACCOUNT,
        "bare_metal_ssh_public_key": "ssh-ed25519 AAAAC3Nz synthetic",
        "bare_metal_lease_generation": GENERATION,
        "escrow_uid": "escrow-abc",
        "physical_host_id": "host-1",
    }
    # Highest-precedence input, so anything a caller could claim about
    # readiness arrives with the strongest standing Ansible offers.
    extra_vars.update(extra or {})
    env = {
        **os.environ,
        "ANSIBLE_CONFIG": str(ANSIBLE_CFG),
        "ANSIBLE_LIBRARY": str(library),
        "ANSIBLE_COLLECTIONS_PATH": str(collections),
        "ANSIBLE_STDOUT_CALLBACK": "ansible.builtin.default",
        "ANSIBLE_CALLBACK_RESULT_FORMAT": "json",
        "ANSIBLE_LOG_PATH": str(tmp_path / "ansible.log"),
        "ANSIBLE_LOCAL_TEMP": str(tmp_path / "local-tmp"),
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
    invoked = [
        json.loads(line)
        for line in (calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [])
    ]
    return completed, invoked


def _modules(invoked: list[dict]) -> list[str]:
    return [call["module"] for call in invoked]


# --- readiness ------------------------------------------------------------


def test_grant_refuses_when_the_host_shows_no_lease_environment(tmp_path):
    completed, invoked = _grant(tmp_path)

    assert completed.returncode != 0, completed.stdout[-3000:]
    # The refusal names what is missing rather than failing obscurely.
    assert "lease environment is not ready" in completed.stdout
    assert "node_grant_access_data" not in completed.stdout


def test_a_refused_grant_issues_no_receipt_and_mutates_no_account(tmp_path):
    completed, invoked = _grant(tmp_path)

    assert completed.returncode != 0
    assert not (ACCOUNT_MUTATING & set(_modules(invoked))), (
        f"a refused grant still ran account modules: {_modules(invoked)}"
    )
    assert '"status": "success"' not in completed.stdout


def test_a_caller_cannot_assert_readiness_the_host_does_not_show(tmp_path):
    """A variable claiming the lease is ready does not make it ready.

    Readiness is whatever the host shows, so an input asserting it — however it
    reached the play — changes nothing about the refusal.
    """
    completed, invoked = _grant(
        tmp_path,
        extra={
            "bare_metal_lease_ready": True,
            "bare_metal_lease_prepared": True,
            "bare_metal_lease_volume_ready": True,
        },
    )

    assert completed.returncode != 0, completed.stdout[-3000:]
    assert "lease environment is not ready" in completed.stdout
    assert not (ACCOUNT_MUTATING & set(_modules(invoked)))


# --- no adoption ----------------------------------------------------------


def test_an_existing_host_account_stops_the_grant_before_any_mutation(tmp_path):
    completed, invoked = _grant(
        tmp_path, passwd=ROOT_LINE + TENANT_LINE + DAEMON_LINE
    )

    assert completed.returncode != 0, completed.stdout[-3000:]
    assert "already exists on the host" in completed.stdout
    assert not (ACCOUNT_MUTATING & set(_modules(invoked))), (
        f"the role touched an account it did not create: {_modules(invoked)}"
    )


def test_the_grant_path_never_creates_a_host_account(tmp_path):
    """Even with every readiness answer present, no host account is made.

    The lease's accounts exist only in the generated view, so the managed path
    has no reason to reach the host's user database at all.
    """
    ready = {"stat": {"exists": True, "isdir": True, "pw_name": "root", "mode": "0700"}}
    completed, invoked = _grant(tmp_path, stat_results=ready)

    assert not (ACCOUNT_MUTATING & set(_modules(invoked))), (
        f"the grant path created or altered a host account: {_modules(invoked)}"
    )
    # The earlier version of this test asserted only the absence of account
    # modules, which also holds when the play fails for an unrelated reason.
    # The grant must refuse, and refusing means writing nothing.
    assert completed.returncode != 0, completed.stdout[-3000:]
    assert "template" not in _modules(invoked)


# --- unfinished preparation ----------------------------------------------


def test_every_path_present_still_refuses_and_writes_nothing(tmp_path):
    """Path existence is not preparation, so a complete set of them grants nothing.

    An ordinary or stale directory satisfies an existence check. It proves
    nothing about who owns the mount, whether it is encrypted, whether it
    belongs to this lease generation, or whether the namespace and preflight
    controls are correct. Until a verifier for those exists, the grant refuses
    even when every observation is positive and every write would succeed.
    """
    completed, invoked = _grant(
        tmp_path,
        # Nested under `stat`, which is the shape the module returns and the
        # role reads; a flat dict here would leave `.stat.exists` undefined and
        # the run would refuse at the earlier check for the wrong reason.
        stat_results={"stat": {"exists": True, "isdir": True, "pw_name": "root"}},
        # A template action that would report success if it were ever reached.
        results={"template": {"changed": True}},
    )

    assert completed.returncode != 0, completed.stdout[-3000:]
    assert "preparation is unfinished" in completed.stdout
    # No receipt, by any spelling.
    assert '"status": "success"' not in completed.stdout
    assert "node_grant_access_data" not in completed.stdout
    # No privileged write of any kind was attempted.
    for writer in ("template", "copy", "file", "systemd"):
        assert writer not in _modules(invoked), (
            f"a refused grant performed a {writer} action: {_modules(invoked)}"
        )
    assert not (ACCOUNT_MUTATING & set(_modules(invoked)))


def test_the_refusal_precedes_the_readiness_observations(tmp_path):
    """The gate does not depend on what the observations returned.

    Whether the paths are present or absent, the production path stops at the
    same place, so a future change to those checks cannot accidentally open it.
    """
    present_root = tmp_path / "present"
    present_root.mkdir()
    absent, absent_calls = _grant(tmp_path)
    present, present_calls = _grant(
        present_root,
        stat_results={"stat": {"exists": True, "isdir": True}},
    )

    assert absent.returncode != 0 and present.returncode != 0
    for calls in (absent_calls, present_calls):
        assert "template" not in _modules(calls)


def test_the_role_reads_the_account_database_before_deciding(tmp_path):
    _, invoked = _grant(tmp_path)

    # The no-adoption check is a read of the host's own database, not a guess.
    reads = [call for call in invoked if call["module"] == "slurp"]
    assert reads, "the grant path never read the host account database"
    assert any(call["args"].get("src") == "/etc/passwd" for call in reads)
