"""The runner's inventory rendering, key handling, and output extraction."""

from __future__ import annotations

import asyncio
import logging
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost, ProtectedValue
from cryptography.fernet import Fernet, InvalidToken
from market_config import encrypt_secret

from compute_provisioning_ansible import SshConnectionCodec
from compute_provisioning_ansible.runner import (
    AnsibleRun,
    AnsibleRunner,
    InventoryTarget,
    extract_fact,
    extract_json_block,
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

    with runner.write_inventory([_embedded()], group="nodes") as inventory:
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
    inventory = runner.write_inventory([_embedded(), _embedded("kvm2")], group="nodes")
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
        runner.write_inventory([_embedded(), _embedded("kvm2", key=wrong_key)], group="nodes")

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

    with runner.write_inventory([_embedded()], group="nodes"):
        pass

    assert created == [0o600]


def test_a_key_path_is_referenced_not_read() -> None:
    runner = AnsibleRunner(SimpleNamespace())
    with runner.write_inventory([inventory_target(_host())], group="nodes") as inventory:
        assert "ansible_ssh_private_key_file=/keys/id" in inventory.path.read_text()
        assert inventory.key_paths == []


def test_only_ssh_connections_reach_an_inventory() -> None:
    host = ExecutionHost("h", None, ConnectionEnvelope(kind="cloud_api", version=1))
    with pytest.raises(ValueError, match="over ssh"):
        inventory_target(host)


def test_a_json_block_is_extracted_whole() -> None:
    text = 'noise "fact": {"a": {"b": "}"}, "c": 1} trailing'

    assert extract_json_block(text, 0) == {"a": {"b": "}"}, "c": 1}
    assert extract_json_block("no json here", 0) is None


def test_credential_shaped_output_is_redacted() -> None:
    assert "hunter2" not in redact_ansible_output('{"password": "hunter2"}')
    assert "hunter2" not in redact_ansible_output("password: hunter2")


def test_every_host_is_listed_under_the_callers_group() -> None:
    runner = AnsibleRunner(SimpleNamespace())
    hosts = [inventory_target(_host())]
    with runner.write_inventory(hosts, group="bare_metal_nodes") as inventory:
        lines = inventory.path.read_text().splitlines()
    assert lines[0] == "[bare_metal_nodes]"
    assert lines[1].startswith("kvm1  ansible_host=10.0.0.1")


def test_a_printed_fact_is_extracted_by_name() -> None:
    stdout = 'ok: [h] => {\n    "node_grant_access_data": {"host": "10.0.0.5", "port": "22"}\n}'

    assert extract_fact(stdout, "node_grant_access_data") == {"host": "10.0.0.5", "port": "22"}
    assert extract_fact(stdout, "vm_creation_data") is None


@pytest.mark.parametrize(
    "text",
    [
        '{"relay_token": "s3cret"}',
        'ok: [h] => {"msg": "{\\n    \\"relay_token\\": \\"s3cret\\"\\n}"}',
        "relay_token: s3cret",
    ],
    ids=["json", "escaped json", "yaml"],
)
def test_a_field_the_caller_names_is_redacted_in_every_form(text) -> None:
    assert "s3cret" not in redact_ansible_output(text, {"relay_token"})
    assert "s3cret" in redact_ansible_output(text)


def test_identity_files_and_sshpass_are_always_redacted() -> None:
    text = "ssh -i /home/u/.ssh/id_ed25519 host; sshpass -p hunter2 ssh host"

    redacted = redact_ansible_output(text)

    assert ".ssh/id_ed25519" not in redacted
    assert "hunter2" not in redacted


def test_empty_and_none_output_are_returned_unchanged() -> None:
    assert redact_ansible_output("") == ""
    assert redact_ansible_output(None) is None


def test_streamed_debug_lines_are_redacted_by_the_callers_redactor(caplog) -> None:
    """Lines logged while a playbook runs pass through the redactor the caller
    gives, which knows its playbook's secret fields. A real subprocess, because
    the streaming loop selects on its pipes."""
    process = subprocess.Popen(
        [sys.executable, "-c", "print('relay_token: s3cret')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    run = AnsibleRun(
        process=process,
        process_id=process.pid,
        vars_path=Path(tempfile.gettempdir()) / "does-not-exist-redaction-test.yml",
    )
    caplog.set_level(logging.DEBUG, logger="compute_provisioning_ansible.runner")

    result = asyncio.run(
        AnsibleRunner(SimpleNamespace()).wait_for_playbook(
            run,
            timeout_seconds=5,
            redact=lambda text: redact_ansible_output(text, {"relay_token"}),
        )
    )

    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("ansible stdout" in message for message in debug), debug
    assert not any("s3cret" in message for message in debug), debug
    # What the caller receives is raw: its consumer redacts it.
    assert "s3cret" in result.stdout
