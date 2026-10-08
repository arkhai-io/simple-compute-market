"""The bare-metal access playbook and role ship with the bare-metal domain."""

from __future__ import annotations

from pathlib import Path

from bare_metal_provisioning_adapter.codec import BARE_METAL_RECLAIM_POLICIES


REPO_ROOT = Path(__file__).resolve().parents[5]
ANSIBLE_ROOT = REPO_ROOT / "domains/vms/provisioning/iac/ansible"
BARE_METAL_ANSIBLE_ROOT = REPO_ROOT / "domains/bare_metal/provisioning/iac/ansible"


def test_bare_metal_actions_have_their_own_playbook_and_role():
    playbook = BARE_METAL_ANSIBLE_ROOT / "playbooks/node-access.yaml"
    role = BARE_METAL_ANSIBLE_ROOT / "roles/bare-metal-access/tasks/main.yml"

    playbook_text = playbook.read_text(encoding="utf-8")
    role_text = role.read_text(encoding="utf-8")

    assert "../roles/bare-metal-access" in playbook_text
    assert "node_grant_access_data" in role_text
    assert "node_reclaim_access_data" in role_text
    assert "ansible.posix.authorized_key" in role_text
    assert "bare_metal_reclaim_policy" in role_text
    # The role implements exactly the policies the bare-metal codec accepts.
    for policy in BARE_METAL_RECLAIM_POLICIES:
        assert policy in role_text
    assert "bare_metal_delete_result" in role_text


def test_vm_management_role_does_not_dispatch_bare_metal_actions():
    main = ANSIBLE_ROOT / "roles/vm-management/tasks/main.yml"

    assert "node_grant_access" not in main.read_text(encoding="utf-8")
    assert "node_reclaim_access" not in main.read_text(encoding="utf-8")
