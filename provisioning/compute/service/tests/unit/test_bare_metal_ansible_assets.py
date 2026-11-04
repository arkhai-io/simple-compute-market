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


def test_bare_metal_relay_calls_share_the_family_roles_without_management_edits():
    text = (BARE_METAL_ANSIBLE_ROOT / "roles/bare-metal-access/tasks/main.yml").read_text()
    assert text.count("name: relay-proxy") == 2
    assert "relay_proxy_action: add" in text and "relay_proxy_action: remove" in text
    assert 'relay_proxy_local_ip: "127.0.0.1"' in text
    assert text.index("Remove the leased bare-metal buyer proxy") < text.index("Look up the bare-metal tenant account")
    assert "frpc-management" not in text
    host_setup = BARE_METAL_ANSIBLE_ROOT / "playbooks/host-kit/host-setup.yaml"
    assert "- relay-client" in host_setup.read_text()
    gate = (REPO_ROOT / "provisioning/compute/iac/scripts/image_syntax_gate.sh").read_text()
    assert gate.count("playbooks/host-kit/host-setup.yaml --syntax-check") == 2


def test_reclaim_activity_barrier_precedes_all_account_policies_and_propagates_failures():
    text = (BARE_METAL_ANSIBLE_ROOT / "roles/bare-metal-access/tasks/main.yml").read_text()
    key = text.index("Remove bare-metal tenant authorized_keys")
    barrier = text.index("End and verify bare-metal tenant activity")
    assert key < barrier < text.index("Lock bare-metal tenant account") < text.index("Delete bare-metal tenant account")
    assert "failed_when: false" not in text
    assert 'activity: "{{ bare_metal_activity_detail | default({}) }}"' in text
    body = text[barrier:text.index("- name: Record verified bare-metal", barrier)]
    assert "bare_metal_account_present | bool" in body
    assert "become: true" in body and "bare_metal_account_lookup.stdout.split(':')[2]" in body


def test_bounded_assets_are_domain_owned_and_initialization_is_operator_only():
    roles = BARE_METAL_ANSIBLE_ROOT / "roles"
    installer = (roles / "bare-metal-working-data/tasks/main.yml").read_text()
    access = (roles / "bare-metal-access/tasks/main.yml").read_text()
    cleanup = (roles / "bare-metal-access/tasks/bounded-reclaim.yml").read_text()
    host_setup = (BARE_METAL_ANSIBLE_ROOT / "playbooks/host-kit/host-setup.yaml").read_text()
    assert "../../roles/bare-metal-working-data" in host_setup
    assert "bare_metal_working_data_initialize | default(false)" in installer
    assert "--init" not in access and "--init" not in cleanup
    assert "remove: false" in cleanup and "remove: yes" not in cleanup
    assert "verify-complete" in cleanup
    assert access.index("Revoke the bounded tenant key") < access.index("End and verify the protected bounded tenant activity") < access.index("Complete bounded working-data reclaim")
    assert (roles / "bare-metal-access/files/tenant_working_data.py").is_file()
    dockerfile = (REPO_ROOT / "provisioning/compute/service/Dockerfile").read_text()
    assert "domains/bare_metal/provisioning/iac /opt/domains/bare_metal/provisioning/iac" in dockerfile
