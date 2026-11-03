import base64
import json
import os
from pathlib import Path

import pytest

from conftest import FakeHost, request
from tenant_working_data import LinuxHost, Refusal, Store, Tree, mount_id


class ObservedHost(FakeHost):
    def __init__(self):
        super().__init__()
        self.records = []
        self.process_uids = []
        self.removed = []
        self.denied = None
        self.after_inventory = None
        self.inventories = 0

    def quiescent(self, uid):
        if self.denied == "process":
            raise PermissionError("injected process observation denied")
        if any(uid in fields for fields in self.process_uids):
            raise Refusal("tenant process remains")

    def ipc(self):
        self.inventories += 1
        if self.denied == "ipc":
            raise PermissionError("injected IPC observation denied")
        result = [dict(row) for row in self.records]
        if self.after_inventory is not None:
            self.after_inventory(self)
        return result

    def remove_ipc(self, record):
        if self.denied == "remove":
            raise PermissionError("injected IPC removal denied")
        self.removed.append(record)
        self.records.remove(record)


@pytest.fixture
def cleanup_installation(installation):
    # Only NSS/kernel/process observations are injected. Ownership, mounts and
    # traversal use actual disposable files belonging to this test process.
    policy = installation.policy
    policy["uid_min"] = os.getuid()
    policy["uid_max"] = os.getuid() + 10
    require_supported_uid = os.getuid() >= 1000
    assert require_supported_uid, "default filesystem fixtures require a non-system test user"
    with os.scandir(installation.root / "scratch"):
        fd = os.open(installation.root / "scratch", os.O_RDONLY | os.O_DIRECTORY)
        try:
            policy["mount_ids"] = [mount_id(fd)]
        finally:
            os.close(fd)
    installation.path.write_text(json.dumps(policy))
    # A new installation fixture is explicit; an established ledger is never
    # rewritten by the helper to accept a different policy.
    ledger = installation.root / "state/ledger.json"
    ledger.unlink()
    (installation.root / "state/lock").unlink()
    host = ObservedHost()
    store = Store(installation.path, owner=os.getuid(), host=host)
    store.initialize()
    installation.store, installation.host = store, host
    installation.receipt = store.execute(request())
    return installation


def run(installation, operation):
    return installation.store.execute(request(operation=operation))


def state(installation):
    return json.loads((installation.root / "state/ledger.json").read_text())


def ipc_record(uid, kind="shm", identifier=1, creator=None):
    return {"kind": kind, "id": identifier, "uid": uid, "cuid": uid if creator is None else creator, "fingerprint": {"ctime": "123"}}


def test_real_tree_cleanup_preserves_symlink_targets_and_external_hardlinks(cleanup_installation):
    installation = cleanup_installation
    root = installation.root
    external = root / "outside"
    external.mkdir(mode=0o700)
    target = external / "sentinel"
    target.write_text("keep")
    scratch = root / "scratch"
    (scratch / "owned").mkdir(mode=0o700)
    (scratch / "owned/file").write_text("remove")
    (scratch / "link").symlink_to(target)
    (scratch / "directory-link").symlink_to(external, target_is_directory=True)
    os.link(target, scratch / "hardlink")
    os.mkfifo(scratch / "fifo")
    home = Path(installation.receipt["home"])
    home.mkdir(mode=0o700)
    (home / "data").write_text("home")
    result = run(installation, "clean")
    assert result["state"] == "cleaned"
    assert list(scratch.iterdir()) == []
    assert target.read_text() == "keep"
    assert (home / "data").read_text() == "home"
    run(installation, "remove-home")
    assert not home.exists()
    assert run(installation, "verify-complete")["state"] == "complete"
    assert state(installation)["consumed"] == [os.getuid()]
    assert run(installation, "verify-complete")["state"] == "complete"
    with pytest.raises(Refusal, match="completed"):
        run(installation, "reserve")


@pytest.mark.parametrize("operation", ["reserve", "verify-identity", "install-key"])
def test_grant_refuses_once_cleanup_started_and_cleanup_still_retries(cleanup_installation, operation):
    installation = cleanup_installation
    receipt = installation.receipt
    home = Path(receipt["home"])
    home.mkdir(mode=0o700)
    (home / "data").write_text("home")
    # The account still exists between clean and its deletion, so only the
    # receipt state stands between a grant and a reinstalled key.
    installation.host.user("tenant_a", receipt["uid"], home=receipt["home"])
    installation.host.group("tenant_a", receipt["gid"])
    assert run(installation, "clean")["state"] == "cleaned"
    ledger = installation.root / "state/ledger.json"
    before = ledger.read_bytes()
    grant = request(operation=operation)
    if operation == "install-key":
        blob = len(b"ssh-ed25519").to_bytes(4, "big") + b"ssh-ed25519" + (32).to_bytes(4, "big") + bytes(32)
        grant["ssh_public_key"] = "ssh-ed25519 " + base64.b64encode(blob).decode()
    with pytest.raises(Refusal, match="in cleanup cannot grant"):
        installation.store.execute(grant)
    assert ledger.read_bytes() == before
    assert not (home / ".ssh").exists()
    assert run(installation, "clean")["state"] == "cleaned"
    installation.host.user_rows.clear()
    installation.host.group_rows.clear()
    run(installation, "remove-home")
    assert not home.exists()
    assert run(installation, "verify-complete")["state"] == "complete"


def test_missing_paths_reserved_account_and_complete_retry(cleanup_installation):
    installation = cleanup_installation
    assert run(installation, "verify-complete")["state"] == "complete"
    (installation.root / "scratch/new").write_text("late data")
    with pytest.raises(Refusal, match="remains"):
        run(installation, "verify-complete")
    assert state(installation)["receipts"]["fixture-a"]["state"] == "complete"
    run(installation, "clean")
    assert run(installation, "verify-complete")["state"] == "complete"


def test_account_absence_does_not_skip_cleanup(cleanup_installation):
    installation = cleanup_installation
    (installation.root / "ipc/posix-object").write_text("covered")
    installation.host.records = [ipc_record(os.getuid(), kind, i) for i, kind in enumerate(("shm", "sem", "msg"))]
    with pytest.raises(Refusal):
        run(installation, "verify-complete")
    result = run(installation, "clean")
    assert result["observations"]["ipc_removed"] == 3
    assert len(installation.host.removed) == 3
    assert list((installation.root / "ipc").iterdir()) == []
    assert run(installation, "verify-complete")["state"] == "complete"


@pytest.mark.parametrize("field", range(4))
def test_any_process_uid_field_blocks(cleanup_installation, field):
    installation = cleanup_installation
    fields = [99999] * 4
    fields[field] = os.getuid()
    installation.host.process_uids = [fields]
    with pytest.raises(Refusal, match="process"):
        run(installation, "clean")
    assert state(installation)["receipts"]["fixture-a"]["state"] == "reserved"


@pytest.mark.parametrize("denied", ["process", "ipc", "remove"])
def test_observation_and_removal_failures_leave_retryable_receipt(cleanup_installation, denied):
    installation = cleanup_installation
    installation.host.records = [ipc_record(os.getuid())]
    installation.host.denied = denied
    with pytest.raises(PermissionError):
        run(installation, "clean")
    assert state(installation)["receipts"]["fixture-a"]["state"] == "reserved"
    installation.host.denied = None
    run(installation, "clean")
    assert run(installation, "verify-complete")["state"] == "complete"


@pytest.mark.parametrize("owner_matches", [True, False])
def test_mixed_ipc_attribution_preflight_deletes_nothing(cleanup_installation, owner_matches):
    installation = cleanup_installation
    uid = os.getuid()
    installation.host.records = [ipc_record(uid if owner_matches else uid + 100, creator=uid + 100 if owner_matches else uid)]
    data = installation.root / "scratch/data"
    data.write_text("keep on refusal")
    with pytest.raises(Refusal, match="ambiguous"):
        run(installation, "clean")
    assert data.exists() and not installation.host.removed


@pytest.mark.parametrize("change", ["disappear", "reuse"])
def test_recycled_or_disappeared_ipc_id_refuses(cleanup_installation, change):
    installation = cleanup_installation
    installation.host.records = [ipc_record(os.getuid())]
    def mutate(host):
        if host.inventories == 1:
            if change == "disappear":
                host.records = []
            else:
                host.records[0]["fingerprint"] = {"ctime": "124"}
    installation.host.after_inventory = mutate
    with pytest.raises(Refusal, match="identity drift"):
        run(installation, "clean")
    assert not installation.host.removed


def test_unrelated_ipc_survives(cleanup_installation):
    installation = cleanup_installation
    unrelated = ipc_record(os.getuid() + 100)
    installation.host.records = [unrelated, ipc_record(os.getuid(), "msg", 2)]
    run(installation, "clean")
    assert installation.host.records == [unrelated]
    assert run(installation, "verify-complete")["state"] == "complete"


def test_home_requires_account_removed_and_completion_requires_group_absent(cleanup_installation):
    installation = cleanup_installation
    receipt = installation.receipt
    home = Path(receipt["home"])
    home.mkdir(mode=0o700)
    installation.host.user("tenant_a", receipt["uid"], home=str(home))
    installation.host.group("tenant_a", receipt["gid"])
    run(installation, "clean")
    with pytest.raises(Refusal, match="account must"):
        run(installation, "remove-home")
    installation.host.user_rows = []
    run(installation, "remove-home")
    with pytest.raises(Refusal, match="group"):
        run(installation, "verify-complete")
    installation.host.group_rows = []
    assert run(installation, "verify-complete")["state"] == "complete"


def test_directory_replacement_refuses_and_retry_recovers(cleanup_installation):
    installation = cleanup_installation
    scratch = installation.root / "scratch"
    (scratch / "data").mkdir(mode=0o700)
    (scratch / "data/old").write_text("keep")
    fired = []
    def replace(parent, name):
        if name == "data" and not fired:
            fired.append(True)
            os.rename("data", "outside-preflight", src_dir_fd=parent, dst_dir_fd=parent)
            os.mkdir("data", mode=0o700, dir_fd=parent)
    installation.store.before_remove = replace
    with pytest.raises(Refusal, match="identity drift"):
        run(installation, "clean")
    assert (scratch / "outside-preflight/old").exists()
    installation.store.before_remove = None
    run(installation, "clean")
    assert list(scratch.iterdir()) == []


def test_mount_identity_refuses_same_device_boundary(cleanup_installation):
    installation = cleanup_installation
    data = installation.root / "scratch/data"
    data.write_text("preserve")
    real = mount_id
    def mounts(fd):
        if Path(f"/proc/self/fd/{fd}").readlink() == data:
            return real(fd) + 100000
        return real(fd)
    installation.store.mounts = mounts
    with pytest.raises(Refusal, match="mount boundary"):
        run(installation, "clean")
    assert data.read_text() == "preserve"


def test_home_symlink_is_unlinked_without_following(cleanup_installation):
    installation = cleanup_installation
    outside = installation.root / "outside"
    outside.mkdir(mode=0o700)
    (outside / "sentinel").write_text("keep")
    home = Path(installation.receipt["home"])
    home.symlink_to(outside, target_is_directory=True)
    run(installation, "clean")
    run(installation, "remove-home")
    assert not home.is_symlink() and (outside / "sentinel").read_text() == "keep"


def test_process_and_ipc_kernel_interface_parsing(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir(mode=0o700)
    (proc / "42/task/42").mkdir(parents=True)
    status = proc / "42/task/42/status"
    status.write_text("Name:\tfixture\nUid:\t1000\t1001\t1002\t1003\n")
    host = LinuxHost(proc_root=proc)
    for uid in range(1000, 1004):
        with pytest.raises(Refusal, match="process"):
            host.quiescent(uid)
    host.quiescent(1004)
    status.write_text("Uid:\t1000\t1001\n")
    with pytest.raises(Refusal):
        host.quiescent(1004)
    ipc = proc / "sysvipc"
    ipc.mkdir(mode=0o700)
    for kind, column in (("shm", "shmid"), ("sem", "semid"), ("msg", "msqid")):
        (ipc / kind).write_text(f"key {column} uid cuid ctime\n0 123 1000 1000 42\n")
    assert {row["kind"] for row in host.ipc()} == {"shm", "sem", "msg"}
    (ipc / "sem").unlink()
    with pytest.raises(FileNotFoundError):
        host.ipc()


def test_foreign_candidate_is_never_removed(tmp_path):
    path = tmp_path / "foreign"
    path.mkdir(mode=0o700)
    (path / "sentinel").write_text("keep")
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        tree = Tree(fd, os.getuid() + 1000, [mount_id(fd)])
        plan = tree.inspect(fd, "foreign")
        assert tree.remove(fd, "foreign", plan) == 0
        with pytest.raises(Refusal, match="foreign descendant"):
            tree.inspect(fd, "foreign", selected=True)
    finally:
        os.close(fd)
    assert (path / "sentinel").read_text() == "keep"


def test_verify_identity_requires_created_account_and_private_group(cleanup_installation):
    installation = cleanup_installation
    with pytest.raises(Refusal, match="absent"):
        run(installation, "verify-identity")
    receipt = installation.receipt
    installation.host.user("tenant_a", receipt["uid"], home=receipt["home"])
    with pytest.raises(Refusal, match="absent"):
        run(installation, "verify-identity")
    installation.host.group("tenant_a", receipt["gid"])
    assert run(installation, "verify-identity")["uid"] == receipt["uid"]


def test_completed_account_name_reuses_only_fresh_numeric_identity(cleanup_installation):
    installation = cleanup_installation
    first = run(installation, "verify-complete")
    second = installation.store.execute(request("fixture-b", "tenant_a"))
    assert second["uid"] == first["uid"] + 1
    assert state(installation)["consumed"] == [first["uid"], second["uid"]]
    with pytest.raises(Refusal, match="incomplete"):
        installation.store.execute(request("fixture-c", "tenant_a"))


def test_unreadable_directory_fails_before_deletion(cleanup_installation):
    installation = cleanup_installation
    blocked = installation.root / "scratch/blocked"
    blocked.mkdir(mode=0o700)
    (blocked / "data").write_text("keep")
    blocked.chmod(0)
    try:
        with pytest.raises(PermissionError):
            run(installation, "clean")
    finally:
        blocked.chmod(0o700)
    assert (blocked / "data").exists()


def test_interrupted_removal_leaves_receipt_retryable(cleanup_installation):
    installation = cleanup_installation
    scratch = installation.root / "scratch"
    for name in ("first", "second"):
        (scratch / name).write_text("owned")
    calls = []
    def interrupt(parent, name):
        calls.append(name)
        if len(calls) == 2:
            raise OSError("injected interruption")
    installation.store.before_remove = interrupt
    with pytest.raises(OSError):
        run(installation, "clean")
    assert len(list(scratch.iterdir())) == 1
    assert state(installation)["receipts"]["fixture-a"]["state"] == "reserved"
    installation.store.before_remove = None
    run(installation, "clean")
    assert run(installation, "verify-complete")["state"] == "complete"


def test_replaced_policy_root_refuses_before_deletion(cleanup_installation):
    installation = cleanup_installation
    scratch = installation.root / "scratch"
    (scratch / "data").write_text("old-root")
    scratch.rename(installation.root / "old-scratch")
    scratch.mkdir(mode=0o700)
    (scratch / "new-data").write_text("new-root")
    with pytest.raises(Refusal, match="root identity drift"):
        run(installation, "clean")
    assert (installation.root / "old-scratch/data").read_text() == "old-root"
    assert (scratch / "new-data").read_text() == "new-root"


def test_symlinked_policy_root_refuses_reservation(cleanup_installation):
    installation = cleanup_installation
    scratch = installation.root / "scratch"
    scratch.rename(installation.root / "outside")
    scratch.symlink_to(installation.root / "outside", target_is_directory=True)
    with pytest.raises(OSError):
        installation.store.execute(request("fixture-b", "tenant_b"))
    assert state(installation)["consumed"] == [os.getuid()]


def test_partial_ipc_removal_and_retry(cleanup_installation):
    installation = cleanup_installation
    uid = os.getuid()
    installation.host.records = [ipc_record(uid, "shm", 1), ipc_record(uid, "sem", 2)]
    remove = installation.host.remove_ipc
    def partial(record):
        if installation.host.removed:
            raise PermissionError("injected second-object removal failure")
        remove(record)
    installation.host.remove_ipc = partial
    with pytest.raises(PermissionError):
        run(installation, "clean")
    assert len(installation.host.records) == 1
    assert state(installation)["receipts"]["fixture-a"]["state"] == "reserved"
    installation.host.remove_ipc = remove
    run(installation, "clean")
    assert run(installation, "verify-complete")["state"] == "complete"


def test_new_ipc_after_removal_prevents_completion(cleanup_installation):
    installation = cleanup_installation
    uid = os.getuid()
    installation.host.records = [ipc_record(uid)]
    remove = installation.host.remove_ipc
    def reappear(record):
        remove(record)
        installation.host.records.append(ipc_record(uid, "msg", 2))
    installation.host.remove_ipc = reappear
    with pytest.raises(Refusal, match="IPC remains"):
        run(installation, "clean")
    assert state(installation)["receipts"]["fixture-a"]["state"] == "reserved"


def test_nonleader_thread_uid_is_observed(tmp_path):
    (tmp_path / "42/task/42").mkdir(parents=True)
    (tmp_path / "42/task/43").mkdir(mode=0o700)
    (tmp_path / "42/task/42/status").write_text("Uid:\t999\t999\t999\t999\n")
    (tmp_path / "42/task/43/status").write_text("Uid:\t999\t999\t999\t1000\n")
    with pytest.raises(Refusal, match="process"):
        LinuxHost(proc_root=tmp_path).quiescent(1000)


def test_unsupported_ipc_inventory_refuses(tmp_path):
    (tmp_path / "sysvipc").mkdir(mode=0o700)
    (tmp_path / "sysvipc/shm").write_text("unsupported header\n")
    with pytest.raises(Refusal, match="unsupported"):
        LinuxHost(proc_root=tmp_path).ipc()


def test_nonsticky_tenant_directory_with_foreign_write_refuses_entire_preflight(cleanup_installation):
    installation = cleanup_installation
    safe = installation.root / "scratch/first-safe"
    safe.write_text("preserve until all candidates safe")
    unsafe = installation.root / "scratch/unsafe"
    unsafe.mkdir(mode=0o700)
    (unsafe / "tenant-data").write_text("keep")
    unsafe.chmod(0o777)
    with pytest.raises(Refusal, match="mutation authority"):
        run(installation, "clean")
    assert safe.exists() and (unsafe / "tenant-data").exists()
    assert state(installation)["receipts"]["fixture-a"]["state"] == "reserved"
    unsafe.chmod(0o700)
    run(installation, "clean")
    assert run(installation, "verify-complete")["state"] == "complete"


@pytest.mark.parametrize("operation", ["clean", "remove-home", "verify-complete"])
def test_absent_account_without_attribution_refuses(cleanup_installation, operation):
    installation = cleanup_installation
    before = state(installation)
    with pytest.raises(Refusal, match="missing receipt"):
        installation.store.execute(request("unrecorded-reservation", "tenant_missing", operation))
    assert state(installation) == before
    assert installation.host.user("tenant_missing") is None
