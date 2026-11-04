"""Shipped bounded access tasks against disposable accounts and actual helper.

Systemd and scheduler commands are explicit external-boundary fixtures because
this container has no systemd daemon. NSS, processes, files and receipts are real.
"""
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import threading
import unittest


from tenant_working_data import LinuxHost, mount_id


class NativeBoundedRole(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get("BARE_METAL_DISPOSABLE_NATIVE"), "private-container-v1")
        self.assertTrue(Path("/.dockerenv").exists())
        self.assertEqual(os.geteuid(), 0)
        # The disposable image exposes Python under /usr/local; the target
        # host entrypoint requires its conventional /usr/bin interpreter.
        if not Path("/usr/bin/python3").exists():
            Path("/usr/bin/python3").symlink_to(sys.executable)
        self.source = Path.cwd()
        self.shipped = Path("/opt/domains/bare_metal/provisioning/iac")
        relative = "ansible/roles/bare-metal-access/files/tenant_working_data.py"
        self.assertEqual((self.source / relative).read_bytes(), (self.shipped / relative).read_bytes())
        self.root = Path(tempfile.mkdtemp(prefix="role-", dir="/work"))
        self.root.chmod(0o755)
        for name in ("state", "homes", "scratch"):
            (self.root / name).mkdir(mode=0o755)
        # Docker's owned /work tmpfs is noexec. Executable boundary fixtures
        # live separately in this disposable container's own writable layer.
        self.bin = Path(tempfile.mkdtemp(prefix="role-tools-", dir="/tmp"))
        self.bin.chmod(0o755)
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            identity = mount_id(descriptor)
        finally:
            os.close(descriptor)
        self.policy = {"version": 1, "policy_id": "native-role-v1", "state_dir": str(self.root / "state"), "home_parent": str(self.root / "homes"), "scratch_roots": [str(self.root / "scratch")], "ipc_roots": [], "uid_min": 42000, "uid_max": 42020, "exclude_ids": [], "mount_ids": [identity]}
        self.account = "arkhai-native-role"
        self.reservation = "native-role-reservation"
        self.key = self.root / "key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.key)], check=True)
        self.variables = {"node_action": "node_grant_access", "node_host_id": "fixture-host", "target_host": "localhost", "bare_metal_ssh_user": self.account, "bare_metal_ssh_public_key": self.key.with_suffix(".pub").read_text(), "bare_metal_reclaim_policy": "bounded_working_data", "bare_metal_capacity_reservation_id": self.reservation, "bare_metal_working_data_policy_id": self.policy["policy_id"]}
        boundary = '''#!/bin/sh
case "$(basename "$0"):$1" in
 loginctl:*) exit 0;;
 systemctl:show) case "$2" in atd.service) printf 'LoadState=not-found\\nActiveState=inactive\\n';; *) printf 'inactive\\n';; esac;;
 systemctl:stop) exit 0;;
 crontab:*) printf 'no crontab for %s\\n' "$2" >&2; exit 1;;
 atq:*) exit 0;;
 *) exit 20;;
esac
'''
        for name in ("loginctl", "systemctl", "crontab", "atq", "atrm"):
            path = self.bin / name
            path.write_text(boundary)
            path.chmod(0o755)
        # The controller image has no procps package. These command-boundary
        # fixtures use actual private-namespace procfs and signals, rather than
        # inventing process observations or changing the runtime image.
        processes = "#!" + sys.executable + "\n" + r'''import os, pathlib, signal, sys
uid = int(sys.argv[-1])
field = 1 if "-u" in sys.argv else 0
found = []
for status in pathlib.Path("/proc").glob("[0-9]*/status"):
    try:
        rows = status.read_text().splitlines()
    except FileNotFoundError:
        continue
    values = next(row.split()[1:] for row in rows if row.startswith("Uid:"))
    if int(values[field]) == uid:
        found.append(int(status.parent.name))
if pathlib.Path(sys.argv[0]).name == "pkill":
    for pid in found:
        try: os.kill(pid, signal.SIGKILL)
        except ProcessLookupError: pass
else:
    for pid in found: print(pid)
sys.exit(0 if found else 1)
'''
        for name in ("pgrep", "pkill"):
            path = self.bin / name
            path.write_text(processes)
            path.chmod(0o755)
        self.path = str(self.bin) + ":" + os.environ["PATH"]
        self.addCleanup(self.cleanup)
        installed = self.play("bare-metal-working-data", {"bare_metal_working_data_policy": self.policy})
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.assertFalse((self.root / "state/lock").exists())
        initialized = self.play("bare-metal-working-data", {"bare_metal_working_data_policy": self.policy, "bare_metal_working_data_initialize": True})
        self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)

    def play(self, role, variables):
        document = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
                     "environment": {"PATH": self.path}, "vars": variables,
                     "roles": [str(self.shipped / "ansible/roles" / role)]}]
        path = self.root / "play.yml"
        path.write_text(json.dumps(document))
        return subprocess.run(["ansible-playbook", "-i", "localhost,", str(path)], env={**os.environ, "ANSIBLE_LOG_PATH": "/dev/null", "ANSIBLE_STDOUT_CALLBACK": "ansible.posix.json", "ANSIBLE_COLLECTIONS_PATH": "/home/appuser/.ansible/collections"}, capture_output=True, text=True, timeout=120, check=False)

    def role(self, action):
        return self.play("bare-metal-access", {**self.variables, "node_action": action})

    def grant(self):
        run = self.role("node_grant_access")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.receipt = json.loads((self.root / "state/ledger.json").read_text())["receipts"][self.reservation]
        account = pwd.getpwnam(self.account)
        self.assertEqual((account.pw_uid, account.pw_gid, account.pw_dir), (self.receipt["uid"], self.receipt["gid"], self.receipt["home"]))
        return self.receipt

    def tenant_file(self, path):
        path.write_text("synthetic tenant working data")
        os.chown(path, self.receipt["uid"], self.receipt["gid"])

    def reclaim(self):
        run = self.role("node_reclaim_access")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIsNone(LinuxHost().user(self.account))
        self.assertIsNone(LinuxHost().group(self.account))
        self.assertFalse(Path(self.receipt["home"]).exists())
        ledger = json.loads((self.root / "state/ledger.json").read_text())
        self.assertEqual(ledger["receipts"][self.reservation]["state"], "complete")
        return ledger

    def test_actual_grant_reclaim_and_complete_replay(self):
        self.grant()
        tenant = subprocess.Popen(["/usr/bin/python3", "-c", "import os,signal,sys; uid=int(sys.argv[1]); os.setgroups([]); os.setgid(uid); os.setuid(uid); print('ready',flush=True); signal.pause()", str(self.receipt["uid"])], stdout=subprocess.PIPE, text=True)
        self.assertEqual(tenant.stdout.readline().strip(), "ready")
        reaper = threading.Thread(target=tenant.wait, daemon=True)
        reaper.start()
        self.addCleanup(lambda: tenant.kill() if tenant.poll() is None else None)
        self.tenant_file(Path(self.receipt["home"]) / "data")
        scratch = self.root / "scratch/data"
        self.tenant_file(scratch)
        self.reclaim()
        reaper.join(timeout=5)
        self.assertFalse(reaper.is_alive())
        self.assertEqual(tenant.returncode, -9)
        tenant.stdout.close()
        self.assertFalse(scratch.exists())
        self.reclaim()
        self.variables["bare_metal_capacity_reservation_id"] = "native-role-second"
        self.reservation = "native-role-second"
        previous = self.receipt["uid"]
        self.grant()
        self.assertGreater(self.receipt["uid"], previous)
        self.reclaim()

    def test_foreign_home_child_refuses_then_ordinary_retry(self):
        self.grant()
        foreign = Path(self.receipt["home"]) / "operator-sentinel"
        foreign.write_text("keep")
        run = self.role("node_reclaim_access")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(foreign.read_text(), "keep")
        self.assertIsNotNone(LinuxHost().user(self.account))
        self.assertNotEqual(json.loads((self.root / "state/ledger.json").read_text())["receipts"][self.reservation]["state"], "complete")
        os.chown(foreign, self.receipt["uid"], self.receipt["gid"])
        self.reclaim()

    def helper(self, operation):
        request = {"version": 1, "operation": operation, "reservation_id": self.reservation, "account": self.account, "policy_id": self.policy["policy_id"]}
        return subprocess.run(["/usr/bin/python3", "/usr/local/lib/arkhai-tenant-working-data.py", "--policy", "/etc/arkhai-working-data/policy.json"], input=json.dumps(request), capture_output=True, text=True, check=True)

    def test_grant_after_cleanup_started_restores_no_account_or_key(self):
        self.grant()
        key = Path(self.receipt["home"]) / ".ssh/authorized_keys"
        self.assertTrue(key.exists())
        # Reclaim's own steps up to a failure after clean: the key is revoked,
        # covered data cleaned, and the account deleted without its home.
        self.helper("revoke-key")
        self.assertEqual(json.loads(self.helper("clean").stdout)["state"], "cleaned")
        subprocess.run(["userdel", self.account], check=True, capture_output=True)
        run = self.role("node_grant_access")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("reservation in cleanup cannot grant", run.stdout + run.stderr)
        self.assertIsNone(LinuxHost().user(self.account))
        self.assertIsNone(LinuxHost().user(self.receipt["uid"]))
        self.assertFalse(key.exists())
        self.assertEqual(json.loads((self.root / "state/ledger.json").read_text())["receipts"][self.reservation]["state"], "cleaned")
        self.reclaim()

    def test_partial_create_and_account_absent_reclaim_do_not_resurrect(self):
        self.receipt = json.loads(self.helper("reserve").stdout)
        subprocess.run(["groupadd", "--gid", str(self.receipt["gid"]), self.account], check=True)
        self.assertIsNone(LinuxHost().user(self.account))
        self.reclaim()
        self.variables["bare_metal_capacity_reservation_id"] = "native-role-second"
        self.reservation = "native-role-second"
        self.grant()
        self.tenant_file(Path(self.receipt["home"]) / "data")
        subprocess.run(["userdel", self.account], check=True, capture_output=True)
        self.reclaim()

    def test_tenant_ssh_symlink_refuses_grant_and_reclaim_without_touching_sentinel(self):
        self.grant()
        ssh = Path(self.receipt["home"]) / ".ssh"
        (ssh / "authorized_keys").unlink()
        ssh.rmdir()
        sentinel = self.root / "operator-ssh"
        sentinel.mkdir(mode=0o755)
        key = sentinel / "authorized_keys"
        key.write_text("operator sentinel")
        before = (sentinel.stat().st_uid, sentinel.stat().st_mode, key.read_bytes())
        ssh.symlink_to(sentinel, target_is_directory=True)
        for action in ("node_grant_access", "node_reclaim_access"):
            with self.subTest(action=action):
                self.assertNotEqual(self.role(action).returncode, 0)
                self.assertEqual((sentinel.stat().st_uid, sentinel.stat().st_mode, key.read_bytes()), before)
                self.assertTrue(ssh.is_symlink())
                self.assertNotEqual(json.loads((self.root / "state/ledger.json").read_text())["receipts"][self.reservation]["state"], "complete")
        ssh.unlink()
        self.grant()
        tenant_key = ssh / "authorized_keys"
        tenant_key.unlink()
        tenant_key.symlink_to(key)
        for action in ("node_grant_access", "node_reclaim_access"):
            self.assertNotEqual(self.role(action).returncode, 0)
            self.assertEqual((sentinel.stat().st_uid, sentinel.stat().st_mode, key.read_bytes()), before)
            self.assertTrue(tenant_key.is_symlink())
        tenant_key.unlink()
        home = Path(self.receipt["home"])
        saved = home.with_name(home.name + "-saved")
        home.rename(saved)
        home.symlink_to(sentinel, target_is_directory=True)
        for action in ("node_grant_access", "node_reclaim_access"):
            self.assertNotEqual(self.role(action).returncode, 0)
            self.assertEqual((sentinel.stat().st_uid, sentinel.stat().st_mode, key.read_bytes()), before)
            self.assertTrue(home.is_symlink())
        home.unlink()
        saved.rename(home)
        self.reclaim()

    def test_missing_receipt_and_reinitialization_refuse(self):
        before = (self.root / "state/ledger.json").read_bytes()
        self.assertNotEqual(self.role("node_reclaim_access").returncode, 0)
        self.assertEqual((self.root / "state/ledger.json").read_bytes(), before)
        self.assertIsNone(LinuxHost().user(self.account))
        run = self.play("bare-metal-working-data", {"bare_metal_working_data_policy": self.policy, "bare_metal_working_data_initialize": True})
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual((self.root / "state/ledger.json").read_bytes(), before)
        changed = {**self.policy, "uid_max": 42021}
        run = self.play("bare-metal-working-data", {"bare_metal_working_data_policy": changed})
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(json.loads(Path("/etc/arkhai-working-data/policy.json").read_text()), self.policy)

    def cleanup(self):
        if hasattr(self, "account") and LinuxHost().user(self.account) is not None:
            subprocess.run(["userdel", self.account], capture_output=True, check=False)
        if hasattr(self, "account") and LinuxHost().group(self.account) is not None:
            subprocess.run(["groupdel", self.account], capture_output=True, check=False)
        # These paths are owned only by this private disposable-container fixture.
        Path("/etc/arkhai-working-data/policy.json").unlink(missing_ok=True)
