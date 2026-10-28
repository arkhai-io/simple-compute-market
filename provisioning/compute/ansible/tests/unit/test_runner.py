"""The runner's inventory rendering, key handling, and output extraction."""

from __future__ import annotations

import asyncio
import json
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
    read_fact,
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


# Synthetic playbook output in the shapes the default stdout callback prints: the
# YAML result format the packaged ansible.cfg selects, and the JSON format. Every
# value is a development value: a documentation address (192.0.2.0/24), a
# synthetic tenant account, a zeroed identifier, and a placeholder key.
_GRANT = {
    "action": "node_grant_access",
    "host_id": "node-0000",
    "physical_host_id": "00000000-0000-0000-0000-000000000000",
    "ssh_user": "tenant0000",
    "escrow_uid": "",
    "timestamp": "2000-01-01T00:00:00Z",
    "host": "192.0.2.10",
    "port": "22",
    "status": "success",
}
_RECLAIM = {**_GRANT, "action": "node_reclaim_access", "reclaim_policy": "remove_lease_key"}


def _task(name: str, *result: str) -> str:
    """One task's banner and its ``ok`` line, then its result lines."""
    return "\n".join([f"TASK [{name}] {'*' * 40}", "ok: [node-0000] => ", *result, ""])


def _msg_block(body: str, *, indicator: str = "|-", indent: int = 4) -> str:
    """A ``debug: msg:`` result printed as a YAML literal block."""
    pad = " " * indent
    lines = [f"{pad}msg: {indicator}"]
    lines += [f"{pad}    {line}" if line else "" for line in body.splitlines()]
    return "\n".join(lines)


def _json_msg(document: object, **block) -> str:
    """The JSON text a role's ``to_nice_json`` prints, as a ``msg:`` block."""
    return _msg_block(json.dumps(document, indent=4), **block)


def _yaml_var(fact_name: str, fact: dict) -> str:
    """A ``debug: var:`` result in the YAML format: an unquoted key."""
    lines = [f"    {fact_name}:"]
    lines += [f"        {key}: '{value}'" for key, value in sorted(fact.items())]
    return "\n".join(lines)


def _json_var(fact_name: str, fact: dict) -> str:
    """A ``debug: var:`` result in the JSON format: a quoted key."""
    return json.dumps({fact_name: fact}, indent=4)


def _summary(indicator: str = "|-") -> str:
    """The bare-metal play's prose summary. ansible-core 2.17 to 2.19 print it as
    ``|-``, though its text ends in a newline; ``|`` is the other valid form."""
    return _task(
        "Summary of bare-metal node access operation",
        _msg_block(
            "Bare-metal Node Access Summary:\n"
            "- Target Host: node-0000\n"
            "- Host ID: node-0000\n"
            "- Action Performed: node_grant_access\n"
            "- Operation completed successfully\n",
            indicator=indicator,
        ),
    )


_SUMMARY = _summary()
_RECAP = "PLAY RECAP *****\nnode-0000 : ok=9 changed=2 unreachable=0 failed=0\n"


def _grant_output(*tasks: str) -> str:
    return "\n".join(["PLAY [Bare-metal Node Access Operations] *****", "", *tasks, _RECAP])


def test_the_shipped_yaml_format_is_read_from_its_msg_block() -> None:
    """The packaged configuration prints the ``var:`` fact as YAML, which only the
    ``msg:`` block beside it carries as JSON."""
    stdout = _grant_output(
        _task("Output node_grant_access data as parsable JSON", _yaml_var("node_grant_access_data", _GRANT)),
        _task("Output node_grant_access JSON string for external parsing", _json_msg(_GRANT)),
        _SUMMARY,
    )

    assert extract_fact(stdout, "node_grant_access_data") is None
    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") == _GRANT


@pytest.mark.parametrize("indent", [2, 4])
@pytest.mark.parametrize("indicator", ["|", "|-"])
def test_a_msg_block_is_read_at_any_indentation_and_chomping(indent, indicator) -> None:
    stdout = _grant_output(_task("Output", _json_msg(_GRANT, indent=indent, indicator=indicator)))

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") == _GRANT


def test_the_json_format_is_read_from_its_var_fact() -> None:
    """Under the JSON format the ``msg:`` result is an escaped string, not a block;
    the quoted ``var:`` fact is taken."""
    escaped_msg = json.dumps({"msg": json.dumps(_GRANT, indent=4)}, indent=4)
    stdout = _grant_output(
        _task("Output node_grant_access data as parsable JSON", _json_var("node_grant_access_data", _GRANT)),
        _task("Output node_grant_access JSON string for external parsing", escaped_msg),
    )

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") == _GRANT
    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") == extract_fact(
        stdout, "node_grant_access_data"
    )


def test_the_json_formats_escaped_msg_alone_is_no_fact() -> None:
    """With no ``var:`` fact, the JSON format's escaped ``msg:`` string is not a
    literal block, so nothing is read from it."""
    escaped_msg = json.dumps({"msg": json.dumps(_GRANT, indent=4)}, indent=4)
    stdout = _grant_output(_task("Output node_grant_access JSON string for external parsing", escaped_msg))

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") is None


def test_only_the_expected_actions_block_is_taken_wherever_it_falls() -> None:
    other = {"action": "vm_list", "vm_count": 0}
    stdout = _grant_output(
        _task("Other", _json_msg(other)),
        _task("Grant", _json_msg(_GRANT)),
        _task("Reclaim", _json_msg(_RECLAIM)),
        _SUMMARY,
    )

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") == _GRANT
    assert read_fact(stdout, "node_reclaim_access_data", action="node_reclaim_access") == _RECLAIM
    assert read_fact(stdout, "vm_creation_data", action="create") is None


def test_the_last_block_for_the_expected_action_is_taken() -> None:
    first = {**_GRANT, "timestamp": "2000-01-01T00:00:00Z"}
    last = {**_GRANT, "timestamp": "2000-01-01T00:00:01Z"}
    stdout = _grant_output(_task("Grant", _json_msg(first)), _task("Grant again", _json_msg(last)))

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") == last


@pytest.mark.parametrize("indicator", ["|-", "|"])
def test_the_plays_summary_block_alone_is_no_fact(indicator) -> None:
    stdout = _grant_output(_summary(indicator))

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") is None


def test_a_later_document_outside_a_msg_block_is_not_adopted() -> None:
    """Only ``msg:`` blocks are read: a later task's document for the action, under
    another key or bare in the output, is not taken after the summary block, as a
    forward scan from the summary's ``msg:`` to the next ``{`` would take it. That a
    block ends at its own indentation is shown by the malformed-block and
    sibling-key cases."""
    later = _task(
        "Record the grant for an operator",
        "    stdout: |-",
        *(f"        {line}" for line in json.dumps(_GRANT, indent=4).splitlines()),
    )
    bare = json.dumps(_GRANT, indent=4)
    stdout = _grant_output(_SUMMARY, later, bare)

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") is None


def test_a_malformed_block_and_an_unrelated_document_after_it_are_neither_taken() -> None:
    truncated = json.dumps(_GRANT, indent=4)[:-40]
    stdout = _grant_output(
        _task("Grant", _msg_block(truncated)),
        _task("Unrelated", _json_msg(_RECLAIM)),
    )

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") is None
    # The malformed block ended at its own boundary; the next block is read on its own.
    assert read_fact(stdout, "node_reclaim_access_data", action="node_reclaim_access") == _RECLAIM


@pytest.mark.parametrize(
    "document",
    [
        {key: value for key, value in _GRANT.items() if key != "action"},
        [_GRANT],
        "node_grant_access",
        None,
    ],
    ids=["no action", "a list", "a string", "null"],
)
def test_a_document_that_is_not_an_object_naming_an_action_is_ignored(document) -> None:
    stdout = _grant_output(_task("Grant", _json_msg(document)))

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") is None


def test_a_block_nested_too_deeply_to_parse_is_ignored() -> None:
    stdout = _grant_output(_task("Deep", _msg_block("[" * 100_000)), _task("Grant", _json_msg(_GRANT)))

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") == _GRANT


def test_a_block_ends_at_a_sibling_key_and_keeps_its_blank_lines() -> None:
    body = json.dumps(_GRANT, indent=4).replace('"host": "192.0.2.10",', '"host": "192.0.2.10",\n')
    stdout = _grant_output(_task("Grant", _msg_block(body), "    changed: false"))

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") == _GRANT


def test_no_fact_at_all_is_absent() -> None:
    stdout = _grant_output(_task("Gather", "    changed: false"))

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") is None
    assert read_fact("", "node_grant_access_data", action="node_grant_access") is None


def test_ignored_blocks_are_counted_in_the_debug_log_without_their_content(caplog) -> None:
    secret = "placeholder-private-key-not-a-real-key"
    stdout = _grant_output(
        _task("Malformed", _msg_block('{"action": "node_grant_access", "key": "' + secret)),
        _task("No action", _json_msg({"key": secret})),
        _task("Not an object", _json_msg([secret])),
        _task("Other action", _json_msg({**_RECLAIM, "key": secret})),
        _SUMMARY,
    )
    caplog.set_level(logging.DEBUG, logger="compute_provisioning_ansible.runner")

    assert read_fact(stdout, "node_grant_access_data", action="node_grant_access") is None

    messages = [record.getMessage() for record in caplog.records]
    assert messages, "the reader logs what it ignored"
    logged = "\n".join(messages)
    assert "5 ignored" in logged
    for reason in ("not_json=2", "not_object=1", "no_action=1", "other_action=1"):
        assert reason in logged
    for content in (secret, "tenant0000", "192.0.2.10", "Summary"):
        assert content not in logged


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
