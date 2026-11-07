"""Behavioral coverage for the cleanup script's relay teardown block.

`test_vm_management_contracts.py` proves specific text exists in this task's
YAML. It cannot prove the embedded shell behaves, and this is shell that runs
unattended on a rented host: `vm-create.yml` writes
`/usr/local/bin/cleanup_vm_<name>.sh` onto the host, and that script removes
the VM's proxy stanza through the shared family helper and reloads the tunnel
client with `curl`. Addresses and admin passwords here are deterministic
development fixtures and must never be used on a public network.

Two properties matter enough to run the real shell for.

It must touch only the VM-facing client. The host's management tunnel is a
separate file and unit, and it is the path an operator reaches a host through
when `sshd` is unusable — a cleanup script that edited it would remove the
recovery path while recovering nothing.

It must reload rather than restart. A restart closes the tunnel client's
control connection, and the relay tears down every proxy that client
registered, so tearing down one buyer's VM would end the established SSH
sessions of every other buyer on the host.

Neither is observable from YAML: both are properties of which commands the
script runs, and the correctness bug this harness exists for — a corrupted
`continue` that parsed fine and invoked a nonexistent binary — is exactly the
kind a substring assertion reports as present and working.
"""

import os
import tempfile
import unittest
from pathlib import Path

from shell_harness import (
    assert_bash_syntax_valid,
    extract_between,
    fake_binaries,
    run_bash,
)


ROOT = Path(__file__).resolve().parents[1]
VM_CREATE = ROOT / "ansible/roles/vm-management/tasks/vm-create.yml"
# The functions the script includes ahead of this block, as the role includes
# them into it.
LIBRARY = (ROOT / "ansible/roles/vm-management/files/guest_teardown.sh").read_text(
    encoding="utf-8"
)

# The relay-teardown block inside the generated cleanup script. Anchored on
# the log line that opens it and the one that opens the next section, so a
# renamed step fails with "the anchor moved" rather than silently extracting
# nothing.
_BLOCK_START = '      log "=== Removing this VM\'s tunnel proxy ==="\n'
_BLOCK_END = '      log "=== Cleaning up port forwarding rules ==="\n'

# Ansible templating the extracted shell still carries. Substituted with the
# values a real run would render, since bash has no opinion about Jinja.
_SUBSTITUTIONS = {
    "{{ relay_proxy_teardown_library | quote }}": "/usr/local/lib/arkhai-relay/remove_proxy.sh",
    "{{ relay_client_config | quote }}": "/etc/frp/frpc-buyers.toml",
    "{{ vm_relay_required | default(true) | bool | ternary('true', 'false') }}": "true",
}


def _teardown_block() -> str:
    text = VM_CREATE.read_text(encoding="utf-8")
    block = extract_between(text, _BLOCK_START, _BLOCK_END)
    block = _BLOCK_START + block
    # The block is indented six spaces inside the `content:` literal.
    dedented = "\n".join(line[6:] if line.startswith(" " * 6) else line
                         for line in block.splitlines())
    for template, value in _SUBSTITUTIONS.items():
        dedented = dedented.replace(template, value)
    return dedented


_PRELUDE = """
set -eu
VM_NAME="agent-vm-01"
log() { echo "LOG: $1"; }
log_error() { echo "ERR: $1" >&2; }
track_step() { echo "STEP|$1|$2"; }
"""


class CleanupScriptRelayTeardownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.block = _teardown_block()

    def test_the_block_parses(self) -> None:
        """A cheap first pass. The behavioural checks below are the real ones:
        a command that does not exist parses fine."""
        assert_bash_syntax_valid(_PRELUDE + LIBRARY + self.block)

    def _run(self, *, config_exists: bool, reload_ok: bool = True, neighbour: bool = False, relay_required: bool = True):
        curl = (
            "#!/bin/bash\necho \"CURL $@\" >> \"$RECORD\"\nexit 0\n"
            if reload_ok
            else "#!/bin/bash\necho \"CURL $@\" >> \"$RECORD\"\nexit 22\n"
        )
        fakes = {
            "curl": curl,
            # Present so the script cannot silently fall back to restarting a
            # unit: any invocation is recorded and asserted against.
            "systemctl": "#!/bin/bash\necho \"SYSTEMCTL $@\" >> \"$RECORD\"\nexit 0\n",
        }
        with fake_binaries(fakes) as fake_bin:
            workdir = tempfile.mkdtemp()
            record = os.path.join(workdir, "record")
            open(record, "w").close()
            etc = os.path.join(workdir, "etc", "frp")
            os.makedirs(etc)
            vms_conf = os.path.join(etc, "frpc-buyers.toml")
            mgmt_conf = os.path.join(etc, "frpc.toml")
            stanza = (
                "serverAddr = \"203.0.113.9\"\n"
                "# BEGIN ANSIBLE MANAGED RELAY PROXY vm-agent-vm-01\n"
                "[[proxies]]\nname = \"vm-agent-vm-01\"\nremotePort = 6142\n"
                "# END ANSIBLE MANAGED RELAY PROXY vm-agent-vm-01\n"
            )
            stanza = 'webServer.port = 740\nwebServer.password = "' + 'a' * 64 + '"\n' + stanza
            library = Path(workdir) / "remove_proxy.sh"
            family = ROOT.parents[3] / "provisioning/compute/iac/ansible/roles/relay-proxy/files/remove_proxy.sh"
            library.write_text(family.read_text(encoding="utf-8"), encoding="utf-8")
            if neighbour:
                # Another guest, whose name begins with this guest's.
                stanza += (
                    "# BEGIN ANSIBLE MANAGED RELAY PROXY vm-agent-vm-012\n"
                    "[[proxies]]\nname = \"vm-agent-vm-012\"\nremotePort = 6143\n"
                    "# END ANSIBLE MANAGED RELAY PROXY vm-agent-vm-012\n"
                )
            if config_exists:
                Path(vms_conf).write_text(stanza, encoding="utf-8")
            # The management tunnel's file always exists, and must be untouched.
            Path(mgmt_conf).write_text(stanza, encoding="utf-8")

            script = (
                _PRELUDE
                + LIBRARY
                + f'RECORD="{record}"\nexport RECORD\n'
                + self.block.replace("if true; then", "if true; then" if relay_required else "if false; then").replace("/etc/frp/", f"{etc}/").replace("/usr/local/lib/arkhai-relay/remove_proxy.sh", str(library))
            )
            result = run_bash(script, fake_bin_dir=fake_bin)
            calls = Path(record).read_text(encoding="utf-8")
            return result, calls, vms_conf, mgmt_conf

    def test_the_vm_proxy_stanza_is_removed(self) -> None:
        result, _, vms_conf, _ = self._run(config_exists=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        remaining = Path(vms_conf).read_text(encoding="utf-8")
        self.assertNotIn("vm-agent-vm-01", remaining)
        self.assertNotIn("remotePort = 6142", remaining)
        # The client's own top-level configuration survives: only the VM's
        # managed block is this script's business.
        self.assertIn('serverAddr = "203.0.113.9"', remaining)

    def test_a_guest_whose_name_begins_with_this_ones_keeps_its_block(self) -> None:
        """Each block is matched by its exact BEGIN and END lines. A pattern
        this guest's name satisfies also matches every name it begins."""
        result, _, vms_conf, _ = self._run(config_exists=True, neighbour=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        remaining = Path(vms_conf).read_text(encoding="utf-8")
        self.assertNotIn('name = "vm-agent-vm-01"\n', remaining)
        self.assertIn('name = "vm-agent-vm-012"', remaining)
        self.assertIn("# BEGIN ANSIBLE MANAGED RELAY PROXY vm-agent-vm-012\n", remaining)
        self.assertIn("# END ANSIBLE MANAGED RELAY PROXY vm-agent-vm-012\n", remaining)

    def test_the_management_tunnel_configuration_is_untouched(self) -> None:
        """The property that matters most, and the one YAML cannot show."""
        _, calls, _, mgmt_conf = self._run(config_exists=True)

        self.assertIn("vm-agent-vm-01", Path(mgmt_conf).read_text(encoding="utf-8"))
        self.assertNotIn("frpc.toml", calls)

    def test_the_client_is_reloaded_and_never_restarted(self) -> None:
        _, calls, _, _ = self._run(config_exists=True)

        self.assertIn("/api/reload", calls)
        self.assertNotIn("SYSTEMCTL", calls)

    def test_a_failed_reload_fails_the_cleanup(self) -> None:
        """The running client may still hold the proxy and its relay port, so
        the teardown fails and its capacity stays held for a retry."""
        result, _, _, _ = self._run(config_exists=True, reload_ok=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STEP|remove_relay_proxy|failed", result.stdout)
        self.assertNotIn("STEP|remove_relay_proxy|success", result.stdout)

    def test_an_absent_configuration_fails_a_required_relay_cleanup(self) -> None:
        result, calls, _, _ = self._run(config_exists=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("/api/reload", calls)

    def test_an_explicit_direct_job_skips_relay_cleanup(self) -> None:
        result, calls, _, _ = self._run(config_exists=False, relay_required=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STEP|remove_relay_proxy|skipped", result.stdout)
        self.assertNotIn("/api/reload", calls)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
