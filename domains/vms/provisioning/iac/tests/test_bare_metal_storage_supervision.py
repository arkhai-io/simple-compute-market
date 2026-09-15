"""Flow tests for the provider-owned lease-storage supervision boundary."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import resource
import select
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


ROLE = (
    Path(__file__).resolve().parents[1]
    / "ansible"
    / "roles"
    / "bare-metal-access"
)
SUPERVISOR = ROLE / "files" / "arkhai-supervise-lease-storage.py"


def _load_supervisor():
    spec = importlib.util.spec_from_file_location("lease_storage_supervisor", SUPERVISOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def private_fixture_root(tmp_path):
    tmp_path.chmod(0o700)


def _profile(module, tmp_path):
    request_root = tmp_path / "requests"
    state_root = tmp_path / "state"
    request_root.mkdir(mode=0o700)
    state_root.mkdir(mode=0o700)
    return module.SupervisionProfile(
        request_root=request_root,
        state_root=state_root,
        tpm_device="/dev/tpm0",
        cryptsetup_path="/usr/sbin/cryptsetup",
        cryptsetup_version="2.4.3",
        required_uid=os.getuid(),
    )


def _request():
    return {
        "schema": "arkhai.lease-storage-request.v1",
        "host_id": "host-1",
        "machine_id": "machine-1",
        "generation": "generation-1",
        "backing_size": 32 * 1024 * 1024,
        "free_space_floor": 1024,
        "nv_index": "0x1500020",
        "counter_headroom": 16,
        "parent_handle": "0x81000020",
        "parent_name": "000b11223344",
    }


def _runtime_evidence(tmp_path, request_id, *, core_pattern=b"core\n"):
    proc = tmp_path / "proc"
    cgroups = tmp_path / "cgroup"
    (proc / "self").mkdir(parents=True)
    (proc / "sys" / "kernel").mkdir(parents=True)
    unit = f"arkhai-lease-storage-prepare@{request_id}.service"
    relative = Path("system.slice") / unit
    (cgroups / relative).mkdir(parents=True)
    (proc / "self" / "status").write_text("Name:\tpython\nNoNewPrivs:\t1\n")
    (proc / "self" / "cgroup").write_text(f"0::/{relative}\n")
    (proc / "sys" / "kernel" / "core_pattern").write_bytes(core_pattern)
    (cgroups / relative / "memory.swap.max").write_text("0\n")
    return proc, cgroups


class StartRunner:
    def __init__(self, on_start=None, returncode=0):
        self.calls = []
        self.on_start = on_start
        self.returncode = returncode

    def run(self, argv, *, timeout):
        self.calls.append((tuple(argv), timeout))
        if self.on_start:
            self.on_start()
        return SimpleNamespace(returncode=self.returncode)


class Backend:
    def __init__(self):
        self.bound = []
        self.closed = 0

    def bind(self, **values):
        self.bound.append(values)

    def close(self):
        self.closed += 1


def test_request_to_unit_to_actual_helper_dispatch(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request = _request()
    backend = Backend()
    observed = {}

    class Custody:
        def __init__(self, selected):
            observed["custody_backend"] = selected

        def close(self):
            backend.close()

    helper = SimpleNamespace(
        PrepareConfig=lambda **values: SimpleNamespace(**values),
        prepare=lambda config, **values: observed.update(
            config=config, prepare=values
        ) or {
            "schema": "arkhai.lease-storage-preparation.v1",
            "host_id": config.host_id,
            "machine_id": config.machine_id,
            "generation": config.generation,
            "counter": 10,
            "nv_index": config.nv_index,
            "parent_name": config.parent_name,
            "sealed_object_name": "000baabbccdd",
            "state": "prepared",
        },
    )
    custody_module = SimpleNamespace(EsapiCustodyExecutor=Custody)

    request_id = module.request_identity(request)

    def execute_unit():
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda expected: observed.update(runtime=expected),
            backend_factory=lambda device: observed.update(device=device) or backend,
            helper_module=helper,
            custody_module=custody_module,
            runner=object(),
        )

    receipt = module.submit_request(
        profile, request, runner=StartRunner(on_start=execute_unit)
    )

    assert observed["device"] == "/dev/tpm0"
    assert observed["runtime"] == request_id
    assert observed["config"].state_root == profile.state_root
    assert observed["prepare"]["custody"].closed
    assert observed["prepare"]["execution_evidence"] == {
        "boundary": "systemd-oneshot",
        "request_id": request_id,
    }
    assert backend.bound == [{"parent_handle": 0x81000020, "nv_index": 0x1500020}]
    assert receipt["state"] == "prepared"
    assert receipt["generation"] == "generation-1"
    outcome = json.loads((profile.request_root / f"{request_id}.execution.json").read_text())
    assert outcome["state"] == "completed"
    assert outcome["receipt"]["generation"] == "generation-1"


def test_supervised_flow_runs_helper_orchestration_with_controlled_boundaries(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request = _request()
    request_id = module.request_identity(request)
    helper = module._load_sibling(
        "controlled_real_storage_helper", "arkhai-prepare-lease-storage.py"
    )
    preparation_tests = Path(__file__).with_name(
        "test_bare_metal_lease_storage_prepare.py"
    )
    spec = importlib.util.spec_from_file_location(
        "controlled_preparation_boundaries", preparation_tests
    )
    assert spec and spec.loader
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    controlled = fixtures.RecordingRunner()
    backend = Backend()

    class ControlledExecutor:
        def __init__(self, selected):
            assert selected is backend

        def __getattr__(self, name):
            return getattr(controlled, name)

        def close(self):
            controlled.close()
            backend.close()

    def execute_unit():
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda _expected: None,
            backend_factory=lambda device: backend if device == "/dev/tpm0" else None,
            helper_module=helper,
            custody_module=SimpleNamespace(EsapiCustodyExecutor=ControlledExecutor),
            runner=controlled,
        )

    receipt = module.submit_request(
        profile, request, runner=StartRunner(on_start=execute_unit)
    )

    assert receipt["state"] == "prepared"
    assert backend.closed == 1
    assert any("luksFormat" in argv for argv, _stdin in controlled.calls)
    manifest = json.loads(
        (profile.state_root / "leases" / "generation-1" / "manifest.json").read_text()
    )
    assert manifest["helper_attempts"][0]["request_id"] == request_id
    assert manifest["helper_attempts"][0]["state"] == "completed"


@pytest.mark.parametrize("failure", ["unsafe runtime", "missing swap controller"])
def test_runtime_controls_refuse_before_tpm_or_helper(tmp_path, failure):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    calls = []

    with pytest.raises(module.SupervisionRefused, match=failure):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda _expected: (_ for _ in ()).throw(
                module.SupervisionRefused(failure)
            ),
            backend_factory=lambda _device: calls.append("tpm"),
            helper_module=SimpleNamespace(),
            custody_module=SimpleNamespace(),
        )

    assert calls == []
    outcome = json.loads((profile.request_root / f"{request_id}.execution.json").read_text())
    assert outcome["state"] == "refused"


@pytest.mark.parametrize(
    "core_pattern",
    [
        b"|/usr/share/apport/apport %p %s\n",
        b"|/usr/lib/systemd/systemd-coredump %P %u %g %s %t %c %h\n",
    ],
)
def test_piped_core_handler_refuses_before_backend_or_helper(tmp_path, core_pattern):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    proc, cgroups = _runtime_evidence(
        tmp_path, request_id, core_pattern=core_pattern
    )
    calls = []

    with pytest.raises(module.SupervisionRefused, match="piped core handler"):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda selected: module.assert_runtime_controls(
                selected,
                proc_root=proc,
                cgroup_root=cgroups,
                effective_uid=0,
                core_limit=(0, 0),
            ),
            backend_factory=lambda _device: calls.append("backend"),
            helper_module=SimpleNamespace(
                PrepareConfig=lambda **_values: calls.append("config"),
                prepare=lambda *_args, **_values: calls.append("helper"),
            ),
            custody_module=SimpleNamespace(),
            runner=object(),
        )

    assert calls == []
    outcome = json.loads(
        (profile.request_root / f"{request_id}.execution.json").read_text()
    )
    assert outcome["state"] == "refused"
    assert outcome["reason_code"] == "runtime-controls-unverified"


def test_missing_core_pattern_refuses_before_backend_or_helper(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    proc, cgroups = _runtime_evidence(tmp_path, request_id)
    (proc / "sys" / "kernel" / "core_pattern").unlink()
    calls = []

    with pytest.raises(module.SupervisionRefused, match="core-pattern policy"):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda selected: module.assert_runtime_controls(
                selected,
                proc_root=proc,
                cgroup_root=cgroups,
                effective_uid=0,
                core_limit=(0, 0),
            ),
            backend_factory=lambda _device: calls.append("backend"),
            runner=object(),
        )

    assert calls == []


def test_unreadable_core_pattern_refuses_before_backend(tmp_path, monkeypatch):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    proc, cgroups = _runtime_evidence(tmp_path, request_id)
    core_pattern_path = proc / "sys" / "kernel" / "core_pattern"
    original_open = module.Path.open
    calls = []

    def deny_core_pattern(path, *args, **kwargs):
        if path == core_pattern_path:
            raise PermissionError("unreadable policy fixture")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(module.Path, "open", deny_core_pattern)
    with pytest.raises(module.SupervisionRefused, match="core-pattern policy"):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda selected: module.assert_runtime_controls(
                selected,
                proc_root=proc,
                cgroup_root=cgroups,
                effective_uid=0,
                core_limit=(0, 0),
            ),
            backend_factory=lambda _device: calls.append("backend"),
            runner=object(),
        )

    assert calls == []


@pytest.mark.parametrize("core_pattern", [b"", b"core\nsecond\n", b"\xff\n"])
def test_malformed_core_pattern_refuses_before_backend(tmp_path, core_pattern):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    proc, cgroups = _runtime_evidence(
        tmp_path, request_id, core_pattern=core_pattern
    )
    calls = []

    with pytest.raises(module.SupervisionRefused, match="malformed core-pattern"):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda selected: module.assert_runtime_controls(
                selected,
                proc_root=proc,
                cgroup_root=cgroups,
                effective_uid=0,
                core_limit=(0, 0),
            ),
            backend_factory=lambda _device: calls.append("backend"),
            runner=object(),
        )

    assert calls == []


def test_zero_hard_core_limit_is_inherited_and_cannot_be_raised_after_exec():
    program = (
        "import json, resource\n"
        "before = resource.getrlimit(resource.RLIMIT_CORE)\n"
        "try:\n"
        "    resource.setrlimit(resource.RLIMIT_CORE, "
        "(resource.RLIM_INFINITY, resource.RLIM_INFINITY))\n"
        "except (ValueError, PermissionError):\n"
        "    pass\n"
        "print(json.dumps([before, resource.getrlimit(resource.RLIMIT_CORE)]))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)),
    )

    assert json.loads(completed.stdout) == [[0, 0], [0, 0]]


def test_unexpected_runtime_probe_failure_is_durable_refusal(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())

    with pytest.raises(module.SupervisionRefused, match="could not be verified"):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda _expected: (_ for _ in ()).throw(OSError("procfs")),
        )

    outcome = json.loads(
        (profile.request_root / f"{request_id}.execution.json").read_text()
    )
    assert outcome["state"] == "refused"
    assert outcome["reason_code"] == "runtime-controls-unverified"


def test_changed_request_is_durably_quarantined_without_dispatch(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    request_path = profile.request_root / f"{request_id}.request.json"
    changed = _request()
    changed["generation"] = "generation-2"
    request_path.write_text(json.dumps(changed), encoding="utf-8")
    request_path.chmod(0o600)

    with pytest.raises(module.SupervisionQuarantined, match="request identity changed"):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda _expected: None,
            backend_factory=lambda _device: pytest.fail("TPM opened"),
        )

    outcome = json.loads((profile.request_root / f"{request_id}.execution.json").read_text())
    assert outcome["state"] == "quarantined"


def test_changed_execution_identity_is_replaced_by_durable_quarantine(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    outcome_path = profile.request_root / f"{request_id}.execution.json"
    outcome_path.write_text(
        json.dumps(
            {
                "schema": "arkhai.lease-storage-execution.v1",
                "request_id": "b" * 64,
                "state": "completed",
            }
        ),
        encoding="utf-8",
    )
    outcome_path.chmod(0o600)

    with pytest.raises(module.SupervisionQuarantined, match="identity changed"):
        module.execute_request(profile, request_id)

    assert json.loads(outcome_path.read_text()) == {
        "schema": "arkhai.lease-storage-execution.v1",
        "request_id": request_id,
        "state": "quarantined",
        "reason_code": "execution-identity-changed",
    }


def test_interrupted_running_request_quarantines_and_never_retries(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    outcome_path = profile.request_root / f"{request_id}.execution.json"
    outcome = json.loads(outcome_path.read_text())
    outcome["state"] = "running"
    outcome_path.write_text(json.dumps(outcome), encoding="utf-8")
    outcome_path.chmod(0o600)
    calls = []

    with pytest.raises(module.SupervisionQuarantined, match="prior execution"):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda _expected: calls.append("runtime"),
            backend_factory=lambda _device: calls.append("tpm"),
        )

    assert calls == []
    assert json.loads(outcome_path.read_text())["state"] == "quarantined"


def test_quarantine_persistence_failure_reports_unresolved(tmp_path, monkeypatch):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    outcome_path = profile.request_root / f"{request_id}.execution.json"
    outcome = json.loads(outcome_path.read_text())
    outcome["state"] = "running"
    outcome_path.write_text(json.dumps(outcome), encoding="utf-8")
    outcome_path.chmod(0o600)
    monkeypatch.setattr(
        module,
        "_replace_owned",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk failure")),
    )

    with pytest.raises(module.SupervisionUnresolved, match="state quarantined"):
        module.execute_request(profile, request_id)

    assert json.loads(outcome_path.read_text())["state"] == "running"


def test_helper_failure_is_quarantined_and_cleanup_is_checked(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    backend = Backend()
    helper = SimpleNamespace(
        PrepareConfig=lambda **values: SimpleNamespace(**values),
        prepare=lambda *_args, **_values: (_ for _ in ()).throw(RuntimeError("child failed")),
    )
    custody_module = SimpleNamespace(
        EsapiCustodyExecutor=lambda selected: SimpleNamespace(
            close=selected.close,
        )
    )

    with pytest.raises(module.SupervisionQuarantined, match="helper completion is uncertain"):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda _expected: None,
            backend_factory=lambda _device: backend,
            helper_module=helper,
            custody_module=custody_module,
            runner=object(),
        )

    assert backend.closed == 1
    outcome = json.loads((profile.request_root / f"{request_id}.execution.json").read_text())
    assert outcome["state"] == "quarantined"


def test_unexpected_helper_receipt_cannot_persist_secret_material(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    backend = Backend()
    helper = SimpleNamespace(
        PrepareConfig=lambda **values: SimpleNamespace(**values),
        prepare=lambda *_args, **_values: {
            "state": "prepared",
            "secret": "must-not-be-durable",
        },
    )
    custody_module = SimpleNamespace(
        EsapiCustodyExecutor=lambda selected: SimpleNamespace(close=selected.close)
    )

    with pytest.raises(module.SupervisionQuarantined, match="completion is uncertain"):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda _expected: None,
            backend_factory=lambda _device: backend,
            helper_module=helper,
            custody_module=custody_module,
            runner=object(),
        )

    outcome_path = profile.request_root / f"{request_id}.execution.json"
    assert b"must-not-be-durable" not in outcome_path.read_bytes()
    assert json.loads(outcome_path.read_text())["state"] == "quarantined"


def test_bind_failure_closes_the_new_esapi_owner_and_quarantines(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request_id = module.accept_request(profile, _request())
    backend = Backend()

    def fail_bind(**_values):
        raise RuntimeError("bind failed")

    backend.bind = fail_bind
    with pytest.raises(module.SupervisionQuarantined, match="completion is uncertain"):
        module.execute_request(
            profile,
            request_id,
            runtime_check=lambda _expected: None,
            backend_factory=lambda _device: backend,
            runner=object(),
        )

    assert backend.closed == 1
    outcome = json.loads((profile.request_root / f"{request_id}.execution.json").read_text())
    assert outcome["state"] == "quarantined"


def test_submit_uses_exact_supported_systemctl_argv_and_never_reuses_request(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request = _request()
    runner = StartRunner()

    with pytest.raises(module.SupervisionUnresolved, match="completion evidence"):
        module.submit_request(profile, request, runner=runner)

    request_id = module.request_identity(request)
    assert runner.calls == [
        ((
            "/usr/bin/systemctl",
            "start",
            "--wait",
            f"arkhai-lease-storage-prepare@{request_id}.service",
        ), 300)
    ]
    with pytest.raises(module.SupervisionRefused, match="already exists"):
        module.submit_request(profile, request, runner=StartRunner())


def test_invalid_request_never_creates_evidence_or_invokes_systemd(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request = _request()
    request["backing_size"] = True
    runner = StartRunner()

    with pytest.raises(module.SupervisionRefused, match="backing_size"):
        module.submit_request(profile, request, runner=runner)

    assert runner.calls == []
    assert list(profile.request_root.iterdir()) == []


def test_request_files_refuse_symlink_hardlink_foreign_and_permissive_modes(tmp_path):
    module = _load_supervisor()
    profile = _profile(module, tmp_path)
    request = _request()
    request_id = module.request_identity(request)
    path = profile.request_root / f"{request_id}.request.json"

    path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(module.SupervisionRefused, match=r"request path is a symlink$"):
        module.accept_request(profile, request)
    path.unlink()

    path.write_text("foreign", encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(module.SupervisionRefused, match="already exists"):
        module.accept_request(profile, request)
    path.unlink()

    request_id = module.accept_request(profile, request)
    path = profile.request_root / f"{request_id}.request.json"
    link = tmp_path / "hardlink"
    os.link(path, link)
    with pytest.raises(module.SupervisionQuarantined, match="cannot be trusted"):
        module.execute_request(profile, request_id, runtime_check=lambda _expected: None)
    outcome = json.loads(
        (profile.request_root / f"{request_id}.execution.json").read_text()
    )
    assert outcome["state"] == "quarantined"


def test_runtime_check_reads_the_exact_unit_cgroup_and_swap_limit(tmp_path):
    module = _load_supervisor()
    request_id = "a" * 64
    proc, cgroups = _runtime_evidence(tmp_path, request_id)
    unit = f"arkhai-lease-storage-prepare@{request_id}.service"
    relative = Path("system.slice") / unit

    module.assert_runtime_controls(
        request_id,
        proc_root=proc,
        cgroup_root=cgroups,
        effective_uid=0,
        core_limit=(0, 0),
    )

    (cgroups / relative / "memory.swap.max").write_text("max\n")
    with pytest.raises(module.SupervisionRefused, match="swap limit"):
        module.assert_runtime_controls(
            request_id,
            proc_root=proc,
            cgroup_root=cgroups,
            effective_uid=0,
            core_limit=(0, 0),
        )


def test_unit_enforces_plaintext_controls_and_cgroup_owned_shutdown():
    unit = (ROLE / "templates" / "lease-storage-prepare@.service.j2").read_text()

    required = {
        "Type=oneshot",
        "Slice=system.slice",
        "Restart=no",
        "KillMode=control-group",
        "SendSIGKILL=yes",
        "MemorySwapMax=0",
        "LimitCORE=0",
        "NoNewPrivileges=yes",
        "UMask=0077",
        "StandardOutput=null",
        "StandardError=null",
        "DevicePolicy=closed",
        "SystemCallFilter=~@keyring @module @mount @reboot @swap @obsolete",
    }
    assert required <= set(unit.splitlines())
    assert "Environment=" not in unit
    assert "ExecStart=" in unit and "execute %i" in unit
    assert "ReadOnlyPaths={{ bare_metal_lease_cryptsetup_path }}" in unit
    assert "Restart=on" not in unit


def _child_readiness_program(
    published_path, *, staged_fd=None, release_fd=None, published_fd=None
):
    checkpoint_fds = (staged_fd, release_fd, published_fd)
    if any(fd is None for fd in checkpoint_fds) and any(
        fd is not None for fd in checkpoint_fds
    ):
        raise ValueError("all publication checkpoint descriptors are required")
    checkpoint = ""
    if staged_fd is not None:
        checkpoint = (
            f"os.write({staged_fd}, b'1')\n"
            f"os.read({release_fd}, 1)\n"
        )
    publication_notice = (
        "" if published_fd is None else f"os.write({published_fd}, b'1')\n"
    )
    return (
        "import json, os, pathlib, resource, time\n"
        f"published = pathlib.Path({str(published_path)!r})\n"
        "temporary = published.with_name("
        "f'.{published.name}.{os.getpid()}.tmp')\n"
        "payload = {'pid': os.getpid(), "
        "'core_limit': resource.getrlimit(resource.RLIMIT_CORE)}\n"
        "with temporary.open('x', encoding='utf-8') as output:\n"
        "    output.write(json.dumps(payload))\n"
        f"{checkpoint}"
        "os.replace(temporary, published)\n"
        f"{publication_notice}"
        "time.sleep(300)\n"
    )


def test_generated_child_readiness_is_atomic_when_publication_is_interrupted(tmp_path):
    published = tmp_path / "child.json"
    staged_read, staged_write = os.pipe()
    release_read, release_write = os.pipe()
    published_read, published_write = os.pipe()
    child = None
    try:
        program = _child_readiness_program(
            published,
            staged_fd=staged_write,
            release_fd=release_read,
            published_fd=published_write,
        )
        child = subprocess.Popen(
            [sys.executable, "-c", program],
            pass_fds=(staged_write, release_read, published_write),
        )
        os.close(staged_write)
        staged_write = -1
        os.close(release_read)
        release_read = -1
        os.close(published_write)
        published_write = -1

        assert select.select([staged_read], [], [], 10)[0] == [staged_read]
        assert os.read(staged_read, 1) == b"1"
        assert not published.exists()

        assert os.write(release_write, b"1") == 1
        assert select.select([published_read], [], [], 10)[0] == [published_read]
        assert os.read(published_read, 1) == b"1"
        assert json.loads(published.read_text()) == {
            "pid": child.pid,
            "core_limit": list(resource.getrlimit(resource.RLIMIT_CORE)),
        }
    finally:
        for fd in (
            staged_read,
            staged_write,
            release_read,
            release_write,
            published_read,
            published_write,
        ):
            if fd >= 0:
                os.close(fd)
        if child is not None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)


def _synthetic_systemd_failure_diagnostics(instance, *, run=subprocess.run):
    commands = (
        (
            "systemctl show",
            [
                "systemctl",
                "show",
                "--no-pager",
                "--property=Result",
                "--property=ExecMainCode",
                "--property=ExecMainStatus",
                "--property=SubState",
                "--property=ControlGroup",
                instance,
            ],
        ),
        (
            "exact-unit journal",
            [
                "journalctl",
                "--no-pager",
                "--output=short-monotonic",
                "--lines=80",
                f"--unit={instance}",
            ],
        ),
    )
    diagnostics = []
    for label, argv in commands:
        try:
            completed = run(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            diagnostics.append(f"{label}: unavailable ({type(exc).__name__})")
            continue
        diagnostics.append(f"{label}: exit {completed.returncode}")
        if completed.stdout:
            diagnostics.append(completed.stdout[:8192])
        if completed.stderr:
            diagnostics.append(f"stderr:\n{completed.stderr[:8192]}")
    return "\n".join(diagnostics)


def test_synthetic_manager_failure_diagnostics_are_exact_and_bounded():
    calls = []
    results = iter(
        [
            SimpleNamespace(
                returncode=0,
                stdout=(
                    "Result=exit-code\n"
                    "ExecMainCode=1\n"
                    "ExecMainStatus=24\n"
                    "SubState=failed\n"
                    "ControlGroup=/system.slice/probe.service\n"
                ),
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout="synthetic worker failed before readiness\n" + "x" * 20000,
                stderr="",
            ),
        ]
    )

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return next(results)

    diagnostics = _synthetic_systemd_failure_diagnostics(
        "probe.service", run=run
    )

    assert calls == [
        (
            [
                "systemctl",
                "show",
                "--no-pager",
                "--property=Result",
                "--property=ExecMainCode",
                "--property=ExecMainStatus",
                "--property=SubState",
                "--property=ControlGroup",
                "probe.service",
            ],
            {"capture_output": True, "text": True, "check": False, "timeout": 10},
        ),
        (
            [
                "journalctl",
                "--no-pager",
                "--output=short-monotonic",
                "--lines=80",
                "--unit=probe.service",
            ],
            {"capture_output": True, "text": True, "check": False, "timeout": 10},
        ),
    ]
    assert "ExecMainStatus=24" in diagnostics
    assert "synthetic worker failed before readiness" in diagnostics
    assert len(diagnostics) < 18000


@pytest.mark.skipif(
    os.environ.get("ARKHAI_SYSTEMD_STORAGE_LANE") != "1",
    reason=(
        "requires an explicitly disposable, systemd-249 container; this lane "
        "starts and stops only its generated probe unit"
    ),
)
def test_systemd_249_kills_descendant_after_main_process_exits(tmp_path):
    """Exercise failed-main cleanup in an isolated manager without TPM access."""
    assert os.geteuid() == 0
    assert Path("/proc/1/comm").read_text().strip() == "systemd"
    assert subprocess.run(
        ["systemd-detect-virt", "--container"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    version = subprocess.run(
        ["systemd-analyze", "--version"], capture_output=True, text=True, check=True
    ).stdout
    assert re.search(r"^systemd 249\b", version)

    probe = f"arkhai-storage-supervision-probe-{uuid.uuid4().hex}"
    root = Path("/run") / probe
    unit_path = Path("/run/systemd/system") / f"{probe}@.service"
    root.mkdir(mode=0o700)
    worker = root / "worker.py"
    evidence_path = root / "child.json"
    profile = root / "profile.json"
    child_program = _child_readiness_program(evidence_path)
    worker.write_text(
        "#!/usr/bin/python3\n"
        "import os, pathlib, subprocess, sys, time\n"
        f"evidence = pathlib.Path({str(evidence_path)!r})\n"
        f"child = subprocess.Popen([sys.executable, '-c', {child_program!r}])\n"
        "for _ in range(200):\n"
        "    if evidence.exists():\n"
        "        break\n"
        "    time.sleep(0.01)\n"
        "os._exit(23 if evidence.exists() else 24)\n",
        encoding="utf-8",
    )
    worker.chmod(0o700)
    profile.write_text("{}\n", encoding="utf-8")
    profile.chmod(0o600)
    template = (ROLE / "templates" / "lease-storage-prepare@.service.j2").read_text()
    replacements = {
        "{{ bare_metal_lease_storage_supervisor_path }}": str(worker),
        "{{ bare_metal_lease_storage_supervision_profile_path }}": str(profile),
        "{{ bare_metal_lease_storage_request_root }}": str(root),
        "{{ bare_metal_lease_storage_state_root }}": str(root),
        "{{ bare_metal_lease_tpm_device }}": "/dev/null",
        "{{ bare_metal_lease_cryptsetup_path }}": "/usr/bin/true",
    }
    for source, target in replacements.items():
        template = template.replace(source, target)
    assert "{{" not in template
    unit_path.write_text(template, encoding="utf-8")
    instance = f"{probe}@{'a' * 64}.service"
    cleanup_complete = False
    failure_diagnostics = ""
    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30)
        subprocess.run(
            ["systemctl", "start", "--no-block", instance], check=True, timeout=30
        )
        for _ in range(200):
            if evidence_path.exists():
                break
            time.sleep(0.05)
        assert evidence_path.exists(), "probe descendant did not record its identity"
        evidence = json.loads(evidence_path.read_text())
        child_pid = evidence["pid"]
        assert evidence["core_limit"] == [0, 0]
        for _ in range(200):
            if not Path(f"/proc/{child_pid}").exists():
                break
            time.sleep(0.05)
        assert not Path(f"/proc/{child_pid}").exists()
        main_status = subprocess.run(
            ["systemctl", "show", "--property=ExecMainStatus", "--value", instance],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert main_status.stdout.strip() == "23"
        result = subprocess.run(
            ["systemctl", "show", "--property=Result", "--value", instance],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert result.stdout.strip() == "exit-code"
    except Exception as exc:
        failure_diagnostics = _synthetic_systemd_failure_diagnostics(instance)
        raise AssertionError(
            f"synthetic manager probe failed before cleanup: {exc}\n"
            f"{failure_diagnostics}"
        ) from exc
    finally:
        try:
            stop = subprocess.run(
                ["systemctl", "stop", instance],
                check=False,
                timeout=30,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            stopped = stop.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            stopped = False
        if stopped:
            unit_path.unlink(missing_ok=True)
            reload_result = subprocess.run(
                ["systemctl", "daemon-reload"], check=False, timeout=30
            )
            if reload_result.returncode == 0:
                shutil.rmtree(root)
                cleanup_complete = True
        if not cleanup_complete:
            retained_diagnostics = (
                f"\n{failure_diagnostics}" if failure_diagnostics else ""
            )
            raise AssertionError(
                "exact probe-unit cleanup was uncertain; evidence is retained and "
                "the disposable container must be discarded"
                f"{retained_diagnostics}"
            )
