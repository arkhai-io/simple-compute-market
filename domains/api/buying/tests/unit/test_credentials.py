"""The file credential store and the run log that never records a delivered secret."""

from __future__ import annotations

import json
import os
import stat
import uuid

import pytest
from core_buyer.run_log import RunLog
from market_identity import Eip191Signer

from arkhai_api_buying.credentials import (
    CredentialStoreError,
    DeliveryRunLog,
    FileCredentialStore,
    public_fields,
)

# Deterministic development key; never use it on a public network.
_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
_CREDENTIALS = {"key_id": "ak_1", "secret": "sk_canary", "base_url": "http://api", "balance": 3}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return tmp_path / "arkhai" / "buy-credentials"


def test_a_saved_credential_is_private_and_loads_by_reference(state):
    store = FileCredentialStore()

    reference = store.save("run-1", _CREDENTIALS)

    assert reference == "file:run-1"
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    path = state / "run-1.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.load(reference) == _CREDENTIALS
    assert [p.name for p in state.iterdir()] == ["run-1.json"]


def test_a_second_save_replaces_the_record(state):
    store = FileCredentialStore()
    store.save("run-1", _CREDENTIALS)
    store.save("run-1", {**_CREDENTIALS, "balance": 1})

    assert store.load("file:run-1")["balance"] == 1


def test_a_loose_directory_is_tightened(state):
    state.mkdir(parents=True, mode=0o755)
    os.chmod(state, 0o755)

    FileCredentialStore().save("run-1", _CREDENTIALS)

    assert stat.S_IMODE(state.stat().st_mode) == 0o700


def test_a_symlinked_directory_is_refused(state, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    state.parent.mkdir(parents=True)
    state.symlink_to(elsewhere)

    with pytest.raises(CredentialStoreError, match="symbolic link"):
        FileCredentialStore().save("run-1", _CREDENTIALS)
    assert list(elsewhere.iterdir()) == []


def test_a_symlinked_file_is_refused_on_write_and_read(state, tmp_path):
    target = tmp_path / "target.json"
    target.write_text(json.dumps({"credentials": _CREDENTIALS}))
    state.mkdir(parents=True)
    (state / "run-1.json").symlink_to(target)
    store = FileCredentialStore()

    with pytest.raises(CredentialStoreError, match="symbolic link"):
        store.save("run-1", _CREDENTIALS)
    with pytest.raises(CredentialStoreError, match="cannot be opened safely"):
        store.load("file:run-1")


@pytest.mark.parametrize("run_id", ["../escape", ".hidden", "a/b", ""])
def test_a_run_id_that_is_not_a_file_name_is_refused(state, run_id):
    with pytest.raises(CredentialStoreError, match="plain file name"):
        FileCredentialStore().save(run_id, _CREDENTIALS)


def test_a_missing_record_loads_as_none_and_a_foreign_scheme_is_refused(state):
    store = FileCredentialStore()

    assert store.load("file:run-1") is None
    with pytest.raises(CredentialStoreError, match="not held by the file store"):
        store.load("keyring:run-1")


def test_public_fields_strips_the_secret_at_any_depth():
    body = {
        "status": "ready",
        "body": {"tenant_credentials": dict(_CREDENTIALS)},
        "history": [{"tenant_credentials": dict(_CREDENTIALS)}],
        "secret": "kept: not a delivered credential",
    }

    public = public_fields(body)

    assert "sk_canary" not in json.dumps(public)
    assert public["body"]["tenant_credentials"] == {"key_id": "ak_1", "base_url": "http://api", "balance": 3}
    assert public["secret"] == body["secret"]


def test_the_delivery_run_log_never_writes_the_secret(state):
    log = DeliveryRunLog.of(RunLog.start(profile_id=uuid.uuid4(), principal=_SIGNER.identity))

    log.event("settle_status", attempt=1, body={"status": "ready", "tenant_credentials": dict(_CREDENTIALS)})
    log.end("ready")

    text = log.path.read_text()
    assert "sk_canary" not in text
    assert '"key_id":"ak_1"' in text


def test_a_failed_replace_keeps_the_old_record_and_leaves_no_temporary(state, monkeypatch):
    store = FileCredentialStore()
    store.save("run-1", _CREDENTIALS)

    def refuse(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError):
        store.save("run-1", {**_CREDENTIALS, "balance": 0})

    assert store.load("file:run-1") == _CREDENTIALS
    assert [p.name for p in state.iterdir()] == ["run-1.json"]


@pytest.mark.parametrize("content", ["{not json", "{}", '{"credentials": 3}'])
def test_an_unreadable_record_is_refused_without_its_content(state, content):
    state.mkdir(parents=True)
    (state / "run-1.json").write_text(content)

    with pytest.raises(CredentialStoreError, match="unreadable") as refused:
        FileCredentialStore().load("file:run-1")
    assert refused.value.__cause__ is None


def test_a_symlinked_directory_is_refused_on_read(state, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "run-1.json").write_text(json.dumps({"credentials": _CREDENTIALS}))
    state.parent.mkdir(parents=True)
    state.symlink_to(elsewhere)

    with pytest.raises(CredentialStoreError, match="symbolic link"):
        FileCredentialStore().load("file:run-1")
