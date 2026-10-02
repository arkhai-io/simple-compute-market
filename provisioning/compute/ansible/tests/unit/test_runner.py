"""The runner's inventory rendering, key handling, and output extraction."""

from __future__ import annotations

import os
import stat
import tempfile
from types import SimpleNamespace

import pytest
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost, ProtectedValue
from cryptography.fernet import Fernet, InvalidToken
from market_config import encrypt_secret

from compute_provisioning_ansible import SshConnectionCodec
from compute_provisioning_ansible.runner import (
    AnsibleRunner,
    InventoryTarget,
    inventory_target,
    redact_ansible_output,
)

# A key generated for this test module only; it protects nothing real.
_KEY = Fernet.generate_key().decode()
_PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\nfixture\n-----END OPENSSH PRIVATE KEY-----\n"


def _host(**protected) -> ExecutionHost:
    public = {"ssh_host": "10.0.0.1", "ssh_port": 2201, "ssh_user": "ops", "public_host": None}
    public["key_path"] = None if protected else "/keys/id"
    return ExecutionHost(
        "kvm1", "default", ConnectionEnvelope(kind="ssh", version=1, public=public, protected=protected)
    )


def _embedded(host_id: str = "kvm1", key: str | None = None) -> InventoryTarget:
    """An inventory target whose key is embedded, protected with ``key``."""
    return InventoryTarget(
        host_id=host_id,
        ssh_host="10.0.0.1",
        public_host=None,
        ssh_port=2201,
        ssh_user="ops",
        ssh_key_type="embedded",
        ssh_key_value=encrypt_secret(_PEM, key or _KEY),
    )


def test_an_embedded_key_is_decrypted_only_into_an_owner_only_file() -> None:
    runner = AnsibleRunner(SimpleNamespace(), ssh_codec=SshConnectionCodec(_KEY))

    with runner.write_inventory([_embedded()]) as inventory:
        text = inventory.path.read_text()
        (key_file,) = inventory.key_paths
        assert f"ansible_ssh_private_key_file={key_file}" in text
        assert "ansible_port=2201" in text and "ansible_user=ops" in text
        assert key_file.read_text() == _PEM
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o400
        assert "fixture" not in text

    assert not key_file.exists()
    assert not inventory.path.exists()


def test_cleanup_removes_the_inventory_and_every_key_and_can_repeat() -> None:
    runner = AnsibleRunner(SimpleNamespace(), ssh_codec=SshConnectionCodec(_KEY))
    inventory = runner.write_inventory([_embedded(), _embedded("kvm2")])
    written = [inventory.path, *inventory.key_paths]
    assert len(written) == 3 and all(path.exists() for path in written)

    inventory.cleanup()
    inventory.cleanup()

    assert not any(path.exists() for path in written)


def test_a_key_that_cannot_be_decrypted_leaves_nothing_behind(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    runner = AnsibleRunner(SimpleNamespace(), ssh_codec=SshConnectionCodec(_KEY))
    wrong_key = Fernet.generate_key().decode()

    with pytest.raises(InvalidToken):
        runner.write_inventory([_embedded(), _embedded("kvm2", key=wrong_key)])

    assert list(tmp_path.iterdir()) == []


def test_a_key_file_is_never_readable_by_others(tmp_path, monkeypatch) -> None:
    """The key file is created owner-only rather than restricted after writing."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    created: list[int] = []
    real_open = os.open

    def recording_open(path, flags, mode=0o777, *args, **kwargs):
        created.append(mode)
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    runner = AnsibleRunner(SimpleNamespace(), ssh_codec=SshConnectionCodec(_KEY))

    with runner.write_inventory([_embedded()]):
        pass

    assert created == [0o600]


def test_a_key_path_is_referenced_not_read() -> None:
    runner = AnsibleRunner(SimpleNamespace())
    with runner.write_inventory([inventory_target(_host())]) as inventory:
        assert "ansible_ssh_private_key_file=/keys/id" in inventory.path.read_text()
        assert inventory.key_paths == []


def test_only_ssh_connections_reach_an_inventory() -> None:
    host = ExecutionHost("h", None, ConnectionEnvelope(kind="cloud_api", version=1))
    with pytest.raises(ValueError, match="over ssh"):
        inventory_target(host)


def test_a_json_block_is_extracted_whole() -> None:
    text = 'noise "fact": {"a": {"b": "}"}, "c": 1} trailing'

    assert AnsibleRunner.extract_json_block(text, 0) == {"a": {"b": "}"}, "c": 1}
    assert AnsibleRunner.extract_json_block("no json here", 0) is None


def test_credential_shaped_output_is_redacted() -> None:
    assert "hunter2" not in redact_ansible_output('{"password": "hunter2"}')
    assert "hunter2" not in redact_ansible_output("password: hunter2")
