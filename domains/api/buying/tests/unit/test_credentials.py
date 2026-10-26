"""The file credential store and the run log that never records a delivered secret."""

from __future__ import annotations

import json
import os
import stat
import uuid

import pytest
from core_buyer.negotiation_client import AuthenticatedHTTPError
from core_buyer.run_log import RunLog, RunLogError
from market_identity import Eip191Signer

from arkhai_api_buying.credentials import (
    CredentialStoreError,
    DeliveryRunLog,
    FileCredentialStore,
    error_text,
    public_fields,
    public_text,
    record_delivery,
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

    def refuse(*_args, **_kwargs):
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


def test_a_link_swapped_in_after_any_check_cannot_redirect_the_write(state, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    state.parent.mkdir(parents=True)
    state.symlink_to(elsewhere)
    # The attacker wins every race a path check could lose.
    monkeypatch.setattr(type(state), "is_symlink", lambda self: False)

    with pytest.raises(CredentialStoreError):
        FileCredentialStore().save("run-1", _CREDENTIALS)
    assert list(elsewhere.iterdir()) == []


def test_missing_directories_are_created_private(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    FileCredentialStore().save("run-1", _CREDENTIALS)

    for directory in (tmp_path / "state", tmp_path / "state" / "arkhai", tmp_path / "state" / "arkhai" / "buy-credentials"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_a_directory_others_can_write_is_refused(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    os.chmod(shared, 0o777)
    monkeypatch.setenv("XDG_STATE_HOME", str(shared / "state"))

    with pytest.raises(CredentialStoreError, match="writable by another user"):
        FileCredentialStore().save("run-1", _CREDENTIALS)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604])
def test_a_record_others_can_read_is_refused(state, mode):
    store = FileCredentialStore()
    store.save("run-1", _CREDENTIALS)
    os.chmod(state / "run-1.json", mode)

    with pytest.raises(CredentialStoreError, match="not private"):
        store.load("file:run-1")


def test_the_store_names_where_a_reference_lives(state):
    store = FileCredentialStore()
    assert store.reference("run-1") == "file:run-1"
    assert store.location("file:run-1") == str(state / "run-1.json")


def test_error_text_never_quotes_a_seller_error_body():
    body = {"status": "ready", "tenant_credentials": dict(_CREDENTIALS)}
    exc = AuthenticatedHTTPError(
        f"GET http://seller/api/v1/settle/x/status -> authenticated HTTP 409: {json.dumps(body)}",
        status_code=409, body=body,
    )

    text = error_text(exc)

    assert "sk_canary" not in text
    assert text == "GET http://seller/api/v1/settle/x/status -> authenticated HTTP 409"


@pytest.mark.parametrize(
    "text",
    [
        'refused: {"tenant_credentials": {"secret": "sk_canary", "key_id": "ak_1"}}',
        "refused: {'secret': 'sk_canary'}",
        'truncated: {"secret": "sk_can',
    ],
)
def test_public_text_redacts_a_quoted_secret(text):
    assert "sk_can" not in public_text(text)


def test_the_delivery_run_log_redacts_secrets_inside_strings(state):
    log = DeliveryRunLog.of(RunLog.start(profile_id=uuid.uuid4(), principal=_SIGNER.identity))

    log.event("settle_status", body={"tenant_credentials": dict(_CREDENTIALS)})
    log.event("settlement_failed", error="seller said sk_canary was already issued")
    log.event("settle_submit_failed", error='{"secret": "sk_other"}')

    text = log.path.read_text()
    assert "sk_canary" not in text and "sk_other" not in text


def test_a_body_carrying_the_key_does_not_stop_the_flow_when_the_log_refuses_it(state, monkeypatch):
    log = DeliveryRunLog.of(RunLog.start(profile_id=uuid.uuid4(), principal=_SIGNER.identity))

    def full(self, event, **fields):
        raise OSError("disk full")

    monkeypatch.setattr(RunLog, "event", full)
    log.event("settle_status", body={"tenant_credentials": dict(_CREDENTIALS)})
    log.event("settle_submitted", body={"status": "queued"})

    assert log.failed


def test_a_log_that_refused_an_append_writes_nothing_more(state, monkeypatch):
    log = DeliveryRunLog.of(RunLog.start(profile_id=uuid.uuid4(), principal=_SIGNER.identity))
    real = RunLog.event
    calls = []

    def once(self, event, **fields):
        calls.append(event)
        if len(calls) == 1:
            raise OSError("fsync failed")
        real(self, event, **fields)

    monkeypatch.setattr(RunLog, "event", once)
    with pytest.raises(OSError):
        log.event("settle_submitted", body={"status": "queued"})
    with pytest.raises(RunLogError, match="refused an earlier append"):
        log.event("settle_status", body={"status": "provisioning"})
    assert calls == ["settle_submitted"]


def test_a_delivery_after_a_refused_append_is_reported_unrecorded(state, monkeypatch):
    log = DeliveryRunLog.of(RunLog.start(profile_id=uuid.uuid4(), principal=_SIGNER.identity))
    monkeypatch.setattr(RunLog, "event", lambda self, event, **fields: (_ for _ in ()).throw(OSError("full")))
    log.event("settle_status", body={"tenant_credentials": dict(_CREDENTIALS)})

    delivery = record_delivery(log, dict(_CREDENTIALS), FileCredentialStore())

    assert delivery.unrecorded and delivery.reference == f"file:{log.run_id}"


def test_a_group_writable_arkhai_directory_is_refused(state):
    state.parent.mkdir(parents=True)
    os.chmod(state.parent, 0o775)

    with pytest.raises(CredentialStoreError, match="writable by another user"):
        FileCredentialStore().save("run-1", _CREDENTIALS)
    assert stat.S_IMODE(state.parent.stat().st_mode) == 0o775


def test_a_save_sweeps_temporaries_an_interrupted_save_left(state):
    store = FileCredentialStore()
    store.save("run-1", _CREDENTIALS)
    (state / ".run-1.json.abcdef.tmp").write_text("{}")

    store.save("run-1", _CREDENTIALS)

    assert sorted(p.name for p in state.iterdir()) == ["run-1.json"]


def test_a_failed_directory_sync_after_the_rename_still_counts_as_saved(state, monkeypatch):
    store = FileCredentialStore()
    real = os.fsync

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("fsync failed")
        real(fd)

    monkeypatch.setattr(os, "fsync", fsync)

    assert store.save("run-1", _CREDENTIALS) == "file:run-1"
    monkeypatch.setattr(os, "fsync", real)
    assert store.load("file:run-1") == _CREDENTIALS


def test_a_directory_that_cannot_be_opened_is_a_store_refusal(state, monkeypatch):
    FileCredentialStore().save("run-1", _CREDENTIALS)
    real = os.open

    def refuse(path, flags, *args, **kwargs):
        if path == "buy-credentials":
            raise PermissionError(13, "Permission denied")
        return real(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", refuse)

    with pytest.raises(CredentialStoreError, match="cannot be opened"):
        FileCredentialStore().load("file:run-1")
