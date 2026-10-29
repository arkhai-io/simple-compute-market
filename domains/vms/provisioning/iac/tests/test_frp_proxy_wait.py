"""A VM create's relay proxy is ready only when its tunnel client reports it.

"Wait for this VM's proxy to come up" asks the client's loopback admin API for
its status. The client answers with a JSON body labelled `text/plain`, and
Ansible's `uri` decodes only a body labelled JSON, so the task reads the body
itself. These tests run the task as `vm-create.yml` ships it, through a real
`ansible-playbook`, against a local HTTP peer standing in for the client's
admin API, so what they exercise is Ansible's own `uri` result and `until`
evaluation, which no structural or shell check can see. The task's retry count
is lowered and its delay removed, so a case that never becomes ready ends in
seconds; nothing else in it is changed. Nothing runs on any host but this one,
over a local connection.

The image's Ansible is `ansible-core>=2.17,<2.20`; with none of those on
`PATH`, the tests are skipped and say so. Whether a real client registers a
real proxy is the live VM lane's evidence.

Every address and name here is a documentation or synthetic fixture value,
never to be used on a public network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
VM_CREATE = ROOT / "ansible/roles/vm-management/tasks/vm-create.yml"
TASK = "Wait for this VM's proxy to come up"

GUEST = "tenant-example"
RETRIES = 2

#: A ready client's status for this guest, as the client prints it.
READY = {"tcp": [{
    "name": f"vm-{GUEST}", "type": "tcp", "status": "running", "err": "",
    "local_addr": "192.0.2.10:22", "remote_addr": "198.51.100.20:22001",
}]}


def _supported_ansible_playbook() -> str | None:
    path = shutil.which("ansible-playbook")
    if path is None:
        return None
    version = subprocess.run(
        [path, "--version"], capture_output=True, text=True, check=False
    ).stdout
    return path if re.search(r"core 2\.(1[7-9])\.", version) else None


ANSIBLE_PLAYBOOK = _supported_ansible_playbook()


class _Peer:
    """Serves one fixed answer to every GET, as the client's admin API would."""

    def __init__(self, body: bytes, *, status: int = 200, content_type: str = "text/plain; charset=utf-8"):
        answer = (status, content_type, body)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - the handler's own name
                code, kind, payload = answer
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_Peer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def _shipped_task() -> dict:
    tasks = yaml.safe_load(VM_CREATE.read_text(encoding="utf-8"))
    (task,) = [task for task in tasks if task.get("name") == TASK]
    return {**task, "retries": RETRIES, "delay": 0}


def _wait(port: int) -> dict:
    """Run the shipped task against the admin API on ``port`` and return its
    result for the one host."""
    play = [{
        "hosts": "localhost",
        "gather_facts": False,
        "connection": "local",
        "vars": {
            "vm_action": "create",
            "vm_name": GUEST,
            "vm_ip": "192.0.2.10",
            "frp_server_addr": "198.51.100.20",
            "vm_remote_port": 22001,
            "frp_admin_port": port,
            "target_host": "localhost",
        },
        "tasks": [_shipped_task()],
    }]
    with tempfile.TemporaryDirectory() as work:
        playbook = Path(work) / "wait.yml"
        playbook.write_text(yaml.safe_dump(play, sort_keys=False), encoding="utf-8")
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")},
            "ANSIBLE_STDOUT_CALLBACK": "ansible.builtin.json",
            "ANSIBLE_LOCALHOST_WARNING": "false",
            "ANSIBLE_NOCOLOR": "true",
        }
        run = subprocess.run(
            [ANSIBLE_PLAYBOOK, "-i", "localhost,", str(playbook)],
            cwd=work, env=env, capture_output=True, text=True, timeout=120, check=False,
        )
    report = json.loads(run.stdout[run.stdout.index("{"):])
    (result,) = [
        task["hosts"]["localhost"]
        for play in report["plays"] for task in play["tasks"]
        if task["task"]["name"] == TASK
    ]
    return result


@unittest.skipIf(
    ANSIBLE_PLAYBOOK is None,
    "needs an ansible-playbook of ansible-core 2.17 to 2.19 on PATH, the image's Ansible",
)
class TestTheProxyWait(unittest.TestCase):
    def assert_ready(self, result: dict) -> None:
        self.assertFalse(result.get("failed"), result.get("msg"))

    def assert_retried_and_not_ready(self, result: dict) -> None:
        self.assertTrue(result.get("failed"))
        self.assertEqual(result.get("attempts"), RETRIES)

    def assert_refused_at_once(self, result: dict) -> None:
        self.assertTrue(result.get("failed"))
        self.assertNotIn("attempts", result)

    def test_a_running_proxy_in_a_body_labelled_plain_text_is_ready(self) -> None:
        with _Peer(json.dumps(READY).encode()) as peer:
            result = _wait(peer.port)
        self.assert_ready(result)
        self.assertTrue(result["content_type"].startswith("text/plain"))
        self.assertNotIn("json", result)

    def test_a_running_proxy_in_a_body_labelled_json_is_ready(self) -> None:
        with _Peer(json.dumps(READY).encode(), content_type="application/json") as peer:
            self.assert_ready(_wait(peer.port))

    def test_the_proxy_among_others_is_found_by_its_exact_name(self) -> None:
        other = {**READY["tcp"][0], "name": "vm-tenant-other"}
        body = {"tcp": [other, READY["tcp"][0]]}
        with _Peer(json.dumps(body).encode()) as peer:
            self.assert_ready(_wait(peer.port))

    def test_no_proxy_but_this_guests_running_one_is_ready(self) -> None:
        proxy = READY["tcp"][0]
        not_ready = {
            "another guest's proxy": {"tcp": [{**proxy, "name": "vm-tenant-other"}]},
            "a name it is a prefix of": {"tcp": [{**proxy, "name": f"vm-{GUEST}-2"}]},
            "a proxy that failed to start": {
                "tcp": [{**proxy, "status": "start error", "err": "port unavailable"}]
            },
            "another spelling of running": {"tcp": [{**proxy, "status": "Running"}]},
            "a proxy of another type": {"http": [proxy]},
            "no proxies": {"tcp": None},
            "no status document": None,
            "a list": [],
        }
        for case, body in not_ready.items():
            with self.subTest(case), _Peer(json.dumps(body).encode()) as peer:
                self.assert_retried_and_not_ready(_wait(peer.port))

    def test_an_empty_body_or_an_error_status_is_retried(self) -> None:
        for case, peer in {
            "empty body": _Peer(b""),
            "server error": _Peer(json.dumps(READY).encode(), status=500),
        }.items():
            with self.subTest(case), peer:
                self.assert_retried_and_not_ready(_wait(peer.port))

    def test_a_client_that_does_not_answer_is_retried(self) -> None:
        with _Peer(b"") as peer:
            port = peer.port
        self.assert_retried_and_not_ready(_wait(port))

    def test_a_body_that_is_not_a_status_document_is_never_ready(self) -> None:
        for case, body in {
            "truncated JSON": json.dumps(READY).encode()[:-3],
            "not JSON": b"<html>ok</html>",
            "a proxy that is not an object": json.dumps({"tcp": [f"vm-{GUEST}"]}).encode(),
        }.items():
            with self.subTest(case), _Peer(body) as peer:
                self.assert_refused_at_once(_wait(peer.port))


if __name__ == "__main__":
    unittest.main()
