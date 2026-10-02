"""The runner's inventory rendering, key handling, and output extraction."""

from __future__ import annotations

import stat
from types import SimpleNamespace

import pytest
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost, ProtectedValue
from cryptography.fernet import Fernet
from market_config import encrypt_secret

from compute_provisioning_ansible import SshConnectionCodec
from compute_provisioning_ansible.runner import (
    AnsibleRunner,
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


def test_an_embedded_key_is_decrypted_only_into_an_owner_only_file() -> None:
    runner = AnsibleRunner(SimpleNamespace(), ssh_codec=SshConnectionCodec(_KEY))
    target = inventory_target(
        _host(private_key=ProtectedValue("fernet-v1", encrypt_secret(_PEM, _KEY)))
    )

    inventory = runner.write_inventory([target])
    try:
        text = inventory.read_text()
        key_file = text.split("ansible_ssh_private_key_file=")[1].split()[0]
        from pathlib import Path

        assert "ansible_port=2201" in text and "ansible_user=ops" in text
        assert Path(key_file).read_text() == _PEM
        assert stat.S_IMODE(Path(key_file).stat().st_mode) == 0o400
        assert "fixture" not in text
    finally:
        inventory.unlink(missing_ok=True)


def test_a_key_path_is_referenced_not_read() -> None:
    runner = AnsibleRunner(SimpleNamespace())
    inventory = runner.write_inventory([inventory_target(_host())])
    try:
        assert "ansible_ssh_private_key_file=/keys/id" in inventory.read_text()
    finally:
        inventory.unlink(missing_ok=True)


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
