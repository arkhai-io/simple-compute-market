#!/usr/bin/python3
"""Prepare one generation-owned LUKS2 volume and TPM-sealed unlock secret.

The executable deliberately has no secret input option. It generates the
keyslot secret in memory, gives it only to the in-process TPM binding and
cryptsetup's standard input, and never places it in argv. Its JSON output and
durable manifest contain identities and TPM public data, never the secret.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Sequence


MAX_COUNTER = (1 << 64) - 1
SCHEMA = "arkhai.lease-storage-preparation.v1"
FAILPOINTS = (
    "lease_state",
    "host_lock",
    "helper_intent",
    "counter_intent",
    "counter_increment",
    "counter_confirmed",
    "policy_digest",
    "policy_session_closed",
    "policy_committed",
    "sealed_object_intent",
    "sealed_object",
    "sealed_object_recorded",
    "object_closed",
    "sealed_object_verified",
    "backing_file_intent",
    "backing_file",
    "luks_format_intent",
    "luks_format",
    "luks_verified",
    "prepared_receipt",
    "helper_completed",
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_HANDLE = re.compile(r"0x[0-9a-fA-F]{8}\Z")
_NV_INDEX = re.compile(r"0x[0-9a-fA-F]{7,8}\Z")
_HEX_NAME = re.compile(r"(?:[0-9a-fA-F]{2}){3,}\Z")


class PreparationRefused(RuntimeError):
    """Preparation stopped before an ambiguous or foreign mutation."""


class PreparationQuarantined(PreparationRefused):
    """The host needs release-owned reconciliation before further prepare."""


class PreparationUnresolved(PreparationRefused):
    """Preparation failed and its quarantine state could not be made durable."""


class InjectedInterruption(RuntimeError):
    """Test-only process interruption after a durable side-effect boundary."""


class PrepareConfig:
    def __init__(
        self,
        *,
        state_root: Path,
        host_id: str,
        machine_id: str,
        generation: str,
        backing_size: int,
        free_space_floor: int,
        nv_index: str,
        counter_headroom: int,
        parent_handle: str,
        parent_name: str,
        required_uid: int = 0,
    ) -> None:
        self.state_root = Path(state_root)
        self.host_id = host_id
        self.machine_id = machine_id
        self.generation = generation
        self.backing_size = backing_size
        self.free_space_floor = free_space_floor
        self.nv_index = nv_index.lower()
        self.counter_headroom = counter_headroom
        self.parent_handle = parent_handle.lower()
        self.parent_name = parent_name.lower()
        self.required_uid = required_uid
        self.validate()

    def validate(self) -> None:
        if not self.state_root.is_absolute() or self.state_root == Path("/"):
            raise PreparationRefused("state root must be a bounded absolute path")
        for label, value in (
            ("host_id", self.host_id),
            ("machine_id", self.machine_id),
            ("generation", self.generation),
        ):
            if not _IDENTIFIER.fullmatch(value):
                raise PreparationRefused(f"invalid {label}")
        if not _NV_INDEX.fullmatch(self.nv_index):
            raise PreparationRefused("invalid NV index")
        if not 0x01000000 <= int(self.nv_index, 16) <= 0x01FFFFFF:
            raise PreparationRefused("NV index is outside the TPM NV handle range")
        if not _HANDLE.fullmatch(self.parent_handle) or not self.parent_handle.startswith("0x81"):
            raise PreparationRefused("parent must use a recorded persistent handle")
        if not _HEX_NAME.fullmatch(self.parent_name):
            raise PreparationRefused("invalid recorded parent Name")
        if self.backing_size < 16 * 1024 * 1024:
            raise PreparationRefused("backing size is too small for LUKS2")
        if self.free_space_floor < 0 or self.counter_headroom < 1:
            raise PreparationRefused("invalid storage safety limit")


class SubprocessRunner:
    """Run only the non-TPM cryptsetup boundary without exposing child stderr."""

    _REQUIRED = {
        command: None
        for command in ("cryptsetup",)
    }

    def __init__(self) -> None:
        self._tools: dict[str, str] = {}
        for command in self._REQUIRED:
            resolved = shutil.which(command)
            if resolved is None:
                raise PreparationRefused(f"required tool unavailable: {command}")
            self._tools[command] = resolved

    def _argv(self, argv: Sequence[str]) -> list[str]:
        command = Path(argv[0]).name
        if command not in self._tools:
            raise PreparationRefused(f"unapproved external command: {command}")
        return [self._tools[command], *argv[1:]]

    def run(self, argv: Sequence[str], *, stdin: bytes | None = None) -> bytes:
        try:
            completed = subprocess.run(
                self._argv(argv),
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                close_fds=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PreparationRefused(f"required tool unavailable: {Path(argv[0]).name}") from exc
        if completed.returncode != 0:
            raise PreparationRefused(
                f"{Path(argv[0]).name} failed with exit status {completed.returncode}"
            )
        return completed.stdout

    def check(self, argv: Sequence[str]) -> bool:
        try:
            completed = subprocess.run(
                self._argv(argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                close_fds=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PreparationRefused(f"required tool unavailable: {Path(argv[0]).name}") from exc
        return completed.returncode == 0


def ownership_record(config: PrepareConfig) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "host_id": config.host_id,
        "machine_id": config.machine_id,
        "generation": config.generation,
        "nv_index": config.nv_index,
        "parent_handle": config.parent_handle,
        "parent_name": config.parent_name,
    }


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _create_private_dir(path: Path, *, uid: int) -> None:
    try:
        path.mkdir(mode=0o700)
        _fsync_dir(path.parent)
    except FileExistsError:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
            raise PreparationRefused(f"unsafe existing directory: {path}")


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise PreparationRefused(f"state path contains a symlink: {current}")


def _read_private_json(path: Path, *, uid: int) -> dict[str, object]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise PreparationRefused(f"refusing symlink: {path}")
    if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
        raise PreparationRefused(f"unsafe owned metadata file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreparationRefused(f"invalid owned metadata file: {path}") from exc
    if not isinstance(value, dict):
        raise PreparationRefused(f"invalid owned metadata object: {path}")
    return value


def _write_new_json(path: Path, value: dict[str, object]) -> None:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(fd, remaining)
            remaining = remaining[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)


def _write_new_private(path: Path, value: bytes) -> None:
    """Create one new root-private artifact without adopting an existing path."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise PreparationRefused(f"refusing existing output path: {path.name}") from exc
    try:
        view = memoryview(value)
        while view:
            written = os.write(fd, view)
            if written < 1:
                raise OSError("short write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)


def _replace_owned_json(path: Path, value: dict[str, object], *, uid: int) -> None:
    if path.exists() or path.is_symlink():
        _read_private_json(path, uid=uid)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    _write_new_json(temporary, value)
    os.replace(temporary, path)
    _fsync_dir(path.parent)


def _owned_regular(path: Path, *, uid: int) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise PreparationRefused(f"refusing symlink: {path}")
    if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
        raise PreparationRefused(f"unsafe existing file: {path}")
    return info


def _sync_owned_output(path: Path, *, uid: int) -> None:
    _owned_regular(path, uid=uid)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)


def _lease_state(config: PrepareConfig) -> tuple[Path, Path, dict[str, object]]:
    leases = config.state_root / "leases"
    lease_dir = leases / config.generation
    created = False
    try:
        lease_dir.mkdir(mode=0o700)
        created = True
        _fsync_dir(leases)
    except FileExistsError:
        _create_private_dir(lease_dir, uid=config.required_uid)
    owner_path = lease_dir / "ownership.json"
    expected = ownership_record(config)
    if created:
        _write_new_json(owner_path, expected)
    elif not owner_path.exists() or _read_private_json(owner_path, uid=config.required_uid) != expected:
        raise PreparationRefused("lease path has no matching ownership record")
    manifest_path = lease_dir / "manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest = _read_private_json(manifest_path, uid=config.required_uid)
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise PreparationRefused("manifest identity does not match this lease")
    else:
        manifest = {**expected, "state": "new", "events": [], "sessions": [], "objects": []}
        _write_new_json(manifest_path, manifest)
    return lease_dir, manifest_path, manifest


def _state_prerequisites(config: PrepareConfig) -> None:
    """Create only generic lock prerequisites before authoritative state is locked."""
    _reject_symlink_components(config.state_root)
    try:
        parent = config.state_root.parent.lstat()
    except FileNotFoundError as exc:
        raise PreparationRefused("state root parent does not exist") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != config.required_uid
        or parent.st_mode & 0o022
    ):
        raise PreparationRefused("state root parent is not safely owned")
    _create_private_dir(config.state_root, uid=config.required_uid)
    leases = config.state_root / "leases"
    locks = config.state_root / "locks"
    hosts = config.state_root / "hosts"
    _create_private_dir(leases, uid=config.required_uid)
    _create_private_dir(locks, uid=config.required_uid)
    _create_private_dir(hosts, uid=config.required_uid)


def _lock_host(config: PrepareConfig):
    lock_key = f"{config.host_id}-{config.nv_index.removeprefix('0x')}"
    lock_path = config.state_root / "locks" / f"{lock_key}.lock"
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.write(fd, (lock_key + "\n").encode())
        os.fsync(fd)
        _fsync_dir(lock_path.parent)
    except FileExistsError:
        _owned_regular(lock_path, uid=config.required_uid)
        fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
        if os.read(fd, 256).decode(errors="strict").strip() != lock_key:
            os.close(fd)
            raise PreparationRefused("host lock ownership does not match")
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _claim_generation(config: PrepareConfig) -> None:
    """Fence one unreleased generation to this host and reserved NV index."""
    fence_path = (
        config.state_root
        / "hosts"
        / f"{config.host_id}-{config.nv_index.removeprefix('0x')}.json"
    )
    expected = {
        "schema": SCHEMA,
        "host_id": config.host_id,
        "machine_id": config.machine_id,
        "nv_index": config.nv_index,
        "parent_handle": config.parent_handle,
        "parent_name": config.parent_name,
        "generation": config.generation,
        "state": "active",
    }
    if fence_path.exists() or fence_path.is_symlink():
        fence = _read_private_json(fence_path, uid=config.required_uid)
        identity_keys = (
            "schema", "host_id", "machine_id", "nv_index",
            "parent_handle", "parent_name",
        )
        if any(fence.get(key) != expected[key] for key in identity_keys):
            raise PreparationRefused("host/index generation fence identity does not match")
        if fence.get("state") != "active" or fence.get("generation") != config.generation:
            raise PreparationRefused(
                "another active generation owns the host/index counter"
            )
        return
    _write_new_json(fence_path, expected)


def _persist(path: Path, manifest: dict[str, object], config: PrepareConfig, event: str) -> None:
    events = manifest.setdefault("events", [])
    assert isinstance(events, list)
    events.append(event)
    _replace_owned_json(path, manifest, uid=config.required_uid)


def _fail(boundary: str, selected: str | None) -> None:
    if selected == boundary:
        raise InjectedInterruption(boundary)


def _reconcile_handles(
    config: PrepareConfig, manifest_path: Path, manifest: dict[str, object]
) -> None:
    sessions = manifest.get("sessions", [])
    objects = manifest.get("objects", [])
    if not isinstance(sessions, list) or not isinstance(objects, list):
        raise PreparationQuarantined("invalid handle evidence")
    for record in [*sessions, *objects]:
        if not isinstance(record, dict):
            raise PreparationQuarantined("invalid TPM ownership evidence")
        if record.get("state") != "confirmed_closed":
            manifest["state"] = "quarantined"
            _persist(manifest_path, manifest, config, "unresolved_tpm_ownership_gap")
            raise PreparationQuarantined(
                "prior ESAPI ownership is incomplete; refusing stale-handle cleanup"
            )
        if record.get("executor") != "same-process-esapi":
            raise PreparationQuarantined(
                "TPM closure evidence is not from the checked ESAPI boundary"
            )


class _ManifestOwnershipRecorder:
    """Fsync ownership transitions before and after each live TPM handle."""

    def __init__(self, config, manifest_path, manifest) -> None:
        self._config = config
        self._manifest_path = manifest_path
        self._manifest = manifest

    def pending(self, kind: str, purpose: str) -> dict[str, object]:
        collection = "sessions" if kind == "session" else "objects"
        records = self._manifest.setdefault(collection, [])
        if not isinstance(records, list):
            raise PreparationQuarantined("invalid TPM ownership evidence")
        record: dict[str, object] = {
            "attempt": len(records) + 1,
            "purpose": purpose,
            "kind": kind,
            "executor": "same-process-esapi",
            "state": "pending",
        }
        records.append(record)
        _persist(
            self._manifest_path,
            self._manifest,
            self._config,
            f"{kind}_intent",
        )
        return record

    def live(self, record: dict[str, object], handle: int) -> None:
        if not isinstance(handle, int) or handle < 0 or handle > 0xFFFFFFFF:
            raise PreparationQuarantined("ESAPI returned an invalid TPM handle identity")
        record["handle"] = f"0x{handle:08x}"
        record["state"] = "live"
        try:
            _persist(self._manifest_path, self._manifest, self._config, "handle_recorded")
        except BaseException:
            record.pop("handle", None)
            record["state"] = "pending"
            raise

    def close_pending(self, record: dict[str, object]) -> None:
        record["state"] = "close_pending"
        try:
            _persist(self._manifest_path, self._manifest, self._config, "handle_close_intent")
        except BaseException:
            record["state"] = "live"
            raise

    def closed(self, record: dict[str, object]) -> None:
        record["state"] = "confirmed_closed"
        try:
            _persist(self._manifest_path, self._manifest, self._config, "handle_confirmed_closed")
        except BaseException:
            record["state"] = "close_pending"
            raise


def _create_backing(path: Path, config: PrepareConfig) -> None:
    if path.exists() or path.is_symlink():
        _owned_regular(path, uid=config.required_uid)
        return
    available = shutil.disk_usage(path.parent).free
    if available - config.backing_size < config.free_space_floor:
        raise PreparationRefused("free-space floor would be violated")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.posix_fallocate(fd, 0, config.backing_size)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        raise
    else:
        os.close(fd)
    _fsync_dir(path.parent)


def _luks_metadata(runner, backing: Path) -> None:
    raw = runner.run(("cryptsetup", "luksDump", "--dump-json-metadata", str(backing)))
    try:
        metadata = json.loads(raw)
        keyslots = metadata["keyslots"]
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PreparationQuarantined("cannot verify LUKS2 keyslots") from exc
    if not isinstance(keyslots, dict) or set(keyslots) != {"0"}:
        raise PreparationQuarantined("lease volume does not have exactly one keyslot")


def _receipt(config: PrepareConfig, manifest: dict[str, object]) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "host_id": config.host_id,
        "machine_id": config.machine_id,
        "generation": config.generation,
        "counter": manifest["counter"],
        "nv_index": config.nv_index,
        "parent_name": config.parent_name,
        "sealed_object_name": manifest["sealed_object_name"],
        "state": "prepared",
    }


def _prepare(
    config: PrepareConfig,
    *,
    runner=None,
    custody=None,
    random_bytes: Callable[[int], bytes] = os.urandom,
    fail_after: str | None = None,
) -> dict[str, object]:
    """Prepare or safely resume one lease generation under its host lock."""
    if fail_after is not None and fail_after not in FAILPOINTS:
        raise ValueError(f"unknown failpoint: {fail_after}")
    runner = runner or SubprocessRunner()
    custody = custody or getattr(runner, "custody", None)
    if custody is None:
        raise PreparationRefused(
            "same-process ESAPI custody is not enabled for production preparation"
        )
    _state_prerequisites(config)
    lock_fd = _lock_host(config)
    try:
        _fail("host_lock", fail_after)
        _claim_generation(config)
        lease_dir, manifest_path, manifest = _lease_state(config)
        _fail("lease_state", fail_after)
        if manifest.get("state") == "quarantined":
            raise PreparationQuarantined("lease preparation is already quarantined")
        attempts = manifest.setdefault("helper_attempts", [])
        if not isinstance(attempts, list):
            raise PreparationRefused("invalid helper-attempt evidence")
        helper_attempt: dict[str, object] = {
            "attempt": len(attempts) + 1,
            "helper": "standalone-preparation-helper",
            "state": "running",
        }
        attempts.append(helper_attempt)
        _persist(manifest_path, manifest, config, "helper_started")
        _fail("helper_intent", fail_after)
        _reconcile_handles(config, manifest_path, manifest)
        recorder = _ManifestOwnershipRecorder(config, manifest_path, manifest)
        try:
            custody.verify_resources(
                parent_handle=int(config.parent_handle, 16),
                parent_name=bytes.fromhex(config.parent_name),
                nv_index=int(config.nv_index, 16),
            )
        except RuntimeError as exc:
            raise PreparationQuarantined("TPM resource verification failed") from exc
        backing = lease_dir / "volume.luks"
        if backing.exists() or backing.is_symlink():
            _owned_regular(backing, uid=config.required_uid)
            if manifest.get("backing_intent") != {
                "path": backing.name,
                "size": config.backing_size,
            }:
                raise PreparationRefused("backing file has no matching ownership intent")
        elif shutil.disk_usage(backing.parent).free - config.backing_size < config.free_space_floor:
            raise PreparationRefused("free-space floor would be violated")

        try:
            current = custody.read_counter()
        except RuntimeError as exc:
            raise PreparationQuarantined("NV counter read failed") from exc
        intent = manifest.get("counter_intent")
        exclusive_writer = {
            "host_id": config.host_id,
            "nv_index": config.nv_index,
            "lock": (
                f"locks/{config.host_id}-"
                f"{config.nv_index.removeprefix('0x')}.lock"
            ),
        }
        if intent is None:
            if current >= MAX_COUNTER - config.counter_headroom:
                raise PreparationRefused("NV counter is inside the configured headroom")
            manifest["counter_intent"] = {
                "pre_increment": current,
                "exclusive_writer": exclusive_writer,
            }
            manifest["state"] = "counter_increment_pending"
            _persist(manifest_path, manifest, config, "counter_intent")
            _fail("counter_intent", fail_after)
            before = current
        elif isinstance(intent, dict) and isinstance(intent.get("pre_increment"), int):
            if intent.get("exclusive_writer") != exclusive_writer:
                raise PreparationQuarantined(
                    "counter advance has no durable exclusive-writer attribution"
                )
            before = intent["pre_increment"]
        else:
            raise PreparationQuarantined("counter intent is missing its pre-increment value")

        if current == before:
            try:
                custody.increment_counter()
                _fail("counter_increment", fail_after)
                current = custody.read_counter()
            except InjectedInterruption:
                raise
            except RuntimeError as exc:
                raise PreparationQuarantined(
                    "counter increment outcome is uncertain"
                ) from exc
        if current != before + 1:
            manifest["state"] = "quarantined"
            _persist(manifest_path, manifest, config, "counter_drift")
            raise PreparationQuarantined("counter drift cannot be attributed to this attempt")
        manifest["counter"] = current
        manifest["state"] = "counter_incremented"
        _persist(manifest_path, manifest, config, "counter_increment_confirmed")
        _fail("counter_confirmed", fail_after)

        policy_path = lease_dir / "policy.nv"
        object_public = lease_dir / "sealed.pub"
        object_private = lease_dir / "sealed.priv"
        secret: bytes | None = None
        public_exists = object_public.exists() or object_public.is_symlink()
        private_exists = object_private.exists() or object_private.is_symlink()
        if not public_exists and not private_exists:
            try:
                policy = custody.build_policy(current, recorder)
            except RuntimeError as exc:
                raise PreparationQuarantined(
                    "PolicyNV transaction did not close cleanly"
                ) from exc
            _fail("policy_digest", fail_after)
            _fail("policy_session_closed", fail_after)
            if policy_path.exists() or policy_path.is_symlink():
                _owned_regular(policy_path, uid=config.required_uid)
                if policy_path.read_bytes() != policy:
                    raise PreparationQuarantined("PolicyNV digest changed across retry")
            else:
                _write_new_private(policy_path, policy)
            _fail("policy_committed", fail_after)
            _owned_regular(policy_path, uid=config.required_uid)
            secret = random_bytes(32)
            if len(secret) != 32:
                raise PreparationRefused("secret generator did not return 32 bytes")
            manifest["sealed_object_intent"] = {
                "public": object_public.name,
                "private": object_private.name,
                "policy": policy.hex(),
            }
            _persist(manifest_path, manifest, config, "sealed_object_intent")
            _fail("sealed_object_intent", fail_after)
            try:
                private_blob, public_blob = custody.create_sealed(secret, policy)
            except RuntimeError as exc:
                raise PreparationQuarantined(
                    "sealed-object creation outcome is uncertain"
                ) from exc
            _write_new_private(object_public, public_blob)
            _write_new_private(object_private, private_blob)
            _fail("sealed_object", fail_after)
            manifest["state"] = "sealed_object_created"
            _persist(manifest_path, manifest, config, "sealed_object_created")
            _fail("sealed_object_recorded", fail_after)
        elif not public_exists or not private_exists:
            raise PreparationQuarantined("sealed object output is partial")
        else:
            for path in (policy_path, object_public, object_private):
                _owned_regular(path, uid=config.required_uid)
            if manifest.get("sealed_object_intent") != {
                "public": object_public.name,
                "private": object_private.name,
                "policy": policy_path.read_bytes().hex(),
            }:
                raise PreparationRefused("sealed object files have no matching ownership intent")
        for path in (policy_path, object_public, object_private):
            _owned_regular(path, uid=config.required_uid)
        policy = policy_path.read_bytes()
        try:
            evidence, recovered_secret = custody.recover_and_verify(
                private_blob=object_private.read_bytes(),
                public_blob=object_public.read_bytes(),
                expected_policy=policy,
                counter=current,
                recorder=recorder,
            )
        except RuntimeError as exc:
            raise PreparationQuarantined(
                "sealed-object transaction did not complete with checked cleanup"
            ) from exc
        if secret is not None and recovered_secret != secret:
            raise PreparationQuarantined("new sealed object did not recover its source secret")
        secret = recovered_secret
        object_name = evidence.name.hex()
        _fail("object_closed", fail_after)
        manifest["sealed_object_name"] = object_name
        manifest["state"] = "sealed_object_verified"
        _persist(manifest_path, manifest, config, "sealed_object_verified")
        _fail("sealed_object_verified", fail_after)
        try:
            custody.close()
        except RuntimeError as exc:
            raise PreparationQuarantined(
                "ESAPI ownership boundary did not finalize"
            ) from exc

        existed = backing.exists() or backing.is_symlink()
        if not existed:
            manifest["backing_intent"] = {
                "path": backing.name,
                "size": config.backing_size,
            }
            _persist(manifest_path, manifest, config, "backing_file_intent")
            _fail("backing_file_intent", fail_after)
        _create_backing(backing, config)
        if backing.stat().st_size != config.backing_size:
            raise PreparationQuarantined("owned backing file has the wrong fixed size")
        if not existed:
            manifest["state"] = "backing_preallocated"
            _persist(manifest_path, manifest, config, "backing_preallocated")
            _fail("backing_file", fail_after)

        is_luks = runner.check(("cryptsetup", "isLuks", "--type", "luks2", str(backing)))
        if not is_luks:
            if manifest.get("luks_formatted") is True or manifest.get("luks_format_intent"):
                raise PreparationQuarantined(
                    "owned backing file no longer has its verified LUKS2 header"
                )
            if secret is None:
                raise PreparationQuarantined("sealed secret must be recovered before formatting")
            manifest["luks_format_intent"] = {
                "path": backing.name,
                "type": "luks2",
                "keyslots": [0],
            }
            _persist(manifest_path, manifest, config, "luks_format_intent")
            _fail("luks_format_intent", fail_after)
            try:
                runner.run(
                    (
                        "cryptsetup", "--batch-mode", "--type", "luks2", "--key-file", "-",
                        "--keyfile-size", "32",
                        "luksFormat", str(backing),
                    ),
                    stdin=secret,
                )
            except PreparationRefused as exc:
                raise PreparationQuarantined("LUKS2 format outcome is uncertain") from exc
            _sync_owned_output(backing, uid=config.required_uid)
            _fail("luks_format", fail_after)
            if not runner.check(
                ("cryptsetup", "isLuks", "--type", "luks2", str(backing))
            ):
                raise PreparationQuarantined("new LUKS2 header cannot be verified")
        try:
            _luks_metadata(runner, backing)
            if secret is None:
                raise PreparationQuarantined("sealed secret is unavailable for LUKS2 verification")
            runner.run(
                (
                    "cryptsetup", "--type", "luks2", "--test-passphrase",
                    "--key-file", "-", "--keyfile-size", "32", "open", str(backing),
                ),
                stdin=secret,
            )
        except PreparationQuarantined:
            raise
        except PreparationRefused as exc:
            raise PreparationQuarantined(
                "sealed secret does not unlock the verified LUKS2 header"
            ) from exc
        if manifest.get("luks_formatted") is not True:
            manifest["luks_formatted"] = True
            manifest["state"] = "luks_verified"
            _persist(manifest_path, manifest, config, "luks_single_keyslot_verified")
            _fail("luks_verified", fail_after)

        manifest["state"] = "prepared"
        receipt = _receipt(config, manifest)
        manifest["receipt"] = receipt
        _persist(manifest_path, manifest, config, "prepared_receipt")
        _fail("prepared_receipt", fail_after)
        helper_attempt["state"] = "completed"
        _persist(manifest_path, manifest, config, "helper_completed")
        _fail("helper_completed", fail_after)
        return receipt
    except PreparationQuarantined as exc:
        if "manifest" not in locals() or "manifest_path" not in locals():
            raise PreparationUnresolved(
                "cannot identify authoritative manifest to persist quarantine"
            ) from exc
        if manifest.get("state") != "quarantined":
            manifest["state"] = "quarantined"
            manifest["quarantine_reason"] = str(exc)
            try:
                _persist(manifest_path, manifest, config, "quarantined")
            except (OSError, PreparationRefused) as persist_error:
                raise PreparationUnresolved(
                    "failed to persist quarantine under the host/index lock"
                ) from persist_error
        raise
    finally:
        os.close(lock_fd)


def prepare(
    config: PrepareConfig,
    *,
    runner=None,
    custody=None,
    random_bytes: Callable[[int], bytes] = os.urandom,
    fail_after: str | None = None,
) -> dict[str, object]:
    """Run preparation with a root-private creation mask, restoring the caller's."""
    previous_umask = os.umask(0o077)
    try:
        return _prepare(
            config,
            runner=runner,
            custody=custody,
            random_bytes=random_bytes,
            fail_after=fail_after,
        )
    finally:
        os.umask(previous_umask)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--host-id", required=True)
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--backing-size", type=int, required=True)
    parser.add_argument("--free-space-floor", type=int, required=True)
    parser.add_argument("--nv-index", required=True)
    parser.add_argument("--counter-headroom", type=int, required=True)
    parser.add_argument("--parent-handle", required=True)
    parser.add_argument("--parent-name", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    os.umask(0o077)
    try:
        receipt = prepare(
            PrepareConfig(
                state_root=args.state_root,
                host_id=args.host_id,
                machine_id=args.machine_id,
                generation=args.generation,
                backing_size=args.backing_size,
                free_space_floor=args.free_space_floor,
                nv_index=args.nv_index,
                counter_headroom=args.counter_headroom,
                parent_handle=args.parent_handle,
                parent_name=args.parent_name,
            )
        )
    except PreparationRefused as exc:
        if isinstance(exc, PreparationUnresolved):
            state = "unresolved"
        elif isinstance(exc, PreparationQuarantined):
            state = "quarantined"
        else:
            state = "refused"
        print(json.dumps({"state": state, "reason": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
