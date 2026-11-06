"""Native Ansible integration of the pinned archive installer against real files.

A local HTTP peer serves synthetic release archives. No system paths are changed.
Every address and binary here is a public test fixture, never for a public network.
"""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import threading
import unittest

import yaml

from test_frp_proxy_wait import ANSIBLE_PLAYBOOK, UNAVAILABLE, _ansible_env

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "ansible/roles"


class Archive:
    def __init__(self):
        self.requests = 0
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for binary in ("frpc", "frps"):
                content = ("fixture-" + binary).encode()
                info = tarfile.TarInfo("frp_0.61.1_linux_fixture/" + binary)
                info.size = len(content)
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(content))
        self.payload = stream.getvalue()
        source = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                source.requests += 1
                self.send_response(200)
                self.send_header("Content-Length", str(len(source.payload)))
                self.end_headers()
                self.wfile.write(source.payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # shutdown() returns only at serve_forever's next poll, and the library
        # has no way to wake it, so the poll is short rather than the default 0.5s.
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def variables(self, install):
        return {
            "frp_install_root": str(install),
            "frp_binary_name": "frpc",
            "frp_platform": "linux_fixture",
            "frp_archives": {"linux_fixture": {
                "url": f"http://127.0.0.1:{self.server.server_port}/v0.61.1/frp_0.61.1_linux_fixture.tar.gz",
                "sha256": hashlib.sha256(self.payload).hexdigest(),
            }},
        }


def install(work, variables):
    play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
             "vars": {"ansible_python_interpreter": os.sys.executable, **variables},
             "roles": ["frp-binary"],
             "tasks": [{"ansible.builtin.copy": {"content": "{{ frp_binary_path }}", "dest": str(work / "returned")}}]}]
    playbook = work / "install.yml"
    playbook.write_text(yaml.safe_dump(play, sort_keys=False))
    return subprocess.run([ANSIBLE_PLAYBOOK, "-i", "localhost,", str(playbook)],
                          cwd=work, env={**_ansible_env(), "ANSIBLE_ROLES_PATH": str(ROLES), "ANSIBLE_NOCOLOR": "true"},
                          text=True, capture_output=True, check=False, timeout=120)


@unittest.skipIf(ANSIBLE_PLAYBOOK is None, UNAVAILABLE)
class TestVerifiedInstaller(unittest.TestCase):
    def test_install_is_versioned_and_only_that_exact_binary_skips_download(self):
        with tempfile.TemporaryDirectory() as directory, Archive() as archive:
            work = Path(directory)
            root = work / "install"
            root.mkdir()
            (root / "frpc").write_text("management-fixture")
            variables = archive.variables(root)
            first = install(work, variables)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            binary = root / "0.61.1/frpc"
            self.assertEqual(binary.read_text(), "fixture-frpc")
            self.assertEqual((work / "returned").read_text(), str(binary))
            self.assertEqual((root / "frpc").read_text(), "management-fixture")
            self.assertEqual(archive.requests, 1)
            second = install(work, variables)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(archive.requests, 1)
            server = install(work, {**variables, "frp_binary_name": "frps"})
            self.assertEqual(server.returncode, 0, server.stdout + server.stderr)
            self.assertEqual((root / "0.61.1/frps").read_text(), "fixture-frps")
            self.assertEqual(archive.requests, 2)

    def test_bad_digest_fails_before_extraction_and_installs_nothing(self):
        with tempfile.TemporaryDirectory() as directory, Archive() as archive:
            work = Path(directory)
            variables = archive.variables(work / "install")
            variables["frp_archives"]["linux_fixture"]["sha256"] = "0" * 64
            run = install(work, variables)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(archive.requests, 1)
            self.assertFalse((work / "install").exists())
            self.assertNotIn("TASK [frp-binary : Extract", run.stdout)
            self.assertFalse((work / "returned").exists())

    def test_unknown_version_or_platform_is_refused_before_download(self):
        with tempfile.TemporaryDirectory() as directory, Archive() as archive:
            work = Path(directory)
            for override in ({"frp_version": "99.0.0"}, {"frp_platform": "linux_unknown"}):
                with self.subTest(override):
                    run = install(work, {**archive.variables(work / "install"), **override})
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn("No pinned archive for frp", run.stdout)
                    self.assertIn(override.get("frp_version", "0.61.1"), run.stdout)
                    self.assertIn(override.get("frp_platform", "linux_fixture"), run.stdout)
            self.assertEqual(archive.requests, 0)
            self.assertFalse((work / "install").exists())
