"""Structural validation for the task files this project ships.

`make validate-playbooks` runs `ansible-playbook --syntax-check`, which parses a
playbook and any statically imported content. It does not parse a file reached
through `include_tasks`: a dynamic include is resolved at run time, so the
included file's structure is not checked until it executes on a host. The
`vm-setup` role reaches every one of its task files that way, which leaves the
bulk of the role unparsed by the project's own validation.

These checks close that gap without needing Ansible installed. They are
deliberately structural rather than semantic — a task is a mapping, it names
itself, it invokes exactly one module, and its keywords are real keywords. That
catches the class of defect a YAML parser cannot see and a syntax check never
reaches: a misspelled `whn:`, two modules in one task, a task that is a bare
string, a `when` accidentally nested under the module.

Semantic correctness of the shell inside those tasks is covered by
`test_passthrough_audit.py`, which runs it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / "ansible"

# Task-level keywords. A key that is neither one of these nor `block`/`rescue`/
# `always` is taken to be the module the task invokes.
TASK_KEYWORDS = {
    "always_run", "any_errors_fatal", "args", "async", "become", "become_exe",
    "become_flags", "become_method", "become_user", "changed_when",
    "check_mode", "collections", "connection", "debugger", "delay",
    "delegate_facts", "delegate_to", "diff", "environment", "failed_when",
    "ignore_errors", "ignore_unreachable", "local_action", "loop",
    "loop_control", "module_defaults", "name", "no_log", "notify", "poll",
    "port", "register", "remote_user", "retries", "run_once", "tags",
    "throttle", "timeout", "until", "vars", "when", "with_dict", "with_fileglob",
    "with_first_found", "with_flattened", "with_items", "with_list",
    "with_nested", "with_random_choice", "with_sequence", "with_subelements",
    "with_together",
}

BLOCK_KEYWORDS = {"block", "rescue", "always"}


def task_files() -> list[Path]:
    files = []
    for role in sorted((ANSIBLE / "roles").iterdir()):
        tasks = role / "tasks"
        if not tasks.is_dir() or "backup" in role.parts:
            continue
        files.extend(sorted(p for p in tasks.rglob("*.yml") if "backup" not in p.parts))
    return files


def walk(tasks: list, path: Path, findings: list[str], where: str = "") -> None:
    for index, task in enumerate(tasks):
        label = f"{path.relative_to(ROOT)}{where}[{index}]"

        if not isinstance(task, dict):
            findings.append(f"{label}: task is {type(task).__name__}, not a mapping")
            continue

        keys = set(task)

        if keys & BLOCK_KEYWORDS:
            for section in sorted(keys & BLOCK_KEYWORDS):
                nested = task[section]
                if not isinstance(nested, list):
                    findings.append(f"{label}: '{section}' is not a list of tasks")
                    continue
                walk(nested, path, findings, f"{where}[{index}].{section}")
            continue

        if "name" not in task:
            findings.append(f"{label}: task has no name")

        modules = sorted(keys - TASK_KEYWORDS)
        if len(modules) == 0:
            findings.append(f"{label}: task invokes no module")
        elif len(modules) > 1:
            findings.append(f"{label}: task invokes several modules: {modules}")


class TestTaskFileStructure(unittest.TestCase):
    def test_every_task_file_parses_as_a_list_of_tasks(self) -> None:
        findings = []
        for path in task_files():
            try:
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as error:
                findings.append(f"{path.relative_to(ROOT)}: {error}")
                continue
            if document is None:
                continue
            if not isinstance(document, list):
                findings.append(
                    f"{path.relative_to(ROOT)}: top level is "
                    f"{type(document).__name__}, not a list"
                )
        self.assertEqual(findings, [])

    def test_every_task_names_itself_and_one_module(self) -> None:
        findings: list[str] = []
        for path in task_files():
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(document, list):
                walk(document, path, findings)
        self.assertEqual(findings, [])

    def test_the_task_files_this_role_reaches_are_all_present(self) -> None:
        """A dynamic include naming a missing file fails only at run time."""
        main = ANSIBLE / "roles/vm-setup/tasks/main.yml"
        document = yaml.safe_load(main.read_text(encoding="utf-8"))
        missing = []
        for task in document:
            if not isinstance(task, dict):
                continue
            for key in ("include_tasks", "import_tasks"):
                spec = task.get(key)
                if spec is None:
                    continue
                name = spec if isinstance(spec, str) else spec.get("file")
                if name and not (main.parent / name).exists():
                    missing.append(name)
        self.assertEqual(missing, [])


class TestPlaybookStructure(unittest.TestCase):
    def test_every_playbook_parses_as_a_list_of_plays(self) -> None:
        findings = []
        for path in sorted((ANSIBLE / "playbooks").rglob("*.yaml")):
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(document, list):
                findings.append(f"{path.relative_to(ROOT)}: top level is not a list")
                continue
            for play in document:
                if not isinstance(play, dict) or "hosts" not in play:
                    findings.append(f"{path.relative_to(ROOT)}: play has no hosts")
        self.assertEqual(findings, [])

    def test_audit_playbook_imports_statically(self) -> None:
        """So that --syntax-check reaches the task file rather than stopping.

        The audit is the one playbook whose whole content is a task file; a
        dynamic include here would leave it entirely uncovered by the project's
        own validation.
        """
        path = ANSIBLE / "playbooks/host-kit/passthrough-audit.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks = document[0]["tasks"]
        self.assertTrue(any("import_tasks" in task for task in tasks))
        self.assertFalse(any("include_tasks" in task for task in tasks))

    def test_audit_playbook_writes_nothing(self) -> None:
        """The audit runs against hardware nothing else has touched.

        Its value depends on being safe to run before any decision is made, so
        the modules it reaches must all be read-only.
        """
        # `shell` is not listed: the audit's core is a shell task, and a shell
        # task can obviously mutate. Its read-only-ness is enforced instead by
        # running it against a fixture tree in test_passthrough_audit.py, which
        # is a stronger check than any name-based one. This test covers the
        # modules whose names alone settle the question.
        mutating = {
            "copy", "template", "file", "lineinfile", "blockinfile", "replace",
            "systemd", "service", "reboot", "apt", "package", "user",
            "authorized_key", "get_url", "unarchive", "command",
        }
        path = ANSIBLE / "roles/vm-setup/tasks/passthrough-audit.yml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        offenders = []
        for task in document:
            for module in set(task) - TASK_KEYWORDS:
                if module in mutating:
                    offenders.append(f"{task.get('name')}: {module}")
        self.assertEqual(offenders, [])

    def test_audit_shell_task_is_marked_unchanging(self) -> None:
        """A read-only shell task must not report itself as a change."""
        path = ANSIBLE / "roles/vm-setup/tasks/passthrough-audit.yml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for task in document:
            if "shell" in task:
                self.assertEqual(task.get("changed_when"), False, task.get("name"))


class TestPassthroughSequencing(unittest.TestCase):
    """Binding must never be reachable from a boot nobody is watching.

    The safety claim of this role is that a wrong bind list costs a GPU, not a
    machine. That holds only while three things are true together: the boot
    configuration phase binds nothing, the bind unit is enabled only after a
    verified live apply, and the apply happens after the reboot rather than
    before it. Each is cheap to break by moving one task, so each is asserted.
    """

    def _tasks(self, name: str) -> list:
        path = ANSIBLE / "roles/vm-setup/tasks" / name
        return yaml.safe_load(path.read_text(encoding="utf-8")) or []

    def _modules(self, task: dict) -> set:
        return set(task) - TASK_KEYWORDS

    def test_boot_configuration_phase_binds_nothing(self) -> None:
        """gpu-passthrough.yml prepares the boot; it must not claim a device."""
        for task in self._tasks("gpu-passthrough.yml"):
            for module in self._modules(task):
                if module != "systemd":
                    continue
                spec = task[module] or {}
                self.assertNotIn(
                    "state", spec,
                    f"{task.get('name')!r} starts a unit during boot configuration",
                )
                self.assertNotEqual(
                    spec.get("enabled"), True,
                    f"{task.get('name')!r} enables the bind unit before any verified apply",
                )

    def test_boot_configuration_phase_writes_no_bind_list(self) -> None:
        source = (ANSIBLE / "roles/vm-setup/tasks/gpu-passthrough.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("vfio_bind_state_path }}\n", source.replace(" ", ""))
        self.assertNotIn("bind_addresses", source)

    def test_binding_is_applied_before_it_is_enabled(self) -> None:
        tasks = self._tasks("gpu-bind.yml")
        names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
        applied = next(i for i, n in enumerate(names) if "Apply the vfio bindings" in n)
        verified = next(i for i, n in enumerate(names) if "Confirm every audited device" in n)
        enabled = next(i for i, n in enumerate(names) if "Enable the vfio bind service" in n)
        self.assertLess(applied, verified, "binding is enabled before it is verified")
        self.assertLess(verified, enabled, "the unit is enabled before verification")

    def test_the_bind_phase_refuses_host_critical_addresses(self) -> None:
        """A second guard, so one classifier defect cannot strand a host."""
        tasks = self._tasks("gpu-bind.yml")
        asserts = [t for t in tasks if isinstance(t, dict) and "assert" in t]
        self.assertTrue(asserts, "gpu-bind.yml has no pre-bind assertion")
        conditions = " ".join(
            " ".join(a["assert"].get("that", [])) for a in asserts
        )
        self.assertIn("route_device", conditions)
        self.assertIn("root_device", conditions)

    def test_the_bind_phase_runs_after_the_reboot(self) -> None:
        tasks = self._tasks("main.yml")
        names = []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            spec = task.get("include_tasks")
            included = spec if isinstance(spec, str) else (spec or {}).get("file", "")
            names.append(("reboot" if "reboot" in task else included) or "")
        reboot = names.index("reboot")
        bind = names.index("gpu-bind.yml")
        self.assertLess(reboot, bind, "gpu-bind.yml runs before the IOMMU reboot")

    def test_the_bind_unit_is_not_ordered_after_the_target_that_wants_it(self) -> None:
        raw = (
            ANSIBLE / "roles/vm-setup/templates/vfio-bind.service.j2"
        ).read_text(encoding="utf-8")
        # Directive lines only: the unit's comments name the dependency types
        # it deliberately omits, and a whole-file search matches that prose.
        unit = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("#")
        )
        self.assertNotIn("After=multi-user.target", unit)
        self.assertIn("WantedBy=multi-user.target", unit)
        self.assertIn("Before=libvirtd.service", unit)
        for hard in ("Requires=", "BindsTo="):
            self.assertNotIn(hard, unit)

    def test_host_gpu_drivers_are_blacklisted_only_when_every_gpu_is_bound(self) -> None:
        """Blacklisting is per-module, so it cannot be scoped to one card.

        Applying it while the audit deliberately left a GPU on its own driver
        would strand that card for the host too.
        """
        source = (ANSIBLE / "roles/vm-setup/tasks/gpu-passthrough.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("blacklist_host_gpu_drivers", source)
        self.assertIn("rejectattr('bindable') | list | length) == 0", source)


if __name__ == "__main__":
    unittest.main()
