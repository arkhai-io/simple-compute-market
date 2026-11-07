"""Native Ansible installation over an operator-supplied fixture wheel.

The fixture is a small program implementing the check CLI, not the real verifier.
Real pip, virtual environments, hash checks, staged bytes and publication are used.
Only filesystem owner/group are adapted to the disposable caller and no_log is
removed for synthetic values. No account or systemd service is changed. Structure
checks retain the shipped root ownership, unprivileged unit and reload contract.
"""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

import yaml

from test_frp_proxy_wait import ANSIBLE_PLAYBOOK, UNAVAILABLE, _ansible_env

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/relay-server"


def wheel(path, distribution, module, body, *, console=False):
    metadata = distribution + "-0.0.0.dist-info"
    files = {
        module + ".py": body,
        metadata + "/METADATA": "Metadata-Version: 2.1\nName: " + distribution.replace("_", "-") + "\nVersion: 0.0.0\n",
        metadata + "/WHEEL": "Wheel-Version: 1.0\nGenerator: public-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    if console:
        files[metadata + "/entry_points.txt"] = "[console_scripts]\nfrp-grant-admission = " + module + ":main\n"
    files[metadata + "/RECORD"] = "".join(name + ",,\n" for name in files) + metadata + "/RECORD,,\n"
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)


def fixture(work, *, bad_hash=False):
    dependency = work / "fixture_admission_dependency-0.0.0-py3-none-any.whl"
    program = work / "frp_grant_admission-0.0.0-py3-none-any.whl"
    if not dependency.exists():
        wheel(dependency, "fixture_admission_dependency", "fixture_dependency", "PRESENT = True\n")
        wheel(program, "frp_grant_admission", "fixture_admission", '''import sys, tomllib
from fixture_dependency import PRESENT

def main():
    assert PRESENT
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        return 2
    with open(sys.argv[2], "rb") as stream:
        config = tomllib.load(stream)
    if not config.get("valid"):
        return 1
    print("listen " + config.get("listen", "127.0.0.1:7300"))
    return 0
''', console=True)
    digest = "0" * 64 if bad_hash else hashlib.sha256(dependency.read_bytes()).hexdigest()
    requirements = work / "requirements.txt"
    requirements.write_text(f"fixture-admission-dependency @ {dependency.as_uri()} --hash=sha256:{digest}\n")
    return program, requirements


def adapt(document):
    """Keep executable task semantics while isolating fixture ownership/logging."""
    result = copy.deepcopy(document)
    for task in result:
        task.pop("no_log", None)
        for module in ("ansible.builtin.file", "ansible.builtin.copy"):
            if module in task:
                task[module].pop("owner", None)
                task[module].pop("group", None)
        for key in ("block", "rescue", "always"):
            if key in task:
                task[key] = adapt(task[key])
    return result


def run(work, text, *, bad_hash=False, python=None):
    program, requirements = fixture(work, bad_hash=bad_hash)
    config = work / "candidate.toml"
    config.write_text(text)
    active = work / "active"
    active.mkdir(exist_ok=True)
    document = adapt(yaml.safe_load((ROLE / "tasks/plugin-artifacts.yml").read_text()))
    publication = yaml.safe_load((ROLE / "tasks/plugin.yml").read_text())
    selected = [task for task in publication if task["name"] in {
        "Inspect the installed admission configuration", "Check the previous admission listener before replacement",
        "Refuse an in-place admission listener relocation",
        "Publish the checked protected admission configuration", "Select the checked admission program",
    }]
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": {"ansible_python_interpreter": os.sys.executable,
                      "frp_grant_admission_python": python or os.sys.executable,
                      "frp_grant_admission_wheel": str(program),
                      "frp_grant_admission_requirements": str(requirements),
                      "frp_grant_admission_config": str(config),
                      "frp_grant_admission_root": str(work / "install"),
                      "frp_grant_admission_config_directory": str(active)},
             "tasks": document + adapt(selected)}]
    playbook = work / "install.yml"
    playbook.write_text(yaml.safe_dump(play, sort_keys=False))
    return subprocess.run(["/bin/sh", "-c", 'umask 077; exec "$@"', "fixture", ANSIBLE_PLAYBOOK, "-i", "localhost,", str(playbook)], cwd=work,
                          env={**_ansible_env(), "ANSIBLE_NOCOLOR": "true", "PIP_NO_INDEX": "1"},
                          capture_output=True, text=True, check=False, timeout=120)


@unittest.skipIf(ANSIBLE_PLAYBOOK is None, UNAVAILABLE)
class NativeAdmissionInstaller(unittest.TestCase):
    def test_supplied_program_is_installed_and_checked_bytes_are_published(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            initial = 'valid = true\nrevision = "initial"\n'
            first = run(work, initial)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            current = (work / "install/current").resolve()
            self.assertTrue((current / "bin/frp-grant-admission").is_file())
            self.assertEqual((current / "bin").stat().st_mode & 0o055, 0o055)
            self.assertEqual((current / "bin/frp-grant-admission").stat().st_mode & 0o055, 0o055)
            self.assertEqual((work / "active/config.toml").read_text(), initial)
            receipt = (current / ".installed").stat().st_mtime_ns
            changed = 'valid = true\nrevision = "changed"\n'
            second = run(work, changed)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual((work / "install/current").resolve(), current)
            self.assertEqual((current / ".installed").stat().st_mtime_ns, receipt)
            self.assertEqual((work / "active/config.toml").read_text(), changed)

    def test_invalid_candidate_preserves_running_configuration_and_program_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            initial = 'valid = true\nrevision = "initial"\n'
            first = run(work, initial)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            current = (work / "install/current").resolve()
            rejected = run(work, "valid = false\n")
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual((work / "active/config.toml").read_text(), initial)
            self.assertEqual((work / "install/current").resolve(), current)

    def test_bad_dependency_hash_prevents_program_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            rejected = run(work, "valid = true\n", bad_hash=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("HASHES", rejected.stdout + rejected.stderr)
            self.assertFalse((work / "install/current").exists())
            self.assertFalse((work / "active/config.toml").exists())

    def test_python_older_than_311_is_refused_before_workspace_or_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            python = work / "old-python"
            python.write_text("#!/bin/sh\nprintf '3.10\\n'\n")
            python.chmod(0o755)
            rejected = run(work, "valid = true\n", python=str(python))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("3.11 or later", rejected.stdout)
            self.assertFalse((work / "install").exists())

    def test_listener_relocation_preserves_checked_active_config_and_program(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            original = 'valid = true\nlisten = "127.0.0.1:7300"\n'
            first = run(work, original)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            current = (work / "install/current").resolve()
            rejected = run(work, 'valid = true\nlisten = "127.0.0.1:7301"\n')
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("separate drained maintenance", rejected.stdout)
            self.assertEqual((work / "active/config.toml").read_text(), original)
            self.assertEqual((work / "install/current").resolve(), current)

    def test_unprivileged_program_can_read_the_published_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            installed = run(work, "valid = true\n")
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            program = work / "install/current/bin/frp-grant-admission"
            config = work / "active/config.toml"
            options = {}
            if os.geteuid() == 0:
                work.chmod(0o755)
                os.chown(work / "active", 0, 65534)
                (work / "active").chmod(0o750)
                os.chown(config, 0, 65534)
                config.chmod(0o640)
                options = {"user": 65534, "group": 65534, "extra_groups": []}
            else:
                self.assertGreater(os.geteuid(), 0)
            result = subprocess.run([str(program), "check", str(config)], capture_output=True, text=True, timeout=10, **options)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("listen 127.0.0.1:7300", result.stdout)
