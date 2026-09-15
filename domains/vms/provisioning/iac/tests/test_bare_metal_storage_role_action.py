"""The production role refuses storage preparation before secret-bearing work."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


IAC = Path(__file__).resolve().parents[1]
PLAYBOOK = IAC / "ansible" / "playbooks" / "bare-metal" / "node-access.yaml"
ANSIBLE_CFG = IAC / "ansible" / "ansible.cfg"
ROLE = IAC / "ansible" / "roles" / "bare-metal-access"
REFUSAL = (
    "node_prepare_lease_storage remains disabled until persistent-path, "
    "mapping, mount, and reboot-recovery readiness are integrated"
)


def _tasks():
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))


def test_real_prepare_playbook_refuses_before_storage_or_secret_work(tmp_path):
    tmp_path.chmod(0o700)
    inventory = tmp_path / "inventory.ini"
    inventory.write_text(
        "[kvm_hosts]\n"
        f"bm1 ansible_connection=local ansible_become=false "
        f"ansible_python_interpreter={sys.executable}\n",
        encoding="utf-8",
    )
    state_root = tmp_path / "must-not-exist"
    extra_vars = {
        "executor_target": "bm1",
        "executor_action": "node_prepare_lease_storage",
        "physical_host_id": "host-1",
        "bare_metal_lease_generation": "generation-1",
        "bare_metal_lease_storage_state_root": str(state_root),
        "bare_metal_lease_backing_size_bytes": 32 * 1024 * 1024,
        "bare_metal_lease_free_space_floor_bytes": 1024,
        "bare_metal_lease_counter_index": "0x1500020",
        "bare_metal_lease_counter_headroom": 16,
        "bare_metal_lease_parent_handle": "0x81000020",
        "bare_metal_lease_parent_name": "000b11223344",
    }
    env = {
        **os.environ,
        "ANSIBLE_CONFIG": str(ANSIBLE_CFG),
        "ANSIBLE_LOCAL_TEMP": str(tmp_path / "local-tmp"),
        "ANSIBLE_REMOTE_TEMP": str(tmp_path / "remote-tmp"),
        "ANSIBLE_SSH_CONTROL_PATH_DIR": str(tmp_path / "control-path"),
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_RETRY_FILES_ENABLED": "0",
    }
    completed = subprocess.run(
        [
            shutil.which("ansible-playbook") or "ansible-playbook",
            "-i",
            str(inventory),
            str(PLAYBOOK),
            "--limit",
            "bm1",
            "-e",
            json.dumps(extra_vars),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=tmp_path,
    )

    assert completed.returncode != 0, completed.stdout[-3000:]
    assert REFUSAL in completed.stdout
    assert not state_root.exists()
    assert "Prepare encrypted lease storage" not in completed.stdout
    assert "arkhai-prepare-lease-storage.py" not in completed.stdout


def test_prepare_refusal_has_no_caller_bypass():
    refusal = next(
        item
        for item in _tasks()
        if item["name"] == "Refuse incomplete encrypted lease storage preparation"
    )

    assert refusal["when"] == "node_action == 'node_prepare_lease_storage'"
    assert refusal["fail"]["msg"] == REFUSAL
    assert "enabled" not in refusal["when"]


def test_grant_refusal_remains_unconditional_after_storage_helper_is_added():
    refusal = next(
        item
        for item in _tasks()
        if item["name"] == "Refuse to expose access while managed preparation is unfinished"
    )
    assert refusal["when"] == 'node_action == "node_grant_access"'
    assert "bare_metal_lease_storage_prepared" not in str(refusal)
