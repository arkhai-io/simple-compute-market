"""Native account/IPC/mount observations in the dedicated disposable container."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest

import tenant_working_data
from tenant_working_data import LinuxHost, Refusal, mount_id


class NativeCleanup(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get("BARE_METAL_DISPOSABLE_NATIVE"), "private-container-v1")
        self.assertTrue(Path("/.dockerenv").exists())
        self.assertEqual(os.geteuid(), 0)
        self.root = Path(tempfile.mkdtemp(prefix="cleanup-", dir="/work"))
        self.root.chmod(0o755)
        for name in ("state", "homes", "scratch", "outside"):
            (self.root / name).mkdir(mode=0o755)
        self.account = "arkhai-native-fixture"
        self.mounted = []
        roots = [str(self.root / "homes"), str(self.root / "scratch"), "/dev/shm", "/dev/mqueue"]
        mounts = []
        for path in roots:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                mounts.append(mount_id(fd))
            finally:
                os.close(fd)
        policy = {"version": 1, "policy_id": "native-fixture-v1", "state_dir": str(self.root / "state"), "home_parent": roots[0], "scratch_roots": [roots[1]], "ipc_roots": roots[2:], "uid_min": 41000, "uid_max": 41010, "exclude_ids": [], "mount_ids": sorted(set(mounts))}
        self.policy_path = self.root / "policy.json"
        self.policy_path.write_text(json.dumps(policy))
        self.policy_path.chmod(0o600)
        initialized = self.command(sys.executable, tenant_working_data.__file__, "--policy", str(self.policy_path), "--init")
        self.assertEqual(json.loads(initialized.stdout)["state"], "initialized")
        self.receipt = self.call("reserve")
        self.uid = self.receipt["uid"]
        self.command("groupadd", "--gid", str(self.uid), self.account)
        self.command("useradd", "--uid", str(self.uid), "--gid", str(self.uid), "--home-dir", self.receipt["home"], "--no-create-home", "--shell", "/bin/sh", self.account)
        self.home = Path(self.receipt["home"])
        self.home.mkdir()
        os.chown(self.home, self.uid, self.uid)
        self.assertEqual(self.call("verify-identity")["uid"], self.uid)

    def command(self, *args):
        return subprocess.run(list(args), check=True, capture_output=True, text=True)

    def call(self, operation, reservation="native-fixture-a"):
        request = {"version": 1, "operation": operation, "reservation_id": reservation, "account": self.account, "policy_id": "native-fixture-v1"}
        result = subprocess.run([sys.executable, tenant_working_data.__file__, "--policy", str(self.policy_path)], input=json.dumps(request), capture_output=True, text=True)
        if result.returncode:
            raise Refusal(json.loads(result.stderr)["message"])
        return json.loads(result.stdout)

    def tenant_file(self, path, content="synthetic tenant data"):
        path.write_text(content)
        os.chown(path, self.uid, self.uid)

    def finish(self):
        self.command("userdel", self.account)
        self.call("remove-home")
        if LinuxHost().group(self.account) is not None:
            self.command("groupdel", self.account)
        self.assertEqual(self.call("verify-complete")["state"], "complete")
        self.assertEqual(self.call("verify-complete")["state"], "complete")

    def test_actual_system_v_posix_ipc_and_absent_account_retry(self):
        code = r'''
import ctypes,json,os,sys
uid=int(sys.argv[1]); os.setgroups([]); os.setgid(uid); os.setuid(uid)
libc=ctypes.CDLL(None,use_errno=True)
ids={}
for kind,args in (("shm",(0,4096,0o1600)),("sem",(0,1,0o1600)),("msg",(0,0o1600))):
    fn=getattr(libc,kind+"get"); fn.restype=ctypes.c_int
    identifier=fn(*args)
    if identifier<0: raise OSError(ctypes.get_errno(),kind)
    ids[kind]=identifier
libc.shm_open.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.c_uint]
fd=libc.shm_open(b"/arkhai_native_shm",os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
if fd<0: raise OSError(ctypes.get_errno(),"shm_open")
os.close(fd)
libc.sem_open.restype=ctypes.c_void_p
libc.sem_open.argtypes=[ctypes.c_char_p,ctypes.c_int]
sem=libc.sem_open(b"/arkhai_native_sem",os.O_CREAT|os.O_EXCL,ctypes.c_uint(0o600),ctypes.c_uint(1))
if sem in (None,ctypes.c_void_p(-1).value): raise OSError(ctypes.get_errno(),"sem_open")
libc.sem_close.argtypes=[ctypes.c_void_p]; libc.sem_close(sem)
class Attr(ctypes.Structure):
    _fields_=[("flags",ctypes.c_long),("maxmsg",ctypes.c_long),("msgsize",ctypes.c_long),("curmsgs",ctypes.c_long),("reserved",ctypes.c_long*4)]
attr=Attr(0,2,32,0)
libc.mq_open.restype=ctypes.c_int
libc.mq_open.argtypes=[ctypes.c_char_p,ctypes.c_int]
mq=libc.mq_open(b"/arkhai_native_mq",os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NONBLOCK,ctypes.c_uint(0o600),ctypes.byref(attr))
if mq<0: raise OSError(ctypes.get_errno(),"mq_open")
libc.mq_close(mq)
print(json.dumps(ids))
'''
        created = json.loads(self.command(sys.executable, "-c", code, str(self.uid)).stdout)
        host = LinuxHost()
        self.assertEqual({r["kind"] for r in host.ipc() if r["uid"] == self.uid}, {"shm", "sem", "msg"})
        for path in ("/dev/shm/arkhai_native_shm", "/dev/shm/sem.arkhai_native_sem", "/dev/mqueue/arkhai_native_mq"):
            self.assertEqual(os.stat(path).st_uid, self.uid)
        self.tenant_file(self.home / "data")
        sentinel = self.root / "scratch/operator-sentinel"
        sentinel.write_text("keep")
        self.command("userdel", self.account)
        self.assertEqual(self.call("clean")["observations"]["ipc_removed"], 3)
        self.assertFalse(any(r["uid"] == self.uid or r["cuid"] == self.uid for r in host.ipc()))
        for path in ("/dev/shm/arkhai_native_shm", "/dev/shm/sem.arkhai_native_sem", "/dev/mqueue/arkhai_native_mq"):
            self.assertFalse(os.path.lexists(path))
        self.call("remove-home")
        if LinuxHost().group(self.account) is not None:
            self.command("groupdel", self.account)
        self.assertEqual(self.call("verify-complete")["state"], "complete")
        self.assertEqual(sentinel.read_text(), "keep")
        second = self.call("reserve", reservation="native-fixture-b")
        self.assertGreater(second["uid"], self.uid)
        self.assertEqual(len(created), 3)

    def test_foreign_descendant_refusal_and_repaired_retry(self):
        owned = self.root / "scratch/owned"
        owned.mkdir()
        os.chown(owned, self.uid, self.uid)
        child = owned / "foreign-sentinel"
        child.write_text("foreign")
        safe = self.root / "scratch/safe"
        self.tenant_file(safe)
        with self.assertRaisesRegex(Refusal, "foreign descendant"):
            self.call("clean")
        self.assertTrue(safe.exists())
        self.assertEqual(child.read_text(), "foreign")
        os.chown(child, self.uid, self.uid)
        self.call("clean")
        self.assertFalse(safe.exists())
        self.assertFalse(owned.exists())
        self.finish()

    def test_real_same_device_bind_mount_and_symlink_escape(self):
        target = self.root / "outside/sentinel"
        target.write_text("keep")
        link = self.root / "scratch/link"
        link.symlink_to(target)
        os.lchown(link, self.uid, self.uid)
        mountpoint = self.root / "scratch/bound"
        mountpoint.mkdir()
        os.chown(mountpoint, self.uid, self.uid)
        self.command("mount", "--bind", str(self.root / "outside"), str(mountpoint))
        self.mounted.append(mountpoint)
        self.assertEqual(os.stat(mountpoint).st_dev, os.stat(self.root / "scratch").st_dev)
        with self.assertRaisesRegex(Refusal, "mount boundary"):
            self.call("clean")
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(), "keep")
        self.command("umount", str(mountpoint))
        self.mounted.remove(mountpoint)
        self.call("clean")
        self.assertFalse(link.is_symlink())
        self.assertEqual(target.read_text(), "keep")
        self.finish()

    def test_mutation_authority_refusal_and_acl_mask(self):
        sentinel = self.root / "scratch/operator-sentinel"
        sentinel.write_text("unrelated operator data")
        for kind in ("foreign-owner", "tenant-world-write", "named-acl-writer"):
            with self.subTest(kind=kind):
                unsafe = self.root / "scratch" / kind
                unsafe.mkdir(mode=0o700)
                os.chown(unsafe, self.uid, self.uid)
                child = unsafe / "tenant-data"
                self.tenant_file(child)
                safe = self.root / "scratch/other-tenant-data"
                self.tenant_file(safe)
                if kind == "foreign-owner":
                    os.chown(unsafe, 42000, 42000)
                    unsafe.chmod(0o555)
                elif kind == "tenant-world-write":
                    unsafe.chmod(0o777)
                else:
                    # Named-user write authority is effective through ACL_MASK,
                    # while ACL_GROUP_OBJ itself grants no write permission.
                    entries = [(1, 7, 0xffffffff), (2, 3, 42000), (4, 0, 0xffffffff), (16, 3, 0xffffffff), (32, 0, 0xffffffff)]
                    acl = struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in entries)
                    os.setxattr(unsafe, "system.posix_acl_access", acl)
                    self.assertEqual(unsafe.stat().st_mode & 0o070, 0o030)
                with self.assertRaisesRegex(Refusal, "mutation authority"):
                    self.call("clean")
                self.assertTrue(child.exists())
                self.assertTrue(safe.exists())
                self.assertEqual(sentinel.read_text(), "unrelated operator data")
                ledger = json.loads((self.root / "state/ledger.json").read_text())
                self.assertNotEqual(ledger["receipts"]["native-fixture-a"]["state"], "complete")
                os.chown(unsafe, self.uid, self.uid)
                unsafe.chmod(0o700)
                self.call("clean")
                self.assertFalse(unsafe.exists())
                self.assertFalse(safe.exists())
                self.assertEqual(sentinel.read_text(), "unrelated operator data")
        self.finish()

    def tearDown(self):
        for mountpoint in self.mounted:
            self.command("umount", str(mountpoint))
        host = LinuxHost()
        if host.user(self.account) is not None:
            self.command("userdel", self.account)
        if host.group(self.account) is not None:
            self.command("groupdel", self.account)
