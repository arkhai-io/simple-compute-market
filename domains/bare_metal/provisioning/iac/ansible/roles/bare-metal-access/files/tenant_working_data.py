#!/usr/bin/env python3
"""Protected reservation identity and bounded Linux working-data operations.

Only the installed policy supplies paths. Ledger continuity across host restores
is an operator precondition: a valid older ledger cannot detect its own rollback.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import uuid


class Refusal(RuntimeError):
    """An observation cannot safely authorize the requested operation."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


def exact(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys), "invalid fields")


def text(value):
    require(isinstance(value, str) and 0 < len(value) <= 200 and not any(ord(c) < 32 for c in value), "invalid text")
    return value


def integer(value):
    require(type(value) is int and 0 <= value < 2**31, "invalid integer")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def json_load(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def normalized(path):
    text(path)
    require(path.startswith("/") and str(Path(path)) == path and ".." not in Path(path).parts and path != "/", "unsafe path")
    return path


def policy_value(value):
    exact(value, ("version", "policy_id", "state_dir", "home_parent", "scratch_roots", "ipc_roots", "uid_min", "uid_max", "exclude_ids", "mount_ids"))
    require(type(value["version"]) is int and value["version"] == 1, "unsupported policy version")
    text(value["policy_id"])
    for key in ("state_dir", "home_parent"):
        normalized(value[key])
    roots = [value["state_dir"], value["home_parent"]]
    for key in ("scratch_roots", "ipc_roots"):
        require(isinstance(value[key], list), "invalid roots")
        roots.extend(normalized(path) for path in value[key])
    forbidden = ("/root", "/etc", "/usr", "/bin", "/sbin", "/boot", "/proc", "/sys", "/var/log", "/var/backups")
    for i, path in enumerate(roots):
        require(not any(Path(path).is_relative_to(other) or Path(other).is_relative_to(path) for other in roots[:i]), "overlapping roots")
        require(not any(Path(path).is_relative_to(base) or Path(base).is_relative_to(path) for base in forbidden), "protected root")
        require(path not in value["scratch_roots"] + value["ipc_roots"] or not Path(path).is_relative_to("/home"), "operator home root")
        if Path(path).is_relative_to("/dev"):
            require(path in ("/dev/shm", "/dev/mqueue") and path in value["ipc_roots"], "unsupported device root")
        if Path(path).is_relative_to("/var/lib"):
            require(path != "/var/lib" and (path == value["state_dir"] or (path == "/var/lib/BrlAPI" and path in value["scratch_roots"])), "service state root")
    lo, hi = integer(value["uid_min"]), integer(value["uid_max"])
    require(1000 <= lo <= hi < 2**31 - 1, "unsafe UID range")
    require(isinstance(value["exclude_ids"], list), "invalid exclusions")
    for item in value["exclude_ids"]:
        integer(item)
    require(isinstance(value["mount_ids"], list) and value["mount_ids"], "missing mount identities")
    for item in value["mount_ids"]:
        require(integer(item) > 0, "invalid mount identity")
    return value


def protection(info, owner, *, directory=False):
    require(info.st_uid == owner, "unexpected protected owner")
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "unexpected protected type")
    require(not info.st_mode & 0o022, "writable protected object")
    if not directory:
        require(info.st_nlink == 1 and not info.st_mode & 0o077, "unsafe protected file")


@contextlib.contextmanager
def directory(path, *, owner=0, protected=True):
    """Pin each ancestor without following links; only root's sticky /tmp is exempt."""
    normalized(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = Path(path).parts[1:]
        for i, part in enumerate(parts):
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            if protected:
                info = os.fstat(fd)
                sticky_tmp = i == 0 and part == "tmp" and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
                if not sticky_tmp:
                    require(info.st_uid in (0, owner) and not info.st_mode & 0o022, "unsafe ancestor")
        if protected:
            protection(os.fstat(fd), owner, directory=True)
        yield fd
    finally:
        os.close(fd)


def read_protected(fd, name, owner):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        protection(os.fstat(handle), owner)
        with os.fdopen(os.dup(handle), "rb") as stream:
            return json_load(stream.read())
    finally:
        os.close(handle)


class Host:
    """Host-global identity observations; errors propagate rather than imply absence."""
    def users(self):
        return pwd.getpwall()

    def groups(self):
        return grp.getgrall()

    def user(self, key):
        try:
            return pwd.getpwuid(key) if type(key) is int else pwd.getpwnam(key)
        except KeyError:
            return None

    def group(self, key):
        try:
            return grp.getgrgid(key) if type(key) is int else grp.getgrnam(key)
        except KeyError:
            return None


class Store:
    def __init__(self, policy_path, *, host=None, owner=0, fsync=os.fsync, replace=os.replace):
        self.owner, self.host = owner, host or Host()
        self.fsync, self.replace = fsync, replace
        policy_path = Path(policy_path)
        with directory(str(policy_path.parent), owner=owner) as fd:
            self.policy = policy_value(read_protected(fd, policy_path.name, owner))
        self.digest = hashlib.sha256(canonical(self.policy)).hexdigest()

    @contextlib.contextmanager
    def locked(self, *, initialize=False):
        with directory(self.policy["state_dir"], owner=self.owner) as fd:
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
            if initialize:
                flags |= os.O_CREAT | os.O_EXCL
            lock = os.open("lock", flags, 0o600, dir_fd=fd)
            try:
                protection(os.fstat(lock), self.owner)
                fcntl.flock(lock, fcntl.LOCK_EX)
                require(os.stat("lock", dir_fd=fd, follow_symlinks=False).st_ino == os.fstat(lock).st_ino, "lock replaced")
                yield fd
            finally:
                os.close(lock)

    def write(self, fd, value):
        name = ".ledger-" + uuid.uuid4().hex
        handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(canonical(value))
                stream.flush()
                self.fsync(stream.fileno())
            self.replace(name, "ledger.json", src_dir_fd=fd, dst_dir_fd=fd)
            self.fsync(fd)
        finally:
            try:
                os.unlink(name, dir_fd=fd)
            except FileNotFoundError:
                pass

    def load(self, fd):
        value = read_protected(fd, "ledger.json", self.owner)
        exact(value, ("version", "policy_digest", "consumed", "receipts"))
        require(type(value["version"]) is int and value["version"] == 1 and value["policy_digest"] == self.digest, "ledger/policy mismatch")
        require(isinstance(value["consumed"], list) and isinstance(value["receipts"], dict), "invalid ledger")
        consumed = value["consumed"]
        require(len(consumed) == len(set(integer(uid) for uid in consumed)), "duplicate consumption")
        seen = set()
        for reservation, receipt in value["receipts"].items():
            text(reservation)
            exact(receipt, ("reservation_id", "account", "uid", "gid", "home", "state", "policy_digest"))
            require(receipt["reservation_id"] == reservation and receipt["policy_digest"] == self.digest, "receipt mismatch")
            self.account(receipt["account"])
            uid = integer(receipt["uid"])
            require(uid in consumed and uid not in seen and receipt["gid"] == uid, "invalid receipt identity")
            require(self.policy["uid_min"] <= uid <= self.policy["uid_max"] and uid not in self.policy["exclude_ids"], "receipt outside policy")
            require(receipt["home"] == self.home(receipt["account"]) and receipt["state"] in ("reserved", "cleaned", "complete"), "invalid receipt")
            seen.add(uid)
        require(seen == set(consumed), "missing consumption history")
        return value

    def initialize(self):
        with self.locked(initialize=True) as fd:
            # The stable lock remains even after a failed initialization; it is never
            # removed or replaced, and normal calls cannot initialize a missing ledger.
            try:
                os.stat("ledger.json", dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                require(not os.listdir(fd) or set(os.listdir(fd)) == {"lock"}, "nonempty initial state")
                self.write(fd, {"version": 1, "policy_digest": self.digest, "consumed": [], "receipts": {}})
            else:
                raise Refusal("ledger already initialized")
        return {"version": 1, "operation": "init", "state": "initialized"}

    def account(self, value):
        require(isinstance(value, str) and re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", value) and value not in ("root", "nobody", "daemon"), "unsafe tenant account")
        return value

    def home(self, account):
        return self.policy["home_parent"] + "/" + account

    def identity(self, receipt, *, absent=False):
        users, groups = list(self.host.users()), list(self.host.groups())
        users += [row for key in (receipt["account"], receipt["uid"]) if (row := self.host.user(key)) is not None]
        groups += [row for key in (receipt["account"], receipt["gid"]) if (row := self.host.group(key)) is not None]
        for user in users:
            if user.pw_uid == receipt["uid"] or user.pw_name == receipt["account"]:
                require(not absent and (user.pw_name, user.pw_uid, user.pw_gid, user.pw_dir) == (receipt["account"], receipt["uid"], receipt["gid"], receipt["home"]), "account identity conflict")
        for group in groups:
            if group.gr_gid == receipt["gid"] or group.gr_name == receipt["account"]:
                require(not absent and (group.gr_name, group.gr_gid, group.gr_mem) == (receipt["account"], receipt["gid"], []), "private group conflict")
        require(not any(user.pw_gid == receipt["gid"] and user.pw_name != receipt["account"] for user in users), "foreign private-group reference")
        require(not any(receipt["account"] in group.gr_mem for group in groups), "tenant supplementary membership")

    def execute(self, request):
        exact(request, ("version", "operation", "reservation_id", "account", "policy_id"))
        require(type(request["version"]) is int and request["version"] == 1, "unsupported request version")
        operation = request["operation"]
        require(operation in ("reserve", "verify-identity", "clean", "remove-home", "verify-complete"), "unknown operation")
        reservation = text(request["reservation_id"])
        account = self.account(request["account"])
        require(request["policy_id"] == self.policy["policy_id"], "policy identity mismatch")
        with self.locked() as fd:
            ledger = self.load(fd)
            receipt = ledger["receipts"].get(reservation)
            if receipt is None:
                require(operation == "reserve", "missing receipt")
                require(not any(r["account"] == account for r in ledger["receipts"].values()), "account already consumed")
                users, groups = self.host.users(), self.host.groups()
                require(self.host.user(account) is None and self.host.group(account) is None and not any(u.pw_name == account for u in users) and not any(g.gr_name == account for g in groups), "unreceipted account/group")
                require(not os.path.lexists(self.home(account)), "unreceipted home")
                unavailable = set(ledger["consumed"]) | set(self.policy["exclude_ids"]) | {u.pw_uid for u in users} | {g.gr_gid for g in groups} | {u.pw_gid for u in users}
                uid = next((n for n in range(self.policy["uid_min"], self.policy["uid_max"] + 1) if n not in unavailable and self.host.user(n) is None and self.host.group(n) is None), None)
                require(uid is not None, "UID range exhausted")
                receipt = {"reservation_id": reservation, "account": account, "uid": uid, "gid": uid, "home": self.home(account), "state": "reserved", "policy_digest": self.digest}
                ledger["consumed"].append(uid)
                ledger["receipts"][reservation] = receipt
                self.write(fd, ledger)
            require(receipt["account"] == account, "reservation/account mismatch")
            self.fsync(fd)
            if operation in ("reserve", "verify-identity"):
                require(receipt["state"] != "complete", "completed reservation cannot grant")
                self.identity(receipt)
            else:
                self.cleanup(operation, receipt)
                if operation in ("clean", "verify-complete"):
                    receipt["state"] = "complete" if operation == "verify-complete" else "cleaned"
                    self.write(fd, ledger)
            return {"version": 1, "operation": operation, **receipt}

    def cleanup(self, operation, receipt):
        raise Refusal("cleanup capability unavailable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--init", action="store_true")
    args = parser.parse_args()
    try:
        require(os.geteuid() == 0, "root required")
        store = Store(args.policy)
        if args.init:
            result = store.initialize()
        else:
            result = store.execute(json_load(sys.stdin.buffer.read(16385)))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refusal, OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"version": 1, "error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
