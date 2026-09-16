#!/usr/bin/python3
"""Own content-addressed activation requests without enabling ordinary use."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import resource
import stat
import subprocess
import sys
from pathlib import Path


_UNIT = "arkhai-lease-storage-open@{}.service"
_CAP_SYS_ADMIN = 1 << 21


def _load_activation():
    path = Path(__file__).resolve().with_name("arkhai-activate-lease-storage.py")
    spec = importlib.util.spec_from_file_location("arkhai_activation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("activation executor is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_new(path: Path, value) -> None:
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def _replace(path: Path, value) -> None:
    current = path.lstat()
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_uid != os.geteuid()
        or current.st_nlink != 1
        or current.st_mode & 0o777 != 0o600
    ):
        raise RuntimeError("activation execution record is unsafe")
    temporary = path.with_suffix(path.suffix + ".tmp")
    _write_new(temporary, value)
    os.replace(temporary, path)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def _read_owned(path: Path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or info.st_mode & 0o777 != 0o600
    ):
        raise RuntimeError("activation request evidence is unsafe")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = os.read(fd, 65537)
        if len(raw) > 65536:
            raise RuntimeError("activation request evidence is oversized")
        return json.loads(raw.decode("utf-8", errors="strict"))
    finally:
        os.close(fd)


def accept_request(request_root: Path, request: dict[str, object]) -> str:
    activation = _load_activation()
    root = request_root.lstat()
    if not stat.S_ISDIR(root.st_mode) or root.st_uid != os.geteuid() or root.st_mode & 0o077:
        raise activation.ActivationRefused("activation request root is unsafe")
    request_id = activation.request_identity(request)
    _write_new(request_root / f"{request_id}.json", request)
    _write_new(
        request_root / f"{request_id}.execution.json",
        {"schema": activation.REQUEST_SCHEMA, "request_id": request_id, "state": "accepted"},
    )
    return request_id


def _manager_properties(unit: str, names: tuple[str, ...], *, runner=None):
    argv = ("systemctl", "show", "--no-pager", *(f"--property={name}" for name in names), unit)
    try:
        completed = (runner or subprocess).run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("activation unit profile is unavailable") from exc
    if completed.returncode != 0 or len(completed.stdout) > 16384:
        raise RuntimeError("activation unit profile is unavailable")
    try:
        lines = completed.stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeError as exc:
        raise RuntimeError("activation unit profile is malformed") from exc
    values = {}
    repeated = []
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or key not in names:
            raise RuntimeError("activation unit profile is malformed")
        if key == "DeviceAllow":
            if not value or value in repeated:
                raise RuntimeError("activation unit profile is malformed")
            repeated.append(value)
            continue
        if key in values:
            raise RuntimeError("activation unit profile is malformed")
        values[key] = value
    if "DeviceAllow" in names:
        if not repeated:
            raise RuntimeError("activation unit profile is malformed")
        values["DeviceAllow"] = tuple(repeated)
    if set(values) != set(names):
        raise RuntimeError("activation unit profile is malformed")
    return values


def assert_runtime_controls(
    request_id: str,
    boot_id: str,
    *,
    unit_root: Path,
    unit_sha256: str,
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    effective_uid=None,
    core_limit=None,
    manager_runner=None,
    required_uid: int = 0,
    system_call_filter: str,
    tpm_device: str,
    loop_device: str,
    request_root: str,
    state_root: str,
    mount_root: str,
    mount_unit_root: str,
) -> None:
    uid = os.geteuid() if effective_uid is None else effective_uid
    limits = resource.getrlimit(resource.RLIMIT_CORE) if core_limit is None else core_limit
    if uid != 0 or limits != (0, 0):
        raise RuntimeError("activation runtime identity or core limits do not match")
    try:
        live_boot = (proc_root / "sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        core_raw = (proc_root / "sys/kernel/core_pattern").read_bytes()
        status = (proc_root / "self/status").read_text(encoding="ascii")
        cgroup = (proc_root / "self/cgroup").read_text(encoding="ascii")
    except OSError as exc:
        raise RuntimeError("activation runtime evidence is unavailable") from exc
    if live_boot != boot_id:
        raise RuntimeError("activation boot identity does not match")
    if core_raw.endswith(b"\n"):
        core_raw = core_raw[:-1]
    if (
        not core_raw or len(core_raw) > 128 or core_raw.startswith(b"|")
        or any(byte < 0x20 or byte == 0x7F for byte in core_raw)
    ):
        raise RuntimeError("activation core policy is not admitted")
    expected_caps = f"{_CAP_SYS_ADMIN:016x}"
    fields = dict(re.findall(r"^(CapEff|CapBnd|CapAmb):\s+([0-9A-Fa-f]+)$", status, re.MULTILINE))
    if fields != {"CapEff": expected_caps, "CapBnd": expected_caps, "CapAmb": "0000000000000000"}:
        raise RuntimeError("activation capability profile does not match")
    if not re.search(r"^NoNewPrivs:\s+1$", status, re.MULTILINE) or not re.search(
        r"^Seccomp:\s+2$", status, re.MULTILINE
    ):
        raise RuntimeError("activation process restrictions do not match")
    unit = _UNIT.format(request_id)
    expected_cgroup = f"/system.slice/{unit}"
    if cgroup.splitlines() != [f"0::{expected_cgroup}"]:
        raise RuntimeError("activation unit cgroup does not match")
    try:
        swap = (cgroup_root / expected_cgroup.removeprefix("/") / "memory.swap.max").read_text(encoding="ascii").strip()
    except OSError as exc:
        raise RuntimeError("activation swap evidence is unavailable") from exc
    if swap != "0":
        raise RuntimeError("activation swap limit does not match")
    fragment = unit_root / unit
    try:
        fragment_info = fragment.lstat()
        fragment_bytes = fragment.read_bytes()
    except OSError as exc:
        raise RuntimeError("activation unit fragment is unavailable") from exc
    if (
        not stat.S_ISREG(fragment_info.st_mode) or fragment_info.st_uid != required_uid
        or fragment_info.st_mode & 0o022 or hashlib.sha256(fragment_bytes).hexdigest() != unit_sha256
    ):
        raise RuntimeError("activation unit fragment does not match")
    expected = {
        "LoadState": "loaded", "FragmentPath": str(fragment), "DropInPaths": "",
        "Slice": "system.slice", "NoNewPrivileges": "yes", "PrivateDevices": "no",
        "ProtectSystem": "strict", "DevicePolicy": "closed",
        "CapabilityBoundingSet": "cap_sys_admin", "MemorySwapMax": "0",
        "SystemCallFilter": system_call_filter,
        "ReadWritePaths": " ".join(
            (request_root, state_root, mount_root, mount_unit_root)
        ),
    }
    syscall_tokens = system_call_filter.removeprefix("~").split(" ")
    paths = (request_root, state_root, mount_root, mount_unit_root)
    if (
        not system_call_filter.startswith("~")
        or any(not re.fullmatch(r"[a-z0-9_]+", token) for token in syscall_tokens)
        or len(set(syscall_tokens)) != len(syscall_tokens)
        or not {"mount", "umount2"}.issubset(syscall_tokens)
        or any(not path.startswith("/") or any(char.isspace() for char in path) for path in paths)
        or not re.fullmatch(r"/dev/tpm[0-9]+", tpm_device)
        or not re.fullmatch(r"/dev/loop[0-9]+", loop_device)
    ):
        raise RuntimeError("activation configured unit profile is malformed")
    observed = _manager_properties(
        unit, (*tuple(expected), "DeviceAllow"), runner=manager_runner
    )
    device_allow = observed.pop("DeviceAllow")
    expected_devices = {
        "/dev/loop-control rw", f"{loop_device} rw", "/dev/mapper/control rw",
        f"{tpm_device} rw", "block-device-mapper rw",
    }
    if (
        observed != expected
        or len(device_allow) != len(expected_devices)
        or set(device_allow) != expected_devices
        or tuple(observed["ReadWritePaths"].split(" ")) != paths
    ):
        raise RuntimeError("activation effective unit profile does not match")


def execute_request(
    request_root: Path, request_id: str, *, executor, runtime_check, **dependencies
):
    """Hold the request lock while the executor holds the nested host/index lock."""
    activation = _load_activation()
    if len(request_id) != 64 or any(char not in "0123456789abcdef" for char in request_id):
        raise activation.ActivationRefused("activation request identity is invalid")
    request_path = request_root / f"{request_id}.json"
    outcome_path = request_root / f"{request_id}.execution.json"
    lock_path = request_root / f"{request_id}.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    lock_info = os.fstat(fd)
    if (
        not stat.S_ISREG(lock_info.st_mode)
        or lock_info.st_uid != os.geteuid()
        or lock_info.st_nlink != 1
        or lock_info.st_mode & 0o777 != 0o600
    ):
        os.close(fd)
        raise activation.ActivationRefused("activation request lock is unsafe")
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        request = _read_owned(request_path)
        if activation.request_identity(request) != request_id:
            raise activation.ActivationQuarantined("accepted activation request changed")
        if outcome_path.exists():
            outcome = _read_owned(outcome_path)
            if outcome.get("state") != "accepted":
                raise activation.ActivationRefused("activation request is not eligible")
        try:
            runtime_check(request_id, request)
        except BaseException:
            outcome["state"] = "refused"
            outcome["reason_code"] = "runtime-controls-unverified"
            _replace(outcome_path, outcome)
            raise
        outcome["state"] = "running"
        _replace(outcome_path, outcome)
        try:
            result = executor(request=request, **dependencies)
        except BaseException:
            outcome["state"] = "quarantined"
            outcome["reason_code"] = "activation-completion-uncertain"
            _replace(outcome_path, outcome)
            raise
        outcome["state"] = "completed"
        outcome["receipt"] = result
        _replace(outcome_path, outcome)
        return result
    finally:
        os.close(fd)


def _load_sibling(name: str, filename: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("activation dependency is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args(argv)
    try:
        profile = _read_owned(args.profile)
        activation = _load_activation()
        helper = _load_sibling("arkhai_activation_prepare", "arkhai-prepare-lease-storage.py")
        custody_api = _load_sibling("arkhai_activation_custody", "arkhai_tpm_esapi_custody.py")
        request_root = Path(profile["request_root"])

        def invoke(*, request):
            config = helper.PrepareConfig(
                state_root=Path(profile["state_root"]),
                host_id=request["host_id"], machine_id=request["machine_id"],
                generation=request["generation"], backing_size=request["backing_size"],
                free_space_floor=request["free_space_floor"], nv_index=request["nv_index"],
                counter_headroom=request["counter_headroom"],
                parent_handle=request["parent_handle"], parent_name=request["parent_name"],
            )
            runner = helper.SubprocessRunner(
                cryptsetup_path=profile["cryptsetup_path"],
                expected_version=profile["cryptsetup_version"],
            )

            def custody_factory():
                backend = custody_api.PytssBackend.open_device(profile["tpm_device"])
                try:
                    backend.bind(
                        parent_handle=int(config.parent_handle, 16),
                        nv_index=int(config.nv_index, 16),
                    )
                    return custody_api.EsapiCustodyExecutor(backend)
                except BaseException:
                    backend.close()
                    raise

            operations = activation.SystemOperations(
                loop_device=Path(profile["loop_device"]),
                mount_unit_root=Path(profile["mount_unit_root"]),
                mount_point=Path(profile["mount_root"]) / config.generation,
            )
            return activation.execute(
                config, request, runner=runner,
                custody_factory=custody_factory, operations=operations,
            )

        receipt = execute_request(
            request_root,
            args.request_id,
            executor=invoke,
            runtime_check=lambda request_id, request: assert_runtime_controls(
                request_id,
                request["boot_id"],
                unit_root=Path(profile["activation_unit_root"]),
                unit_sha256=profile["activation_unit_sha256"],
                system_call_filter=profile["system_call_filter"],
                tpm_device=profile["tpm_device"],
                loop_device=profile["loop_device"],
                request_root=profile["request_root"],
                state_root=profile["state_root"],
                mount_root=profile["mount_root"],
                mount_unit_root=profile["mount_unit_root"],
            ),
        )
    except BaseException as exc:
        print(json.dumps({"state": "refused", "reason_code": type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
