#!/usr/bin/python3
"""Accept and execute one provider-owned lease-storage preparation request."""

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
import uuid
from pathlib import Path


REQUEST_SCHEMA = "arkhai.lease-storage-request.v1"
EXECUTION_SCHEMA = "arkhai.lease-storage-execution.v1"
_REQUEST_ID = re.compile(r"[0-9a-f]{64}\Z")
_DIRECT_TPM = re.compile(r"/dev/tpm[0-9]+\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_NV_INDEX = re.compile(r"0x[0-9a-f]{7,8}\Z")
_PARENT_HANDLE = re.compile(r"0x81[0-9a-f]{6}\Z")
_HEX_NAME = re.compile(r"(?:[0-9a-f]{2}){3,}\Z")
_MAX_DOCUMENT = 64 * 1024
_SYSTEMCTL = "/usr/bin/systemctl"
_UNIT = "arkhai-lease-storage-prepare@{}.service"


class SupervisionRefused(RuntimeError):
    """The request is outside the enforced provider boundary."""


class SupervisionQuarantined(SupervisionRefused):
    """Durable evidence cannot prove that a mutation is safe to retry."""


class SupervisionUnresolved(SupervisionRefused):
    """The boundary cannot prove a durable final outcome."""


class _InvalidOwnedContent(SupervisionRefused):
    """An admitted private file has invalid bounded content."""


class SupervisionProfile:
    def __init__(
        self,
        *,
        request_root,
        state_root,
        tpm_device,
        cryptsetup_path,
        cryptsetup_version,
        required_uid=0,
    ):
        self.request_root = Path(request_root)
        self.state_root = Path(state_root)
        self.tpm_device = str(tpm_device)
        self.cryptsetup_path = Path(cryptsetup_path)
        self.cryptsetup_version = str(cryptsetup_version)
        self.required_uid = required_uid
        if (
            not self.request_root.is_absolute()
            or self.request_root == Path("/")
            or not self.state_root.is_absolute()
            or self.state_root == Path("/")
        ):
            raise SupervisionRefused("supervision roots must be bounded absolute paths")
        if not _DIRECT_TPM.fullmatch(self.tpm_device) or self.tpm_device == "/dev/tpmrm0":
            raise SupervisionRefused("profile requires an explicit direct TPM device")
        if (
            not self.cryptsetup_path.is_absolute()
            or self.cryptsetup_path.name != "cryptsetup"
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", self.cryptsetup_version)
        ):
            raise SupervisionRefused("profile has invalid cryptsetup qualification")


class _SystemctlRunner:
    def run(self, argv, *, timeout):
        try:
            return subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SupervisionUnresolved("systemd request outcome is unresolved") from exc


class _CloseOnceCustody:
    def __init__(self, custody):
        self._custody = custody
        self.closed = False

    def __getattr__(self, name):
        return getattr(self._custody, name)

    def close(self):
        if not self.closed:
            self._custody.close()
            self.closed = True


def _canonical(value) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    except (TypeError, UnicodeError) as exc:
        raise SupervisionRefused("request is not canonical JSON") from exc


def request_identity(request) -> str:
    _validate_request(request)
    return hashlib.sha256(_canonical(request)).hexdigest()


def _validate_request(request) -> None:
    fields = {
        "schema",
        "host_id",
        "machine_id",
        "generation",
        "backing_size",
        "free_space_floor",
        "nv_index",
        "counter_headroom",
        "parent_handle",
        "parent_name",
    }
    if not isinstance(request, dict) or set(request) != fields:
        raise SupervisionRefused("request fields do not match the storage schema")
    if request.get("schema") != REQUEST_SCHEMA:
        raise SupervisionRefused("request schema is unsupported")
    for field in ("host_id", "machine_id", "generation"):
        value = request[field]
        if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
            raise SupervisionRefused(f"request has invalid {field}")
    for field in ("backing_size", "free_space_floor", "counter_headroom"):
        if type(request[field]) is not int:
            raise SupervisionRefused(f"request has invalid {field}")
    if request["backing_size"] < 16 * 1024 * 1024:
        raise SupervisionRefused("request backing size is too small for LUKS2")
    if request["free_space_floor"] < 0 or request["counter_headroom"] < 1:
        raise SupervisionRefused("request has invalid storage safety limit")
    if not isinstance(request["nv_index"], str) or not _NV_INDEX.fullmatch(
        request["nv_index"]
    ) or not 0x01000000 <= int(request["nv_index"], 16) <= 0x01FFFFFF:
        raise SupervisionRefused("request has invalid NV index")
    if not isinstance(request["parent_handle"], str) or not _PARENT_HANDLE.fullmatch(
        request["parent_handle"]
    ):
        raise SupervisionRefused("request has invalid persistent parent handle")
    if not isinstance(request["parent_name"], str) or not _HEX_NAME.fullmatch(
        request["parent_name"]
    ):
        raise SupervisionRefused("request has invalid parent Name")


def _owned_directory(path: Path, uid: int) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SupervisionRefused(f"owned directory is unavailable: {path}") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != uid
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise SupervisionRefused(f"owned directory is not private: {path}")


def _owned_file(path: Path, uid: int, *, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SupervisionRefused(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode):
        raise SupervisionRefused(f"{label} is a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise SupervisionRefused(f"{label} is not a regular file")
    if info.st_uid != uid:
        raise SupervisionRefused(f"{label} has foreign ownership")
    if info.st_nlink != 1:
        raise SupervisionRefused(f"{label} must have exactly one link")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise SupervisionRefused(f"{label} is not mode 0600")


def _owned_open_file(fd: int, uid: int, *, label: str) -> None:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise SupervisionRefused(f"{label} is not a regular file")
    if info.st_uid != uid:
        raise SupervisionRefused(f"{label} has foreign ownership")
    if info.st_nlink != 1:
        raise SupervisionRefused(f"{label} must have exactly one link")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise SupervisionRefused(f"{label} is not mode 0600")


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_new(path: Path, value) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        remaining = memoryview(_canonical(value) + b"\n")
        while remaining:
            written = os.write(fd, remaining)
            if written == 0:
                raise OSError("short write while persisting supervision evidence")
            remaining = remaining[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_directory(path.parent)


def _replace_owned(path: Path, value, uid: int) -> None:
    _owned_file(path, uid, label="execution record")
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        _write_new(temporary, value)
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_owned(path: Path, uid: int, *, label: str):
    _owned_file(path, uid, label=label)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        _owned_open_file(fd, uid, label=label)
        chunks = []
        remaining = _MAX_DOCUMENT + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    if len(data) > _MAX_DOCUMENT:
        raise _InvalidOwnedContent(f"{label} is too large")
    try:
        return json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _InvalidOwnedContent(f"{label} is not valid JSON") from exc


def _paths(profile: SupervisionProfile, request_id: str):
    if not _REQUEST_ID.fullmatch(request_id):
        raise SupervisionRefused("invalid request identity")
    root = profile.request_root
    return (
        root / f"{request_id}.request.json",
        root / f"{request_id}.execution.json",
        root / f"{request_id}.lock",
    )


def accept_request(profile: SupervisionProfile, request) -> str:
    _owned_directory(profile.request_root, profile.required_uid)
    request_id = request_identity(request)
    request_path, outcome_path, _ = _paths(profile, request_id)
    if request_path.is_symlink():
        raise SupervisionRefused("request path is a symlink")
    if request_path.exists() or outcome_path.exists():
        raise SupervisionRefused("request already exists; automatic retry is forbidden")
    try:
        _write_new(request_path, request)
    except FileExistsError as exc:
        raise SupervisionRefused(
            "request already exists; automatic retry is forbidden"
        ) from exc
    try:
        _write_new(
            outcome_path,
            {"schema": EXECUTION_SCHEMA, "request_id": request_id, "state": "accepted"},
        )
    except BaseException:
        # The request itself is durable evidence and is intentionally retained.
        raise SupervisionUnresolved("request acceptance evidence is incomplete")
    return request_id


def _lock_request(path: Path, uid: int):
    try:
        fd = os.open(
            path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as exc:
        raise SupervisionRefused("request lock cannot be opened safely") from exc
    try:
        _owned_open_file(fd, uid, label="request lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _persist_outcome(path, outcome, profile, state, *, receipt=None, reason_code=None):
    outcome["state"] = state
    if receipt is not None:
        outcome["receipt"] = receipt
    if reason_code is not None:
        outcome["reason_code"] = reason_code
    _replace_owned(path, outcome, profile.required_uid)


def _required_transition(
    path, outcome, profile, state, *, receipt=None, reason_code=None
):
    try:
        _persist_outcome(
            path,
            outcome,
            profile,
            state,
            receipt=receipt,
            reason_code=reason_code,
        )
    except BaseException as exc:
        raise SupervisionUnresolved(
            f"failed to persist supervised execution state {state}"
        ) from exc


def _verified_receipt(receipt, request):
    fields = {
        "schema",
        "host_id",
        "machine_id",
        "generation",
        "counter",
        "nv_index",
        "parent_name",
        "sealed_object_name",
        "state",
    }
    if not isinstance(receipt, dict) or set(receipt) != fields:
        raise SupervisionRefused("helper receipt has unexpected fields")
    for field in ("host_id", "machine_id", "generation", "nv_index", "parent_name"):
        if receipt[field] != request[field]:
            raise SupervisionRefused("helper receipt identity does not match request")
    if (
        receipt["schema"] != "arkhai.lease-storage-preparation.v1"
        or receipt["state"] != "prepared"
        or type(receipt["counter"]) is not int
        or receipt["counter"] < 0
        or not isinstance(receipt["sealed_object_name"], str)
        or not _HEX_NAME.fullmatch(receipt["sealed_object_name"])
    ):
        raise SupervisionRefused("helper receipt is not a valid prepared receipt")
    return receipt


def assert_runtime_controls(
    request_id: str,
    *,
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    effective_uid=None,
    core_limit=None,
) -> None:
    """Verify live unit controls before TPM access or lease-state mutation."""
    uid = os.geteuid() if effective_uid is None else effective_uid
    limits = resource.getrlimit(resource.RLIMIT_CORE) if core_limit is None else core_limit
    if uid != 0:
        raise SupervisionRefused("supervised preparation is not provider root")
    if limits != (0, 0):
        raise SupervisionRefused("core-dump hard and soft limits are not zero")
    # RLIMIT_CORE constrains file dumps but not a kernel pipe to a userspace
    # handler, so a hard-zero limit is sufficient only with a non-piped policy.
    core_pattern_path = proc_root / "sys" / "kernel" / "core_pattern"
    try:
        with core_pattern_path.open("rb") as core_pattern_file:
            raw_core_pattern = core_pattern_file.read(130)
    except OSError as exc:
        raise SupervisionRefused("core-pattern policy is unavailable") from exc
    if raw_core_pattern.endswith(b"\n"):
        raw_core_pattern = raw_core_pattern[:-1]
    if (
        not raw_core_pattern
        or len(raw_core_pattern) > 128
        or b"\n" in raw_core_pattern
        or b"\r" in raw_core_pattern
        or b"\x00" in raw_core_pattern
        or any(byte < 0x20 or byte == 0x7F for byte in raw_core_pattern)
    ):
        raise SupervisionRefused("malformed core-pattern policy")
    try:
        core_pattern = raw_core_pattern.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SupervisionRefused("malformed core-pattern policy") from exc
    if core_pattern != core_pattern.strip():
        raise SupervisionRefused("malformed core-pattern policy")
    if core_pattern.startswith("|"):
        raise SupervisionRefused("piped core handler is not admitted")
    try:
        status = (proc_root / "self" / "status").read_text(encoding="ascii")
        cgroup = (proc_root / "self" / "cgroup").read_text(encoding="ascii")
    except OSError as exc:
        raise SupervisionRefused("runtime control evidence is unavailable") from exc
    if not re.search(r"^NoNewPrivs:\s+1$", status, re.MULTILINE):
        raise SupervisionRefused("no-new-privileges is not active")
    expected = f"/system.slice/{_UNIT.format(request_id)}"
    entries = [line.split(":", 2) for line in cgroup.splitlines()]
    unified = [parts[2] for parts in entries if len(parts) == 3 and parts[:2] == ["0", ""]]
    if unified != [expected]:
        raise SupervisionRefused("process is not in its exact storage unit cgroup")
    swap_path = cgroup_root / expected.removeprefix("/") / "memory.swap.max"
    try:
        swap_max = swap_path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise SupervisionRefused("missing swap controller evidence") from exc
    if swap_max != "0":
        raise SupervisionRefused("unit swap limit is not zero")


def _load_sibling(name: str, filename: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SupervisionRefused("storage implementation cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execute_request(
    profile: SupervisionProfile,
    request_id: str,
    *,
    runtime_check=assert_runtime_controls,
    backend_factory=None,
    helper_module=None,
    custody_module=None,
    runner=None,
):
    _owned_directory(profile.request_root, profile.required_uid)
    _owned_directory(profile.state_root, profile.required_uid)
    request_path, outcome_path, lock_path = _paths(profile, request_id)
    lock_fd = _lock_request(lock_path, profile.required_uid)
    try:
        try:
            outcome = _read_owned(
                outcome_path, profile.required_uid, label="execution record"
            )
        except _InvalidOwnedContent as exc:
            outcome = {"schema": EXECUTION_SCHEMA, "request_id": request_id}
            _required_transition(
                outcome_path,
                outcome,
                profile,
                "quarantined",
                reason_code="execution-content-invalid",
            )
            raise SupervisionQuarantined("execution content changed") from exc
        except SupervisionRefused as exc:
            raise SupervisionUnresolved(
                "execution evidence cannot be admitted or safely replaced"
            ) from exc
        if (
            not isinstance(outcome, dict)
            or outcome.get("schema") != EXECUTION_SCHEMA
            or outcome.get("request_id") != request_id
        ):
            outcome = {"schema": EXECUTION_SCHEMA, "request_id": request_id}
            _required_transition(
                outcome_path,
                outcome,
                profile,
                "quarantined",
                reason_code="execution-identity-changed",
            )
            raise SupervisionQuarantined("execution identity changed")
        state = outcome.get("state")
        if state == "quarantined":
            raise SupervisionQuarantined("request is already quarantined")
        if state == "running":
            _required_transition(
                outcome_path,
                outcome,
                profile,
                "quarantined",
                reason_code="prior-execution-incomplete",
            )
            raise SupervisionQuarantined("prior execution has uncertain completion")
        if state not in {"accepted", "refused", "completed"}:
            _required_transition(
                outcome_path,
                outcome,
                profile,
                "quarantined",
                reason_code="execution-state-invalid",
            )
            raise SupervisionQuarantined("execution state is invalid")
        if state != "accepted":
            raise SupervisionRefused("request is not eligible for execution")
        try:
            request = _read_owned(
                request_path, profile.required_uid, label="request path"
            )
            if request_identity(request) != request_id:
                raise SupervisionQuarantined("request identity changed")
        except SupervisionRefused as exc:
            _required_transition(
                outcome_path,
                outcome,
                profile,
                "quarantined",
                reason_code="accepted-request-changed",
            )
            if isinstance(exc, SupervisionQuarantined):
                raise
            raise SupervisionQuarantined("accepted request cannot be trusted") from exc
        try:
            runtime_check(request_id)
        except BaseException as exc:
            _required_transition(
                outcome_path,
                outcome,
                profile,
                "refused",
                reason_code="runtime-controls-unverified",
            )
            if isinstance(exc, SupervisionRefused):
                raise
            raise SupervisionRefused("runtime controls could not be verified") from exc
        try:
            helper = helper_module or _load_sibling(
                "arkhai_lease_storage_prepare", "arkhai-prepare-lease-storage.py"
            )
            custody_api = custody_module or _load_sibling(
                "arkhai_tpm_esapi_custody", "arkhai_tpm_esapi_custody.py"
            )
            if runner is None:
                runner = helper.SubprocessRunner(
                    cryptsetup_path=profile.cryptsetup_path,
                    expected_version=profile.cryptsetup_version,
                )
        except BaseException as exc:
            _required_transition(
                outcome_path,
                outcome,
                profile,
                "refused",
                reason_code="runtime-dependency-unavailable",
            )
            raise SupervisionRefused("storage runtime dependency is unavailable") from exc
        _required_transition(outcome_path, outcome, profile, "running")

        factory = backend_factory or custody_api.PytssBackend.open_device
        backend = None
        custody = None
        try:
            backend = factory(profile.tpm_device)
            backend.bind(
                parent_handle=int(request["parent_handle"], 16),
                nv_index=int(request["nv_index"], 16),
            )
            custody = _CloseOnceCustody(custody_api.EsapiCustodyExecutor(backend))
            config = helper.PrepareConfig(
                state_root=profile.state_root,
                host_id=request["host_id"],
                machine_id=request["machine_id"],
                generation=request["generation"],
                backing_size=request["backing_size"],
                free_space_floor=request["free_space_floor"],
                nv_index=request["nv_index"],
                counter_headroom=request["counter_headroom"],
                parent_handle=request["parent_handle"],
                parent_name=request["parent_name"],
                required_uid=profile.required_uid,
            )
            receipt = helper.prepare(
                config,
                runner=runner,
                custody=custody,
                execution_evidence={
                    "boundary": "systemd-oneshot",
                    "request_id": request_id,
                },
            )
            custody.close()
            receipt = _verified_receipt(receipt, request)
        except BaseException as exc:
            cleanup_failure = None
            if custody is not None and not custody.closed:
                try:
                    custody.close()
                except BaseException as close_exc:
                    cleanup_failure = close_exc
            elif backend is not None:
                try:
                    backend.close()
                except BaseException as close_exc:
                    cleanup_failure = close_exc
            _required_transition(
                outcome_path,
                outcome,
                profile,
                "quarantined",
                reason_code="helper-completion-uncertain",
            )
            raise SupervisionQuarantined(
                "helper completion is uncertain; request quarantined"
            ) from (cleanup_failure or exc)
        _required_transition(
            outcome_path, outcome, profile, "completed", receipt=receipt
        )
        return receipt
    finally:
        os.close(lock_fd)


def submit_request(profile: SupervisionProfile, request, *, runner=None):
    request_id = accept_request(profile, request)
    command = (
        _SYSTEMCTL,
        "start",
        "--wait",
        _UNIT.format(request_id),
    )
    completed = (runner or _SystemctlRunner()).run(command, timeout=300)
    outcome_path = profile.request_root / f"{request_id}.execution.json"
    outcome = _read_owned(outcome_path, profile.required_uid, label="execution record")
    if completed.returncode != 0 or outcome.get("state") != "completed":
        raise SupervisionUnresolved(
            "systemd returned without durable helper completion evidence"
        )
    return outcome["receipt"]


def load_profile(path: Path) -> SupervisionProfile:
    value = _read_owned(path, 0, label="supervision profile")
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "request_root",
        "state_root",
        "tpm_device",
        "cryptsetup_path",
        "cryptsetup_version",
    } or value.get("schema") != "arkhai.lease-storage-supervision.v1":
        raise SupervisionRefused("supervision profile is invalid")
    return SupervisionProfile(
        request_root=value["request_root"],
        state_root=value["state_root"],
        tpm_device=value["tpm_device"],
        cryptsetup_path=value["cryptsetup_path"],
        cryptsetup_version=value["cryptsetup_version"],
    )


def _parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("submit", "execute"))
    parser.add_argument("request_id", nargs="?")
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("/etc/arkhai/lease-storage-supervision.json"),
    )
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    os.umask(0o077)
    try:
        profile = load_profile(args.profile)
        if args.action == "execute":
            if args.request_id is None:
                raise SupervisionRefused("execute requires a request identity")
            execute_request(profile, args.request_id)
        else:
            if args.request_id is not None:
                raise SupervisionRefused("submit reads its request from standard input")
            raw = sys.stdin.buffer.read(_MAX_DOCUMENT + 1)
            if len(raw) > _MAX_DOCUMENT:
                raise SupervisionRefused("request is too large")
            submit_request(profile, json.loads(raw))
    except (SupervisionRefused, UnicodeError, json.JSONDecodeError):
        # The durable fixed-schema outcome is authoritative; stderr carries no
        # exception detail because a future dependency might include secrets.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
