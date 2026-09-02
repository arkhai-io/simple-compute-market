from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "ansible/roles/vm-management/tasks"
MAIN = TASKS / "main.yml"
PREREQUISITES = TASKS / "prerequisites.yml"
VM_CREATE = TASKS / "vm-create.yml"
VM_DESTROY = TASKS / "vm-destroy.yml"
VM_UNDEFINE = TASKS / "vm-undefine.yml"
JSON_OUTPUT = TASKS / "json-output.yml"


def _directives(text: str) -> str:
    """Non-comment lines only.

    An assertion that scans a whole file can be satisfied by its own comments:
    these tasks explain at length which mechanism they deliberately avoid, so a
    check for the absence of that mechanism must not read the explanation.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class VmManagementContractTests(unittest.TestCase):
    def test_main_orchestrates_prerequisites_actions_and_json_output(self) -> None:
        text = _read(MAIN)

        prerequisites_idx = text.index("Include prerequisites and validation")
        create_idx = text.index("Include VM create tasks")
        destroy_idx = text.index("Include VM destroy tasks")
        undefine_idx = text.index("Include VM undefine tasks")
        json_output_idx = text.index("Include JSON output formatting")

        self.assertLess(prerequisites_idx, create_idx)
        self.assertLess(create_idx, destroy_idx)
        self.assertLess(destroy_idx, undefine_idx)
        self.assertLess(undefine_idx, json_output_idx)
        self.assertIn("when: vm_action == \"create\"", text)
        self.assertIn("when: vm_action == \"destroy\"", text)
        self.assertIn("when: vm_action == \"undefine\"", text)
        self.assertIn("file: prerequisites.yml", text)
        self.assertIn("file: json-output.yml", text)

    def test_prerequisites_fail_fast_if_vm_already_exists(self) -> None:
        text = _read(PREREQUISITES)

        self.assertIn("Check if VM already exists (single-tenant mode)", text)
        self.assertIn("Fail if VM already exists", text)
        self.assertIn("vm_exists_check.rc == 0", text)
        self.assertIn(
            "VM '{{ vm_name }}' already exists on host '{{ target_host }}'. "
            "Use a different name or remove the existing VM first.",
            text,
        )

    def test_vm_create_verifies_the_proxy_through_the_local_admin_api(self) -> None:
        """The client that registered the proxy is asked whether it worked.

        Polling the relay's dashboard was a round trip to ask a third party
        about our own state, and it required that every relay run a management
        surface, publish a DNS name for it, hold a certificate, and distribute
        a second credential.
        """
        text = _read(VM_CREATE)
        wait_idx = text.index("Wait for this VM's proxy to come up")
        display_idx = text.index("Report buyer access for this VM")
        wait_block = text[wait_idx:display_idx]

        self.assertIn("http://127.0.0.1:{{ frp_admin_port", wait_block)
        self.assertIn("/api/status", wait_block)
        self.assertIn("'status', 'equalto', 'running'", wait_block)

    def test_vm_create_contacts_no_relay_management_surface(self) -> None:
        """Scanned over directives rather than the whole file: the comments
        explain which mechanism the tasks deliberately avoid, and an assertion
        matching its own explanation proves nothing."""
        directives = _directives(_read(VM_CREATE))

        for absent in (
            "frp-admin",
            "frp_dashboard_password",
            "frp_domain",
            "frp_subdomain",
            "subdomain =",
        ):
            self.assertNotIn(absent, directives)

    def test_vm_create_applies_a_supplied_port_and_selects_none(self) -> None:
        """A remote port binds a listening socket on the relay, so every client
        dialing it draws from one namespace. The playbook writes the stanza it
        is given; the provisioning service is the single authority that can
        avoid collisions and reclaim what it issued."""
        directives = _directives(_read(VM_CREATE))

        self.assertIn("remotePort = {{ vm_remote_port }}", directives)
        self.assertNotIn("seq 7002 8000", directives)

    def test_vm_create_applies_a_proxy_by_reloading(self) -> None:
        """Adding a proxy must never restart the client. A restart closes the
        control connection, so the relay tears down every proxy this client
        registered — ending the established SSH session of every buyer on the
        host, not just the VM being added."""
        text = _read(VM_CREATE)
        start = text.index("- name: Apply the new proxy by reloading")
        end = text.index("- name: Wait for this VM's proxy to come up")
        block = _directives(text[start:end])

        self.assertIn("/api/reload", block)
        self.assertNotIn("state: restarted", block)

    def test_vm_create_restarts_only_to_adopt_a_changed_baseline(self) -> None:
        """The one restart that is correct, and the condition that makes it so.

        A client's rendezvous and credential are not reloadable, so adopting a
        changed one needs a restart. It is safe only because the service
        refuses the changes that cause it while the relay holds leases, so a
        host reaching this task has no proxies of its own to lose — which is
        why the restart is guarded on the baseline having actually changed
        rather than run unconditionally.
        """
        directives = _directives(_read(VM_CREATE))

        self.assertIn("name: frpc-vms", directives)
        self.assertIn("state: restarted", directives)
        self.assertIn("frpc_vms_baseline is changed", directives)
        # The old unit name would be the management tunnel's.
        self.assertNotIn("name: frpc\n", directives)

    def test_vm_create_reconciles_the_baseline_before_writing_a_proxy(self) -> None:
        """Order matters: a proxy registered against a stale rendezvous or
        credential is refused by the relay, and the refusal arrives in a client
        log rather than as a failed task."""
        text = _read(VM_CREATE)

        self.assertLess(
            text.index("- name: Reconcile the VM tunnel client's baseline"),
            text.index("- name: Add this VM's proxy"),
        )

    def test_vm_create_carries_the_resolved_token_to_the_client(self) -> None:
        """The token reaches the host's configuration, not only the job's
        variables. Resolving it at execution and never writing it down leaves
        the host presenting whatever credential it was built with."""
        directives = _directives(_read(VM_CREATE))

        self.assertIn("auth.token = ", directives)
        self.assertIn("{{ frp_auth_token }}", directives)

    def test_vm_create_writes_only_the_vm_facing_client_configuration(self) -> None:
        """The host's own management tunnel is a separate file and unit,
        written when the host was prepared. No VM operation may touch it."""
        directives = _directives(_read(VM_CREATE))

        self.assertIn("/etc/frp/frpc-vms.toml", directives)
        self.assertNotIn("/etc/frp/frpc.toml", directives)

    def test_vm_destroy_emits_force_destroy_json_contract(self) -> None:
        text = _read(VM_DESTROY)

        for token in (
            "virsh destroy {{ vm_name }}",
            "vm_destroy_data:",
            'action: "destroy"',
            "vm_name: \"{{ vm_name }}\"",
            "host: \"{{ target_host }}\"",
            "shutdown_method: \"force\"",
            "operation_initiated:",
            "status: \"{{ 'success' if (destroy_result is defined and destroy_result.rc == 0) else 'failed' }}\"",
            "note: \"VM was forcefully stopped and may lose unsaved data\"",
        ):
            self.assertIn(token, text)

    def test_vm_undefine_requires_stopped_vm_and_cleans_up_access_artifacts(self) -> None:
        text = _read(VM_UNDEFINE)

        for token in (
            "virsh domifaddr {{ vm_name }}",
            "path: /etc/frp/frpc-vms.toml",
            "/api/reload",
            "Fail if VM is running",
            "Cannot undefine VM '{{ vm_name }}' - VM is currently running",
            "iptables -t nat -L PREROUTING -n --line-numbers",
            "iptables -D FORWARD $line",
            "iptables-save > /etc/iptables/rules.v4",
            "iptables-save > /etc/sysconfig/iptables",
            "iptables-save > /etc/iptables.rules",
        ):
            self.assertIn(token, text)

    def test_json_output_exports_create_destroy_and_undefine_payloads(self) -> None:
        text = _read(JSON_OUTPUT)

        for token in (
            'vm_creation_json: "{{ vm_creation_data | to_nice_json }}"',
            'vm_destroy_json: "{{ vm_destroy_data | to_nice_json }}"',
            'vm_undefine_json: "{{ vm_undefine_data | to_nice_json }}"',
            "var: vm_creation_data",
            "var: vm_destroy_data",
            "var: vm_undefine_data",
            'msg: "{{ vm_creation_json }}"',
            'msg: "{{ vm_destroy_json }}"',
            'msg: "{{ vm_undefine_json }}"',
        ):
            self.assertIn(token, text)

    def test_vm_create_protects_every_password_bearing_task_with_no_log(self) -> None:
        """Every task that generates or displays tenant_password/root_password
        in vm-create.yml must be `no_log: true`, matching
        vm-reset-password.yml's existing pattern -- with one deliberate
        exception this test also pins: the password-generating/display
        tasks here are protected, but json-output.yml's own `debug:
        var:`/`debug: msg:` tasks (which also render the credential-bearing
        vm_creation_data/vm_creation_json) MUST NOT gain no_log, since they
        are the literal transport AnsibleService._extract_ansible_json
        parses out of raw stdout -- see ansible_service.py's
        redact_ansible_output docstring.
        """
        text = _read(VM_CREATE)

        task_names = (
            "Generate random password for tenant user",
            "Generate random password for root user",
            "Set root password available for Golden VMs",
            "Create tenant user via SSH connection",
            "Create JSON data structure for VM creation (generated tenant key)",
            "Create JSON data structure for VM creation (provided tenant key)",
        )
        for name in task_names:
            idx = text.index(f"- name: {name}")
            # The task's own block ends at the next "- name:" line (or EOF);
            # no_log must appear somewhere inside that span.
            next_idx = text.find("\n- name:", idx + 1)
            block = text[idx:next_idx] if next_idx != -1 else text[idx:]
            self.assertIn(
                "no_log: true", block,
                f"task {name!r} is missing no_log: true",
            )

        # The two "Display VM creation result" debug messages must not
        # interpolate the raw password inline.
        for name in (
            "Display VM creation result (SSH-ready, generated tenant key)",
            "Display VM creation result (SSH-ready, with provided tenant key)",
        ):
            idx = text.index(f"- name: {name}")
            next_idx = text.find("\n- name:", idx + 1)
            block = text[idx:next_idx] if next_idx != -1 else text[idx:]
            self.assertNotIn("{{ root_password }}", block)
            self.assertNotIn("{{ tenant_password }}", block)

    def test_json_output_transport_tasks_are_not_no_log_protected(self) -> None:
        """The inverse of the previous test: json-output.yml's tasks are a
        deliberate exception and must stay readable by
        AnsibleService._extract_ansible_json's marker search."""
        text = _read(JSON_OUTPUT)
        idx = text.index("- name: Output VM creation data as parsable JSON")
        next_idx = text.find("\n- name:", idx + 1)
        block = text[idx:next_idx] if next_idx != -1 else text[idx:]
        self.assertNotIn("no_log", block)


if __name__ == "__main__":
    unittest.main()
