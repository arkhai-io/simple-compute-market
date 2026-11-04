import json
import multiprocessing
import os

import pytest

from conftest import FakeHost, request
from tenant_working_data import Refusal, Store


def allocate(policy, reservation, account, queue):
    try:
        queue.put(Store(policy, owner=os.getuid(), host=FakeHost()).execute(request(reservation, account)))
    except Exception as error:
        queue.put(repr(error))


def read(installation):
    return json.loads((installation.root / "state/ledger.json").read_text())


def test_failed_create_consumption_and_same_retry(installation):
    first = installation.store.execute(request())
    assert first["uid"] == first["gid"] == 41000
    assert installation.store.execute(request()) == first
    second = installation.store.execute(request("fixture-b", "tenant_b"))
    assert second["uid"] == 41001
    assert read(installation)["consumed"] == [41000, 41001]
    with pytest.raises(Refusal):
        installation.store.execute(request("fixture-b", "tenant_a"))
    with pytest.raises(Refusal):
        installation.store.execute(request("fixture-c", "tenant_a"))


def test_competing_processes(installation):
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    jobs = [context.Process(target=allocate, args=(installation.path, f"fixture-{i}", f"tenant_{i}", queue)) for i in range(4)]
    for job in jobs:
        job.start()
    answers = [queue.get(timeout=15) for _ in jobs]
    for job in jobs:
        job.join(15)
        assert job.exitcode == 0
    assert sorted(a["uid"] for a in answers) == [41000, 41001, 41002, 41003]
    assert len(read(installation)["receipts"]) == 4


@pytest.mark.parametrize("kind", ["uid", "gid", "primary-gid", "username", "groupname"])
def test_nss_conflicts(installation, kind):
    if kind == "uid":
        installation.host.user("service_fixture", 41000, gid=900)
    elif kind == "gid":
        installation.host.group("service_fixture", 41000)
    elif kind == "primary-gid":
        installation.host.user("service_fixture", 900, gid=41000)
    elif kind == "username":
        installation.host.user("tenant_a", 42000)
    else:
        installation.host.group("tenant_a", 42000)
    if kind in ("username", "groupname"):
        with pytest.raises(Refusal):
            installation.store.execute(request())
    else:
        assert installation.store.execute(request())["uid"] == 41001


def test_exhaustion_and_exclusions(installation):
    for i in range(11):
        installation.store.execute(request(f"fixture-{i}", f"tenant_{i}"))
    before = read(installation)
    with pytest.raises(Refusal, match="exhausted"):
        installation.store.execute(request("fixture-extra", "tenant_extra"))
    assert read(installation) == before


@pytest.mark.parametrize("name", ["policy.json", "state/ledger.json", "state/lock"])
@pytest.mark.parametrize("fault", ["symlink", "hardlink", "mode", "type"])
def test_protected_objects(installation, name, fault):
    path = installation.root / name
    if fault in ("symlink", "type"):
        path.unlink()
        if fault == "symlink":
            path.symlink_to(installation.root / "missing")
        else:
            path.mkdir()
    elif fault == "hardlink":
        os.link(path, installation.root / "link")
    else:
        path.chmod(0o666)
    with pytest.raises((Refusal, OSError)):
        Store(installation.path, owner=os.getuid(), host=installation.host).execute(request())


@pytest.mark.parametrize("fault", ["missing", "corrupt", "mismatched", "lost-receipt"])
def test_established_history_never_reinitialized(installation, fault):
    installation.store.execute(request())
    path = installation.root / "state/ledger.json"
    if fault == "missing":
        path.unlink()
    elif fault == "corrupt":
        path.write_text("{")
    else:
        ledger = read(installation)
        ledger["policy_digest" if fault == "mismatched" else "receipts"] = "wrong" if fault == "mismatched" else {}
        path.write_text(json.dumps(ledger))
    with pytest.raises((Refusal, OSError, ValueError)):
        installation.store.execute(request())
    with pytest.raises((Refusal, OSError)):
        installation.store.initialize()


@pytest.mark.parametrize("failure", ["file-fsync", "replace", "directory-fsync"])
def test_interrupted_atomic_write(installation, failure):
    before = read(installation)
    calls = []
    def sync(fd):
        calls.append(fd)
        if failure == "file-fsync" or (failure == "directory-fsync" and len(calls) == 2):
            raise OSError("injected fsync failure")
        os.fsync(fd)
    def replace(*args, **kwargs):
        if failure == "replace":
            raise OSError("injected replace failure")
        os.replace(*args, **kwargs)
    store = Store(installation.path, owner=os.getuid(), host=installation.host, fsync=sync, replace=replace)
    with pytest.raises(OSError):
        store.execute(request())
    ledger = read(installation)
    assert ledger == before if failure != "directory-fsync" else ledger["consumed"] == [41000]
    assert set(p.name for p in (installation.root / "state").iterdir()) == {"ledger.json", "lock"}
    recovered = installation.store.execute(request())
    assert recovered["uid"] == 41000
    assert read(installation)["consumed"] == [41000]


def test_service_restore_does_not_touch_host_ledger(installation):
    first = installation.store.execute(request())
    service = installation.root / "service-fixture.json"
    service.write_text('{"version":1}')
    service.write_text('{"version":0}')
    redeployed = Store(installation.path, owner=os.getuid(), host=FakeHost())
    assert redeployed.execute(request()) == first
    assert redeployed.execute(request("fixture-b", "tenant_b"))["uid"] == 41001


def test_retry_detects_account_drift(installation):
    receipt = installation.store.execute(request())
    installation.host.user("tenant_a", receipt["uid"], home=receipt["home"])
    installation.host.group("tenant_a", receipt["gid"])
    assert installation.store.execute(request())["uid"] == receipt["uid"]
    installation.host.user("foreign_fixture", 900, gid=receipt["gid"])
    with pytest.raises(Refusal):
        installation.store.execute(request())


def test_competing_exact_retries(installation):
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    jobs = [context.Process(target=allocate, args=(installation.path, "fixture-a", "tenant_a", queue)) for _ in range(3)]
    for job in jobs:
        job.start()
    answers = [queue.get(timeout=15) for _ in jobs]
    for job in jobs:
        job.join(15)
        assert job.exitcode == 0
    assert all(answer == answers[0] for answer in answers)
    assert read(installation)["consumed"] == [41000]


def test_excluded_identity_and_owner_rejection(installation):
    policy = installation.policy
    policy["exclude_ids"] = [41000]
    installation.path.write_text(json.dumps(policy))
    store = Store(installation.path, owner=os.getuid(), host=installation.host)
    with pytest.raises(Refusal, match="mismatch"):
        store.execute(request())
    with pytest.raises(Refusal):
        Store(installation.path, owner=os.getuid() + 1)


@pytest.mark.parametrize("key,value", [("operation", "reset"), ("version", 2), ("version", True), ("reservation_id", ""), ("account", "root"), ("account", "tenant_../a"), ("policy_id", "")])
def test_rejects_request(installation, key, value):
    value_request = request()
    value_request[key] = value
    with pytest.raises(Refusal):
        installation.store.execute(value_request)
    assert json.loads((installation.root / "state/ledger.json").read_text())["consumed"] == []


def test_provider_username_and_direct_nss(installation):
    assert installation.store.execute(request(account="arkhai-example"))["account"] == "arkhai-example"
    host = FakeHost()
    host.user("invisible_fixture", 41001)
    host.group("invisible_fixture", 41002)
    host.users = lambda: []
    host.groups = lambda: []
    store = Store(installation.path, owner=os.getuid(), host=host)
    assert store.execute(request("fixture-b", "arkhai-another"))["uid"] == 41003
    host.user("arkhai-third", 42000)
    with pytest.raises(Refusal, match="unreceipted"):
        store.execute(request("fixture-c", "arkhai-third"))


def test_inspect_is_read_only_and_never_allocates(installation):
    store = installation.store
    ledger = installation.root / "state/ledger.json"
    before = ledger.read_bytes()
    with pytest.raises(Refusal, match="missing receipt"):
        store.execute(request(operation="inspect"))
    assert ledger.read_bytes() == before
    receipt = store.execute(request())
    before = ledger.read_bytes()
    assert store.execute(request(operation="inspect"))["uid"] == receipt["uid"]
    assert ledger.read_bytes() == before
    with pytest.raises(Refusal, match="reservation/account mismatch"):
        store.execute(request(account="other_tenant", operation="inspect"))
    assert ledger.read_bytes() == before
    installation.host.user("foreign", receipt["uid"], home=receipt["home"])
    with pytest.raises(Refusal, match="account identity conflict"):
        store.execute(request(operation="inspect"))
    assert ledger.read_bytes() == before


def test_inspect_complete_receipt_rechecks_identity_without_mutating(installation):
    store = installation.store
    receipt = store.execute(request())
    installation.host.quiescent = lambda uid: None
    installation.host.ipc = lambda: []
    store.execute(request(operation="verify-complete"))
    ledger = installation.root / "state/ledger.json"
    before = ledger.read_bytes()
    assert store.execute(request(operation="inspect"))["state"] == "complete"
    assert ledger.read_bytes() == before
    installation.host.group("tenant_a", receipt["gid"])
    with pytest.raises(Refusal, match="private group conflict"):
        store.execute(request(operation="inspect"))
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("key", ["not-a-key", "ssh-ed25519 !!!", "ssh-ed25519 AAAA\nssh-ed25519 AAAA", 17])
def test_key_installation_refuses_invalid_public_keys_before_path_effects(installation, key):
    receipt = installation.store.execute(request())
    installation.host.user("tenant_a", receipt["uid"], home=receipt["home"])
    installation.host.group("tenant_a", receipt["gid"])
    before = (installation.root / "state/ledger.json").read_bytes()
    with pytest.raises(Refusal, match="invalid SSH public key"):
        installation.store.execute({**request(operation="install-key"), "ssh_public_key": key})
    assert not os.path.lexists(receipt["home"])
    assert (installation.root / "state/ledger.json").read_bytes() == before


@pytest.mark.parametrize("operation", ["reserve", "inspect", "revoke-key"])
def test_only_key_installation_accepts_a_public_key_field(installation, operation):
    with pytest.raises(Refusal, match="invalid fields"):
        installation.store.execute({**request(operation=operation), "ssh_public_key": "unused"})
