"""The Ansible implementation's readiness component."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from compute_provisioning.jobs.executor_mock import MockRuleSet

from compute_provisioning_ansible import AnsibleJobExecutor
from compute_provisioning_ansible.readiness import (
    ANSIBLE_COMPONENT,
    ANSIBLE_READINESS_KIND,
    AnsibleReadinessDetail,
    ansible_readiness_component,
    collect_ssh_keys_from_hosts,
)


def _host(host_id: str, *, key_path: str | None = None, embedded: bool = False):
    return SimpleNamespace(
        host_id=host_id,
        connection=SimpleNamespace(
            public={"key_path": key_path},
            protected={"private_key": object()} if embedded else {},
        ),
    )


class _Runner:
    """A runner stand-in: the readiness report reads only ``rules``."""

    def __init__(self, *, mocked: bool) -> None:
        self.rules = MockRuleSet() if mocked else None


def _executor(playbook: Path, *, mocked: bool) -> AnsibleJobExecutor:
    return AnsibleJobExecutor(
        _Runner(mocked=mocked), codec=None, playbook_path=playbook, timeout_seconds=5
    )


class _OtherExecutor:
    """An executor of another implementation, which the component ignores."""

    rules = None


def ansible_on_path() -> str:
    return "ansible [core 2.17.0]"


def no_ansible() -> None:
    return None


def _detail(component) -> AnsibleReadinessDetail:
    assert component.name == ANSIBLE_COMPONENT
    assert (component.detail.kind, component.detail.schema_version) == (ANSIBLE_READINESS_KIND, 1)
    return AnsibleReadinessDetail.model_validate(component.detail.payload)


def test_every_offering_mode_playbook_is_reported(tmp_path):
    vm_playbook = tmp_path / "vm.yaml"
    vm_playbook.write_text("- hosts: all\n")
    bare_metal_playbook = tmp_path / "bare_metal.yaml"
    bare_metal_playbook.write_text("- hosts: nodes\n")

    component = ansible_readiness_component(
        version_probe=ansible_on_path,
        executors_by_offering_mode={
            "vm": (_executor(vm_playbook, mocked=False),),
            "bare_metal": (_executor(bare_metal_playbook, mocked=False), _OtherExecutor()),
        },
        list_hosts=lambda: [_host("a", embedded=True)],
    )
    detail = _detail(component)

    assert component.ready is True
    assert [(p.offering_mode, p.path, p.exists) for p in detail.playbooks] == [
        ("vm", str(vm_playbook), True),
        ("bare_metal", str(bare_metal_playbook), True),
    ]
    assert detail.playbooks[1].sha256 == hashlib.sha256(b"- hosts: nodes\n").hexdigest()
    assert detail.ansible_version == "ansible [core 2.17.0]"
    assert [key.key_type for key in detail.ssh_keys] == ["embedded"]
    assert detail.host_registry_readable is True


def test_a_missing_playbook_makes_the_component_not_ready(tmp_path):
    present = tmp_path / "vm.yaml"
    present.write_text("- hosts: all\n")

    component = ansible_readiness_component(
        version_probe=ansible_on_path,
        executors_by_offering_mode={
            "vm": (_executor(present, mocked=False),),
            "bare_metal": (_executor(tmp_path / "absent.yaml", mocked=False),),
        },
        list_hosts=list,
    )

    assert component.ready is False
    missing = [p for p in _detail(component).playbooks if not p.exists]
    assert [(p.offering_mode, p.sha256) for p in missing] == [("bare_metal", None)]
    assert _detail(component).not_ready_reasons == [
        f"the bare_metal playbook is missing: {tmp_path / 'absent.yaml'}"
    ]


def test_real_executors_without_ansible_are_not_ready(tmp_path):
    playbook = tmp_path / "vm.yaml"
    playbook.write_text("- hosts: all\n")

    component = ansible_readiness_component(
        version_probe=no_ansible,
        executors_by_offering_mode={"vm": (_executor(playbook, mocked=False),)},
        list_hosts=list,
    )

    assert component.ready is False
    assert _detail(component).not_ready_reasons == ["ansible is not on PATH"]


def test_mocked_executors_are_ready_without_ansible_or_playbooks(tmp_path):
    component = ansible_readiness_component(
        version_probe=no_ansible,
        executors_by_offering_mode={"vm": (_executor(tmp_path / "absent.yaml", mocked=True),)},
        list_hosts=list,
    )

    assert component.ready is True
    assert [p.mocked for p in _detail(component).playbooks] == [True]


@pytest.mark.parametrize("mocked", [True, False], ids=["mocked", "real"])
def test_an_unreadable_host_registry_is_not_ready_whatever_runs(tmp_path, mocked):
    """Every job resolves its host in the registry, and the hosts' credentials
    cannot be verified without it, so this holds even when execution is mocked."""
    playbook = tmp_path / "vm.yaml"
    playbook.write_text("- hosts: all\n")

    def failing():
        raise RuntimeError("database unavailable")

    component = ansible_readiness_component(
        version_probe=ansible_on_path,
        executors_by_offering_mode={"vm": (_executor(playbook, mocked=mocked),)},
        list_hosts=failing,
    )
    detail = _detail(component)

    assert (detail.host_registry_readable, detail.ssh_keys) == (False, [])
    assert component.ready is False
    assert detail.not_ready_reasons == ["the host registry could not be read"]


def test_a_missing_key_file_blocks_real_execution(tmp_path):
    playbook = tmp_path / "vm.yaml"
    playbook.write_text("- hosts: all\n")
    present = tmp_path / "id_present"
    present.write_bytes(b"key")
    missing = tmp_path / "id_missing"

    component = ansible_readiness_component(
        version_probe=ansible_on_path,
        executors_by_offering_mode={"vm": (_executor(playbook, mocked=False),)},
        list_hosts=lambda: [
            _host("a", key_path=str(present)),
            _host("b", key_path=str(missing)),
            _host("c", embedded=True),
        ],
    )

    assert component.ready is False
    assert _detail(component).not_ready_reasons == [
        f"the key file {missing} is missing (hosts: b)"
    ]


def test_a_missing_key_file_does_not_block_mocked_execution(tmp_path):
    component = ansible_readiness_component(
        version_probe=no_ansible,
        executors_by_offering_mode={"vm": (_executor(tmp_path / "absent.yaml", mocked=True),)},
        list_hosts=lambda: [_host("b", key_path=str(tmp_path / "id_missing"))],
    )

    assert component.ready is True
    assert _detail(component).not_ready_reasons == []


def test_one_real_executor_makes_keys_count_for_the_mixed_deployment(tmp_path):
    """A host's mode is its pool's, which the component does not see, so once
    any executor is real every enabled host's key counts; a mocked executor's
    missing playbook still does not."""
    playbook = tmp_path / "vm.yaml"
    playbook.write_text("- hosts: all\n")

    component = ansible_readiness_component(
        version_probe=ansible_on_path,
        executors_by_offering_mode={
            "vm": (_executor(playbook, mocked=False),),
            "bare_metal": (_executor(tmp_path / "absent.yaml", mocked=True),),
        },
        list_hosts=lambda: [_host("node", key_path=str(tmp_path / "id_missing"))],
    )

    reasons = _detail(component).not_ready_reasons
    assert component.ready is False
    assert len(reasons) == 1 and reasons[0].startswith("the key file")


def test_the_detail_discloses_no_key_material(tmp_path):
    component = ansible_readiness_component(
        version_probe=ansible_on_path,
        executors_by_offering_mode={},
        list_hosts=lambda: [_host("a", embedded=True)],
    )

    assert "private_key" not in component.detail.model_dump_json()


def test_key_references_are_grouped_by_path_and_embedded_keys_listed_alone(tmp_path):
    key_file = tmp_path / "id_ed25519"
    key_file.write_bytes(b"key")
    hosts = [
        _host("b", key_path=str(key_file)),
        _host("a", key_path=str(key_file)),
        _host("c", key_path=str(tmp_path / "missing")),
        _host("d", embedded=True),
    ]

    keys = {info.raw_path: info for info in collect_ssh_keys_from_hosts(hosts)}

    assert keys[str(key_file)].referenced_by == ["a", "b"]
    assert keys[str(key_file)].sha256 == hashlib.sha256(b"key").hexdigest()
    assert keys[str(tmp_path / "missing")].exists is False
    assert keys["<encrypted>"].key_type == "embedded"
    assert keys["<encrypted>"].referenced_by == ["d"]
