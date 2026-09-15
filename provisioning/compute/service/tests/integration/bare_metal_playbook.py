"""Run the real bare-metal access playbook through the production spawn, isolated.

``AnsibleService.start_playbook`` launches ``ansible-playbook`` from ``PATH``, as
it does in the provisioning image, so every variable, precedence rule and
connection-plugin decision is Ansible's own and every SSH command line is the one
the plugin built. Nothing here reconstructs an SSH command.

What makes a run safe to perform on a developer or CI machine:

* **Client configuration.** OpenSSH resolves ``~`` from the account database,
  not from ``HOME``, so replacing ``HOME`` does not exclude a personal
  ``ssh_config``. The recorder therefore hands the real client an explicit
  fixture-owned ``-F`` configuration, which neutralises agent, identity,
  forwarding, proxy and known-hosts settings that the command line does not
  already fix. System-wide configuration cannot re-enable them: an option
  already set on the command line or in that file wins.
* **Pre-connection validation.** The recorder inspects the effective (first)
  value of every option that decides where the connection goes and what it
  trusts, and refuses before exec unless the destination is an endpoint this
  fixture owns. Hostile options exist only as controlled fixture inputs; they
  never come from the invoking environment.
* **Ansible configuration.** The fixture owns a minimal ``ansible.cfg`` and an
  allowlisted child environment, rather than inheriting the repository's
  configuration and whatever ``ANSIBLE_*`` the invoking shell carries.
* **Process tree.** The production spawn puts the run in its own session, and
  every run ends with that group terminated and verified empty, on success,
  failure, timeout and cancellation alike.

Every module the role can run is a test-only stand-in. If a connection other
than OpenSSH were ever selected — ``local`` included — the stand-ins are what
would run, so nothing on the machine running the test is read or changed.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import ansible

from vm_provisioning_adapter.services import ansible_service as ansible_service_module
from vm_provisioning_adapter.services.ansible_service import (
    AnsibleError,
    AnsibleService,
    SshHostTrust,
)

REPO = Path(__file__).resolve().parents[5]
IAC_ANSIBLE = REPO / "domains" / "vms" / "provisioning" / "iac" / "ansible"
PLAYBOOK = IAC_ANSIBLE / "playbooks" / "bare-metal" / "node-access.yaml"
ADAPTER_SOURCE = (
    REPO / "domains" / "vms" / "provisioning" / "adapter" / "src"
    / "vm_provisioning_adapter" / "services" / "ansible_service.py"
)
INVENTORY_HOST = "bm1"
INVENTORY_ADDRESS = "127.0.0.1"
ACCOUNT = "arkhai-70f5f19cca87f7e6"
PLAYBOOK_TIMEOUT = 180
GROUP_EXIT_TIMEOUT = 10.0
# The ansible-core range the provisioning image installs.
ANSIBLE_RANGE = ((2, 17), (2, 20))
# Before choosing a transport Ansible asks the ssh on PATH whether it supports
# ControlPersist. The probe connects nowhere.
CONTROLPERSIST_PROBE = ["-o", "ControlPersist"]
# Kept out of the child's environment only where the suite itself needs them;
# everything else is removed rather than inherited.
_ALLOWED_ENVIRONMENT = frozenset(
    {"PATH", "HOME", "LC_ALL", "TMPDIR", "PYTEST_CURRENT_TEST", "ACTIVE_PROFILES"}
)

_MODULE_PARAMS = {
    "user": ["name", "group", "shell", "create_home", "state", "password_lock", "remove"],
    "group": ["name", "state"],
    "file": ["path", "owner", "group", "mode", "state"],
    "getent": ["database", "key", "fail_key", "split", "service"],
    "slurp": ["src"],
}
_AUTHORIZED_KEY_PARAMS = ["user", "key", "state", "manage_dir", "comment"]

# Options whose effective value decides where the connection goes or what it
# trusts. Anything not fixed by the production command line is fixed by the
# fixture's own client configuration instead.
_FORBIDDEN_OPTIONS = (
    "ProxyCommand",
    "ProxyJump",
    "LocalCommand",
    "PermitLocalCommand",
    "RemoteCommand",
    "ForwardAgent",
    "ForwardX11",
    "ForwardX11Trusted",
    "LocalForward",
    "RemoteForward",
    "DynamicForward",
    "Tunnel",
    "IdentityAgent",
    "Include",
)

_SSH_CONFIG = """\
# Fixture-owned client configuration, handed to ssh as -F so no personal or
# system setting can supply an agent, an identity, a proxy, a Match hook, a
# forwarding rule or a host key. Options the production command line already
# sets win over this file; this file wins over the system configuration.
Host *
    IdentityAgent none
    IdentitiesOnly yes
    AddKeysToAgent no
    ForwardAgent no
    ForwardX11 no
    ForwardX11Trusted no
    PermitLocalCommand no
    Tunnel no
    ControlMaster no
    ControlPath none
    ProxyCommand none
    ProxyJump none
    StrictHostKeyChecking yes
    UserKnownHostsFile /dev/null
    GlobalKnownHostsFile /dev/null
    KnownHostsCommand /bin/true
    VerifyHostKeyDNS no
    CheckHostIP no
    BatchMode yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    GSSAPIAuthentication no
    HostbasedAuthentication no
    NumberOfPasswordPrompts 0
    ConnectionAttempts 1
"""

_ANSIBLE_CFG = """\
# Fixture-owned, minimal, and not the repository's ansible.cfg: a run must not
# inherit settings that the test did not choose.
[defaults]
# The image default the managed profile has to override. It is an adversarial
# baseline supplied by this fixture, not by the invoking environment.
host_key_checking = False
stdout_callback = default
callback_result_format = json
nocolor = 1
retry_files_enabled = False
interpreter_python = {interpreter}
roles_path = {roles}
library = {library}
collections_path = {collections}
local_tmp = {local_tmp}
log_path = {log_path}

[ssh_connection]
# Also adversarial, also fixture-owned: the enforced extra-vars must beat it.
# Ansible's own defaults are kept and the hostile option added, so a run that
# is not the managed profile still behaves as it does in the image.
ssh_args = -C -o ControlMaster=auto -o ControlPersist=60s -o StrictHostKeyChecking=no
"""

_MODULE_STUB = '''#!/usr/bin/python
import json

from ansible.module_utils.basic import AnsibleModule

KIND = {kind!r}
PARAMS = {params!r}
CALLS = {calls!r}


def main():
    module = AnsibleModule(
        argument_spec={{name: dict(type="raw") for name in PARAMS}},
        supports_check_mode=True,
    )
    with open(CALLS, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({{"module": KIND}}) + "\\n")
    module.exit_json(changed=False)


if __name__ == "__main__":
    main()
'''

# The recorder is the only thing that ever starts the real client. It records
# what Ansible built, validates it against the fixture's own policy, and only
# then execs -- with the fixture configuration prepended.
_RECORDER = '''#!{python}
import json
import os
import sys

RECORD = {record!r}
NAME = {name!r}
POLICY = {policy!r}
SSH_CONFIG = {ssh_config!r}
REAL_SSH = {real_ssh!r}
STALL = {stall!r}
FORBIDDEN = {forbidden!r}


def write(entry):
    with open(RECORD, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\\n")


def first_option(argv, name):
    for index, token in enumerate(argv[:-1]):
        if token == "-o":
            key, _, value = argv[index + 1].partition("=")
            if key.lower() == name.lower():
                return value.strip('"')
    return None


def destination(argv):
    """The positional host, if this invocation is a connection at all."""
    skip_value = {{"-o", "-p", "-l", "-i", "-F", "-b", "-c", "-D", "-E", "-e",
                   "-I", "-J", "-L", "-m", "-O", "-Q", "-R", "-S", "-W", "-w"}}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in skip_value:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return None


def problems(argv):
    policy = json.load(open(POLICY, encoding="utf-8"))
    found = []
    if "-F" in argv:
        found.append("argv already carries -F; the fixture owns that file")
    host = destination(argv)
    if host is None:
        return found  # a capability probe: connects nowhere
    # Always on, whatever the run is testing: a connection may only ever reach
    # an endpoint this fixture created, with identities this fixture wrote.
    if host not in policy["hosts"]:
        found.append("destination %r is not a fixture endpoint" % host)
    hostname = first_option(argv, "HostName")
    if hostname is not None and hostname not in policy["hosts"]:
        found.append("HostName %r is not a fixture endpoint" % hostname)
    port = first_option(argv, "Port")
    if port is None or int(port) not in policy["ports"]:
        found.append("port %r is not a fixture endpoint port" % port)
    # The trust invariants hold only where the run is meant to be enforcing
    # them. A control that must show what happens WITHOUT enforcement still
    # has to satisfy every check above.
    if policy.get("require_trust", True):
        if first_option(argv, "StrictHostKeyChecking") != "yes":
            found.append("host key checking is not strict")
        known_hosts = first_option(argv, "UserKnownHostsFile")
        if known_hosts not in policy["known_hosts"]:
            found.append("UserKnownHostsFile %r is not a fixture pin file" % known_hosts)
        if first_option(argv, "GlobalKnownHostsFile") != "/dev/null":
            found.append("a global known_hosts file is in effect")
        known_hosts_command = first_option(argv, "KnownHostsCommand")
        if known_hosts_command not in (None, "/bin/true"):
            found.append("KnownHostsCommand %r would run" % known_hosts_command)
    for option in FORBIDDEN:
        value = first_option(argv, option)
        if value is not None and value.lower() != "none":
            found.append("%s=%r is in effect" % (option, value))
    for index, token in enumerate(argv[:-1]):
        identity = None
        if token == "-i":
            identity = argv[index + 1]
        elif token == "-o" and argv[index + 1].lower().startswith("identityfile="):
            identity = argv[index + 1].partition("=")[2].strip('"')
        if identity is not None and not os.path.abspath(identity).startswith(policy["root"]):
            found.append("identity %r is outside the fixture" % identity)
    return found


argv = sys.argv[1:]
entry = {{"executable": NAME, "argv": argv}}
refusals = problems(argv)
if refusals:
    entry["action"] = "rejected"
    entry["problems"] = refusals
    write(entry)
    sys.stderr.write("ssh stand-in refused: %s\\n" % "; ".join(refusals))
    # 255 is how a client that could not connect exits, so Ansible treats this
    # as the connection failure it is instead of retrying a "failed command".
    # The recorded verdict, not the exit code, says why it refused.
    sys.exit(255)
if STALL:
    entry["action"] = "stalled"
    write(entry)
    sys.stderr.write("ssh stand-in: holding without connecting\\n")
    os.execv("/bin/sleep", ["/bin/sleep", "600"])
if REAL_SSH is None:
    entry["action"] = "refused"
    write(entry)
    sys.stderr.write("ssh stand-in: no connection is made\\n")
    sys.exit(255)
final = ["-F", SSH_CONFIG] + argv
entry["action"] = "handed-over"
entry["final_argv"] = final
write(entry)
os.execv(REAL_SSH, [REAL_SSH, *final])
'''


def pinned_toolchain() -> dict:
    """Fail unless the Ansible and adapter under test are the intended ones."""
    version = tuple(int(part) for part in ansible.__version__.split(".")[:2])
    if not ANSIBLE_RANGE[0] <= version < ANSIBLE_RANGE[1]:
        raise AssertionError(f"ansible-core {ansible.__version__} is outside {ANSIBLE_RANGE}")
    installed = Path(ansible_service_module.__file__)
    if installed.read_bytes() != ADAPTER_SOURCE.read_bytes():
        raise AssertionError(
            "the installed adapter is not the corrected worktree source; "
            f"rebuild and reinit ({installed})"
        )
    return {"ansible": ansible.__version__, "adapter": str(installed)}


def process_group_members(pgid: int) -> list[int]:
    """PIDs still in *pgid*, read from /proc rather than guessed."""
    members = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            stat = Path(f"/proc/{entry}/stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fields = stat[stat.rfind(")") + 2 :].split()
        if len(fields) >= 3 and fields[2] == str(pgid):
            members.append(int(entry))
    return members


def end_process_group(pgid: int | None) -> list[int]:
    """End the run's own group and return whatever survived it."""
    if pgid is None or pgid == os.getpgrp():
        # Never signal the group this test itself runs in.
        return []
    for number in (signal.SIGTERM, signal.SIGKILL):
        if not process_group_members(pgid):
            return []
        try:
            os.killpg(pgid, number)
        except ProcessLookupError:
            return []
        except PermissionError:
            break
        deadline = time.monotonic() + GROUP_EXIT_TIMEOUT / 2
        while time.monotonic() < deadline:
            if not process_group_members(pgid):
                return []
            time.sleep(0.05)
    return process_group_members(pgid)


@dataclass
class PlaybookRun:
    returncode: int | None
    output: str
    executable_calls: list[dict]
    module_calls: list[str]
    # What production left in the run's group, observed before the fixture's
    # safety cleanup. Assertions belong here: ``survivors`` is what remained
    # after the fixture repaired the leak, so it can only ever report zero.
    production_survivors: list[int] = field(default_factory=list)
    survivors: list[int] = field(default_factory=list)

    def calls(self, executable: str) -> list[list[str]]:
        """Every command line the named executable was started with."""
        return [
            call["argv"] for call in self.executable_calls if call["executable"] == executable
        ]

    def entries(self, executable: str) -> list[dict]:
        return [call for call in self.executable_calls if call["executable"] == executable]

    def connections(self, executable: str) -> list[list[str]]:
        """Command lines the named executable was given to reach the host."""
        return [argv for argv in self.calls(executable) if INVENTORY_ADDRESS in argv]

    def unexplained_calls(self) -> list[dict]:
        """Recorded calls that are neither a connection nor the capability probe."""
        return [
            call
            for call in self.executable_calls
            if INVENTORY_ADDRESS not in call["argv"] and call["argv"] != CONTROLPERSIST_PROBE
        ]


def first_option(argv: list[str], name: str) -> str | None:
    """The value OpenSSH honours for *name*: the first ``-o`` that sets it."""
    for index, token in enumerate(argv[:-1]):
        if token == "-o":
            key, _, value = argv[index + 1].partition("=")
            if key.lower() == name.lower():
                return value.strip('"')
    return None


class BareMetalPlaybook:
    """The node-access playbook, runnable through ``AnsibleService``.

    ``real_ssh`` hands each validated call to that client; ``stall`` holds
    without connecting, for cleanup tests; otherwise every call is refused.
    ``hostile_environment`` adds fixture-owned ``ANSIBLE_*`` values that try to
    select paramiko, swap the ssh executable, relax host-key checking and move
    the control socket.
    """

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch,
        *,
        real_ssh: str | None = None,
        stall: bool = False,
        hostile_environment: bool = False,
    ) -> None:
        self.toolchain = pinned_toolchain()
        self.root = tmp_path / "playbook-run"
        bin_dir = self.root / "bin"
        hostile_dir = self.root / "hostile"
        library = self.root / "library"
        collections = self.root / "collections"
        posix = collections / "ansible_collections" / "ansible" / "posix" / "plugins" / "modules"
        self.home = self.root / "home"
        for directory in (bin_dir, hostile_dir, library, posix, self.home):
            directory.mkdir(parents=True)

        self._executable_record = self.root / "executable-calls.jsonl"
        self._module_record = self.root / "module-calls.jsonl"
        self._cli_record = self.root / "cli-calls.log"
        self.ssh_config = self.root / "ssh_config"
        self.ssh_config.write_text(_SSH_CONFIG, encoding="utf-8")
        self.policy = self.root / "ssh-policy.json"
        self._policy = {
            "hosts": [INVENTORY_ADDRESS],
            "ports": [],
            "known_hosts": [],
            "root": str(tmp_path),
        }
        self._write_policy()

        playbook_cli = bin_dir / "ansible-playbook"
        playbook_cli.write_text(
            "#!/bin/sh\n"
            f'echo started >> "{self._cli_record}"\n'
            f'exec "{sys.executable}" -m ansible.cli.playbook "$@"\n',
            encoding="utf-8",
        )
        playbook_cli.chmod(0o755)
        self._write_recorder(bin_dir / "ssh", "ssh", real_ssh=real_ssh, stall=stall)
        # Named by the hostile inventory and environment, never on PATH: if it
        # records a call, a hostile executable override won.
        self.hostile_executable = hostile_dir / "ssh"
        self._write_recorder(self.hostile_executable, "hostile", real_ssh=None, stall=False)
        self.hostile_known_hosts = hostile_dir / "known_hosts"
        self.hostile_known_hosts.write_text("", encoding="utf-8")
        self.hostile_known_hosts_command = hostile_dir / "known-hosts-command"
        self.hostile_known_hosts_command.write_text(
            f"#!/bin/sh\ncat {self.hostile_known_hosts}\n", encoding="utf-8"
        )
        self.hostile_known_hosts_command.chmod(0o755)

        for kind, params in _MODULE_PARAMS.items():
            (library / f"{kind}.py").write_text(
                _MODULE_STUB.format(kind=kind, params=params, calls=str(self._module_record)),
                encoding="utf-8",
            )
        (posix / "authorized_key.py").write_text(
            _MODULE_STUB.format(
                kind="authorized_key",
                params=_AUTHORIZED_KEY_PARAMS,
                calls=str(self._module_record),
            ),
            encoding="utf-8",
        )

        self.ansible_cfg = self.root / "ansible.cfg"
        self.ansible_cfg.write_text(
            _ANSIBLE_CFG.format(
                interpreter=sys.executable,
                roles=IAC_ANSIBLE / "roles",
                library=library,
                collections=collections,
                local_tmp=self.root / "local-tmp",
                log_path=self.root / "ansible.log",
            ),
            encoding="utf-8",
        )

        # The production spawn copies this process's environment, so the child
        # gets exactly what is allowlisted here and nothing else.
        environment = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(self.home),
            # ansible-core refuses to start without a UTF-8 locale; C.UTF-8
            # keeps its and OpenSSH's diagnostics in their untranslated form.
            "LC_ALL": "C.UTF-8",
            "ANSIBLE_CONFIG": str(self.ansible_cfg),
        }
        self.hostile_environment_names = {
            "ANSIBLE_TRANSPORT": "paramiko",
            "ANSIBLE_SSH_EXECUTABLE": str(self.hostile_executable),
            "ANSIBLE_SSH_ARGS": "-o StrictHostKeyChecking=no",
            "ANSIBLE_HOST_KEY_CHECKING": "False",
            "ANSIBLE_PARAMIKO_HOST_KEY_CHECKING": "False",
            "ANSIBLE_SSH_CONTROL_PATH": str(hostile_dir / "environment-control"),
            "ANSIBLE_SSH_COMMON_ARGS": "-o StrictHostKeyChecking=no",
        }
        if hostile_environment:
            environment.update(self.hostile_environment_names)
        keep = _ALLOWED_ENVIRONMENT | set(environment)
        for name in list(os.environ):
            if name not in keep:
                monkeypatch.delenv(name, raising=False)
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        self._runs = 0

    # fixture-owned policy ----------------------------------------------

    def _write_policy(self) -> None:
        self.policy.write_text(json.dumps(self._policy), encoding="utf-8")

    def allow_endpoint(
        self, port: int, pins: Path | None = None, *, require_trust: bool = True
    ) -> None:
        """Permit the recorder to reach this fixture endpoint with these pins.

        ``require_trust=False`` belongs to the deliberate control run that has
        to show what happens without enforcement. The destination, identity and
        forbidden-option checks still apply; only the assertions about pinned
        trust are relaxed, and only for this fixture's own endpoints.
        """
        self._policy["ports"] = sorted({*self._policy["ports"], int(port)})
        if pins is not None:
            self._policy["known_hosts"] = sorted({*self._policy["known_hosts"], str(pins)})
        self._policy["require_trust"] = require_trust
        self._write_policy()

    def _write_recorder(
        self, path: Path, name: str, *, real_ssh: str | None, stall: bool
    ) -> None:
        path.write_text(
            _RECORDER.format(
                python=sys.executable,
                record=str(self._executable_record),
                name=name,
                policy=str(self.policy),
                ssh_config=str(self.ssh_config),
                real_ssh=real_ssh,
                stall=stall,
                forbidden=_FORBIDDEN_OPTIONS,
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    # inventory ----------------------------------------------------------

    def hostile_vars(self, *, connection: str | None, replace_executables: bool = True) -> str:
        """Inventory host variables that try every route around pinned trust.

        Selecting another connection plugin, the plugin-specific checking
        aliases, replacing the ssh/scp/sftp executables, a pre-set control
        socket, and OpenSSH options adding host-key sources or disabling the
        check. ``replace_executables=False`` leaves the real client in place,
        for a control that must show the remaining options actually connect.
        """
        control = self.root / "hostile" / "control"
        known_hosts = self.hostile_known_hosts
        parts = [] if connection is None else [f"ansible_connection={connection}"]
        parts += [
            "ansible_paramiko_host_key_checking=false",
            "ansible_host_key_checking=false",
            "ansible_ssh_host_key_checking=false",
        ]
        if replace_executables:
            parts += [
                f"ansible_ssh_executable={self.hostile_executable}",
                f"ansible_scp_executable={self.hostile_executable}",
                f"ansible_sftp_executable={self.hostile_executable}",
            ]
        parts += [
            f"ansible_control_path={control}-plugin",
            'ansible_ssh_args="-o StrictHostKeyChecking=no'
            ' -o ControlMaster=auto -o ControlPersist=60s"',
            'ansible_ssh_common_args="-o StrictHostKeyChecking=no'
            f" -o UserKnownHostsFile={known_hosts}"
            f" -o KnownHostsCommand={self.hostile_known_hosts_command}"
            " -o VerifyHostKeyDNS=yes"
            f' -o ControlMaster=auto -o ControlPath={control}-common"',
            f'ansible_ssh_extra_args="-o GlobalKnownHostsFile={known_hosts}"',
        ]
        return " ".join(parts)

    def write_inventory(
        self,
        *,
        port: int,
        host_vars: str = "",
        identity: Path | None = None,
        user: str = "arkhai-harness",
    ) -> Path:
        line = [
            INVENTORY_HOST,
            f"ansible_host={INVENTORY_ADDRESS}",
            f"ansible_port={port}",
            f"ansible_user={user}",
            "ansible_become=false",
            f"ansible_python_interpreter={sys.executable}",
        ]
        if identity is not None:
            line.append(f"ansible_ssh_private_key_file={identity}")
        if host_vars:
            line.append(host_vars)
        inventory = self.root / f"inventory-{self._runs + 1}.ini"
        inventory.write_text("[kvm_hosts]\n" + " ".join(line) + "\n", encoding="utf-8")
        return inventory

    # the run ------------------------------------------------------------

    async def run(
        self,
        inventory: Path,
        host_trust: SshHostTrust | None,
        *,
        timeout: int = PLAYBOOK_TIMEOUT,
    ) -> PlaybookRun:
        """Spawn and await one reclaim run exactly as the job service does."""
        self._runs += 1
        for record in (self._executable_record, self._module_record, self._cli_record):
            record.unlink(missing_ok=True)
        job_vars = self.root / f"job-vars-{self._runs}.yml"
        job_vars.write_text(
            json.dumps(
                {
                    "executor_target": INVENTORY_HOST,
                    "executor_action": "node_reclaim_access",
                    "bare_metal_ssh_user": ACCOUNT,
                    "bare_metal_reclaim_policy": "remove_lease_key",
                    "escrow_uid": "escrow-harness",
                    "physical_host_id": "host-harness",
                }
            ),
            encoding="utf-8",
        )
        service = AnsibleService(MagicMock())
        spawned = None
        group = None
        self.last_group = None
        self.production_survivors = []
        self.survivors = []
        try:
            spawned = service.start_playbook(
                playbook_path=PLAYBOOK,
                inventory_path=inventory,
                extra_vars_path=job_vars,
                limit=INVENTORY_HOST,
                host_trust=host_trust,
            )
            # The production spawn starts a new session, so the run's group id
            # is the playbook's own pid; nothing else can be in it.
            group = spawned.process.pid
            self.last_group = group
            try:
                result = await service.wait_for_playbook(spawned, timeout_seconds=timeout)
                output = result.stdout + result.stderr
            except AnsibleError as failure:
                output = failure.stdout + failure.stderr
        finally:
            # Production's own result, read before the safety cleanup below: a
            # fixture that cleans first can only ever report zero, which would
            # turn a production leak into a passing assertion. A signalled group
            # takes a moment to empty, so allow a bounded settle rather than
            # reading it the instant control returns.
            if group is not None:
                deadline = time.monotonic() + GROUP_EXIT_TIMEOUT / 2
                remaining = process_group_members(group)
                while remaining and time.monotonic() < deadline:
                    time.sleep(0.05)
                    remaining = process_group_members(group)
                self.production_survivors = remaining
            # Unconditional: success, assertion failure, timeout or cancellation.
            # This keeps the machine clean; it is never what an assertion rests on.
            self.survivors = end_process_group(group)
        if not self._cli_record.exists():
            raise AssertionError(
                "the ansible-playbook that ran was not this interpreter's ansible-core; "
                f"output: {output[-2000:]}"
            )
        return PlaybookRun(
            returncode=spawned.process.returncode,
            output=output,
            executable_calls=_read_jsonl(self._executable_record),
            module_calls=[call["module"] for call in _read_jsonl(self._module_record)],
            production_survivors=self.production_survivors,
            survivors=self.survivors,
        )


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
