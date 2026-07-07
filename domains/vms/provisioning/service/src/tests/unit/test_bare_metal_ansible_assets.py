from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[7]
ANSIBLE_ROOT = REPO_ROOT / "domains/vms/provisioning/iac/ansible"


def test_bare_metal_actions_have_separate_playbook_and_role():
    playbook = ANSIBLE_ROOT / "playbooks/bare-metal/node-access.yaml"
    role = ANSIBLE_ROOT / "roles/bare-metal-access/tasks/main.yml"

    playbook_text = playbook.read_text(encoding="utf-8")
    role_text = role.read_text(encoding="utf-8")

    assert "../../roles/bare-metal-access" in playbook_text
    assert "node_grant_access_data" in role_text
    assert "node_reclaim_access_data" in role_text
    assert "ansible.posix.authorized_key" in role_text


def test_vm_management_role_does_not_dispatch_bare_metal_actions():
    main = ANSIBLE_ROOT / "roles/vm-management/tasks/main.yml"

    assert "node_grant_access" not in main.read_text(encoding="utf-8")
    assert "node_reclaim_access" not in main.read_text(encoding="utf-8")
