import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tenant_working_data import Store, mount_id


class FakeHost:
    def __init__(self):
        self.user_rows = []
        self.group_rows = []

    def users(self):
        return self.user_rows

    def groups(self):
        return self.group_rows

    def user(self, name, uid=None, gid=None, home="/unused"):
        if uid is None:
            return next((row for row in self.user_rows if (row.pw_uid if type(name) is int else row.pw_name) == name), None)
        self.user_rows.append(SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=uid if gid is None else gid, pw_dir=home))

    def group(self, name, gid=None, members=None):
        if gid is None:
            return next((row for row in self.group_rows if (row.gr_gid if type(name) is int else row.gr_name) == name), None)
        self.group_rows.append(SimpleNamespace(gr_name=name, gr_gid=gid, gr_mem=members or []))


@pytest.fixture
def installation(tmp_path):
    tmp_path.chmod(0o700)
    for name in ("state", "homes", "scratch", "ipc"):
        (tmp_path / name).mkdir(mode=0o700)
    policy = {"version": 1, "policy_id": "fixture-v1", "state_dir": str(tmp_path / "state"), "home_parent": str(tmp_path / "homes"), "scratch_roots": [str(tmp_path / "scratch")], "ipc_roots": [str(tmp_path / "ipc")], "uid_min": 41000, "uid_max": 41010, "exclude_ids": [], "mount_ids": [1]}
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        policy["mount_ids"] = [mount_id(fd)]
    finally:
        os.close(fd)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    path.chmod(0o600)
    host = FakeHost()
    store = Store(path, owner=os.getuid(), host=host)
    store.initialize()
    return SimpleNamespace(path=path, policy=policy, store=store, host=host, root=tmp_path)


def request(reservation="fixture-a", account="tenant_a", operation="reserve"):
    return {"version": 1, "operation": operation, "reservation_id": reservation, "account": account, "policy_id": "fixture-v1"}


@pytest.fixture
def policy_fixture():
    return {"version": 1, "policy_id": "fixture-v1", "state_dir": "/srv/fixture-state", "home_parent": "/srv/fixture-homes", "scratch_roots": ["/var/lib/BrlAPI"], "ipc_roots": ["/dev/shm", "/dev/mqueue"], "uid_min": 41000, "uid_max": 41010, "exclude_ids": [], "mount_ids": [123]}


def pytest_collection_modifyitems(items):
    for item in items:
        if item.path.name.startswith("test_native"):
            item.add_marker(pytest.mark.native)
