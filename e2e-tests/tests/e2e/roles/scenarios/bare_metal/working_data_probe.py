"""Independent Linux observations and nonce-scoped qualification fixtures.

Executed over pinned SSH. This observer never invokes the working-data helper,
changes its policy/ledger, or removes tenant data on the service's behalf.
"""
from __future__ import annotations

import contextlib
import ctypes
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys


@contextlib.contextmanager
def directory(path):
    """Open each absolute component without following a symlink."""
    path = Path(path)
    assert path.is_absolute() and ".." not in path.parts and str(path) != "/"
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def protected_json(path):
    with directory(str(Path(path).parent)) as parent:
        fd = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
            assert not info.st_mode & 0o077, "unprotected operator state"
            return json.load(stream)


def checked(argv, *, input=None):
    result = subprocess.run(argv, input=input, capture_output=True, text=True,
                            timeout=30, env={**os.environ, "LC_ALL": "C"})
    assert result.returncode == 0, f"required observation failed: {argv[0]}"
    return result.stdout


def owned_entries(root, uid):
    """Walk without following links; unreadable paths fail the observation."""
    found = []
    with directory(root) as fd:
        def visit(parent, prefix):
            for name in os.listdir(parent):
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                relative = f"{prefix}/{name}"
                if info.st_uid == uid:
                    found.append(relative)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    try:
                        visit(child, relative)
                    finally:
                        os.close(child)
        visit(fd, root)
    return found


def uid_processes(uid, proc=Path("/proc")):
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            lines = (entry / "status").read_text().splitlines()
        except FileNotFoundError:
            continue
        row = next(line for line in lines if line.startswith("Uid:"))
        if uid in [int(value) for value in row.split()[1:]]:
            found.append(int(entry.name))
    return found


def uid_ipc(uid, proc=Path("/proc/sysvipc")):
    found = []
    for kind in ("shm", "sem", "msg"):
        lines = (proc / kind).read_text().splitlines()
        header = lines[0].split()
        for line in lines[1:]:
            fields = dict(zip(header, line.split(), strict=True))
            if uid in (int(fields["uid"]), int(fields["cuid"])):
                found.append((kind, int(fields[{"shm": "shmid", "sem": "semid", "msg": "msqid"}[kind]])))
    return found


def sentinel(fd, name, token, *, create=False):
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if create:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    handle = os.open(name, flags, 0o600, dir_fd=fd)
    with os.fdopen(handle, "w" if create else "r") as stream:
        info = os.fstat(stream.fileno())
        assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
        assert not info.st_mode & 0o077
        if create:
            stream.write(token)
        else:
            assert stream.read() == token, "operator sentinel changed"
        return [info.st_dev, info.st_ino]


def tenant_seed(request):
    uid = os.getuid()
    assert uid == request["uid"] and uid >= 1000
    assert pwd.getpwuid(uid).pw_dir == request["home"]
    nonce = request["nonce"]
    roots = [request["home"], request["scratch"], request["ipc_root"]]
    paths = []
    for root in roots:
        with directory(root) as parent:
            os.mkdir(nonce, 0o700, dir_fd=parent)
            fd = os.open(nonce, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                handle = os.open("data", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
                with os.fdopen(handle, "w") as stream:
                    stream.write(nonce)
                os.mkfifo("fifo", 0o600, dir_fd=fd)
            finally:
                os.close(fd)
            paths.append(str(Path(root) / nonce))
    # IPC_PRIVATE yields fresh kernel objects, retained after this seed exits.
    libc = ctypes.CDLL(None, use_errno=True)
    ipc = []
    for kind, function, args in (("shm", "shmget", (0, 4096, 0o1600)),
                                 ("sem", "semget", (0, 1, 0o1600)),
                                 ("msg", "msgget", (0, 0o1600))):
        identifier = getattr(libc, function)(*args)
        assert identifier >= 0, f"cannot seed {kind} IPC"
        ipc.append([kind, identifier])
    assert shutil.which("crontab"), "crontab is a required qualification prerequisite"
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                              env={**os.environ, "LC_ALL": "C"})
    assert existing.returncode == 1 and existing.stderr.strip() == f"no crontab for {pwd.getpwuid(uid).pw_name}"
    checked(["crontab", "-"], input="* * * * * sleep 120 # " + nonce + "\n")
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    return {"uid": uid, "paths": paths, "ipc": ipc, "process": process.pid,
            "cron_seeded": nonce in checked(["crontab", "-l"])}


def observe(request, policy):
    uid, account = request["uid"], request["account"]
    assert not any(row.pw_uid == uid or row.pw_name == account for row in pwd.getpwall()), "tenant account remains"
    assert not any(row.gr_gid == uid or row.gr_name == account for row in grp.getgrall()), "tenant private group remains"
    assert not os.path.lexists(request["home"]), "tenant home remains"
    for root in policy["scratch_roots"] + policy["ipc_roots"]:
        assert not owned_entries(root, uid), "covered tenant-owned data remains"
    assert not uid_processes(uid), "tenant UID process remains"
    assert not uid_ipc(uid), "tenant IPC remains"
    for row in checked(["loginctl", "list-sessions", "--no-legend", "--no-pager"]).splitlines():
        fields = row.split()
        assert len(fields) >= 3 and fields[1].isdigit(), "unrecognized session observation"
        assert int(fields[1]) != uid, "tenant session remains"
    for row in checked(["loginctl", "list-users", "--no-legend", "--no-pager"]).splitlines():
        fields = row.split()
        assert len(fields) >= 2 and fields[0].isdigit()
        assert int(fields[0]) != uid, "tenant login manager remains"
    state = checked(["systemctl", "show", f"user@{uid}.service", "--property=ActiveState", "--value"]).strip()
    assert state in ("inactive", "failed"), "tenant user service remains"
    for root in ("/var/lib/systemd/linger", "/var/spool/cron", "/var/spool/cron/crontabs"):
        assert not os.path.lexists(str(Path(root) / account)), "tenant scheduled activity remains"
    at_roots = ("/var/spool/cron/atjobs", "/var/spool/cron/atspool", "/var/spool/at", "/var/spool/atjobs")
    if shutil.which("atq"):
        for line in checked(["atq"]).splitlines():
            fields = line.split()
            assert len(fields) >= 3 and fields[0].isdigit()
            assert fields[-1] not in (account, str(uid)), "tenant at job remains"
    else:
        state = checked(["systemctl", "show", "atd.service", "--property=LoadState", "--property=ActiveState"])
        fields = dict(row.split("=", 1) for row in state.splitlines() if "=" in row)
        assert fields.get("LoadState") in ("loaded", "not-found") and fields.get("ActiveState") in ("inactive", "failed")
    for root in at_roots:
        if Path(root).exists():
            assert not owned_entries(root, uid), "tenant at spool remains"
    return {"account_absent": True, "group_absent": True, "home_absent": True,
            "scratch_absent": True, "ipc_absent": True, "activity_absent": True}


def operator(request):
    assert os.geteuid() == 0, "operator observation requires root"
    policy = protected_json("/etc/arkhai-working-data/policy.json")
    assert policy["policy_id"] == request["policy_id"]
    assert policy["scratch_roots"] and policy["ipc_roots"], "qualification needs scratch and IPC roots"
    assert shutil.which("crontab"), "crontab is a required qualification prerequisite"
    for tool in ("loginctl", "systemctl"):
        assert shutil.which(tool), f"required observation utility missing: {tool}"
    if request["operation"] == "policy":
        assert policy["uid_max"] - policy["uid_min"] >= 1
        # Read-only established state: no initialization, repair or adoption.
        ledger = protected_json(str(Path(policy["state_dir"]) / "ledger.json"))
        assert ledger["version"] == 1 and isinstance(ledger["consumed"], list)
        unavailable = set(ledger["consumed"]) | set(policy["exclude_ids"])
        unavailable.update(row.pw_uid for row in pwd.getpwall())
        unavailable.update(row.pw_gid for row in pwd.getpwall())
        unavailable.update(row.gr_gid for row in grp.getgrall())
        available = (uid for uid in range(policy["uid_min"], policy["uid_max"] + 1) if uid not in unavailable)
        needed = request.get("needed_uids", 2)
        assert type(needed) is int and needed in (1, 2)
        for _ in range(needed):
            assert next(available, None) is not None, "qualification has insufficient unused UID/GID pairs"
        for root in [policy["home_parent"], *policy["scratch_roots"], *policy["ipc_roots"]]:
            with directory(root):
                pass
        checked(["loginctl", "list-sessions", "--no-legend", "--no-pager"])
        return {"scratch": policy["scratch_roots"][0], "ipc_root": policy["ipc_roots"][0],
                "home_parent": policy["home_parent"], "consumed": ledger["consumed"]}
    nonce = request["nonce"]
    assert re.fullmatch(r"scm-qualification-[0-9a-f]{32}", nonce), "invalid fixture nonce"
    account, uid = request["account"], request["uid"]
    assert re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", account) and uid >= 1000
    assert request["home"] == str(Path(policy["home_parent"]) / account)
    operation = request["operation"]
    if operation == "identity":
        row = pwd.getpwnam(account)
        assert (row.pw_uid, row.pw_gid, row.pw_dir) == (uid, uid, request["home"])
        ledger = protected_json(str(Path(policy["state_dir"]) / "ledger.json"))
        receipt = ledger["receipts"][request["reservation_id"]]
        assert (receipt["account"], receipt["uid"], receipt["home"]) == (account, uid, request["home"])
        return {"receipt_bound": True}
    with directory(policy["scratch_roots"][0]) as scratch:
        sentinels = [nonce + "-operator", nonce + "-service"]
        if operation == "sentinels":
            return {"sentinels": [sentinel(scratch, name, nonce, create=True) for name in sentinels]}
        if operation == "arm":
            fixture = os.open(nonce, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=scratch)
            try:
                info = os.fstat(fixture)
                assert info.st_uid == uid and stat.S_IMODE(info.st_mode) == 0o700
                identity = sentinel(fixture, "foreign-child", nonce, create=True)
                return {"foreign_child": identity, "parent": [info.st_dev, info.st_ino]}
            finally:
                os.close(fixture)
        if operation == "repair":
            fixture = os.open(nonce, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=scratch)
            try:
                info = os.fstat(fixture)
                assert [info.st_dev, info.st_ino] == request["parent"] and info.st_uid == uid
                assert sentinel(fixture, "foreign-child", nonce) == request["foreign_child"]
                os.unlink("foreign-child", dir_fd=fixture)
            finally:
                os.close(fixture)
            return {"fixture_only_repaired": True}
        assert operation == "observe", "unsupported operator operation"
        result = observe(request, policy)
        identities = [sentinel(scratch, name, nonce) for name in sentinels]
        assert identities == request["sentinels"], "sentinel inode changed"
        result["sentinels_unchanged"] = True
        # Retire only the observer's own unchanged, nonce-scoped files.
        for name in sentinels:
            os.unlink(name, dir_fd=scratch)
        return result


def main():
    request = json.loads(sys.argv[1])
    result = tenant_seed(request) if request["operation"] == "seed" else operator(request)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
