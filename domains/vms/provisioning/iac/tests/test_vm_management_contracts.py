from pathlib import Path
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

import jinja2
import jinja2.meta
import yaml


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

    def test_vm_create_delegates_the_allocated_guest_proxy_to_the_family(self) -> None:
        tasks = yaml.safe_load(_read(VM_CREATE))
        (proxy,) = [task for task in tasks if task.get("vars", {}).get("relay_proxy_action") == "add"]
        self.assertEqual(proxy["include_role"]["name"], "relay-proxy")
        self.assertEqual(proxy["include_role"]["apply"]["delegate_to"], "{{ target_host }}")
        self.assertIs(proxy["no_log"], True)
        self.assertEqual(proxy["vars"], {
            "relay_proxy_action": "add", "relay_proxy_name": "vm-{{ vm_name }}",
            "relay_proxy_local_ip": "{{ vm_ip }}", "relay_proxy_remote_port": "{{ vm_remote_port }}",
        })
        self.assertIn("frp_server_addr is defined", proxy["when"])
        self.assertNotIn("uri", {key for task in tasks for key in task})

    def test_every_cleanup_script_uses_the_installed_family_library(self) -> None:
        tasks = yaml.safe_load(_read(VM_CREATE))
        installer = next(i for i, task in enumerate(tasks) if task.get("include_role", {}).get("tasks_from") == "helper")
        writer = next(i for i, task in enumerate(tasks) if task["name"] == "Create VM cleanup script on target host")
        self.assertLess(installer, writer)
        content = tasks[writer]["copy"]["content"]
        self.assertIn("source {{ relay_proxy_teardown_library | quote }}", content)
        self.assertIn('"vm-$VM_NAME"', content)
        self.assertNotIn("remove_guest_proxy()", content)

    def test_both_create_fact_variants_report_relay(self) -> None:
        tasks = yaml.safe_load(_read(VM_CREATE))
        facts = [task["set_fact"]["vm_creation_data"] for task in tasks if "vm_creation_data" in task.get("set_fact", {})]
        self.assertEqual(len(facts), 2)
        for fact in facts:
            self.assertIn("relay", fact)
            self.assertNotIn("frp", fact)

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
            "name: relay-proxy",
            "relay_proxy_action: remove",
            'relay_proxy_name: "vm-{{ vm_name }}"',
            "Fail if VM is running",
            "Cannot undefine VM '{{ vm_name }}' - VM is currently running",
            "{{ lookup('file', 'guest_teardown.sh') }}",
            'remove_guest_rules "{{ vm_guest_rule_marker }}"',
            'remove_guest_ufw_rules "{{ vm_guest_rule_marker }}"',
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
        are the literal transport the VM codec's fact extraction parses
        out of raw stdout -- see the Ansible runner's redact_ansible_output
        docstring.
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
        deliberate exception and must stay readable by the VM codec's
        fact extraction."""
        text = _read(JSON_OUTPUT)
        idx = text.index("- name: Output VM creation data as parsable JSON")
        next_idx = text.find("\n- name:", idx + 1)
        block = text[idx:next_idx] if next_idx != -1 else text[idx:]
        self.assertNotIn("no_log", block)


#: `virt-install` as a command word: not part of a file name such as
#: `gpu-virt-install-retry.yml` or of a variable such as `virt_install_success`.
_VIRT_INSTALL = re.compile(r"(?<![\w-])virt-install(?![\w.-])")


class VmCreationRequestsKvmTests(unittest.TestCase):
    """A VM is never created under software emulation."""

    def test_every_virt_install_names_kvm(self) -> None:
        commands = 0
        findings = []
        for path in sorted(TASKS.glob("*.yml")):
            lines = _read(path).splitlines()
            for number, line in enumerate(lines):
                text = line.strip()
                if text.startswith("#") or text.startswith("- name:"):
                    continue
                if not _VIRT_INSTALL.search(text):
                    continue
                commands += 1
                following = lines[number + 1].strip() if number + 1 < len(lines) else ""
                if text != "virt-install \\" or following != "--virt-type kvm \\":
                    findings.append(f"{path.name}:{number + 1}: {text!r}")
        self.assertGreater(commands, 0, "no virt-install command found")
        self.assertEqual(findings, [])

    def test_a_create_refuses_a_host_without_kvm_before_anything_else(self) -> None:
        """Before anything is created for the guest: its first two tasks."""
        tasks = yaml.safe_load(_read(VM_CREATE))
        stat, refusal = tasks[0], tasks[1]
        self.assertEqual(stat["stat"], {"path": "/dev/kvm"})
        self.assertEqual(stat["register"], "kvm_device")
        self.assertEqual(stat["delegate_to"], "{{ target_host }}")
        self.assertIn("KVM is unavailable", refusal["fail"]["msg"])
        self.assertEqual(
            refusal["when"], ['vm_action == "create"', "not kvm_device.stat.exists"]
        )


#: The guest interface every create passes: the role's template, looked up.
GUEST_INTERFACE = "{{ lookup('template', 'guest-interface-args.j2') | trim }}"
GUEST_INTERFACE_TEMPLATE = ROOT / "ansible/roles/vm-management/templates/guest-interface-args.j2"


def _continues(line: str) -> bool:
    """Whether a command's line continues onto the next: it ends with a
    backslash, or with one closed inside a conditional (`\\{% endif %}`), or
    it is a blank line a conditional left."""
    return line == "" or line.endswith("\\") or line.endswith("\\{% endif %}")


def _virt_install_commands() -> list[tuple[str, int, list[str]]]:
    """Every virt-install command in the role's tasks: its file, its line, and
    its lines up to the first that does not continue onto the next."""
    commands = []
    for path in sorted(TASKS.glob("*.yml")):
        lines = _read(path).splitlines()
        for number, line in enumerate(lines):
            text = line.strip()
            if text.startswith("#") or text.startswith("- name:") or not _VIRT_INSTALL.search(text):
                continue
            block = [text]
            index = number
            while _continues(block[-1]) and index + 1 < len(lines):
                index += 1
                block.append(lines[index].strip())
            commands.append((path.name, number + 1, block))
    return commands


class VmGuestInterfaceTests(unittest.TestCase):
    """Every guest's interface is isolated and filtered, a GPU guest's too."""

    def test_every_virt_install_passes_the_one_interface_definition(self) -> None:
        commands = _virt_install_commands()
        self.assertEqual(len(commands), 9)
        findings = []
        for name, number, block in commands:
            interfaces = [line for line in block if line == f"{GUEST_INTERFACE} \\"]
            networks = [line for line in block if "--network" in line or "network=" in line]
            if len(interfaces) != 1 or networks:
                findings.append(f"{name}:{number}: {interfaces} {networks}")
        self.assertEqual(findings, [])
        self.assertTrue(any(
            any(line.startswith("--hostdev") for line in block) for _, _, block in commands
        ), "no GPU create found among the virt-install commands")

    def test_no_task_states_the_default_network_alone(self) -> None:
        offenders = [
            path.name for path in sorted(TASKS.glob("*.yml"))
            if "network=default" in _directives(_read(path))
        ]
        self.assertEqual(offenders, [])

    def _template(self) -> jinja2.Template:
        environment = jinja2.Environment(trim_blocks=True, undefined=jinja2.StrictUndefined)
        return environment.from_string(_read(GUEST_INTERFACE_TEMPLATE))

    def test_the_definition_isolates_the_port_and_filters_it_by_its_leased_address(self) -> None:
        """Rendered as the lookup renders it, and read as the shell reads the
        lines it continues."""
        rendered = self._template().render().strip()
        self.assertEqual(shlex.split(rendered.replace("\\\n", " ")), [
            "--network", "network=default,model=virtio",
            "--xml", "./devices/interface/port/@isolated=yes",
            "--xml", "./devices/interface/filterref/@filter=clean-traffic",
            "--xml", "./devices/interface/filterref/parameter[@name='CTRL_IP_LEARNING']/@value=dhcp",
            "--xml", "./devices/interface/filterref/parameter[@name='DHCPSERVER']/@value=192.168.122.1",
        ])
        self.assertFalse(rendered.endswith("\\"), "the site's own continuation follows it")

    def test_no_variable_can_name_another_interface(self) -> None:
        """An extra variable, such as a pool's extra_vars, overrides every
        variable; the template reads none, so nothing a pool sets changes it."""
        environment = jinja2.Environment()
        parsed = environment.parse(_read(GUEST_INTERFACE_TEMPLATE))
        self.assertEqual(jinja2.meta.find_undeclared_variables(parsed), set())


def _ansible() -> tuple[str | None, str]:
    binary = shutil.which("ansible-playbook")
    if binary is None:
        return None, "native tests require ansible-core 2.17 to 2.19"
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
    if not re.search(r"core 2\.(1[7-9])\.", version.stdout):
        return None, "native tests require ansible-core 2.17 to 2.19"
    return binary, ""


ANSIBLE_PLAYBOOK, UNAVAILABLE = _ansible()


@unittest.skipIf(ANSIBLE_PLAYBOOK is None, UNAVAILABLE)
class VmGuestInterfaceNativeTests(unittest.TestCase):
    """The sites' lookup, rendered by ansible-playbook from a play's templates
    directory, gives the arguments the static case reads: Ansible's template
    lookup strips the comment and keeps the continued lines."""

    def test_the_lookup_renders_the_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "templates").mkdir()
            shutil.copy(GUEST_INTERFACE_TEMPLATE, work / "templates" / GUEST_INTERFACE_TEMPLATE.name)
            output = work / "arguments.txt"
            play = [{
                "hosts": "localhost", "connection": "local", "gather_facts": False,
                "tasks": [{"name": "Render the guest interface", "copy": {
                    "content": GUEST_INTERFACE, "dest": str(output), "mode": "0600"}}],
            }]
            path = work / "play.yml"
            path.write_text(yaml.safe_dump(play, sort_keys=False), encoding="utf-8")
            environment = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
            environment.update(ANSIBLE_NOCOLOR="true", ANSIBLE_LOG_PATH="/dev/null")
            run = subprocess.run(
                [ANSIBLE_PLAYBOOK, "-i", "localhost,", str(path)],
                cwd=work, env=environment, capture_output=True, text=True, timeout=90,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            rendered = output.read_text(encoding="utf-8")
        environment = jinja2.Environment(trim_blocks=True, undefined=jinja2.StrictUndefined)
        expected = environment.from_string(_read(GUEST_INTERFACE_TEMPLATE)).render().strip()
        self.assertEqual(rendered, expected)
        self.assertTrue(rendered.startswith("--network network=default,model=virtio \\\n--xml "))


class VmCreateForwardingTests(unittest.TestCase):
    """A create inserts its forwarding accepts at FORWARD's first position, ahead
    of the host's guest policy jump, so neither may admit a packet a guest
    originates."""

    def test_the_inbound_accept_excludes_the_bridge_and_the_reply_accept_is_established_only(self) -> None:
        tasks = yaml.safe_load(_read(VM_CREATE))
        (task,) = [t for t in tasks if t.get("name") == "Set up iptables port forwarding for SSH"]
        inserts = [line.strip() for line in task["shell"].splitlines()
                   if line.strip().startswith("iptables -I FORWARD")]
        self.assertEqual(len(inserts), 2)
        inbound, reply = sorted(inserts, key=lambda line: "--sport" in line)
        self.assertIn("! -i virbr0", inbound)
        self.assertIn("--dport 22", inbound)
        self.assertIn("--sport 22", reply)
        self.assertIn("-m conntrack --ctstate ESTABLISHED ", reply)


if __name__ == "__main__":
    unittest.main()
