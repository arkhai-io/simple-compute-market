import importlib.util
import hashlib
import json
import os
import subprocess
import stat
from pathlib import Path

import pytest


FILES = Path(__file__).parents[1] / "ansible/roles/bare-metal-access/files"

SYSTEMD_249_AMD64_MOUNT_DENY = (
    "~chroot fsconfig fsmount fsopen fspick mount mount_setattr move_mount "
    "open_tree pivot_root umount umount2"
)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, FILES / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixtures():
    path = Path(__file__).with_name("test_bare_metal_lease_storage_prepare.py")
    spec = importlib.util.spec_from_file_location("activation_prepare_fixtures", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _custody_fixtures():
    path = Path(__file__).with_name("test_tpm_esapi_custody.py")
    spec = importlib.util.spec_from_file_location("activation_custody_fixtures", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _actual_custody(config, prepared_runner, *, fail_at=None, sealed_name=None):
    custody_api = _load("activation_actual_custody", "arkhai_tpm_esapi_custody.py")
    backend = _custody_fixtures().Backend(fail_at=fail_at)
    policy = (
        config.state_root / "leases" / config.generation / "policy.nv"
    ).read_bytes()
    expected_name = sealed_name or prepared_runner.sealed_name

    def verify_resources(**values):
        backend._call("verify_resources", values)

    def read_counter():
        backend._call("read_counter")
        return prepared_runner.counter

    def close():
        backend._call("close")

    def sealed_public(handle):
        backend._call("sealed_public", handle)
        return {
            "name": expected_name,
            "policy": policy,
            "attributes": frozenset(("fixedtpm", "fixedparent")),
            "type": "keyedhash",
        }

    backend.verify_resources = verify_resources
    backend.read_counter = read_counter
    backend.close = close
    backend.sealed_public = sealed_public
    return custody_api.EsapiCustodyExecutor(backend), backend


def _prepared(tmp_path):
    helper = _load("activation_preparation", "arkhai-prepare-lease-storage.py")
    fixtures = _fixtures()
    tmp_path.chmod(0o700)
    config = fixtures._config(helper, tmp_path)
    runner = fixtures.RecordingRunner()
    helper.prepare(
        config,
        runner=runner,
        random_bytes=lambda size: b"S" * size,
        execution_evidence={"boundary": "controlled-test", "request_id": "a" * 64},
    )
    return helper, config, runner


class Operations:
    def __init__(self, *, fail=None):
        self.events = []
        self.fail = fail

    def _event(self, name, value):
        self.events.append(name)
        if self.fail == name:
            raise RuntimeError("controlled lost response")
        return value

    def attach_loop(self, _backing, evidence):
        assert evidence["preparation_request_id"] == "a" * 64
        return self._event("loop", {"loop_device": "/dev/loop7", "backing_inode": evidence["st_ino"]})

    def open_mapper(self, mapper, secret, expected_luks_uuid, loop):
        assert secret == b"S" * 32
        assert expected_luks_uuid == "12345678-1234-4abc-8def-1234567890ab"
        assert loop["loop_device"] == "/dev/loop7"
        return self._event("mapper", {"mapper": mapper, "major": 253, "minor": 7, "dm_uuid": "CRYPT-LUKS2-test"})

    def format_ext4(self, mapped, filesystem_uuid, expected_luks_uuid, loop):
        assert mapped["mapper"].startswith("arkhai-")
        return self._event("format", {"type": "ext4", "uuid": filesystem_uuid})

    def mount(self, mapped, filesystem_uuid, expected_luks_uuid, loop):
        assert mapped["mapper"].startswith("arkhai-")
        return self._event("mount", {"unit": "run-arkhai-lease.mount", "mount_point": "/run/arkhai/lease", "type": "ext4", "uuid": filesystem_uuid})


def _request(activation, config):
    return {
        "schema": activation.REQUEST_SCHEMA,
        "host_id": config.host_id,
        "machine_id": config.machine_id,
        "generation": config.generation,
        "preparation_request_id": "a" * 64,
        "boot_id": "boot-1",
    }


def test_prepared_secret_is_consumed_under_lock_and_activation_completes(tmp_path):
    _helper, config, runner = _prepared(tmp_path)
    activation = _load("lease_activation", "arkhai-activate-lease-storage.py")
    operations = Operations()

    receipt = activation.execute(
        config,
        _request(activation, config),
        runner=runner,
        custody_factory=lambda: runner,
        operations=operations,
    )

    assert operations.events == ["loop", "mapper", "format", "mount"]
    assert receipt["state"] == "completed"
    journal = json.loads(
        (config.state_root / "leases" / config.generation / "activation.json").read_text()
    )
    assert journal["stage"] == "completed"
    assert journal["receipt"] == receipt
    calls = [call[0][0] for call in runner.calls]
    assert calls.index("esapi_recover_and_verify") < calls.index("esapi_finalize")


@pytest.mark.parametrize(
    ("failure", "expected"),
    [("loop", ["loop"]), ("mapper", ["loop", "mapper"]),
     ("format", ["loop", "mapper", "format"]),
     ("mount", ["loop", "mapper", "format", "mount"])],
)
def test_lost_operation_response_quarantines_and_retry_performs_zero_mutation(
    tmp_path, failure, expected
):
    _helper, config, runner = _prepared(tmp_path)
    activation = _load("lease_activation_lost", "arkhai-activate-lease-storage.py")
    request = _request(activation, config)
    first = Operations(fail=failure)
    with pytest.raises(activation.ActivationQuarantined):
        activation.execute(
            config, request, runner=runner,
            custody_factory=lambda: runner, operations=first,
        )
    assert first.events == expected
    second = Operations()
    with pytest.raises(Exception, match="already owned"):
        activation.execute(
            config, request, runner=runner,
            custody_factory=lambda: runner, operations=second,
        )
    assert second.events == []


def test_pending_activation_refuses_preparation_before_lazy_custody(tmp_path):
    helper, config, runner = _prepared(tmp_path)
    lease = config.state_root / "leases" / config.generation
    activation = {
        "schema": helper.ACTIVATION_SCHEMA,
        "host_id": config.host_id,
        "machine_id": config.machine_id,
        "generation": config.generation,
        "nv_index": config.nv_index,
        "request_id": "b" * 64,
        "boot_id": "other-boot",
        "state": "pending",
    }
    (lease / "activation.json").write_text(json.dumps(activation), encoding="utf-8")
    (lease / "activation.json").chmod(0o600)
    opened = []
    calls = list(runner.calls)
    with pytest.raises(helper.PreparationQuarantined, match="activation ownership"):
        helper.prepare(
            config, runner=runner,
            custody_factory=lambda: opened.append(True) or runner,
            execution_evidence={"boundary": "systemd-oneshot", "request_id": "c" * 64},
        )
    assert opened == []
    assert runner.calls == calls


def test_changed_keyslot_refuses_before_activation_mutation_or_custody(tmp_path):
    _helper, config, runner = _prepared(tmp_path)
    activation = _load("activation_changed_keyslot", "arkhai-activate-lease-storage.py")
    runner.luks_json = json.dumps({"keyslots": {"0": {}, "1": {}}})
    operations = Operations()
    opened = []
    with pytest.raises(activation.ActivationQuarantined, match="admission is ambiguous"):
        activation.execute(
            config, _request(activation, config), runner=runner,
            custody_factory=lambda: opened.append(True) or runner,
            operations=operations,
        )
    assert opened == []
    assert operations.events == []
    lease = config.state_root / "leases" / config.generation
    assert json.loads((lease / "manifest.json").read_text())["state"] == "quarantined"
    assert json.loads((lease / "activation.json").read_text())["state"] == "quarantined"
    retry = Operations()
    with pytest.raises(Exception, match="already quarantined"):
        activation.execute(
            config, {**_request(activation, config), "boot_id": "other-boot"},
            runner=runner, custody_factory=lambda: runner, operations=retry,
        )
    assert retry.events == []


@pytest.mark.parametrize("failure", ["missing", "unreadable"])
def test_backing_read_failure_durably_quarantines_generation_before_custody(
    tmp_path, monkeypatch, failure
):
    _helper, config, runner = _prepared(tmp_path)
    activation = _load(f"activation_backing_{failure}", "arkhai-activate-lease-storage.py")
    backing = config.state_root / "leases" / config.generation / "volume.luks"
    saved = backing.with_name("volume.saved")
    original_open = os.open
    if failure == "missing":
        backing.rename(saved)
    else:
        def controlled_open(path, flags, *args, **kwargs):
            if Path(path) == backing and flags & os.O_ACCMODE == os.O_RDONLY:
                raise PermissionError("controlled unreadable backing")
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", controlled_open)
    opened = []
    operations = Operations()

    with pytest.raises(activation.ActivationQuarantined, match="admission is ambiguous"):
        activation.execute(
            config, _request(activation, config), runner=runner,
            custody_factory=lambda: opened.append(True) or runner,
            operations=operations,
        )
    if failure == "missing":
        saved.rename(backing)
    else:
        monkeypatch.setattr(os, "open", original_open)
    lease = config.state_root / "leases" / config.generation
    assert json.loads((lease / "manifest.json").read_text())["state"] == "quarantined"
    assert json.loads((lease / "activation.json").read_text())["state"] == "quarantined"
    assert opened == []
    assert operations.events == []

    retry = Operations()
    with pytest.raises(Exception, match="already (?:owned|quarantined)"):
        activation.execute(
            config, {**_request(activation, config), "boot_id": "other-boot"},
            runner=runner, custody_factory=lambda: opened.append(True) or runner,
            operations=retry,
        )
    assert opened == []
    assert retry.events == []


def test_real_mapper_command_uses_only_stdin_secret_and_parses_identity(tmp_path, monkeypatch):
    activation = _load("activation_real_commands", "arkhai-activate-lease-storage.py")
    observed = []
    mapper = "arkhai-0123456789abcdef"
    luks_uuid = "12345678-1234-4abc-8def-1234567890ab"
    dm_uuid = f"CRYPT-LUKS2-{luks_uuid.replace('-', '')}-{mapper}"
    mapper_root = tmp_path / "mapper"
    mapper_root.mkdir()
    (tmp_path / "dm-7").write_bytes(b"")
    node = mapper_root / mapper
    node.symlink_to("../dm-7")
    sys_root = tmp_path / "sys" / "253:7"
    (sys_root / "dm").mkdir(parents=True)
    (sys_root / "slaves" / "loop7").mkdir(parents=True)
    (sys_root / "dm/name").write_text(mapper + "\n")
    (sys_root / "dm/uuid").write_text(dm_uuid + "\n")
    original_stat = os.stat

    def controlled_stat(path, *args, **values):
        if Path(path) == node and values.get("follow_symlinks", True):
            return type("Stat", (), {
                "st_mode": stat.S_IFBLK | 0o600, "st_rdev": os.makedev(253, 7)
            })()
        return original_stat(path, *args, **values)

    monkeypatch.setattr(os, "stat", controlled_stat)

    def controlled_run(argv, **values):
        observed.append((tuple(argv), values))
        output = b"" if argv[0] == "cryptsetup" else f"{mapper}:253:7:{dm_uuid}\n".encode()
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(activation.subprocess, "run", controlled_run)
    operations = activation.SystemOperations(
        loop_device=Path("/dev/loop7"),
        mount_unit_root=tmp_path,
        mount_point=tmp_path / "volume",
        mapper_root=mapper_root,
        sys_dev_block=tmp_path / "sys",
        required_uid=os.getuid(),
    )
    secret = b"K" * 32
    identity = operations.open_mapper(
        mapper, secret, luks_uuid, {"loop_device": "/dev/loop7"}
    )

    assert identity == {
        "mapper": mapper,
        "major": 253,
        "minor": 7,
        "dm_uuid": dm_uuid,
        "dm_node": "/dev/dm-7",
    }
    cryptsetup, values = observed[0]
    assert "--disable-keyring" in cryptsetup
    assert secret not in cryptsetup
    assert values["input"] == secret


def test_filesystem_readback_uses_qualified_value_queries(tmp_path, monkeypatch):
    activation = _load("activation_filesystem_values", "arkhai-activate-lease-storage.py")
    observed = []
    filesystem_uuid = "12345678-1234-4abc-8def-1234567890ab"

    def controlled_run(argv, **_values):
        argv = tuple(argv)
        observed.append(argv)
        tag = argv[argv.index("--match-tag") + 1]
        value = "ext4" if tag == "TYPE" else filesystem_uuid
        return subprocess.CompletedProcess(argv, 0, stdout=f"{value}\n".encode(), stderr=b"")

    monkeypatch.setattr(activation.subprocess, "run", controlled_run)
    operations = activation.SystemOperations(
        loop_device=Path("/dev/loop7"), mount_unit_root=tmp_path,
        mount_point=tmp_path / "volume",
    )

    assert operations.read_filesystem("arkhai-test", filesystem_uuid) == {
        "type": "ext4", "uuid": filesystem_uuid,
    }
    assert observed == [
        (
            "blkid", "--probe", "--output", "value", "--match-tag", "TYPE",
            "/dev/mapper/arkhai-test",
        ),
        (
            "blkid", "--probe", "--output", "value", "--match-tag", "UUID",
            "/dev/mapper/arkhai-test",
        ),
    ]


@pytest.mark.parametrize("bad_value", ["ext4\next4\n", "ext4", "FOREIGN\n", "TYPE=ext4\n"])
def test_filesystem_readback_rejects_malformed_or_foreign_values(
    tmp_path, monkeypatch, bad_value
):
    activation = _load("activation_filesystem_bad", "arkhai-activate-lease-storage.py")
    monkeypatch.setattr(
        activation.subprocess,
        "run",
        lambda argv, **_values: subprocess.CompletedProcess(
            argv, 0, stdout=bad_value.encode(), stderr=b""
        ),
    )
    operations = activation.SystemOperations(
        loop_device=Path("/dev/loop7"), mount_unit_root=tmp_path,
        mount_point=tmp_path / "volume",
    )

    with pytest.raises(activation.ActivationQuarantined, match="filesystem identity"):
        operations.read_filesystem(
            "arkhai-test", "12345678-1234-4abc-8def-1234567890ab"
        )


@pytest.mark.parametrize(
    ("observed_uuid", "slave"),
    [
        ("FOREIGN", "loop7"),
        (
            "CRYPT-LUKS2-1234567812344abc8def1234567890ab-arkhai-0123456789abcdef",
            "loop8",
        ),
    ],
)
def test_mapper_kernel_identity_rejects_foreign_uuid_or_loop_dependency(
    tmp_path, monkeypatch, observed_uuid, slave
):
    activation = _load("activation_mapper_identity", "arkhai-activate-lease-storage.py")
    mapper = "arkhai-0123456789abcdef"
    mapper_root = tmp_path / "mapper"
    mapper_root.mkdir()
    (tmp_path / "dm-7").write_bytes(b"")
    node = mapper_root / mapper
    node.symlink_to("../dm-7")
    sys_root = tmp_path / "sys" / "253:7"
    (sys_root / "dm").mkdir(parents=True)
    (sys_root / "slaves" / slave).mkdir(parents=True)
    (sys_root / "dm/name").write_text(mapper + "\n")
    (sys_root / "dm/uuid").write_text(observed_uuid + "\n")
    original_stat = os.stat

    def controlled_stat(path, *args, **values):
        if Path(path) == node and values.get("follow_symlinks", True):
            return type("Stat", (), {
                "st_mode": stat.S_IFBLK | 0o600, "st_rdev": os.makedev(253, 7)
            })()
        return original_stat(path, *args, **values)

    monkeypatch.setattr(os, "stat", controlled_stat)
    operations = activation.SystemOperations(
        loop_device=Path("/dev/loop7"), mount_unit_root=tmp_path,
        mount_point=tmp_path / "volume", mapper_root=mapper_root,
        sys_dev_block=tmp_path / "sys", required_uid=os.getuid(),
    )

    with pytest.raises(activation.ActivationQuarantined, match="dependency identity"):
        operations._verify_mapper(
            mapper,
            "12345678-1234-4abc-8def-1234567890ab",
            {"loop_device": "/dev/loop7"},
        )


def test_native_mount_rejects_search_path_unit_or_dropin_collision(tmp_path):
    activation = _load("activation_mount_collision", "arkhai-activate-lease-storage.py")
    publication = tmp_path / "run-units"
    override = tmp_path / "etc-units"
    publication.mkdir()
    override.mkdir()
    operations = activation.SystemOperations(
        loop_device=Path("/dev/loop7"), mount_unit_root=publication,
        mount_point=tmp_path / "volume", systemd_search_roots=(override, publication),
    )
    (override / "run-arkhai-volume.mount.d").mkdir()

    with pytest.raises(activation.ActivationRefused, match="drop-in already exists"):
        operations._reject_unit_collision("run-arkhai-volume.mount")


def test_activation_supervisor_owns_content_addressed_request_and_outcome(tmp_path):
    activation = _load("activation_request_shape", "arkhai-activate-lease-storage.py")
    supervisor = _load(
        "activation_supervisor", "arkhai-supervise-lease-storage-activation.py"
    )
    root = tmp_path / "requests"
    root.mkdir(mode=0o700)
    request = _request(activation, type("Config", (), {
        "host_id": "host-1", "machine_id": "machine-1", "generation": "generation-1"
    })())
    request_id = supervisor.accept_request(root, request)
    observed = []
    receipt = supervisor.execute_request(
        root, request_id,
        executor=lambda *, request, marker: observed.append(request) or {"state": marker},
        runtime_check=lambda _request_id, _request: None,
        marker="completed",
    )
    assert observed == [request]
    assert receipt == {"state": "completed"}
    outcome = json.loads((root / f"{request_id}.execution.json").read_text())
    assert outcome["state"] == "completed"


def test_activation_supervisor_quarantines_executor_lost_response(tmp_path):
    activation = _load("activation_request_failure", "arkhai-activate-lease-storage.py")
    supervisor = _load(
        "activation_supervisor_failure", "arkhai-supervise-lease-storage-activation.py"
    )
    root = tmp_path / "requests"
    root.mkdir(mode=0o700)
    config = type("Config", (), {
        "host_id": "host-1", "machine_id": "machine-1", "generation": "generation-1"
    })()
    request_id = supervisor.accept_request(root, _request(activation, config))
    with pytest.raises(RuntimeError, match="lost response"):
        supervisor.execute_request(
            root, request_id,
            executor=lambda **_values: (_ for _ in ()).throw(RuntimeError("lost response")),
            runtime_check=lambda _request_id, _request: None,
        )
    outcome = json.loads((root / f"{request_id}.execution.json").read_text())
    assert outcome["state"] == "quarantined"
    assert outcome["reason_code"] == "activation-completion-uncertain"


def test_role_does_not_install_or_enable_activation_artifacts():
    tasks = (
        Path(__file__).parents[1]
        / "ansible/roles/bare-metal-access/tasks/main.yml"
    ).read_text(encoding="utf-8")
    assert "arkhai-activate-lease-storage.py" not in tasks
    assert "arkhai-supervise-lease-storage-activation.py" not in tasks
    assert "lease-storage-open@.service.j2" not in tasks
    assert "lease-volume.mount.j2" not in tasks


def test_actual_loop_attach_encodes_uapi_and_validates_full_readback(tmp_path, monkeypatch):
    activation = _load("activation_loop_uapi", "arkhai-activate-lease-storage.py")
    backing = tmp_path / "volume.luks"
    loop = Path("/dev/loop7")
    backing_dev = 0x801
    backing_stat = type("Stat", (), {
        "st_mode": stat.S_IFREG | 0o600, "st_dev": backing_dev,
        "st_ino": 12345, "st_size": 64 * 1024 * 1024,
        "st_uid": 0, "st_gid": 0, "st_nlink": 1,
    })()
    loop_stat = type("Stat", (), {
        "st_mode": stat.S_IFBLK | 0o600, "st_rdev": os.makedev(7, 7),
    })()
    opened = iter((10, 11))
    monkeypatch.setattr(activation.os, "open", lambda *_args, **_values: next(opened))
    monkeypatch.setattr(
        activation.os, "fstat", lambda fd: backing_stat if fd == 10 else loop_stat
    )
    monkeypatch.setattr(activation.os, "close", lambda _fd: None)
    payloads = []
    monkeypatch.setattr(
        activation.fcntl, "ioctl",
        lambda fd, command, payload: payloads.append((fd, command, payload)),
    )
    readback = {
        "loopdevices": [{
            "name": "/dev/loop7", "autoclear": False,
            "back-file": str(backing), "back-ino": 12345,
            "back-maj:min": "8:1", "maj:min": "7:7", "offset": 0,
            "partscan": False, "ro": False, "sizelimit": 64 * 1024 * 1024,
            "dio": False, "log-sec": 512,
        }]
    }
    monkeypatch.setattr(
        activation.subprocess, "run",
        lambda argv, **_values: subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps(readback).encode(), stderr=b""
        ),
    )
    operations = activation.SystemOperations(
        loop_device=loop, mount_unit_root=tmp_path, mount_point=tmp_path / "mount"
    )
    expected = {
        "st_dev": backing_dev, "st_ino": 12345, "st_size": 64 * 1024 * 1024,
        "st_uid": 0, "st_gid": 0, "st_mode": 0o600, "st_nlink": 1,
    }

    identity = operations.attach_loop(backing, expected)

    assert identity == {
        "loop_device": "/dev/loop7", "loop_major_minor": "7:7",
        "backing_device": "8:1", "backing_inode": 12345,
        "size": 64 * 1024 * 1024,
    }
    decoded = activation._LOOP_CONFIG.unpack(payloads[0][2])
    assert decoded[0:7] == (10, 512, backing_dev, 12345, 0, 0, 64 * 1024 * 1024)


def _runtime_fixture(supervisor, tmp_path, request_id, boot_id):
    proc = tmp_path / "proc"
    cgroups = tmp_path / "cgroup"
    units = tmp_path / "units"
    (proc / "sys/kernel/random").mkdir(parents=True)
    (proc / "self").mkdir()
    (proc / "sys/kernel/random/boot_id").write_text(boot_id + "\n")
    (proc / "sys/kernel/core_pattern").write_text("core\n")
    (proc / "self/status").write_text(
        "CapEff:\t0000000000200000\nCapBnd:\t0000000000200000\n"
        "CapAmb:\t0000000000000000\nNoNewPrivs:\t1\nSeccomp:\t2\n"
    )
    unit = supervisor._UNIT.format(request_id)
    relative = Path("system.slice") / unit
    (proc / "self/cgroup").write_text(f"0::/{relative}\n")
    (cgroups / relative).mkdir(parents=True)
    (cgroups / relative / "memory.swap.max").write_text("0\n")
    units.mkdir()
    fragment = units / unit
    fragment.write_bytes(b"qualified activation unit\n")
    fragment.chmod(0o600)
    controls = {
        "system_call_filter": SYSTEMD_249_AMD64_MOUNT_DENY,
        "tpm_device": "/dev/tpm0",
        "loop_device": "/dev/loop7",
        "request_root": str(tmp_path / "requests"),
        "state_root": str(tmp_path / "state"),
        "mount_root": str(tmp_path / "mounts"),
        "mount_unit_root": str(tmp_path / "mount-units"),
    }
    expected = {
        "LoadState": "loaded", "FragmentPath": str(fragment), "DropInPaths": "",
        "Slice": "system.slice", "NoNewPrivileges": "yes", "PrivateDevices": "no",
        "ProtectSystem": "strict", "DevicePolicy": "closed",
        "CapabilityBoundingSet": "cap_sys_admin", "MemorySwapMax": "0",
        # systemd v249 resolves @mount through libseccomp for the native
        # architecture and sorts the names before publishing the D-Bus value.
        # Keep this producer fixture independent from the configured value so
        # a bad expected profile cannot manufacture a matching observation.
        "SystemCallFilter": SYSTEMD_249_AMD64_MOUNT_DENY,
        "ReadWritePaths": " ".join(
            controls[name]
            for name in ("request_root", "state_root", "mount_root", "mount_unit_root")
        ),
    }
    device_allow = (
        "/dev/loop-control rw", f"{controls['loop_device']} rw",
        "/dev/mapper/control rw", f"{controls['tpm_device']} rw",
        "block-device-mapper rw",
    )

    class Manager:
        values = expected
        devices = device_allow
        raw_override = None

        def run(self, _argv, **_values):
            if self.raw_override is not None:
                return subprocess.CompletedProcess(
                    [], 0, stdout=self.raw_override, stderr=b""
                )
            raw = "".join(f"{key}={value}\n" for key, value in self.values.items())
            raw += "".join(f"DeviceAllow={value}\n" for value in self.devices)
            return subprocess.CompletedProcess([], 0, stdout=raw.encode(), stderr=b"")

    return proc, cgroups, units, fragment, Manager(), controls


def test_runtime_fixture_uses_systemd_249_resolved_sorted_mount_group(tmp_path):
    supervisor = _load(
        "activation_runtime_syscall_fixture",
        "arkhai-supervise-lease-storage-activation.py",
    )
    _proc, _cgroups, _units, _fragment, manager, controls = _runtime_fixture(
        supervisor, tmp_path, "a" * 64, "boot-1"
    )

    assert controls["system_call_filter"] == SYSTEMD_249_AMD64_MOUNT_DENY
    assert manager.values["SystemCallFilter"] == SYSTEMD_249_AMD64_MOUNT_DENY
    assert SYSTEMD_249_AMD64_MOUNT_DENY.removeprefix("~").split() == sorted(
        SYSTEMD_249_AMD64_MOUNT_DENY.removeprefix("~").split()
    )


@pytest.mark.parametrize(
    "observed",
    [
        SYSTEMD_249_AMD64_MOUNT_DENY.replace(" fspick", ""),
        SYSTEMD_249_AMD64_MOUNT_DENY.replace("chroot", "chdir"),
    ],
)
def test_runtime_admission_rejects_missing_or_changed_resolved_mount_syscall(
    tmp_path, observed
):
    supervisor = _load(
        "activation_runtime_syscall_observed",
        "arkhai-supervise-lease-storage-activation.py",
    )
    proc, cgroups, units, fragment, manager, controls = _runtime_fixture(
        supervisor, tmp_path, "a" * 64, "boot-1"
    )
    manager.values = {**manager.values, "SystemCallFilter": observed}

    with pytest.raises(RuntimeError, match="effective unit profile"):
        supervisor.assert_runtime_controls(
            "a" * 64, "boot-1", unit_root=units,
            unit_sha256=hashlib.sha256(fragment.read_bytes()).hexdigest(),
            proc_root=proc, cgroup_root=cgroups, effective_uid=0,
            core_limit=(0, 0), manager_runner=manager,
            required_uid=os.getuid(), **controls,
        )


def test_runtime_admission_rejects_wrong_configured_syscall_order(tmp_path):
    supervisor = _load(
        "activation_runtime_syscall_configured",
        "arkhai-supervise-lease-storage-activation.py",
    )
    proc, cgroups, units, fragment, manager, controls = _runtime_fixture(
        supervisor, tmp_path, "a" * 64, "boot-1"
    )
    tokens = controls["system_call_filter"].split()
    controls["system_call_filter"] = " ".join((tokens[0], tokens[2], tokens[1], *tokens[3:]))
    assert manager.values["SystemCallFilter"] == SYSTEMD_249_AMD64_MOUNT_DENY

    with pytest.raises(RuntimeError, match="effective unit profile"):
        supervisor.assert_runtime_controls(
            "a" * 64, "boot-1", unit_root=units,
            unit_sha256=hashlib.sha256(fragment.read_bytes()).hexdigest(),
            proc_root=proc, cgroup_root=cgroups, effective_uid=0,
            core_limit=(0, 0), manager_runner=manager,
            required_uid=os.getuid(), **controls,
        )


def test_actual_runtime_admission_rejects_wrong_boot_before_executor(tmp_path):
    activation = _load("activation_runtime_request", "arkhai-activate-lease-storage.py")
    supervisor = _load(
        "activation_runtime_supervisor", "arkhai-supervise-lease-storage-activation.py"
    )
    root = tmp_path / "requests"
    root.mkdir(mode=0o700)
    config = type("Config", (), {
        "host_id": "host-1", "machine_id": "machine-1", "generation": "generation-1"
    })()
    request = _request(activation, config)
    request_id = supervisor.accept_request(root, request)
    proc, cgroups, units, fragment, manager, controls = _runtime_fixture(
        supervisor, tmp_path, request_id, "different-boot"
    )
    invoked = []
    runtime = lambda selected, value: supervisor.assert_runtime_controls(
        selected, value["boot_id"], unit_root=units,
        unit_sha256=hashlib.sha256(fragment.read_bytes()).hexdigest(),
        proc_root=proc, cgroup_root=cgroups, effective_uid=0, core_limit=(0, 0),
        manager_runner=manager, required_uid=os.getuid(), **controls,
    )

    with pytest.raises(RuntimeError, match="boot identity"):
        supervisor.execute_request(
            root, request_id, executor=lambda **_values: invoked.append(True),
            runtime_check=runtime,
        )
    assert invoked == []
    outcome = json.loads((root / f"{request_id}.execution.json").read_text())
    assert outcome["state"] == "refused"


@pytest.mark.parametrize(
    ("property_name", "replacement"),
    [
        ("SystemCallFilter", "~mount"),
        ("ReadWritePaths", "/foreign"),
        ("DeviceAllow", ("/dev/loop-control rw",)),
    ],
)
def test_runtime_admission_rejects_effective_profile_mismatch_before_executor(
    tmp_path, property_name, replacement
):
    activation = _load("activation_runtime_profile_request", "arkhai-activate-lease-storage.py")
    supervisor = _load(
        "activation_runtime_profile_supervisor",
        "arkhai-supervise-lease-storage-activation.py",
    )
    root = tmp_path / "requests"
    root.mkdir(mode=0o700)
    config = type("Config", (), {
        "host_id": "host-1", "machine_id": "machine-1", "generation": "generation-1"
    })()
    request = _request(activation, config)
    request_id = supervisor.accept_request(root, request)
    proc, cgroups, units, fragment, manager, controls = _runtime_fixture(
        supervisor, tmp_path, request_id, request["boot_id"]
    )
    if property_name == "DeviceAllow":
        manager.devices = replacement
    else:
        manager.values = {**manager.values, property_name: replacement}
    invoked = []

    with pytest.raises(RuntimeError, match="effective unit profile"):
        supervisor.execute_request(
            root,
            request_id,
            executor=lambda **_values: invoked.append(True),
            runtime_check=lambda selected, value: supervisor.assert_runtime_controls(
                selected, value["boot_id"], unit_root=units,
                unit_sha256=hashlib.sha256(fragment.read_bytes()).hexdigest(),
                proc_root=proc, cgroup_root=cgroups, effective_uid=0,
                core_limit=(0, 0), manager_runner=manager,
                required_uid=os.getuid(), **controls,
            ),
        )
    assert invoked == []


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "device-duplicate", "malformed"])
def test_runtime_admission_rejects_incomplete_or_malformed_manager_profile(
    tmp_path, corruption
):
    activation = _load("activation_runtime_malformed_request", "arkhai-activate-lease-storage.py")
    supervisor = _load(
        "activation_runtime_malformed_supervisor",
        "arkhai-supervise-lease-storage-activation.py",
    )
    root = tmp_path / "requests"
    root.mkdir(mode=0o700)
    config = type("Config", (), {
        "host_id": "host-1", "machine_id": "machine-1", "generation": "generation-1"
    })()
    request = _request(activation, config)
    request_id = supervisor.accept_request(root, request)
    proc, cgroups, units, fragment, manager, controls = _runtime_fixture(
        supervisor, tmp_path, request_id, request["boot_id"]
    )
    lines = [f"{key}={value}\n" for key, value in manager.values.items()]
    lines.extend(f"DeviceAllow={value}\n" for value in manager.devices)
    if corruption == "missing":
        lines = [line for line in lines if not line.startswith("SystemCallFilter=")]
    elif corruption == "duplicate":
        lines.append(f"ReadWritePaths={manager.values['ReadWritePaths']}\n")
    elif corruption == "device-duplicate":
        lines.append(f"DeviceAllow={manager.devices[0]}\n")
    else:
        lines.append("not-a-property\n")
    manager.raw_override = "".join(lines).encode()
    invoked = []

    with pytest.raises(RuntimeError, match="unit profile is malformed"):
        supervisor.execute_request(
            root, request_id, executor=lambda **_values: invoked.append(True),
            runtime_check=lambda selected, value: supervisor.assert_runtime_controls(
                selected, value["boot_id"], unit_root=units,
                unit_sha256=hashlib.sha256(fragment.read_bytes()).hexdigest(),
                proc_root=proc, cgroup_root=cgroups, effective_uid=0,
                core_limit=(0, 0), manager_runner=manager,
                required_uid=os.getuid(), **controls,
            ),
        )
    assert invoked == []


@pytest.mark.parametrize("mask", [0o002, 0o077])
def test_runtime_fixture_fragment_is_private_under_ordinary_umasks(tmp_path, mask):
    supervisor = _load(
        f"activation_runtime_umask_{mask:o}",
        "arkhai-supervise-lease-storage-activation.py",
    )
    previous = os.umask(mask)
    try:
        proc, cgroups, units, fragment, manager, controls = _runtime_fixture(
            supervisor, tmp_path, "a" * 64, "boot-1"
        )
    finally:
        os.umask(previous)
    assert stat.S_IMODE(fragment.stat().st_mode) == 0o600
    supervisor.assert_runtime_controls(
        "a" * 64, "boot-1", unit_root=units,
        unit_sha256=hashlib.sha256(fragment.read_bytes()).hexdigest(),
        proc_root=proc, cgroup_root=cgroups, effective_uid=0,
        core_limit=(0, 0), manager_runner=manager,
        required_uid=os.getuid(), **controls,
    )


def test_outcome_rename_fsync_failure_never_dispatches_executor(tmp_path, monkeypatch):
    activation = _load("activation_fsync_request", "arkhai-activate-lease-storage.py")
    supervisor = _load(
        "activation_fsync_supervisor", "arkhai-supervise-lease-storage-activation.py"
    )
    root = tmp_path / "requests"
    root.mkdir(mode=0o700)
    config = type("Config", (), {
        "host_id": "host-1", "machine_id": "machine-1", "generation": "generation-1"
    })()
    request_id = supervisor.accept_request(root, _request(activation, config))
    fsync_calls = []

    def fail_post_rename(_fd):
        fsync_calls.append(True)
        if len(fsync_calls) == 3:
            raise OSError("controlled directory fsync failure")

    monkeypatch.setattr(supervisor.os, "fsync", fail_post_rename)
    invoked = []
    with pytest.raises(OSError, match="directory fsync"):
        supervisor.execute_request(
            root, request_id, runtime_check=lambda *_args: None,
            executor=lambda **_values: invoked.append(True),
        )
    assert len(fsync_calls) == 3
    assert invoked == []
    assert json.loads((root / f"{request_id}.execution.json").read_text())["state"] == "running"


def test_supervisor_to_actual_operations_completes_with_only_external_boundaries_controlled(
    tmp_path, monkeypatch
):
    helper, config, prepared_runner = _prepared(tmp_path)
    custody, custody_backend = _actual_custody(config, prepared_runner)
    activation = _load("activation_composed", "arkhai-activate-lease-storage.py")
    supervisor = _load(
        "activation_composed_supervisor", "arkhai-supervise-lease-storage-activation.py"
    )
    request_root = tmp_path / "activation-requests"
    request_root.mkdir(mode=0o700)
    request = _request(activation, config)
    request_id = supervisor.accept_request(request_root, request)
    proc, cgroups, units, fragment, manager, controls = _runtime_fixture(
        supervisor, tmp_path, request_id, request["boot_id"]
    )
    mount_units = tmp_path / "mount-units"
    mount_units.mkdir()
    mount_parent = tmp_path / "mounts"
    mount_parent.mkdir()
    mount_point = mount_parent / config.generation
    mapper_root = tmp_path / "mapper"
    mapper_root.mkdir()
    loop_path = Path("/dev/loop7")
    loop_placeholder = tmp_path / "loop7"
    loop_placeholder.write_bytes(b"")
    sys_root = tmp_path / "sys-dev-block"
    mountinfo = tmp_path / "pid1-mountinfo"
    mountinfo.write_text("")
    backing = config.state_root / "leases" / config.generation / "volume.luks"
    backing_stat = backing.stat()
    mapper_name = f"arkhai-{request_id[:16]}"
    luks_uuid = prepared_runner.luks_uuid
    dm_uuid = f"CRYPT-LUKS2-{luks_uuid.replace('-', '')}-{mapper_name}"
    node = mapper_root / mapper_name
    loop_fds = set()
    original_open = os.open
    original_fstat = os.fstat
    original_stat = os.stat

    def controlled_open(path, flags, *args, **values):
        if Path(path) == loop_path:
            path = loop_placeholder
        fd = original_open(path, flags, *args, **values)
        if Path(path) == loop_placeholder:
            loop_fds.add(fd)
        return fd

    def controlled_fstat(fd):
        if fd in loop_fds:
            return type("Stat", (), {
                "st_mode": stat.S_IFBLK | 0o600, "st_rdev": os.makedev(7, 7)
            })()
        return original_fstat(fd)

    def controlled_stat(path, *args, **values):
        if Path(path) == node and values.get("follow_symlinks", True):
            return type("Stat", (), {
                "st_mode": stat.S_IFBLK | 0o600, "st_rdev": os.makedev(253, 7)
            })()
        return original_stat(path, *args, **values)

    monkeypatch.setattr(os, "open", controlled_open)
    monkeypatch.setattr(os, "fstat", controlled_fstat)
    monkeypatch.setattr(os, "stat", controlled_stat)
    ioctl_payloads = []
    monkeypatch.setattr(
        activation.fcntl, "ioctl",
        lambda fd, command, payload: ioctl_payloads.append((command, payload)),
    )
    formatted_uuid = {"value": None}
    command_log = []

    def command_boundary(argv, **values):
        argv = tuple(str(item) for item in argv)
        command_log.append((argv, values.get("input")))
        if argv[0] == "losetup":
            value = {"loopdevices": [{
                "name": str(loop_path), "autoclear": False,
                "back-file": str(backing), "back-ino": backing_stat.st_ino,
                "back-maj:min": f"{os.major(backing_stat.st_dev)}:{os.minor(backing_stat.st_dev)}",
                "maj:min": "7:7", "offset": 0, "partscan": False, "ro": False,
                "sizelimit": backing_stat.st_size, "dio": False, "log-sec": 512,
            }]}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(value).encode(), stderr=b"")
        if argv[0] == "cryptsetup":
            assert values["input"] == b"S" * 32
            (tmp_path / "dm-7").write_bytes(b"")
            node.symlink_to("../dm-7")
            kernel = sys_root / "253:7"
            (kernel / "dm").mkdir(parents=True)
            (kernel / "slaves" / "loop7").mkdir(parents=True)
            (kernel / "dm/name").write_text(mapper_name + "\n")
            (kernel / "dm/uuid").write_text(dm_uuid + "\n")
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        if argv[0] == "dmsetup":
            return subprocess.CompletedProcess(
                argv, 0, stdout=f"{mapper_name}:253:7:{dm_uuid}\n".encode(), stderr=b""
            )
        if argv[0] == "wipefs":
            return subprocess.CompletedProcess(argv, 0, stdout=b'{"signatures":[]}\n', stderr=b"")
        if argv[0] == "mkfs.ext4":
            formatted_uuid["value"] = argv[argv.index("-U") + 1]
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        if argv[0] == "blkid":
            tag = argv[argv.index("--match-tag") + 1]
            value = "ext4" if tag == "TYPE" else formatted_uuid["value"]
            raw = f"{value}\n".encode()
            return subprocess.CompletedProcess(argv, 0, stdout=raw, stderr=b"")
        if argv[0] == "systemd-escape":
            return subprocess.CompletedProcess(
                argv, 0, stdout=b"tmp-arkhai-generation\\x2d1.mount\n", stderr=b""
            )
        if argv[:2] == ("systemctl", "daemon-reload"):
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        if argv[:2] == ("systemctl", "show"):
            names = [item.removeprefix("--property=") for item in argv if item.startswith("--property=")]
            unit_path = mount_units / argv[-1]
            profile = {
                "LoadState": "loaded", "FragmentPath": str(unit_path),
                "DropInPaths": "", "UnitFileState": "static",
                "What": str(node), "Where": str(mount_point), "Type": "ext4",
                "Options": "rw,nosuid,nodev,noexec", "Slice": "system.slice",
                "ActiveState": "active", "SubState": "mounted", "Result": "success",
            }
            raw = "".join(f"{name}={profile[name]}\n" for name in names).encode()
            return subprocess.CompletedProcess(argv, 0, stdout=raw, stderr=b"")
        if argv[:2] == ("systemctl", "start"):
            mountinfo.write_text(
                f"41 30 253:7 / {mount_point} rw,nosuid,nodev,noexec - ext4 {node} rw\n"
            )
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        raise AssertionError(f"unsupported command: {argv}")

    monkeypatch.setattr(activation.subprocess, "run", command_boundary)
    operations = activation.SystemOperations(
        loop_device=loop_path, mount_unit_root=mount_units, mount_point=mount_point,
        mapper_root=mapper_root, sys_dev_block=sys_root,
        systemd_search_roots=(mount_units,), pid1_mountinfo=mountinfo,
        required_uid=os.getuid(),
    )
    controls.update({
        "loop_device": str(loop_path),
        "request_root": str(request_root),
        "state_root": str(config.state_root),
        "mount_root": str(mount_parent),
        "mount_unit_root": str(mount_units),
    })
    manager.values = {
        **manager.values,
        "ReadWritePaths": " ".join(
            controls[name]
            for name in ("request_root", "state_root", "mount_root", "mount_unit_root")
        ),
    }
    manager.devices = (
        "/dev/loop-control rw", f"{controls['loop_device']} rw",
        "/dev/mapper/control rw", f"{controls['tpm_device']} rw",
        "block-device-mapper rw",
    )
    runtime = lambda selected, value: supervisor.assert_runtime_controls(
        selected, value["boot_id"], unit_root=units,
        unit_sha256=hashlib.sha256(fragment.read_bytes()).hexdigest(),
        proc_root=proc, cgroup_root=cgroups, effective_uid=0, core_limit=(0, 0),
        manager_runner=manager, required_uid=os.getuid(), **controls,
    )

    receipt = supervisor.execute_request(
        request_root, request_id, runtime_check=runtime,
        executor=lambda *, request: activation.execute(
            config, request, runner=prepared_runner,
            custody_factory=lambda: custody,
            operations=operations,
        ),
    )

    assert receipt["state"] == "completed"
    assert receipt["mapper"]["dm_uuid"] == dm_uuid
    assert receipt["mount"]["options"] == ["nodev", "noexec", "nosuid", "rw"]
    assert len(ioctl_payloads) == 1
    assert all(secret is None or secret == b"S" * 32 for _argv, secret in command_log)
    custody_calls = [call[0] for call in custody_backend.calls]
    assert custody_calls.index("load_sealed") < custody_calls.index("start_policy")
    assert custody_calls.index("unseal") < custody_calls.index("flush:0x80000001")
    assert custody_calls.index("flush:0x80000001") < custody_calls.index("close")


@pytest.mark.parametrize(
    ("failure", "sealed_name", "expected_events", "forbidden_call"),
    [
        (None, b"\x00\x0b" + b"X" * 32, ["loop"], "start_policy"),
        ("unseal", None, ["loop"], None),
        ("close", None, ["loop", "mapper"], None),
    ],
)
def test_supervised_activation_with_actual_custody_quarantines_before_later_mutation(
    tmp_path, failure, sealed_name, expected_events, forbidden_call
):
    _helper, config, prepared_runner = _prepared(tmp_path)
    activation = _load(
        f"activation_actual_custody_failure_{failure or 'name'}",
        "arkhai-activate-lease-storage.py",
    )
    supervisor = _load(
        f"activation_actual_custody_supervisor_{failure or 'name'}",
        "arkhai-supervise-lease-storage-activation.py",
    )
    custody, backend = _actual_custody(
        config, prepared_runner, fail_at=failure, sealed_name=sealed_name
    )
    root = tmp_path / "activation-requests"
    root.mkdir(mode=0o700)
    request_id = supervisor.accept_request(root, _request(activation, config))
    operations = Operations()

    with pytest.raises(Exception):
        supervisor.execute_request(
            root, request_id, runtime_check=lambda *_args: None,
            executor=lambda *, request: activation.execute(
                config, request, runner=prepared_runner,
                custody_factory=lambda: custody, operations=operations,
            ),
        )

    assert operations.events == expected_events
    calls = [call[0] for call in backend.calls]
    if forbidden_call is not None:
        assert forbidden_call not in calls
    if failure == "unseal":
        assert "unseal" in calls
        assert "flush:0x80000001" in calls
        assert "flush:0x3000001" in calls
    assert "close" in calls
    outcome = json.loads((root / f"{request_id}.execution.json").read_text())
    assert outcome["state"] == "quarantined"
