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

    def test_vm_create_reads_frp_dashboard_from_compressed_response_env(self) -> None:
        text = _read(VM_CREATE)
        wait_idx = text.index("Wait for FRP proxy to appear online in dashboard")
        display_idx = text.index("Display FRP proxy information")
        wait_block = text[wait_idx:display_idx]

        self.assertIn(
            'curl --compressed -fsS -u "admin:{{ frp_dashboard_password }}"',
            wait_block,
        )
        self.assertIn('export FRP_DASHBOARD_RESPONSE="$RESPONSE"', wait_block)
        self.assertIn('json.loads(os.environ["FRP_DASHBOARD_RESPONSE"])', wait_block)
        self.assertIn('proxy.get("status") == "online"', wait_block)
        self.assertNotIn("json.load(sys.stdin)", wait_block)
        self.assertNotIn("| python3 - <<'PY'", wait_block)

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
            "path: /etc/frp/frpc.toml",
            "notify: restart frpc",
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


if __name__ == "__main__":
    unittest.main()
