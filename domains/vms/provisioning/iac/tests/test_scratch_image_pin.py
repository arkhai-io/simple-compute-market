"""The scratch image a VM create boots is pinned, verified, and x86-64 only.

Two kinds of check. The role's structure is read as YAML: the pin is a dated
release, never `current`; the download is checked against the pinned digest;
the verification runs on both the download and the existing-file paths and
directly before the `qemu-img create` that uses the image as a backing file;
and the architecture check precedes every task of the create that changes the
host. The two shell steps that decide, the architecture check and the image
verification, are then run for real through `shell_harness`: `uname` is faked,
and the verification hashes a real file with the real `sha256sum`.

Neither proves a real download or a real guest boot; those are the live VM
lane's evidence.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from shell_harness import assert_bash_syntax_valid, fake_binaries, run_bash


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/vm-management"
VARS = ROLE / "vars/main.yml"
PREREQUISITES = ROLE / "tasks/prerequisites.yml"
VM_CREATE = ROLE / "tasks/vm-create.yml"

ARCH_TASK = "Refuse a scratch create on a host whose architecture has no pinned image"
STAT_TASK = "Check whether the pinned scratch image is already on the host"
DOWNLOAD_TASK = "Download the pinned scratch image"
VERIFY_TASK = "Verify the pinned scratch image before it backs any disk"
DISK_TASK = "Create VM disk image from cloud image"

# Modules that read or decide without changing the host they run against.
READ_ONLY_MODULES = {"set_fact", "debug", "fail", "assert", "stat", "slurp"}
TASK_KEYWORDS = {
    "args", "become", "become_method", "changed_when", "delegate_to",
    "failed_when", "ignore_errors", "name", "no_log", "register", "tags",
    "when", "until", "retries", "delay", "loop", "vars", "environment",
}


def _pin() -> dict:
    return yaml.safe_load(VARS.read_text(encoding="utf-8"))


def _render(value: str, variables: dict) -> str:
    """Substitute `{{ name }}` references, the only templating the pin uses."""
    return re.sub(
        r"\{\{\s*(\w+)\s*\}\}", lambda match: str(variables[match.group(1)]), value
    )


def _tasks(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _named(tasks: list[dict], name: str) -> tuple[int, dict]:
    for index, task in enumerate(tasks):
        if task.get("name") == name:
            return index, task
    raise AssertionError(f"no task named {name!r}")


def _module(task: dict) -> str:
    (module,) = set(task) - TASK_KEYWORDS
    return module


def _shell(task: dict) -> str:
    body = task["shell"]
    return body if isinstance(body, str) else body["cmd"]


def _conditions(task: dict) -> str:
    when = task.get("when", [])
    return " ".join(when if isinstance(when, list) else [when])


class ThePin(unittest.TestCase):
    def test_the_pin_is_one_dated_release_never_current(self) -> None:
        pin = _pin()
        release = pin["vm_scratch_image_release"]
        self.assertRegex(release, r"^\d{8}$")
        url = _render(pin["vm_scratch_image_url"], pin)
        self.assertEqual(
            url,
            f"https://cloud-images.ubuntu.com/noble/{release}/noble-server-cloudimg-amd64.img",
        )
        self.assertNotIn("current", url)

    def test_the_digest_is_a_sha256(self) -> None:
        self.assertRegex(_pin()["vm_scratch_image_sha256"], r"^[0-9a-f]{64}$")

    def test_the_stored_name_carries_the_release(self) -> None:
        """So no image left under another name is ever taken for the pinned one."""
        pin = _pin()
        path = _render(pin["vm_scratch_image_path"], pin)
        self.assertEqual(
            path,
            "/var/lib/libvirt/images/"
            f"noble-server-cloudimg-amd64-{pin['vm_scratch_image_release']}.img",
        )

    def test_only_x86_64_is_pinned(self) -> None:
        self.assertEqual(_pin()["vm_scratch_image_architecture"], "x86_64")

    def test_the_create_names_no_image_but_the_pin(self) -> None:
        directives = "\n".join(
            line
            for line in VM_CREATE.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertNotIn("/current/", directives)
        self.assertNotIn("noble-server-cloudimg-amd64.img", directives)


class TheCreateUsesOnlyAVerifiedImage(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = _tasks(VM_CREATE)

    def test_the_download_lands_at_the_pinned_path_checked_against_the_digest(self) -> None:
        _, download = _named(self.tasks, DOWNLOAD_TASK)
        spec = download["get_url"]
        self.assertEqual(spec["url"], "{{ vm_scratch_image_url }}")
        self.assertEqual(spec["dest"], "{{ vm_scratch_image_path }}")
        self.assertEqual(spec["checksum"], "sha256:{{ vm_scratch_image_sha256 }}")
        self.assertNotIn("force", spec)

    def test_a_file_already_on_the_host_is_never_downloaded_over(self) -> None:
        """get_url replaces a file whose digest differs; the create must fail on
        such a file instead, so the download runs only when none is there."""
        _, stat = _named(self.tasks, STAT_TASK)
        _, download = _named(self.tasks, DOWNLOAD_TASK)
        self.assertEqual(stat["stat"]["path"], "{{ vm_scratch_image_path }}")
        self.assertIn("not ubuntu_image_exists.stat.exists", _conditions(download))

    def test_verification_runs_on_both_paths_directly_before_the_disk(self) -> None:
        stat_index, _ = _named(self.tasks, STAT_TASK)
        download_index, _ = _named(self.tasks, DOWNLOAD_TASK)
        verify_index, verify = _named(self.tasks, VERIFY_TASK)
        disk_index, disk = _named(self.tasks, DISK_TASK)

        self.assertLess(stat_index, download_index)
        self.assertLess(download_index, verify_index)
        self.assertEqual(verify_index + 1, disk_index)
        self.assertNotIn("ubuntu_image_exists", _conditions(verify))
        self.assertEqual(_conditions(verify), _conditions(disk))
        self.assertIn("{{ vm_scratch_image_path }}", _shell(verify))
        self.assertIn("{{ vm_scratch_image_sha256 }}", _shell(verify))
        self.assertIn("-b {{ vm_scratch_image_path }} ", _shell(disk))

    def test_no_disk_or_domain_is_defined_before_verification(self) -> None:
        verify_index, _ = _named(self.tasks, VERIFY_TASK)
        before = yaml.safe_dump(self.tasks[:verify_index])
        for effect in ("qemu-img", "virt-install", "virsh define"):
            self.assertNotIn(effect, before)


class TheArchitectureIsCheckedBeforeAnyHostEffect(unittest.TestCase):
    def test_the_check_precedes_every_task_that_changes_the_host(self) -> None:
        """Prerequisites run before the create's own tasks (main.yml), and the
        check is the first of them that touches the target host at all."""
        tasks = _tasks(PREREQUISITES)
        arch_index, arch = _named(tasks, ARCH_TASK)
        for task in tasks[:arch_index]:
            self.assertIn(_module(task), READ_ONLY_MODULES, task.get("name"))
            self.assertNotIn("delegate_to", task, task.get("name"))
        self.assertEqual(arch["changed_when"], False)
        self.assertEqual(arch["delegate_to"], "{{ target_host }}")
        first_effect = next(
            index
            for index, task in enumerate(tasks)
            if _module(task) not in READ_ONLY_MODULES and task is not arch
            and task.get("changed_when") is not False
        )
        self.assertLess(arch_index, first_effect)

    def test_the_check_applies_to_a_scratch_create_alone(self) -> None:
        _, arch = _named(_tasks(PREREQUISITES), ARCH_TASK)
        conditions = _conditions(arch)
        self.assertIn('vm_action == "create"', conditions)
        self.assertIn('vm_image_type == "scratch"', conditions)


class TheArchitectureCheckShell(unittest.TestCase):
    def _run(self, uname_output: str):
        _, arch = _named(_tasks(PREREQUISITES), ARCH_TASK)
        script = _render(_shell(arch), _pin())
        assert_bash_syntax_valid(script)
        with fake_binaries(
            {"uname": f"#!/bin/sh\nprintf '%s' '{uname_output}'\n"}
        ) as fake_bin:
            return run_bash(script, fake_bin_dir=fake_bin)

    def test_an_x86_64_host_passes(self) -> None:
        result = self._run("x86_64\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "x86_64")

    def test_another_architecture_fails_naming_it(self) -> None:
        result = self._run("aarch64\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("'aarch64'", result.stderr)
        self.assertIn("only x86_64 is pinned", result.stderr)

    def test_an_unreadable_architecture_fails(self) -> None:
        result = self._run("")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("'unknown'", result.stderr)


class TheImageVerificationShell(unittest.TestCase):
    """The real step against a real file: only `{{ ... }}` is substituted."""

    def setUp(self) -> None:
        _, verify = _named(_tasks(VM_CREATE), VERIFY_TASK)
        self.template = _shell(verify)
        self.workdir = Path(tempfile.mkdtemp(prefix="scratch-image-"))
        self.image = self.workdir / "noble-server-cloudimg-amd64-00000000.img"
        # Synthetic bytes, never a real image.
        self.content = b"synthetic scratch image, not a real cloud image\n"

    def _run(self, expected_digest: str):
        script = _render(
            self.template,
            {
                "vm_scratch_image_path": self.image,
                "vm_scratch_image_sha256": expected_digest,
            },
        )
        assert_bash_syntax_valid(script)
        return run_bash(script)

    def test_a_matching_image_is_verified(self) -> None:
        self.image.write_bytes(self.content)
        result = self._run(hashlib.sha256(self.content).hexdigest())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Verified", result.stdout)

    def test_a_mismatching_image_fails_and_is_left_unused(self) -> None:
        self.image.write_bytes(self.content)
        result = self._run("0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(hashlib.sha256(self.content).hexdigest(), result.stderr)
        self.assertIn("not the pinned " + "0" * 64, result.stderr)
        self.assertEqual(self.image.read_bytes(), self.content)

    def test_a_missing_image_fails(self) -> None:
        result = self._run(hashlib.sha256(self.content).hexdigest())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not on the host", result.stderr)


if __name__ == "__main__":
    unittest.main()
