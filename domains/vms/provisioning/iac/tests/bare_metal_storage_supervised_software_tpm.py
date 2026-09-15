#!/opt/custody-venv/bin/python
"""Qualify supervised storage preparation in a disposable systemd container.

The executable doubles as the test-only unit entrypoint.  It uses the
production request, runtime-admission, helper and custody code while replacing
only the production raw-device transport with a private software-TPM socket.
It never creates a mapping or mount and must not run on a host manager.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

TESTS = Path(__file__).resolve().parent
IAC = TESTS.parent
ROLE = IAC / "ansible" / "roles" / "bare-metal-access"
SUPERVISOR = ROLE / "files" / "arkhai-supervise-lease-storage.py"
PREPARE = ROLE / "files" / "arkhai-prepare-lease-storage.py"
CUSTODY = ROLE / "files" / "arkhai_tpm_esapi_custody.py"
UNIT_TEMPLATE = ROLE / "templates" / "lease-storage-prepare@.service.j2"
SOFTWARE_TPM_TEST = TESTS / "test_bare_metal_storage_software_tpm.py"
RUN = os.environ.get("ARKHAI_RUN_SUPERVISED_SOFTWARE_TPM") == "1"
UNIT = "arkhai-lease-storage-prepare@{}.service"
UNIT_PATH = Path("/run/systemd/system/arkhai-lease-storage-prepare@.service")
_WAIT_BUS_PROBE_UNIT = (
    "arkhai-m22-dispatch-probe-6d82b624f8ab4dd390c89f50e08f6701.service"
)
SYSTEMD_UNIT_SEARCH_DIRS = (
    Path("/run/systemd/system"),
    Path("/etc/systemd/system"),
    Path("/usr/local/lib/systemd/system"),
    Path("/usr/lib/systemd/system"),
    Path("/lib/systemd/system"),
)
CRYPTSETUP = Path("/usr/sbin/cryptsetup")
CRYPTSETUP_VERSION = "2.4.3"
_REQUEST_ID = re.compile(r"[0-9a-f]{64}\Z")
_UNIT_INSTANCE = re.compile(
    r"arkhai-lease-storage-prepare@(?P<request_id>[0-9a-f]{64})\.service\Z"
)
_QUALIFICATION_SCHEMA = "arkhai.supervised-software-tpm-qualification.v1"
_UNIT_FAILURE_SCHEMA = "arkhai.supervised-software-tpm-unit-failure.v5"
_CORE_PATTERN = Path("/proc/sys/kernel/core_pattern")
_CUSTODY_STAGES = {
    "after-policy-session-create",
    "after-object-load",
    "after-unseal-session-create",
    "after-unseal",
    "after-flush-session",
    "after-flush-object",
}
_SAFE_UNIT_STAGES = {
    "request-admission",
    "runtime-and-helper-dispatch",
    "software-tpm-start",
    "foreign-sentinel-create",
    "esapi-backend-open",
    "custody-finalize",
    "custody-finalized",
    "foreign-sentinel-verify",
} | {f"custody-{event}" for event in _CUSTODY_STAGES}
_SAFE_ERROR_CODES = {
    "AssertionError": "assertion-error",
    "CalledProcessError": "child-process-error",
    "CustodyRefused": "custody-refused",
    "CustodyUncertain": "custody-uncertain",
    "OSError": "os-error",
    "PreparationQuarantined": "preparation-quarantined",
    "PreparationRefused": "preparation-refused",
    "PreparationUnresolved": "preparation-unresolved",
    "SupervisionQuarantined": "supervision-quarantined",
    "SupervisionRefused": "supervision-refused",
    "SupervisionUnresolved": "supervision-unresolved",
    "TimeoutExpired": "child-timeout",
    "TSS2_Exception": "tpm-error",
    "ValueError": "value-error",
}
_SAFE_ERROR_CODE_VALUES = frozenset(_SAFE_ERROR_CODES.values()) | {
    "unexpected-error"
}
_PREPARATION_REFUSAL_CODES = {
    "state root must be a bounded absolute path": "state-root-unbounded",
    "invalid NV index": "nv-index-invalid",
    "NV index is outside the TPM NV handle range": "nv-index-out-of-range",
    "parent must use a recorded persistent handle": "parent-handle-invalid",
    "invalid recorded parent Name": "parent-name-invalid",
    "backing size is too small for LUKS2": "backing-size-too-small",
    "invalid storage safety limit": "storage-safety-limit-invalid",
    "required tool unavailable: cryptsetup": "cryptsetup-unavailable",
    "cryptsetup path is not an absolute binary path": "cryptsetup-path-invalid",
    "cryptsetup binary is not safely owned": "cryptsetup-ownership-invalid",
    "cryptsetup version cannot be verified": "cryptsetup-version-unverifiable",
    "cryptsetup version is not qualified": "cryptsetup-version-unqualified",
    "state root parent is not safely owned": "state-root-parent-ownership-invalid",
    "lease path has no matching ownership record": "lease-ownership-missing",
    "manifest identity does not match this lease": "manifest-identity-mismatch",
    "state root parent does not exist": "state-root-parent-missing",
    "host lock ownership does not match": "host-lock-ownership-mismatch",
    "host/index generation fence identity does not match": "generation-fence-identity-mismatch",
    "another active generation owns the host/index counter": "generation-fence-active",
    "invalid handle evidence": "handle-evidence-invalid",
    "invalid TPM ownership evidence": "tpm-ownership-evidence-invalid",
    "prior ESAPI ownership is incomplete; refusing stale-handle cleanup": "prior-esapi-ownership-incomplete",
    "TPM closure evidence is not from the checked ESAPI boundary": "tpm-closure-evidence-invalid",
    "ESAPI returned an invalid TPM handle identity": "esapi-handle-identity-invalid",
    "free-space floor would be violated": "free-space-floor-violated",
    "cannot verify LUKS2 keyslots": "luks2-keyslots-unverifiable",
    "lease volume does not have exactly one keyslot": "luks2-keyslot-count-invalid",
    "same-process ESAPI custody is not enabled for production preparation": "esapi-custody-disabled",
    "lease preparation is already quarantined": "preparation-already-quarantined",
    "invalid helper-attempt evidence": "helper-attempt-evidence-invalid",
    "invalid supervised execution evidence": "supervised-execution-evidence-invalid",
    "TPM resource verification failed": "tpm-resource-verification-failed",
    "backing file has no matching ownership intent": "backing-ownership-intent-missing",
    "NV counter read failed": "nv-counter-read-failed",
    "NV counter is inside the configured headroom": "nv-counter-headroom-refused",
    "counter advance has no durable exclusive-writer attribution": "counter-attribution-missing",
    "counter intent is missing its pre-increment value": "counter-preincrement-value-missing",
    "counter increment outcome is uncertain": "counter-increment-uncertain",
    "counter drift cannot be attributed to this attempt": "counter-drift-unattributed",
    "PolicyNV transaction did not close cleanly": "policy-nv-close-failed",
    "PolicyNV digest changed across retry": "policy-nv-digest-changed",
    "secret generator did not return 32 bytes": "secret-length-invalid",
    "sealed-object creation outcome is uncertain": "sealed-object-create-uncertain",
    "sealed object output is partial": "sealed-object-output-partial",
    "sealed object files have no matching ownership intent": "sealed-object-ownership-intent-missing",
    "sealed-object transaction did not complete with checked cleanup": "sealed-object-cleanup-unverified",
    "new sealed object did not recover its source secret": "sealed-object-source-secret-mismatch",
    "ESAPI ownership boundary did not finalize": "esapi-boundary-finalization-failed",
    "owned backing file has the wrong fixed size": "backing-size-mismatch",
    "owned backing file no longer has its verified LUKS2 header": "luks2-header-changed",
    "sealed secret must be recovered before formatting": "sealed-secret-not-recovered",
    "LUKS2 format outcome is uncertain": "luks2-format-uncertain",
    "new LUKS2 header cannot be verified": "luks2-header-unverifiable",
    "sealed secret is unavailable for LUKS2 verification": "sealed-secret-unavailable",
    "sealed secret does not unlock the verified LUKS2 header": "sealed-secret-unlock-failed",
    "cannot identify authoritative manifest to persist quarantine": "quarantine-manifest-unresolved",
    "failed to persist quarantine under the host/index lock": "quarantine-persistence-failed",
}
_PREPARATION_REFUSAL_PATTERNS = (
    (re.compile(r"invalid (?:host_id|machine_id|generation)\Z"), "lease-identity-invalid"),
    (re.compile(r"unapproved external command: [^\s]+\Z"), "external-command-unapproved"),
    (re.compile(r"cryptsetup failed with exit status -?[0-9]+\Z"), "cryptsetup-exit-status"),
    (re.compile(r"[^\s]+ failed with exit status -?[0-9]+\Z"), "external-command-exit-status"),
    (re.compile(r"required tool unavailable: [^\s]+\Z"), "external-tool-unavailable"),
    (re.compile(r"unsafe existing directory: .+\Z"), "existing-directory-unsafe"),
    (re.compile(r"state path contains a symlink: .+\Z"), "state-path-symlink"),
    (re.compile(r"refusing symlink: .+\Z"), "path-symlink"),
    (re.compile(r"unsafe owned metadata file: .+\Z"), "owned-metadata-file-unsafe"),
    (re.compile(r"invalid owned metadata file: .+\Z"), "owned-metadata-file-invalid"),
    (re.compile(r"invalid owned metadata object: .+\Z"), "owned-metadata-object-invalid"),
    (re.compile(r"refusing existing output path: [^/]+\Z"), "generated-output-exists"),
    (re.compile(r"unsafe existing file: .+\Z"), "existing-file-unsafe"),
)
_PREPARATION_ORIGIN_CODES = frozenset(_PREPARATION_REFUSAL_CODES.values()) | {
    code for _pattern, code in _PREPARATION_REFUSAL_PATTERNS
} | {"preparation-refusal-unclassified", "not-captured"}
_PREPARATION_ORIGIN_STAGES = {"helper-prepare", "not-captured"}
_HELPER_OPERATIONS = {
    "cryptsetup-is-luks",
    "cryptsetup-luks-format",
    "cryptsetup-luks-metadata",
    "cryptsetup-test-passphrase",
    "cryptsetup-unclassified",
    "not-observed",
}
_HELPER_OPERATION_RESULTS = {
    "exit-status",
    "not-observed",
    "os-error",
    "refused-without-returncode",
    "returncode-out-of-range",
    "returncode-zero",
    "signal-sigabrt",
    "signal-sigkill",
    "signal-sigsegv",
    "signal-sigsys",
    "signal-other",
    "timeout",
}
_TSS2_LAYERS = {
    0: "tpm",
    6: "feature",
    7: "esapi",
    8: "sys",
    9: "mu",
    10: "tcti",
    11: "resmgr",
    12: "resmgr-tpm",
}
_TSS2_SUBJECTS = {
    "not-observed",
    "software-layer",
    "tpm-format-zero",
    "tpm-handle",
    "tpm-parameter",
    "tpm-session",
    "unknown-layer",
}


class QualificationRefused(RuntimeError):
    """The isolated environment does not satisfy qualification prerequisites."""


class UnitOwnership:
    """An open descriptor pins the exact unit inode for this process lifetime."""

    __slots__ = ("descriptor", "device", "inode")

    def __init__(self, descriptor: int, device: int, inode: int):
        self.descriptor = descriptor
        self.device = device
        self.inode = inode


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _supervisor():
    return _load(SUPERVISOR, "supervised_qualification_supervisor")


def _custody():
    return _load(CUSTODY, "supervised_qualification_custody")


def _software_tpm():
    return _load(SOFTWARE_TPM_TEST, "supervised_qualification_software_tpm")


def _private_directory(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise AssertionError(f"qualification directory is not private: {path}")


def _write_private_json(path: Path, value) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
                "ascii"
            ) + b"\n"
            while payload:
                written = os.write(descriptor, payload)
                if written == 0:
                    raise OSError("short qualification write")
                payload = payload[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_private_json_once(path: Path, value) -> bool:
    """Atomically publish first-failure evidence without replacing a prior run."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
                "ascii"
            ) + b"\n"
            while payload:
                written = os.write(descriptor, payload)
                if written == 0:
                    raise OSError("short qualification write")
                payload = payload[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            return False
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _safe_error_code(exc: BaseException) -> str:
    current = exc
    visited = set()
    for _ in range(8):
        if id(current) in visited:
            break
        visited.add(id(current))
        next_error = current.__cause__
        if next_error is None:
            break
        current = next_error
    return _SAFE_ERROR_CODES.get(type(current).__name__, "unexpected-error")


def _preparation_refusal_code(exc: BaseException) -> str:
    message = str(exc)
    exact = _PREPARATION_REFUSAL_CODES.get(message)
    if exact is not None:
        return exact
    for pattern, code in _PREPARATION_REFUSAL_PATTERNS:
        if pattern.fullmatch(message):
            return code
    return "preparation-refusal-unclassified"


def _preparation_refusal_chain(exc: BaseException, refusal_type: type) -> tuple[str, str]:
    outer = _preparation_refusal_code(exc)
    deepest = outer
    current = exc
    visited = {id(current)}
    for _ in range(8):
        candidate = current.__cause__
        if candidate is None or id(candidate) in visited:
            break
        visited.add(id(candidate))
        if isinstance(candidate, refusal_type):
            deepest = _preparation_refusal_code(candidate)
        current = candidate
    return outer, deepest


def _tss2_failure_identity(exc: BaseException) -> tuple[int | None, str, str]:
    """Extract only the public numeric TSS return-code identity from a cause chain."""
    current = exc
    visited = set()
    for _ in range(8):
        if id(current) in visited:
            break
        visited.add(id(current))
        if type(current).__name__ == "TSS2_Exception":
            rc = getattr(current, "rc", None)
            if isinstance(rc, bool) or not isinstance(rc, int) or not 0 < rc < 2**32:
                return None, "not-observed", "not-observed"
            layer_number = (rc >> 16) & 0xFF
            layer = _TSS2_LAYERS.get(layer_number, "unknown")
            if layer not in {"tpm", "resmgr-tpm"}:
                subject = (
                    "unknown-layer" if layer == "unknown" else "software-layer"
                )
                return rc, layer, subject
            tpm_rc = rc & 0xFFFF
            if not tpm_rc & 0x80:
                return rc, layer, "tpm-format-zero"
            if tpm_rc & 0x40:
                return rc, layer, "tpm-parameter"
            if tpm_rc & 0x800:
                return rc, layer, "tpm-session"
            return rc, layer, "tpm-handle"
        if current.__cause__ is None:
            break
        current = current.__cause__
    return None, "not-observed", "not-observed"


def _valid_tss2_failure(rc, layer, subject) -> bool:
    if rc is None:
        return layer == "not-observed" and subject == "not-observed"
    if isinstance(rc, bool) or not isinstance(rc, int) or not 0 < rc < 2**32:
        return False
    if layer not in set(_TSS2_LAYERS.values()) | {"unknown"}:
        return False
    if subject not in _TSS2_SUBJECTS - {"not-observed"}:
        return False
    if layer in {"tpm", "resmgr-tpm"}:
        return subject.startswith("tpm-")
    if layer == "unknown":
        return subject == "unknown-layer"
    return subject == "software-layer"


def _cryptsetup_operation(argv) -> str:
    command = tuple(str(part) for part in argv)
    if not command or command[0] != "cryptsetup":
        return "cryptsetup-unclassified"
    without_path = command[:-1]
    if without_path == ("cryptsetup", "isLuks", "--type", "luks2"):
        return "cryptsetup-is-luks"
    if without_path == (
        "cryptsetup",
        "--batch-mode",
        "--type",
        "luks2",
        "--key-file",
        "-",
        "--keyfile-size",
        "32",
        "luksFormat",
    ):
        return "cryptsetup-luks-format"
    if without_path == (
        "cryptsetup",
        "luksDump",
        "--dump-json-metadata",
    ):
        return "cryptsetup-luks-metadata"
    if without_path == (
        "cryptsetup",
        "--type",
        "luks2",
        "--test-passphrase",
        "--disable-keyring",
        "--key-file",
        "-",
        "--keyfile-size",
        "32",
        "open",
    ):
        return "cryptsetup-test-passphrase"
    return "cryptsetup-unclassified"


def _cryptsetup_operation_result(exc: BaseException) -> tuple[str, int | None]:
    current = exc
    visited = set()
    for _ in range(8):
        if id(current) in visited:
            break
        visited.add(id(current))
        if isinstance(current, subprocess.TimeoutExpired):
            return "timeout", None
        if isinstance(current, OSError):
            return "os-error", None
        if current.__cause__ is None:
            break
        current = current.__cause__
    matched = re.fullmatch(
        r"cryptsetup failed with exit status (-?[0-9]+)", str(exc)
    )
    if matched is None:
        return "refused-without-returncode", None
    status = int(matched.group(1))
    if not -(2**31) <= status < 2**31:
        return "returncode-out-of-range", None
    if status > 0:
        return "exit-status", status
    if status == 0:
        return "returncode-zero", status
    signals = {
        -int(signal.SIGKILL): "signal-sigkill",
        -int(signal.SIGSYS): "signal-sigsys",
        -int(signal.SIGSEGV): "signal-sigsegv",
        -int(signal.SIGABRT): "signal-sigabrt",
    }
    return signals.get(status, "signal-other"), status


def _valid_operation_result(result, returncode) -> bool:
    if result not in _HELPER_OPERATION_RESULTS:
        return False
    if returncode is None:
        return result in {
            "not-observed",
            "os-error",
            "refused-without-returncode",
            "returncode-out-of-range",
            "timeout",
        }
    if (
        isinstance(returncode, bool)
        or not isinstance(returncode, int)
        or not -(2**31) <= returncode < 2**31
    ):
        return False
    if result == "exit-status":
        return returncode > 0
    if result == "returncode-zero":
        return returncode == 0
    known_signals = {
        "signal-sigkill": -int(signal.SIGKILL),
        "signal-sigsys": -int(signal.SIGSYS),
        "signal-sigsegv": -int(signal.SIGSEGV),
        "signal-sigabrt": -int(signal.SIGABRT),
    }
    if result in known_signals:
        return returncode == known_signals[result]
    return result == "signal-other" and returncode < 0 and returncode not in set(
        known_signals.values()
    )


def _parse_memory_events(raw: str) -> dict[str, int] | None:
    expected = {"low", "high", "max", "oom", "oom_kill"}
    values = {}
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 2 or not fields[1].isascii() or not fields[1].isdigit():
            return None
        if fields[0] in expected:
            if fields[0] in values:
                return None
            values[fields[0]] = int(fields[1])
    if set(values) != expected:
        return None
    return {name: values[name] for name in sorted(expected)}


def _unit_memory_events(request_id: str) -> dict[str, int] | None:
    unit = UNIT.format(request_id)
    expected_cgroup = f"0::/system.slice/{unit}\n"
    try:
        if Path("/proc/self/cgroup").read_text(encoding="ascii") != expected_cgroup:
            return None
        raw = Path(f"/sys/fs/cgroup/system.slice/{unit}/memory.events").read_text(
            encoding="ascii"
        )
    except (OSError, UnicodeError):
        return None
    return _parse_memory_events(raw)


def _publish_unit_failure(
    profile_path: Path,
    request_id: str,
    stage: str,
    exc: BaseException,
    *,
    origin_stage: str,
    origin_error_code: str,
    origin_cause_code: str,
    origin_operation: str,
    origin_operation_result: str,
    origin_operation_returncode: int | None,
    origin_tss2_rc: int | None,
    origin_tss2_layer: str,
    origin_tss2_subject: str,
    unit_memory_events: dict[str, int] | None,
) -> bool:
    root = profile_path.parent.resolve(strict=True)
    _private_directory(root)
    request_root = root / "requests"
    _private_directory(request_root)
    return _publish_private_json_once(
        request_root / "unit-failure.json",
        {
            "schema": _UNIT_FAILURE_SCHEMA,
            "request_id": request_id,
            "stage": stage,
            "error_code": _safe_error_code(exc),
            "origin_stage": origin_stage,
            "origin_error_code": origin_error_code,
            "origin_cause_code": origin_cause_code,
            "origin_operation": origin_operation,
            "origin_operation_result": origin_operation_result,
            "origin_operation_returncode": origin_operation_returncode,
            "origin_tss2_rc": origin_tss2_rc,
            "origin_tss2_layer": origin_tss2_layer,
            "origin_tss2_subject": origin_tss2_subject,
            "unit_memory_events": unit_memory_events,
        },
    )


def _read_private_json(path: Path):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 64 * 1024
        ):
            raise AssertionError("qualification configuration is not private")
        raw = os.read(descriptor, info.st_size + 1)
    finally:
        os.close(descriptor)
    if len(raw) != info.st_size:
        raise AssertionError("qualification configuration changed while reading")
    return json.loads(raw)


def command_tcti(root: Path, socket_path: Path) -> str:
    root = root.resolve(strict=True)
    socket_path = socket_path.absolute()
    if (
        not socket_path.is_absolute()
        or socket_path.parent != root
        or any(character.isspace() for character in str(socket_path))
        or not socket_path.name.endswith(".sock")
    ):
        raise ValueError("qualification TCTI must name a private generated socket")
    _private_directory(root)
    return f"cmd:nc -q 0 -U {socket_path}"


def admit_underlying_core_policy(raw: bytes) -> str:
    """Admit only the genuine non-piped kernel policy production accepts."""
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if (
        not raw
        or len(raw) > 128
        or b"\n" in raw
        or b"\r" in raw
        or b"\x00" in raw
        or any(byte < 0x20 or byte == 0x7F for byte in raw)
    ):
        raise QualificationRefused("malformed underlying core-pattern policy")
    try:
        policy = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise QualificationRefused(
            "malformed underlying core-pattern policy"
        ) from exc
    if policy != policy.strip():
        raise QualificationRefused("malformed underlying core-pattern policy")
    if policy.startswith("|"):
        raise QualificationRefused("piped core handler is not admitted")
    return policy


def require_underlying_core_policy() -> str:
    """Read the fixed procfs policy without following or substituting a path."""
    try:
        descriptor = os.open(
            _CORE_PATTERN, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        )
        try:
            raw = os.read(descriptor, 130)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise QualificationRefused(
            "underlying core-pattern policy is unavailable"
        ) from exc
    return admit_underlying_core_policy(raw)


def require_wait_bus_dispatch() -> None:
    """Prove systemctl --wait reaches the manager before mutable setup."""
    if "SYSTEMD_OFFLINE" in os.environ or "SYSTEMD_IGNORE_CHROOT" in os.environ:
        raise QualificationRefused("qualification systemd environment is overridden")
    assert_fresh_unit_boundary(
        unit_path=Path("/run/systemd/system") / _WAIT_BUS_PROBE_UNIT
    )
    try:
        inspected = subprocess.run(
            [
                "/usr/bin/systemctl",
                "show",
                "--property=LoadState",
                "--value",
                _WAIT_BUS_PROBE_UNIT,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationRefused(
            "systemctl wait-bus probe unit cannot be inspected"
        ) from exc
    inspected_stderr = inspected.stderr[:1024].decode("utf-8", errors="replace")
    inspected_stdout = inspected.stdout[:256].decode("utf-8", errors="replace")
    inspected_detail = json.dumps(
        {
            "returncode": inspected.returncode,
            "stderr": inspected_stderr,
            "stdout": inspected_stdout,
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    if (
        inspected.returncode != 0
        or inspected.stdout != b"not-found\n"
        or inspected.stderr
    ):
        raise QualificationRefused(
            f"systemctl wait-bus probe unit is not absent: {inspected_detail}"
        )
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "start", "--wait", _WAIT_BUS_PROBE_UNIT],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationRefused(
            "systemctl wait-bus manager response is unavailable"
        ) from exc
    expected = (
        f"Failed to start {_WAIT_BUS_PROBE_UNIT}: "
        f"Unit {_WAIT_BUS_PROBE_UNIT} not found.\n"
    ).encode("ascii")
    if result.returncode == 5 and result.stdout == b"" and result.stderr == expected:
        return
    stderr = result.stderr[:1024].decode("utf-8", errors="replace")
    stdout = result.stdout[:256].decode("utf-8", errors="replace")
    detail = json.dumps(
        {"returncode": result.returncode, "stderr": stderr, "stdout": stdout},
        ensure_ascii=True,
        sort_keys=True,
    )
    if b"Failed to connect to bus" in result.stderr:
        raise QualificationRefused(
            f"system bus is unavailable for systemctl --wait: {detail}"
        )
    raise QualificationRefused(
        f"systemctl wait-bus manager response was not observed: {detail}"
    )


def _unit_collisions(unit_path: Path, search_dirs) -> list[Path]:
    collisions = []
    template_name = unit_path.name
    instance_prefix = template_name.removesuffix("@.service") + "@"
    for directory in search_dirs:
        candidates = (directory / template_name, directory / f"{template_name}.d")
        for candidate in candidates:
            try:
                candidate.lstat()
            except FileNotFoundError:
                pass
            else:
                collisions.append(candidate)
        try:
            entries = tuple(directory.iterdir())
        except FileNotFoundError:
            continue
        for entry in entries:
            if entry.name.startswith(instance_prefix) and entry.name.endswith(
                ".service.d"
            ):
                collisions.append(entry)
    return collisions


def assert_fresh_unit_boundary(
    *, unit_path: Path = UNIT_PATH, search_dirs=SYSTEMD_UNIT_SEARCH_DIRS
) -> None:
    """Refuse to adopt a unit or drop-in from outside this process lifetime."""
    if _unit_collisions(unit_path, search_dirs):
        raise QualificationRefused("qualification unit or drop-in already exists")


def _assert_owned_unit_boundary(
    identity, *, unit_path: Path = UNIT_PATH,
    search_dirs=SYSTEMD_UNIT_SEARCH_DIRS,
) -> None:
    collisions = _unit_collisions(unit_path, search_dirs)
    if collisions != [unit_path]:
        raise QualificationRefused("qualification unit ownership changed")
    try:
        descriptor = os.open(
            unit_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        )
    except OSError as exc:
        raise QualificationRefused("qualification unit ownership changed") from exc
    try:
        _admit_owned_unit(descriptor, identity)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, content: str) -> None:
    payload = content.encode("utf-8")
    while payload:
        written = os.write(descriptor, payload)
        if written == 0:
            raise OSError("short qualification unit write")
        payload = payload[written:]


def _admit_owned_unit(descriptor: int, identity) -> tuple[int, int]:
    info = os.fstat(descriptor)
    current = (info.st_dev, info.st_ino)
    expected = None
    if identity is not None:
        expected = (identity.device, identity.inode)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o644
        or (expected is not None and current != expected)
    ):
        raise QualificationRefused("qualification unit ownership changed")
    return current


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_owned_unit(
    content: str, *, identity=None, unit_path: Path = UNIT_PATH
) -> UnitOwnership:
    """Create exclusively, then update only the unit created by this lifetime."""
    flags = os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    if identity is None:
        flags |= os.O_CREAT | os.O_EXCL
    if identity is None:
        try:
            descriptor = os.open(unit_path, flags, 0o644)
        except FileExistsError as exc:
            raise QualificationRefused("qualification unit already exists") from exc
        keep_descriptor = False
    else:
        descriptor = identity.descriptor
        keep_descriptor = True
    try:
        if identity is None:
            os.fchmod(descriptor, 0o644)
        admitted = _admit_owned_unit(descriptor, identity)
        path_info = unit_path.lstat()
        if (path_info.st_dev, path_info.st_ino) != admitted:
            raise QualificationRefused("qualification unit ownership changed")
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        _write_all(descriptor, content)
        os.fsync(descriptor)
        _fsync_directory(unit_path.parent)
        if identity is None:
            identity = UnitOwnership(descriptor, *admitted)
            keep_descriptor = True
        return identity
    finally:
        if not keep_descriptor:
            os.close(descriptor)


def remove_owned_unit(identity, *, unit_path: Path = UNIT_PATH) -> None:
    """Remove only the unit inode recorded by this process lifetime."""
    descriptor = identity.descriptor
    admitted = _admit_owned_unit(descriptor, identity)
    try:
        path_info = unit_path.lstat()
    except OSError as exc:
        raise QualificationRefused("qualification unit ownership changed") from exc
    if (path_info.st_dev, path_info.st_ino) != admitted:
        raise QualificationRefused("qualification unit ownership changed")
    unit_path.unlink()
    _fsync_directory(unit_path.parent)
    os.close(descriptor)


def render_qualification_unit(
    *, executable: Path, profile: Path, request_root: Path,
    state_root: Path, invalid_slice: bool = False,
) -> str:
    template = UNIT_TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "{{ bare_metal_lease_storage_supervisor_path }}": str(executable),
        "{{ bare_metal_lease_storage_supervision_profile_path }}": str(profile),
        "{{ bare_metal_lease_storage_request_root }}": str(request_root),
        "{{ bare_metal_lease_storage_state_root }}": str(state_root),
        "{{ bare_metal_lease_tpm_device }}": "/dev/null",
        "{{ bare_metal_lease_cryptsetup_path }}": str(CRYPTSETUP),
    }
    for source, target in replacements.items():
        if template.count(source) < 1:
            raise AssertionError(f"unit template lost qualification seam: {source}")
        template = template.replace(source, target)
    if "{{" in template:
        raise AssertionError("qualification unit has unresolved template values")
    if invalid_slice:
        if template.count("Slice=system.slice") != 1:
            raise AssertionError("production unit slice is not singular")
        template = template.replace("Slice=system.slice", "Slice=user.slice")
    return template


def _qualification_path(profile_path: Path) -> Path:
    return profile_path.with_name("qualification.json")


def _validate_unit_config(value, profile_path: Path):
    fields = {"schema", "mode", "state", "backend_marker", "checkpoint"}
    if not isinstance(value, dict) or set(value) != fields:
        raise AssertionError("qualification configuration fields changed")
    if value["schema"] != _QUALIFICATION_SCHEMA:
        raise AssertionError("qualification configuration schema changed")
    if value["mode"] not in {"prepare", "interrupt", "no-custody"}:
        raise AssertionError("qualification mode is unsupported")
    if value["checkpoint"] not in {None, "after-unseal"}:
        raise AssertionError("qualification checkpoint is unsupported")
    root = profile_path.parent.resolve(strict=True)
    state = Path(value["state"])
    marker = Path(value["backend_marker"])
    if state.parent != root or marker.parent != root:
        raise AssertionError("qualification paths escaped their private root")
    _private_directory(root)
    return value


def _start_swtpm_unix(root: Path, state: Path):
    software = _software_tpm()
    command_socket = root / "command.sock"
    control_socket = root / "control.sock"
    if command_socket.exists() or control_socket.exists():
        raise AssertionError("software-TPM socket path is already present")
    state.mkdir(mode=0o700, exist_ok=True)
    tcti = command_tcti(root, command_socket)
    previous = os.environ.get("TPM2TOOLS_TCTI")
    process = subprocess.Popen(
        [
            "swtpm", "socket", "--tpm2", f"--tpmstate=dir={state}",
            f"--server=type=unixio,path={command_socket},mode=0600",
            f"--ctrl=type=unixio,path={control_socket},mode=0600",
            "--flags=not-need-init,startup-clear",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    os.environ["TPM2TOOLS_TCTI"] = tcti
    deadline = time.monotonic() + 5
    try:
        while True:
            started = software._run(
                ["tpm2_startup", "-c"], check=False, timeout=1
            )
            if started.returncode == 0:
                return process, previous, tcti
            if process.poll() is not None or time.monotonic() >= deadline:
                raise AssertionError("disposable Unix-socket swtpm did not start")
            time.sleep(0.05)
    except BaseException:
        try:
            software._stop_process(process)
        finally:
            software._restore_tcti(previous)
        raise


def _open_backend(custody, tcti: str):
    # Routine tests do not install the binding; only the opt-in image reaches
    # this transport boundary.
    import tpm2_pytss

    prefix = "cmd:nc -q 0 -U "
    if not tcti.startswith(prefix):
        raise AssertionError("qualification selected a non-command TCTI")
    socket_path = Path(tcti.removeprefix(prefix))
    command_tcti(socket_path.parent, socket_path)
    loaded = tpm2_pytss.TCTILdr("cmd", tcti.removeprefix("cmd:"))
    return custody.PytssBackend.for_test_transport(loaded, pytss=tpm2_pytss)


def _ephemeral_sentinels(root: Path):
    software = _software_tpm()
    suffix = time.monotonic_ns()
    object_context = root / f"unit-foreign-object-{suffix}.ctx"
    session_context = root / f"unit-foreign-session-{suffix}.ctx"
    software._run(
        ["tpm2_createprimary", "-C", "o", "-g", "sha256", "-G", "rsa",
         "-c", str(object_context)]
    )
    object_handle = software._raw_primary_handle(object_context)
    software._run(["tpm2_startauthsession", "-S", str(session_context)])
    session_handle = software._session_handle(session_context)
    return object_handle, session_context, session_handle


def _verify_and_close_ephemeral(sentinels) -> None:
    software = _software_tpm()
    object_handle, session_context, session_handle = sentinels
    software._run(["tpm2_readpublic", "-c", object_handle])
    software._run(["tpm2_getpolicydigest", "-S", str(session_context)])
    software._run(["tpm2_flushcontext", session_handle])
    software._run(["tpm2_flushcontext", object_handle])


def unit_execute(request_id: str, profile_path: Path) -> int:
    if not _REQUEST_ID.fullmatch(request_id):
        return 1
    supervisor = _supervisor()
    stage = "request-admission"
    origin_stage = "not-captured"
    origin_error_code = "not-captured"
    origin_cause_code = "not-captured"
    origin_operation = "not-observed"
    origin_operation_result = "not-observed"
    origin_operation_returncode = None
    origin_tss2_rc = None
    origin_tss2_layer = "not-observed"
    origin_tss2_subject = "not-observed"
    try:
        profile = supervisor.load_profile(profile_path)
        config = _validate_unit_config(
            _read_private_json(_qualification_path(profile_path)), profile_path
        )
        if config["mode"] == "no-custody":
            def forbidden_backend(_device):
                Path(config["backend_marker"]).write_text("opened\n")
                raise AssertionError("runtime refusal reached custody")

            supervisor.execute_request(
                profile, request_id, backend_factory=forbidden_backend
            )
            return 0

        interrupted = config["mode"] == "interrupt"
        software = _software_tpm()
        custody = _custody()
        process = None
        previous = None
        sentinels = None

        def backend_factory(device):
            nonlocal process, previous, sentinels, stage
            if device != "/dev/tpm0":
                raise AssertionError("qualification profile lost direct-device binding")
            stage = "software-tpm-start"
            process, previous, tcti = _start_swtpm_unix(
                profile_path.parent, Path(config["state"])
            )
            stage = "foreign-sentinel-create"
            sentinels = _ephemeral_sentinels(profile_path.parent)
            stage = "esapi-backend-open"
            return _open_backend(custody, tcti)

        checkpoint = config["checkpoint"]

        class ObservedExecutor(custody.EsapiCustodyExecutor):
            def __init__(self, backend):
                def observe(event):
                    nonlocal stage
                    if event not in _CUSTODY_STAGES:
                        raise AssertionError("custody emitted an unsupported checkpoint")
                    stage = f"custody-{event}"
                    if interrupted and event == checkpoint:
                        os._exit(97)

                super().__init__(backend, _checkpoint=observe)

            def close(self):
                nonlocal stage
                stage = "custody-finalize"
                super().close()
                stage = "custody-finalized"

        class ObservedHelper:
            def __init__(self):
                self._actual = None
                self._runner = None

            def _module(self):
                if self._actual is None:
                    self._actual = _load(PREPARE, "supervised_qualification_prepare")
                return self._actual

            def __getattr__(self, name):
                if name == "SubprocessRunner":
                    return self._runner_class()
                return getattr(self._module(), name)

            def _runner_class(self):
                nonlocal origin_operation, origin_operation_result
                nonlocal origin_operation_returncode
                if self._runner is not None:
                    return self._runner
                actual = self._module()

                class ObservedRunner(actual.SubprocessRunner):
                    def run(self, argv, *, stdin=None):
                        nonlocal origin_operation, origin_operation_result
                        nonlocal origin_operation_returncode
                        operation = _cryptsetup_operation(argv)
                        try:
                            return super().run(argv, stdin=stdin)
                        except actual.PreparationRefused as exc:
                            origin_operation = operation
                            (
                                origin_operation_result,
                                origin_operation_returncode,
                            ) = _cryptsetup_operation_result(exc)
                            raise

                    def check(self, argv):
                        nonlocal origin_operation, origin_operation_result
                        nonlocal origin_operation_returncode
                        operation = _cryptsetup_operation(argv)
                        try:
                            return super().check(argv)
                        except actual.PreparationRefused as exc:
                            origin_operation = operation
                            (
                                origin_operation_result,
                                origin_operation_returncode,
                            ) = _cryptsetup_operation_result(exc)
                            raise

                self._runner = ObservedRunner
                return self._runner

            def prepare(self, *args, **kwargs):
                nonlocal origin_stage, origin_error_code, origin_cause_code
                nonlocal origin_tss2_rc, origin_tss2_layer, origin_tss2_subject
                actual = self._module()
                try:
                    return actual.prepare(*args, **kwargs)
                except actual.PreparationRefused as exc:
                    origin_stage = "helper-prepare"
                    origin_error_code, origin_cause_code = _preparation_refusal_chain(
                        exc, actual.PreparationRefused
                    )
                    (
                        origin_tss2_rc,
                        origin_tss2_layer,
                        origin_tss2_subject,
                    ) = _tss2_failure_identity(exc)
                    raise

        custody_api = SimpleNamespace(EsapiCustodyExecutor=ObservedExecutor)
        helper_api = ObservedHelper()
        try:
            stage = "runtime-and-helper-dispatch"
            supervisor.execute_request(
                profile,
                request_id,
                backend_factory=backend_factory,
                custody_module=custody_api,
                helper_module=helper_api,
            )
            if sentinels is None:
                raise AssertionError("accepted execution did not open test custody")
            stage = "foreign-sentinel-verify"
            _verify_and_close_ephemeral(sentinels)
        finally:
            if process is not None:
                try:
                    software._stop_process(process)
                finally:
                    software._restore_tcti(previous)
        return 0
    except (
        AssertionError,
        OSError,
        ValueError,
        supervisor.SupervisionRefused,
    ) as exc:
        try:
            _publish_unit_failure(
                profile_path,
                request_id,
                stage,
                exc,
                origin_stage=origin_stage,
                origin_error_code=origin_error_code,
                origin_cause_code=origin_cause_code,
                origin_operation=origin_operation,
                origin_operation_result=origin_operation_result,
                origin_operation_returncode=origin_operation_returncode,
                origin_tss2_rc=origin_tss2_rc,
                origin_tss2_layer=origin_tss2_layer,
                origin_tss2_subject=origin_tss2_subject,
                unit_memory_events=_unit_memory_events(request_id),
            )
        except (AssertionError, OSError, ValueError):
            return 2
        return 1


def _profile_value(root: Path):
    return {
        "schema": "arkhai.lease-storage-supervision.v1",
        "request_root": str(root / "requests"),
        "state_root": str(root),
        "tpm_device": "/dev/tpm0",
        "cryptsetup_path": str(CRYPTSETUP),
        "cryptsetup_version": CRYPTSETUP_VERSION,
    }


def _request(parent_name: str, *, floor: int = 1024 * 1024):
    return {
        "schema": "arkhai.lease-storage-request.v1",
        "host_id": "supervised-software-tpm-host",
        "machine_id": "supervised-software-tpm-machine",
        "generation": "supervised-software-tpm-generation-1",
        "backing_size": 32 * 1024 * 1024,
        "free_space_floor": floor,
        "nv_index": "0x1500020",
        "counter_headroom": 16,
        "parent_handle": "0x81000020",
        "parent_name": parent_name,
    }


def _systemctl(argv, *, check=False, timeout=330):
    return subprocess.run(
        ["systemctl", *argv],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
        timeout=timeout,
    )


def _journal_diagnostics(instance: str) -> str:
    try:
        result = subprocess.run(
            [
                "journalctl", "--unit", instance, "--lines=80", "--no-pager",
                "--output=short-monotonic",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"journal unavailable: {type(exc).__name__}"
    return "\n".join(
        part.decode(errors="replace")[:8192]
        for part in (result.stdout, result.stderr)
        if part
    )


def _diagnostic_outcome(path: Path | None, request_id: str) -> str:
    if path is None:
        return "durable_state=unavailable"
    try:
        value = _read_private_json(path)
    except (AssertionError, OSError, ValueError, json.JSONDecodeError) as exc:
        return f"durable_state=unreadable:{type(exc).__name__}"
    if (
        not isinstance(value, dict)
        or value.get("schema") != "arkhai.lease-storage-execution.v1"
        or value.get("request_id") != request_id
    ):
        return "durable_state=identity-invalid"
    state = value.get("state")
    if state not in {"accepted", "running", "refused", "quarantined", "completed"}:
        return "durable_state=value-invalid"
    reason = value.get("reason_code")
    if reason is not None and not isinstance(reason, str):
        reason = "value-invalid"
    return f"durable_state={state} reason_code={reason or 'absent'}"


def _diagnostic_unit_failure(path: Path | None, request_id: str) -> str:
    if path is None:
        return "unit_failure=unavailable"
    failure_path = path.with_name("unit-failure.json")
    try:
        value = _read_private_json(failure_path)
    except FileNotFoundError:
        return "unit_failure=absent"
    except (AssertionError, OSError, ValueError, json.JSONDecodeError) as exc:
        return f"unit_failure=unreadable:{type(exc).__name__}"
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema",
            "request_id",
            "stage",
            "error_code",
            "origin_stage",
            "origin_error_code",
            "origin_cause_code",
            "origin_operation",
            "origin_operation_result",
            "origin_operation_returncode",
            "origin_tss2_rc",
            "origin_tss2_layer",
            "origin_tss2_subject",
            "unit_memory_events",
        }
        or value.get("schema") != _UNIT_FAILURE_SCHEMA
        or value.get("request_id") != request_id
        or value.get("stage") not in _SAFE_UNIT_STAGES
        or value.get("error_code") not in _SAFE_ERROR_CODE_VALUES
        or value.get("origin_stage") not in _PREPARATION_ORIGIN_STAGES
        or value.get("origin_error_code") not in _PREPARATION_ORIGIN_CODES
        or value.get("origin_cause_code") not in _PREPARATION_ORIGIN_CODES
        or value.get("origin_operation") not in _HELPER_OPERATIONS
        or not _valid_operation_result(
            value.get("origin_operation_result"),
            value.get("origin_operation_returncode"),
        )
        or not _valid_tss2_failure(
            value.get("origin_tss2_rc"),
            value.get("origin_tss2_layer"),
            value.get("origin_tss2_subject"),
        )
        or (
            value.get("unit_memory_events") is not None
            and (
                not isinstance(value.get("unit_memory_events"), dict)
                or set(value["unit_memory_events"])
                != {"high", "low", "max", "oom", "oom_kill"}
                or any(
                    isinstance(counter, bool)
                    or not isinstance(counter, int)
                    or counter < 0
                    for counter in value["unit_memory_events"].values()
                )
            )
        )
        or (
            (value.get("origin_operation") == "not-observed")
            != (value.get("origin_operation_result") == "not-observed")
        )
        or (
            value.get("origin_stage") == "not-captured"
            and (
                value.get("origin_error_code") != "not-captured"
                or value.get("origin_cause_code") != "not-captured"
            )
        )
        or (
            value.get("origin_stage") == "helper-prepare"
            and (
                value.get("origin_error_code") == "not-captured"
                or value.get("origin_cause_code") == "not-captured"
            )
        )
    ):
        return "unit_failure=identity-invalid"
    return (
        f"unit_failure_last_stage={value['stage']}\n"
        f"unit_failure_error_code={value['error_code']}\n"
        f"unit_failure_origin_stage={value['origin_stage']}\n"
        f"unit_failure_origin_error_code={value['origin_error_code']}\n"
        f"unit_failure_origin_cause_code={value['origin_cause_code']}\n"
        f"unit_failure_origin_operation={value['origin_operation']}\n"
        "unit_failure_origin_operation_result="
        f"{value['origin_operation_result']}\n"
        "unit_failure_origin_operation_returncode="
        f"{value['origin_operation_returncode'] if value['origin_operation_returncode'] is not None else 'absent'}\n"
        "unit_failure_origin_tss2_rc="
        f"{value['origin_tss2_rc'] if value['origin_tss2_rc'] is not None else 'absent'}\n"
        f"unit_failure_origin_tss2_layer={value['origin_tss2_layer']}\n"
        f"unit_failure_origin_tss2_subject={value['origin_tss2_subject']}\n"
        "unit_failure_unit_memory_events="
        f"{json.dumps(value['unit_memory_events'], sort_keys=True, separators=(',', ':')) if value['unit_memory_events'] is not None else 'unavailable'}"
    )


def _diagnostics(instance: str, outcome_path: Path | None = None) -> str:
    matched = _UNIT_INSTANCE.fullmatch(instance)
    if matched is None:
        return "qualification diagnostic unit identity is invalid"
    request_id = matched.group("request_id")
    outputs = [
        _diagnostic_outcome(outcome_path, request_id),
        _diagnostic_unit_failure(outcome_path, request_id),
    ]
    show_arguments = [
        "show", "--no-pager",
        "--property=Result", "--property=ExecMainCode",
        "--property=ExecMainStatus", "--property=SubState",
        "--property=ControlGroup", "--property=ConditionResult",
        "--property=AssertResult", "--property=InvocationID",
        "--property=ExecStart", "--property=ExecStartEx",
        "--property=ExecMainStartTimestampMonotonic",
        "--property=ExecMainExitTimestampMonotonic",
        "--property=ActiveEnterTimestampMonotonic",
        "--property=InactiveEnterTimestampMonotonic",
        "--property=FragmentPath", "--property=DropInPaths",
        "--property=LoadState", "--property=LoadError",
        "--property=NeedDaemonReload", instance,
    ]
    for argv in (
        show_arguments,
        ["cat", "--no-pager", instance],
        ["status", "--no-pager", "--lines=0", instance],
    ):
        try:
            result = _systemctl(argv, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            outputs.append(type(exc).__name__)
        else:
            decoded = result.stdout.decode(errors="replace")[:8192]
            outputs.append(decoded)
            outputs.append(result.stderr.decode(errors="replace")[:8192])
            if argv is show_arguments:
                properties = dict(
                    line.split("=", 1) for line in decoded.splitlines() if "=" in line
                )
                if properties.get("InvocationID") == "":
                    outputs.append("main_process_observed=no")
                elif properties.get("InvocationID"):
                    outputs.append("main_process_observed=yes")
                else:
                    outputs.append("main_process_observed=unknown")
                outputs.append(
                    f"condition_result={properties.get('ConditionResult', 'unknown')}"
                )
                outputs.append(
                    f"assert_result={properties.get('AssertResult', 'unknown')}"
                )
    outputs.append(_journal_diagnostics(instance))
    return "\n".join(outputs)


def _raise_qualification_failure(exc: BaseException, detail: str) -> None:
    if detail:
        print(
            f"QUALIFICATION_FAILURE_DIAGNOSTICS\n{detail}",
            file=sys.stderr,
            flush=True,
        )
    raise AssertionError(
        f"supervised custody qualification failed: {exc}\n{detail}"
    ) from exc


def _install_case(
    root: Path, *, mode: str, unit_ownership: dict, invalid_slice=False
) -> tuple[object, str]:
    supervisor = _supervisor()
    identity = unit_ownership["identity"]
    if identity is None:
        assert_fresh_unit_boundary()
    else:
        _assert_owned_unit_boundary(identity)
    root.mkdir(mode=0o700)
    (root / "requests").mkdir(mode=0o700)
    profile_path = root / "profile.json"
    _write_private_json(profile_path, _profile_value(root))
    marker = root / "backend-opened"
    _write_private_json(
        _qualification_path(profile_path),
        {
            "schema": _QUALIFICATION_SCHEMA,
            "mode": mode,
            "state": str(root / "tpm-state"),
            "backend_marker": str(marker),
            "checkpoint": "after-unseal" if mode == "interrupt" else None,
        },
    )
    if identity is None:
        assert_fresh_unit_boundary()
    else:
        _assert_owned_unit_boundary(identity)
    identity = publish_owned_unit(
        render_qualification_unit(
            executable=Path(__file__).resolve(),
            profile=profile_path,
            request_root=root / "requests",
            state_root=root,
            invalid_slice=invalid_slice,
        ),
        identity=identity,
    )
    unit_ownership["identity"] = identity
    _assert_owned_unit_boundary(identity)
    _systemctl(["daemon-reload"], check=True)
    return supervisor, str(marker)


def _set_mode(root: Path, mode: str) -> None:
    path = root / "qualification.json"
    value = _read_private_json(path)
    value["mode"] = mode
    value["checkpoint"] = "after-unseal" if mode == "interrupt" else None
    _write_private_json(path, value)


def _provision(root: Path):
    software = _software_tpm()
    process, previous, _ = _start_swtpm_unix(root, root / "tpm-state")
    try:
        software._run(
            ["tpm2_nvdefine", "-C", "o", "-s", "8", "-a",
             "ownerread|ownerwrite|authread|authwrite|nt=counter", "0x1500020"]
        )
        software._run(["tpm2_nvincrement", "0x1500020"])
        parent_name, _ = software._provision_persistent_parent(root, "0x81000020")
        sentinels = software._provision_foreign_sentinels(root)
        software._run(["tpm2_flushcontext", sentinels["session_handle"]])
        software._run(["tpm2_flushcontext", sentinels["object_handle"]])
        durable = {
            "persistent_handle": sentinels["persistent_handle"],
            "persistent_name": sentinels["persistent_name"],
            "nv_index": sentinels["nv_index"],
            "nv_value": sentinels["nv_value"],
        }
        return parent_name.read_bytes().hex(), durable
    finally:
        try:
            software._stop_process(process)
        finally:
            software._restore_tcti(previous)


def _inspect_tpm(root: Path, durable) -> int:
    software = _software_tpm()
    process, previous, _ = _start_swtpm_unix(root, root / "tpm-state")
    try:
        software._verify_durable_foreign_sentinels(root, durable)
        return software._read_counter_for_probe(root, "0x1500020")
    finally:
        try:
            software._stop_process(process)
        finally:
            software._restore_tcti(previous)


def _validated_retry_then_inspect(submit_retry, validate_retry, inspect_tpm):
    """Keep independent CLI authorization attempts after the real retry."""
    receipt = submit_retry()
    validate_retry(receipt)
    return receipt, inspect_tpm()


def _start_instance(request_id: str):
    instance = UNIT.format(request_id)
    result = _systemctl(["start", "--wait", instance])
    return instance, result


def _assert_unit_cgroup_empty(instance: str) -> None:
    expected = f"/system.slice/{instance}"
    shown = _systemctl(
        ["show", "--property=ControlGroup", "--value", instance]
    )
    if shown.returncode != 0 or shown.stdout.decode().strip() not in {"", expected}:
        raise AssertionError("failed unit reported an unexpected control group")
    processes = Path("/sys/fs/cgroup") / expected.removeprefix("/") / "cgroup.procs"
    deadline = time.monotonic() + 10
    while processes.exists() and processes.read_text(encoding="ascii").strip():
        if time.monotonic() >= deadline:
            raise AssertionError("failed unit retained a live descendant")
        time.sleep(0.05)


def _outcome(root: Path, request_id: str):
    return json.loads(
        (root / "requests" / f"{request_id}.execution.json").read_text()
    )


def qualify() -> dict[str, object]:
    require_underlying_core_policy()
    if os.geteuid() != 0 or Path("/proc/1/comm").read_text().strip() != "systemd":
        raise AssertionError("qualification requires a disposable systemd PID 1")
    if subprocess.run(
        ["systemd-detect-virt", "--container"], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, check=False, timeout=10,
    ).returncode != 0:
        raise AssertionError("qualification refuses a non-container manager")
    version = subprocess.run(
        ["systemd-analyze", "--version"], capture_output=True, text=True,
        check=True, timeout=10,
    ).stdout
    if re.search(r"^systemd 249\b", version) is None:
        raise AssertionError("qualification requires systemd 249")
    require_wait_bus_dispatch()
    assert_fresh_unit_boundary()
    if resource.getrlimit(resource.RLIMIT_CORE) != (0, 0):
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    qualification = Path("/run") / f"arkhai-supervised-custody-{uuid.uuid4().hex}"
    completed = False
    active_instance = None
    active_outcome = None
    unit_ownership = {"identity": None}
    try:
        qualification.mkdir(mode=0o700)
        positive = qualification / "positive"
        supervisor, _ = _install_case(
            positive, mode="prepare", unit_ownership=unit_ownership
        )
        parent_name, durable = _provision(positive)
        request = _request(parent_name)
        profile = supervisor.load_profile(positive / "profile.json")
        request_id = supervisor.request_identity(request)
        active_instance = UNIT.format(request_id)
        active_outcome = positive / "requests" / f"{request_id}.execution.json"
        receipt = supervisor.submit_request(profile, request)
        first = _outcome(positive, request_id)
        if first["receipt"] != receipt:
            raise AssertionError("submitted request and durable receipt differ")
        lease = positive / "leases" / request["generation"]
        preserved = {
            name: (lease / name).read_bytes()
            for name in ("sealed.pub", "sealed.priv", "policy.nv")
        }
        retry = _request(parent_name, floor=request["free_space_floor"] + 1)
        retry_id = supervisor.request_identity(retry)
        active_instance = UNIT.format(retry_id)
        active_outcome = positive / "requests" / f"{retry_id}.execution.json"

        def validate_retry(retry_receipt):
            if (
                retry_receipt != receipt
                or _outcome(positive, retry_id)["receipt"] != receipt
            ):
                raise AssertionError("prepared retry changed its receipt")
            if any(
                (lease / name).read_bytes() != value
                for name, value in preserved.items()
            ):
                raise AssertionError("prepared retry changed durable sealed evidence")

        _retry_receipt, inspected_counter = _validated_retry_then_inspect(
            lambda: supervisor.submit_request(profile, retry),
            validate_retry,
            lambda: _inspect_tpm(positive, durable),
        )
        if inspected_counter != receipt["counter"]:
            raise AssertionError("prepared retry advanced the lease counter")

        active_instance = None
        active_outcome = None
        refused = qualification / "refused"
        supervisor, marker = _install_case(
            refused, mode="no-custody", unit_ownership=unit_ownership,
            invalid_slice=True,
        )
        refused_request = _request("000b11223344")
        refused_profile = supervisor.load_profile(refused / "profile.json")
        refused_id = supervisor.request_identity(refused_request)
        active_instance = UNIT.format(refused_id)
        active_outcome = refused / "requests" / f"{refused_id}.execution.json"
        try:
            supervisor.submit_request(refused_profile, refused_request)
        except supervisor.SupervisionUnresolved:
            pass
        else:
            raise AssertionError("invalid live cgroup was admitted")
        refused_outcome = _outcome(refused, refused_id)
        if refused_outcome.get("state") != "refused" or Path(marker).exists():
            raise AssertionError("live-control refusal reached custody")
        if (refused / "leases").exists():
            raise AssertionError("live-control refusal created lease state")

        active_instance = None
        active_outcome = None
        interrupted = qualification / "interrupted"
        supervisor, marker = _install_case(
            interrupted, mode="interrupt", unit_ownership=unit_ownership
        )
        interrupted_parent, interrupted_durable = _provision(interrupted)
        interrupted_request = _request(interrupted_parent)
        interrupted_profile = supervisor.load_profile(interrupted / "profile.json")
        interrupted_id = supervisor.request_identity(interrupted_request)
        active_instance = UNIT.format(interrupted_id)
        active_outcome = interrupted / "requests" / f"{interrupted_id}.execution.json"
        try:
            supervisor.submit_request(interrupted_profile, interrupted_request)
        except supervisor.SupervisionUnresolved:
            pass
        else:
            raise AssertionError("abrupt checkpoint unexpectedly completed")
        _assert_unit_cgroup_empty(active_instance)
        if _outcome(interrupted, interrupted_id).get("state") != "running":
            raise AssertionError("abrupt execution lost its durable running evidence")
        counter_after_exit = _inspect_tpm(interrupted, interrupted_durable)
        _set_mode(interrupted, "no-custody")
        active_instance, retry_result = _start_instance(interrupted_id)
        if retry_result.returncode == 0:
            raise AssertionError("ambiguous execution retry unexpectedly completed")
        interrupted_outcome = _outcome(interrupted, interrupted_id)
        if (
            interrupted_outcome.get("state") != "quarantined"
            or interrupted_outcome.get("reason_code") != "prior-execution-incomplete"
            or Path(marker).exists()
        ):
            raise AssertionError("ambiguous execution retry was not safely quarantined")
        if _inspect_tpm(interrupted, interrupted_durable) != counter_after_exit:
            raise AssertionError("ambiguous retry advanced the counter")
        completed = True
        return {
            "abrupt_execution_quarantined": True,
            "foreign_durable_tpm_state_preserved": True,
            "luks_target": "disposable regular file",
            "prepared_retry_revalidated": True,
            "production_device_transport_used": False,
            "runtime_controls_refused_before_custody": True,
            "state": "qualified",
        }
    except BaseException as exc:
        detail = (
            _diagnostics(active_instance, active_outcome) if active_instance else ""
        )
        _raise_qualification_failure(exc, detail)
    finally:
        if active_instance:
            _systemctl(["stop", active_instance])
            _systemctl(["reset-failed", active_instance])
        if unit_ownership["identity"] is not None:
            remove_owned_unit(unit_ownership["identity"])
        reload_result = _systemctl(["daemon-reload"])
        if completed and reload_result.returncode == 0:
            shutil.rmtree(qualification)
        elif qualification.exists():
            raise AssertionError(
                "qualification cleanup is uncertain; discard the disposable container"
            )


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) == 4 and arguments[0] == "execute" and arguments[2] == "--profile":
        return unit_execute(arguments[1], Path(arguments[3]))
    if arguments == ["qualify"]:
        if not RUN:
            return 1
        print(json.dumps(qualify(), sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
