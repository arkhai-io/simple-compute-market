"""The Ansible implementation's readiness component."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost, ProtectedValue
from compute_provisioning.jobs.executor_mock import MockRuleSet
from cryptography.fernet import Fernet

from compute_provisioning_ansible import AnsibleJobExecutor, SshConnectionCodec
from compute_provisioning_ansible.readiness import (
    ANSIBLE_COMPONENT,
    ANSIBLE_READINESS_KIND,
    AnsibleReadinessDetail,
    ansible_readiness_component,
    collect_ssh_keys_from_hosts,
)

# Keys generated for this test module only; they protect nothing real.
_KEY = Fernet.generate_key().decode()
_OTHER_KEY = Fernet.generate_key().decode()
_CODEC = SshConnectionCodec(_KEY)
_PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\nfixture\n-----END OPENSSH PRIVATE KEY-----\n"


def _host(
    host_id: str,
    *,
    key_path: str | None = None,
    embedded: bool = False,
    protected_under: str = _KEY,
    ciphertext: str | None = None,
    version: int = 2,
) -> ExecutionHost:
    """An enabled host as the host authority's internal read returns it."""
    public = {"ssh_host": "10.0.0.1", "ssh_port": 22, "ssh_user": "ops", "key_path": key_path}
    protected = {}
    if embedded:
        if ciphertext is None:
            ciphertext = (
                SshConnectionCodec(protected_under)
                .build({"ssh_host": "10.0.0.1"}, {"private_key": _PEM})
                .protected["private_key"]
                .ciphertext
            )
        protected["private_key"] = ProtectedValue("fernet-v1", ciphertext)
    return ExecutionHost(
        host_id, "default", ConnectionEnvelope(kind="ssh", version=version, public=public, protected=protected)
    )


def _component(executors, hosts, *, codec=_CODEC, version_probe=None):
    return ansible_readiness_component(
        version_probe=version_probe or ansible_on_path,
        executors_by_offering_mode=executors,
        execution_hosts=hosts if callable(hosts) else (lambda: hosts),
        ssh_codec=codec,
    )


def _real(tmp_path) -> dict:
    playbook = tmp_path / "vm.yaml"
    playbook.write_text("- hosts: all\n")
    return {"vm": (_executor(playbook, mocked=False),)}


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
    assert (component.detail.kind, component.detail.schema_version) == (ANSIBLE_READINESS_KIND, 2)
    return AnsibleReadinessDetail.model_validate(component.detail.payload)


def test_every_offering_mode_playbook_is_reported(tmp_path):
    vm_playbook = tmp_path / "vm.yaml"
    vm_playbook.write_text("- hosts: all\n")
    bare_metal_playbook = tmp_path / "bare_metal.yaml"
    bare_metal_playbook.write_text("- hosts: nodes\n")

    component = _component(
        {
            "vm": (_executor(vm_playbook, mocked=False),),
            "bare_metal": (_executor(bare_metal_playbook, mocked=False), _OtherExecutor()),
        },
        [_host("a", embedded=True)],
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

    component = _component(
        {
            "vm": (_executor(present, mocked=False),),
            "bare_metal": (_executor(tmp_path / "absent.yaml", mocked=False),),
        },
        [],
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

    component = _component(
        {"vm": (_executor(playbook, mocked=False),)}, [], version_probe=no_ansible
    )

    assert component.ready is False
    assert _detail(component).not_ready_reasons == ["ansible is not on PATH"]


def test_mocked_executors_are_ready_without_ansible_or_playbooks(tmp_path):
    component = _component(
        {"vm": (_executor(tmp_path / "absent.yaml", mocked=True),)}, [], version_probe=no_ansible
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

    component = _component({"vm": (_executor(playbook, mocked=mocked),)}, failing)
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

    component = _component(
        {"vm": (_executor(playbook, mocked=False),)},
        [
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
    component = _component(
        {"vm": (_executor(tmp_path / "absent.yaml", mocked=True),)},
        [_host("b", key_path=str(tmp_path / "id_missing"))],
        version_probe=no_ansible,
    )

    assert component.ready is True
    assert _detail(component).not_ready_reasons == []


def test_one_real_executor_makes_keys_count_for_the_mixed_deployment(tmp_path):
    """A host's mode is its pool's, which the component does not see, so once
    any executor is real every enabled host's key counts; a mocked executor's
    missing playbook still does not."""
    playbook = tmp_path / "vm.yaml"
    playbook.write_text("- hosts: all\n")

    component = _component(
        {
            "vm": (_executor(playbook, mocked=False),),
            "bare_metal": (_executor(tmp_path / "absent.yaml", mocked=True),),
        },
        [_host("node", key_path=str(tmp_path / "id_missing"))],
    )

    reasons = _detail(component).not_ready_reasons
    assert component.ready is False
    assert len(reasons) == 1 and reasons[0].startswith("the key file")


def test_the_detail_discloses_no_key_material(tmp_path):
    readable = _host("a", embedded=True)
    unreadable = _host("b", embedded=True, protected_under=_OTHER_KEY)
    component = _component(_real(tmp_path), [readable, unreadable])

    rendered = component.detail.model_dump_json()
    assert "private_key" not in rendered
    for host in (readable, unreadable):
        assert host.connection.protected["private_key"].ciphertext not in rendered
    assert "fixture" not in rendered and "PRIVATE KEY" not in rendered


def test_key_references_are_grouped_by_path_and_embedded_keys_listed_alone(tmp_path):
    key_file = tmp_path / "id_ed25519"
    key_file.write_bytes(b"key")
    hosts = [
        _host("b", key_path=str(key_file)),
        _host("a", key_path=str(key_file)),
        _host("c", key_path=str(tmp_path / "missing")),
        _host("d", embedded=True),
    ]

    report = collect_ssh_keys_from_hosts(hosts, _CODEC)
    keys = {info.raw_path: info for info in report.ssh_keys}

    assert keys[str(key_file)].referenced_by == ["a", "b"]
    assert keys[str(key_file)].sha256 == hashlib.sha256(b"key").hexdigest()
    assert keys[str(tmp_path / "missing")].exists is False
    assert keys["<encrypted>"].key_type == "embedded"
    assert keys["<encrypted>"].referenced_by == ["d"]
    assert report.host_reasons == []


def test_an_embedded_key_that_decrypts_exists_and_the_component_is_ready(tmp_path):
    component = _component(_real(tmp_path), [_host("a", embedded=True)])
    detail = _detail(component)

    assert component.ready is True
    assert [(key.key_type, key.exists, key.referenced_by) for key in detail.ssh_keys] == [
        ("embedded", True, ["a"])
    ]


def _unreadable_message(host_id: str, codec: SshConnectionCodec, ciphertext: str) -> str:
    """The codec's own message for a key it cannot decrypt."""
    try:
        codec.decrypt_private_key(ciphertext, host_id=host_id)
    except ValueError as exc:
        return str(exc)
    raise AssertionError("the key decrypted")


@pytest.mark.parametrize(
    "host,codec",
    [
        (_host("bad", embedded=True, protected_under=_OTHER_KEY), _CODEC),
        (_host("bad", embedded=True, ciphertext="not-a-fernet-token"), _CODEC),
        (_host("bad", embedded=True), SshConnectionCodec(None)),
    ],
    ids=["another-key", "malformed", "no-key"],
)
def test_an_embedded_key_that_does_not_decrypt_names_its_host_and_spares_the_others(
    tmp_path, host, codec
):
    key_file = tmp_path / "id_present"
    key_file.write_bytes(b"key")
    good = _host("good", key_path=str(key_file))

    component = _component(_real(tmp_path), [good, host], codec=codec)
    detail = _detail(component)

    expected = _unreadable_message("bad", codec, host.connection.protected["private_key"].ciphertext)
    assert "'bad'" in expected
    assert component.ready is False
    assert detail.not_ready_reasons == [expected]
    keys = {tuple(key.referenced_by): key for key in detail.ssh_keys}
    assert (keys[("bad",)].key_type, keys[("bad",)].exists) == ("embedded", False)
    assert (keys[("good",)].exists, keys[("good",)].sha256) == (
        True,
        hashlib.sha256(b"key").hexdigest(),
    )


def test_a_host_stored_at_version_1_is_refused_as_execution_refuses_it(tmp_path):
    """Its key file exists, but execution refuses the connection before reading
    it, so readiness does too; the other host is reported unchanged."""
    key_file = tmp_path / "id_present"
    key_file.write_bytes(b"key")
    legacy = _host("legacy", key_path=str(key_file), version=1)
    current = _host("current", key_path=str(key_file))

    component = _component(_real(tmp_path), [legacy, current])
    detail = _detail(component)

    assert component.ready is False
    (reason,) = detail.not_ready_reasons
    assert reason.startswith("host 'legacy' cannot be executed against: ")
    assert "'ssh' at 1" in reason and "re-register the host at version 2" in reason
    assert [(key.raw_path, key.referenced_by, key.exists) for key in detail.ssh_keys] == [
        (str(key_file), ["current"], True)
    ]


def test_a_host_stored_at_version_1_with_a_key_that_decrypts_is_refused(tmp_path):
    legacy = _host("legacy", embedded=True, version=1)

    component = _component(_real(tmp_path), [legacy])
    detail = _detail(component)

    assert component.ready is False
    (reason,) = detail.not_ready_reasons
    assert reason.startswith("host 'legacy' cannot be executed against: ")
    assert "'ssh' at 1" in reason
    assert detail.ssh_keys == []


def test_a_connection_naming_no_key_is_refused_naming_its_host_once(tmp_path):
    keyless = _host("keyless")

    component = _component(_real(tmp_path), [keyless])
    detail = _detail(component)

    assert component.ready is False
    assert detail.not_ready_reasons == ["host 'keyless' has an ssh connection naming no key"]
    assert detail.ssh_keys == []


def test_a_host_of_another_connection_kind_is_skipped(tmp_path):
    other = ExecutionHost("cloud", "default", ConnectionEnvelope(kind="cloud_api", version=1))

    component = _component(_real(tmp_path), [other])
    detail = _detail(component)

    assert component.ready is True
    assert (detail.ssh_keys, detail.not_ready_reasons) == ([], [])


def test_an_empty_host_list_is_ready(tmp_path):
    component = _component(_real(tmp_path), [])

    assert component.ready is True
    assert _detail(component).ssh_keys == []


def test_with_mocked_executors_only_a_key_that_will_not_decrypt_is_reported_not_counted(tmp_path):
    component = _component(
        {"vm": (_executor(tmp_path / "absent.yaml", mocked=True),)},
        [_host("bad", embedded=True, protected_under=_OTHER_KEY)],
        version_probe=no_ansible,
    )
    detail = _detail(component)

    assert component.ready is True
    assert detail.not_ready_reasons == []
    assert [(key.referenced_by, key.exists) for key in detail.ssh_keys] == [(["bad"], False)]
