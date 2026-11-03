#!/usr/bin/env python3
"""Protected reservation identity and bounded Linux working-data operations.

Only the installed policy supplies paths. Ledger continuity across host restores
is an operator precondition: a valid older ledger cannot detect its own rollback.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import ctypes
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
    require(path.startswith("/") and not path.startswith("//") and str(Path(path)) == path and ".." not in Path(path).parts and path != "/", "unsafe path")
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
def directory(path, *, owner=0, protected=True, shared=False):
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
                sticky_tmp = ((i == 0 and part == "tmp") or (shared and i == len(parts) - 1)) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
                if not sticky_tmp:
                    require(info.st_uid in (0, owner) and not info.st_mode & 0o022, "unsafe ancestor")
        if protected:
            info = os.fstat(fd)
            if shared and info.st_uid == owner and info.st_mode & stat.S_ISVTX:
                require(stat.S_ISDIR(info.st_mode), "unexpected root type")
            else:
                protection(info, owner, directory=True)
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
    def __init__(self, policy_path, *, host=None, owner=0, fsync=os.fsync, replace=os.replace, mounts=None, before_remove=None):
        self.owner, self.host = owner, host or LinuxHost()
        self.mounts, self.before_remove = mounts or mount_id, before_remove
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
        exact(value, ("version", "policy_digest", "roots", "consumed", "receipts"))
        require(type(value["version"]) is int and value["version"] == 1 and value["policy_digest"] == self.digest, "ledger/policy mismatch")
        require(value["roots"] == self.validate_roots(), "policy-root identity drift")
        require(isinstance(value["consumed"], list) and isinstance(value["receipts"], dict), "invalid ledger")
        consumed = value["consumed"]
        require(len(consumed) == len(set(integer(uid) for uid in consumed)), "duplicate consumption")
        seen = set()
        for reservation, receipt in value["receipts"].items():
            text(reservation)
            exact(receipt, ("reservation_id", "account", "uid", "gid", "home", "state", "policy_digest", "observations"))
            require(receipt["reservation_id"] == reservation and receipt["policy_digest"] == self.digest, "receipt mismatch")
            self.account(receipt["account"])
            uid = integer(receipt["uid"])
            require(uid in consumed and uid not in seen and receipt["gid"] == uid, "invalid receipt identity")
            require(self.policy["uid_min"] <= uid <= self.policy["uid_max"] and uid not in self.policy["exclude_ids"], "receipt outside policy")
            require(receipt["home"] == self.home(receipt["account"]) and receipt["state"] in ("reserved", "cleaned", "complete"), "invalid receipt")
            require(isinstance(receipt["observations"], dict) and set(receipt["observations"]).issubset({"scratch_removed", "ipc_removed", "home_removed"}), "invalid observations")
            for count in receipt["observations"].values():
                integer(count)
            seen.add(uid)
        require(seen == set(consumed), "missing consumption history")
        return value

    def validate_roots(self):
        roots = {}
        for path in [self.policy["home_parent"], *self.policy["scratch_roots"], *self.policy["ipc_roots"]]:
            with directory(path, owner=self.owner, shared=path != self.policy["home_parent"]) as fd:
                identity = self.mounts(fd)
                require(identity in self.policy["mount_ids"], "unapproved policy-root mount")
                info = os.fstat(fd)
                roots[path] = {"device": info.st_dev, "inode": info.st_ino, "mount_id": identity}
        return roots

    def initialize(self):
        roots = self.validate_roots()
        with self.locked(initialize=True) as fd:
            # The stable lock remains even after a failed initialization; it is never
            # removed or replaced, and normal calls cannot initialize a missing ledger.
            try:
                os.stat("ledger.json", dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                require(not os.listdir(fd) or set(os.listdir(fd)) == {"lock"}, "nonempty initial state")
                self.write(fd, {"version": 1, "policy_digest": self.digest, "roots": roots, "consumed": [], "receipts": {}})
            else:
                raise Refusal("ledger already initialized")
        return {"version": 1, "operation": "init", "state": "initialized"}

    def account(self, value):
        require(isinstance(value, str) and re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", value) and value not in ("root", "nobody", "daemon"), "unsafe tenant account")
        return value

    def home(self, account):
        return self.policy["home_parent"] + "/" + account

    def identity(self, receipt, *, absent=False, present=False):
        users, groups = list(self.host.users()), list(self.host.groups())
        users += [row for key in (receipt["account"], receipt["uid"]) if (row := self.host.user(key)) is not None]
        groups += [row for key in (receipt["account"], receipt["gid"]) if (row := self.host.group(key)) is not None]
        if present:
            require(any(user.pw_name == receipt["account"] for user in users) and any(group.gr_name == receipt["account"] for group in groups), "expected account/private group absent")
        for user in users:
            if user.pw_uid == receipt["uid"] or user.pw_name == receipt["account"]:
                require(not absent and (user.pw_name, user.pw_uid, user.pw_gid, user.pw_dir) == (receipt["account"], receipt["uid"], receipt["gid"], receipt["home"]), "account identity conflict")
        for group in groups:
            if group.gr_gid == receipt["gid"] or group.gr_name == receipt["account"]:
                require(not absent and (group.gr_name, group.gr_gid, group.gr_mem) == (receipt["account"], receipt["gid"], []), "private group conflict")
        require(not any(user.pw_gid == receipt["gid"] and user.pw_name != receipt["account"] for user in users), "foreign private-group reference")
        require(not any(receipt["account"] in group.gr_mem for group in groups), "tenant supplementary membership")

    def execute(self, request):
        fields = ("version", "operation", "reservation_id", "account", "policy_id")
        exact(request, fields + (("ssh_public_key",) if isinstance(request, dict) and request.get("operation") == "install-key" else ()))
        require(type(request["version"]) is int and request["version"] == 1, "unsupported request version")
        operation = request["operation"]
        require(operation in ("reserve", "inspect", "verify-identity", "install-key", "revoke-key", "clean", "remove-home", "verify-complete"), "unknown operation")
        reservation = text(request["reservation_id"])
        account = self.account(request["account"])
        require(request["policy_id"] == self.policy["policy_id"], "policy identity mismatch")
        self.validate_roots()
        with self.locked() as fd:
            ledger = self.load(fd)
            receipt = ledger["receipts"].get(reservation)
            if receipt is None:
                require(operation == "reserve", "missing receipt")
                for previous in ledger["receipts"].values():
                    if previous["account"] == account:
                        require(previous["state"] == "complete", "account already consumed by incomplete reservation")
                        self.cleanup("verify-complete", previous)
                users, groups = self.host.users(), self.host.groups()
                require(self.host.user(account) is None and self.host.group(account) is None and not any(u.pw_name == account for u in users) and not any(g.gr_name == account for g in groups), "unreceipted account/group")
                require(not os.path.lexists(self.home(account)), "unreceipted home")
                unavailable = set(ledger["consumed"]) | set(self.policy["exclude_ids"]) | {u.pw_uid for u in users} | {g.gr_gid for g in groups} | {u.pw_gid for u in users}
                uid = next((n for n in range(self.policy["uid_min"], self.policy["uid_max"] + 1) if n not in unavailable and self.host.user(n) is None and self.host.group(n) is None), None)
                require(uid is not None, "UID range exhausted")
                receipt = {"reservation_id": reservation, "account": account, "uid": uid, "gid": uid, "home": self.home(account), "state": "reserved", "policy_digest": self.digest, "observations": {}}
                ledger["consumed"].append(uid)
                ledger["receipts"][reservation] = receipt
                self.write(fd, ledger)
            require(receipt["account"] == account, "reservation/account mismatch")
            self.fsync(fd)
            if operation in ("reserve", "verify-identity", "install-key"):
                # Once reclaim has cleaned or completed a receipt it stays on the
                # reclaim path: the account may already be deleted, so a grant
                # here would recreate it and restore access while teardown is
                # unproven.
                require(receipt["state"] != "complete", "completed reservation cannot grant")
                require(receipt["state"] == "reserved", "reservation in cleanup cannot grant")
            if operation in ("inspect", "install-key", "revoke-key"):
                self.identity(receipt, absent=receipt["state"] == "complete", present=operation == "install-key")
                if operation != "inspect":
                    self.ssh_key(operation, receipt, request.get("ssh_public_key"))
            elif operation in ("reserve", "verify-identity"):
                self.identity(receipt, present=operation == "verify-identity")
            else:
                receipt["observations"] = self.cleanup(operation, receipt)
                if operation in ("clean", "verify-complete"):
                    receipt["state"] = "complete" if operation == "verify-complete" or receipt["state"] == "complete" else "cleaned"
                    self.write(fd, ledger)
            return {"version": 1, "operation": operation, **receipt}

    def ssh_key(self, operation, receipt, key):
        """Touch only the receipt's key file through pinned no-follow descriptors."""
        install = operation == "install-key"
        if install:
            require(isinstance(key, str), "invalid SSH public key")
            key = key.strip()
            require(0 < len(key) <= 16384 and not any(ord(c) < 32 for c in key), "invalid SSH public key")
            parts = key.split()
            require(len(parts) >= 2 and parts[0].startswith(("ssh-", "ecdsa-", "sk-")), "invalid SSH public key")
            try:
                blob = base64.b64decode(parts[1], validate=True)
                length = int.from_bytes(blob[:4], "big")
                require(0 < length and 4 + length < len(blob) and blob[4:4 + length].decode("ascii") == parts[0], "invalid SSH public key")
            except (ValueError, UnicodeError, binascii.Error):
                raise Refusal("invalid SSH public key") from None
        with directory(self.policy["home_parent"], owner=self.owner) as parent:
            try:
                home = os.open(receipt["account"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                require(not install, "tenant home absent")
                return
            try:
                home_info = os.fstat(home)
                require((home_info.st_uid, home_info.st_gid) == (receipt["uid"], receipt["gid"]), "tenant home identity conflict")
                require(not home_info.st_mode & 0o022, "unsafe tenant home permissions")
                require(self.mounts(home) == self.mounts(parent), "unexpected SSH home mount")
                try:
                    ssh = os.open(".ssh", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=home)
                except FileNotFoundError:
                    if not install:
                        return
                    os.mkdir(".ssh", 0o700, dir_fd=home)
                    ssh = os.open(".ssh", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=home)
                    os.fchown(ssh, receipt["uid"], receipt["gid"])
                try:
                    ssh_info = os.fstat(ssh)
                    require((ssh_info.st_uid, ssh_info.st_gid) == (receipt["uid"], receipt["gid"]), "tenant SSH directory identity conflict")
                    require(not ssh_info.st_mode & 0o022, "unsafe SSH directory permissions")
                    require(self.mounts(ssh) == self.mounts(home), "unexpected SSH directory mount")
                    try:
                        current = os.stat("authorized_keys", dir_fd=ssh, follow_symlinks=False)
                    except FileNotFoundError:
                        current = None
                    if current is not None:
                        require(stat.S_ISREG(current.st_mode) and current.st_nlink == 1 and (current.st_uid, current.st_gid) == (receipt["uid"], receipt["gid"]), "unsafe SSH key file")
                    if install:
                        temporary = ".authorized-" + uuid.uuid4().hex
                        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=ssh)
                        try:
                            with os.fdopen(handle, "wb") as stream:
                                os.fchown(stream.fileno(), receipt["uid"], receipt["gid"])
                                stream.write((key.strip() + "\n").encode())
                                stream.flush()
                                self.fsync(stream.fileno())
                            os.replace(temporary, "authorized_keys", src_dir_fd=ssh, dst_dir_fd=ssh)
                            os.fchmod(ssh, 0o700)
                            self.fsync(ssh)
                        finally:
                            try:
                                os.unlink(temporary, dir_fd=ssh)
                            except FileNotFoundError:
                                pass
                    elif current is not None:
                        require(os.stat("authorized_keys", dir_fd=ssh, follow_symlinks=False) == current, "SSH key file replaced")
                        os.unlink("authorized_keys", dir_fd=ssh)
                        self.fsync(ssh)
                    require(os.stat(".ssh", dir_fd=home, follow_symlinks=False).st_ino == ssh_info.st_ino and os.stat(receipt["account"], dir_fd=parent, follow_symlinks=False).st_ino == home_info.st_ino, "SSH directory replaced")
                finally:
                    os.close(ssh)
            finally:
                os.close(home)

    def cleanup(self, operation, receipt):
        uid = receipt["uid"]
        self.identity(receipt, absent=operation == "verify-complete" or receipt["state"] == "complete")
        self.host.quiescent(uid)
        if operation == "remove-home":
            require(self.host.user(receipt["account"]) is None and self.host.user(uid) is None, "account must be removed before home")
        ipc = attributable(self.host.ipc(), uid)
        counts = {"scratch_removed": 0, "ipc_removed": 0, "home_removed": 0}
        with contextlib.ExitStack() as stack:
            roots = []
            for path in [self.policy["home_parent"], *self.policy["scratch_roots"], *self.policy["ipc_roots"]]:
                fd = stack.enter_context(directory(path, owner=self.owner, shared=path != self.policy["home_parent"]))
                tree = Tree(fd, uid, self.policy["mount_ids"], mounts=self.mounts, before_remove=self.before_remove)
                names = [receipt["account"]] if path == self.policy["home_parent"] else os.listdir(fd)
                plans = {}
                for name in names:
                    try:
                        plans[name] = tree.inspect(fd, name, selected=path == self.policy["home_parent"])
                    except FileNotFoundError:
                        require(path == self.policy["home_parent"], "entry disappeared during inventory")
                roots.append((path, fd, tree, plans))
            # Every candidate, including the dedicated home and IPC inventory, is
            # inspected before the first deletion. Foreign children cannot be
            # discovered only after their siblings have already been removed.
            if operation == "verify-complete":
                require(not ipc, "tenant IPC remains")
                for path, fd, tree, plans in roots:
                    require(not any(tree.has_owned(plan) for plan in plans.values()), "covered data remains")
                    require(path != self.policy["home_parent"] or not plans, "home remains")
            else:
                for path, fd, tree, plans in roots:
                    home = path == self.policy["home_parent"]
                    if (operation == "clean" and not home) or (operation == "remove-home" and home):
                        for name, plan in plans.items():
                            counts["home_removed" if home else "scratch_removed"] += tree.remove(fd, name, plan)
                if operation == "clean":
                    for record in ipc:
                        current = [item for item in attributable(self.host.ipc(), uid) if (item["kind"], item["id"]) == (record["kind"], record["id"])]
                        require(current == [record], "IPC identity drift")
                        self.host.remove_ipc(record)
                        counts["ipc_removed"] += 1
                remaining = attributable(self.host.ipc(), uid)
                require(not remaining, "tenant IPC remains")
                for path, fd, tree, plans in roots:
                    if (operation == "clean" and path != self.policy["home_parent"]) or (operation == "remove-home" and path == self.policy["home_parent"]):
                        names = [receipt["account"]] if path == self.policy["home_parent"] else os.listdir(fd)
                        for name in names:
                            try:
                                plan = tree.inspect(fd, name, selected=path == self.policy["home_parent"])
                            except FileNotFoundError:
                                require(path == self.policy["home_parent"], "entry disappeared during verification")
                                continue
                            require(not tree.has_owned(plan), "covered data remains")
            for path, fd, tree, plans in roots:
                with directory(path, owner=self.owner, shared=path != self.policy["home_parent"]) as current:
                    require(signature(os.fstat(fd)) == signature(os.fstat(current)) and self.mounts(current) == tree.mount, "policy root replaced")
        self.host.quiescent(uid)
        if operation == "verify-complete":
            self.identity(receipt, absent=True)
        return counts



def mount_id(fd):
    """Linux fdinfo reports the mount, including a same-device bind mount."""
    fields = Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines()
    values = [line.split(":", 1)[1].strip() for line in fields if line.startswith("mnt_id:")]
    require(len(values) == 1, "mount identity unavailable")
    return int(values[0])


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


class Tree:
    """Descriptor-relative inventory and removal inside one pinned root mount."""
    def __init__(self, root_fd, uid, allowed_mounts, *, mounts=mount_id, before_remove=None):
        self.root_fd, self.uid = root_fd, uid
        self.mounts, self.before_remove = mounts, before_remove
        self.mount = mounts(root_fd)
        require(self.mount in allowed_mounts, "unapproved root mount")

    @contextlib.contextmanager
    def opened(self, parent, name, *, listing=False):
        flags = os.O_RDONLY | os.O_DIRECTORY if listing else os.O_PATH
        fd = os.open(name, flags | os.O_NOFOLLOW, dir_fd=parent)
        try:
            require(self.mounts(fd) == self.mount, "unexpected mount boundary")
            require(signature(os.fstat(fd)) == signature(os.stat(name, dir_fd=parent, follow_symlinks=False)), "entry replaced")
            yield fd
        finally:
            os.close(fd)

    def authority(self, fd):
        info = os.fstat(fd)
        require(info.st_uid in (0, self.uid), "foreign directory mutation authority")
        # Linux exposes the POSIX ACL class mask in the group mode bits. A
        # nonsticky group/other-write directory therefore admits foreign rename
        # authority, including named ACL writers, even when its owning UID is quiet.
        require(not info.st_mode & 0o022 or info.st_mode & stat.S_ISVTX, "unsafe directory mutation authority")

    def inspect(self, parent, name, *, selected=False):
        with self.opened(parent, name) as fd:
            info = os.fstat(fd)
        owned = info.st_uid == self.uid
        require(not selected or owned, "foreign descendant")
        children = {}
        if stat.S_ISDIR(info.st_mode):
            with self.opened(parent, name, listing=True) as child:
                require(signature(os.fstat(child)) == signature(info), "directory replaced")
                for entry in os.listdir(child):
                    children[entry] = self.inspect(child, entry, selected=selected or owned)
                require(signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) == signature(info), "directory replaced")
        plan = (signature(info), owned, children)
        if self.has_owned(plan):
            self.authority(parent)
            if stat.S_ISDIR(info.st_mode):
                with self.opened(parent, name, listing=True) as child:
                    self.authority(child)
        return plan

    def remove(self, parent, name, plan):
        expected, owned, children = plan
        if self.before_remove is not None:
            self.before_remove(parent, name)
        if self.has_owned(plan):
            self.authority(parent)
        count = 0
        try:
            with self.opened(parent, name) as entry:
                require(signature(os.fstat(entry)) == expected, "entry identity drift")
                if stat.S_ISDIR(expected[2]):
                    with self.opened(parent, name, listing=True) as child:
                        require(signature(os.fstat(child)) == expected, "directory identity drift")
                        if self.has_owned(plan):
                            self.authority(child)
                        require(set(os.listdir(child)) == set(children), "directory contents drift")
                        for child_name, child_plan in children.items():
                            count += self.remove(child, child_name, child_plan)
                        require(signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) == expected, "directory replaced")
                        if owned:
                            self.authority(parent)
                            os.rmdir(name, dir_fd=parent)
                            count += 1
                elif owned:
                    self.authority(parent)
                    require(signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) == expected, "entry replaced")
                    os.unlink(name, dir_fd=parent)
                    count += 1
        except FileNotFoundError:
            raise Refusal("entry disappeared during cleanup") from None
        return count

    def has_owned(self, plan):
        return plan[1] or any(self.has_owned(child) for child in plan[2].values())


class LinuxHost(Host):
    def __init__(self, *, proc_root="/proc"):
        self.proc_root = Path(proc_root)

    def quiescent(self, uid):
        require(sys.platform == "linux", "unsupported process observer")
        for entry in self.proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                tasks = list((entry / "task").iterdir())
            except FileNotFoundError:
                require(not entry.exists(), "process tasks unavailable")
                continue
            for task in tasks:
                if not task.name.isdigit():
                    continue
                try:
                    status = (task / "status").read_text()
                except FileNotFoundError:
                    require(not task.exists(), "thread UID observation unavailable")
                    continue
                lines = [line for line in status.splitlines() if line.startswith("Uid:")]
                require(len(lines) == 1, "process UID observation unavailable")
                values = lines[0].split()[1:]
                require(len(values) == 4 and all(value.isdecimal() for value in values), "invalid process UID fields")
                require(uid not in map(int, values), "tenant process remains")

    def ipc(self):
        require(sys.platform == "linux", "unsupported System V IPC")
        records = []
        for kind, id_column in (("shm", "shmid"), ("sem", "semid"), ("msg", "msqid")):
            lines = (self.proc_root / "sysvipc" / kind).read_text().splitlines()
            require(bool(lines), "IPC inventory unavailable")
            header = lines[0].split()
            require(all(key in header for key in (id_column, "uid", "cuid", "ctime")), "unsupported IPC inventory")
            for line in lines[1:]:
                values = line.split()
                require(len(values) == len(header), "invalid IPC inventory")
                row = dict(zip(header, values))
                records.append({"kind": kind, "id": int(row[id_column]), "uid": int(row["uid"]), "cuid": int(row["cuid"]), "fingerprint": row})
        return records

    def remove_ipc(self, record):
        # Numeric identifiers contain kernel sequence bits. The full inventory
        # fingerprint is checked immediately before IPC_RMID to refuse reuse.
        current = [item for item in self.ipc() if (item["kind"], item["id"]) == (record["kind"], record["id"])]
        require(current == [record], "IPC identity drift")
        libc = ctypes.CDLL(None, use_errno=True)
        if record["kind"] == "sem":
            fn = libc.semctl
            fn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
            result = fn(record["id"], 0, 0)
        else:
            fn = libc.shmctl if record["kind"] == "shm" else libc.msgctl
            fn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
            result = fn(record["id"], 0, None)
        require(result == 0, "IPC removal failed: " + str(ctypes.get_errno()))


def attributable(records, uid):
    selected = []
    seen = set()
    for record in records:
        require(record["kind"] in ("shm", "sem", "msg"), "unknown IPC kind")
        key = (record["kind"], integer(record["id"]))
        require(key not in seen, "duplicate IPC identity")
        seen.add(key)
        owner, creator = integer(record["uid"]), integer(record["cuid"])
        require((owner == uid) == (creator == uid), "ambiguous IPC attribution")
        if owner == uid:
            selected.append(record)
    return selected


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
            data = sys.stdin.buffer.read(16385)
            require(len(data) <= 16384, "request too large")
            result = store.execute(json_load(data))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refusal, OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"version": 1, "error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
