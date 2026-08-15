"""Versioned append-only buyer run logs bound to durable buyer profiles."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_identity import (
    REQUEST_PROTOCOL,
    Identity,
    IdentityScheme,
    ProfileRepository,
    ProfileStore,
    Signer,
)

RUN_LOG_VERSION = 3
SIGNATURE_VERSION = 2
_MIGRATION_MANIFEST = ".profile-migration-v3.json"
_MIGRATION_BACKUPS = ".profile-migration-v3.backups"
_FORBIDDEN_SECRET_FIELDS = {
    "admin_api_key",
    "api_key",
    "buyer_private_key",
    "config_snapshot",
    "credential",
    "credential_locator",
    "credential_provider",
    "credential_reference",
    "database_url",
    "environment_value",
    "identity_credential",
    "keyring_value",
    "mnemonic",
    "private_key",
    "provider_locator",
    "provider_secret",
    "resolved_config",
    "seed",
    "settlement_config",
    "signer",
    "signer_secret",
    "webhook_secret",
}
_RESERVED_EVENT_FIELDS = {
    "event",
    "log_version",
    "buyer_profile_id",
    "buyer_principal",
    "run_id",
    "signature_protocol",
    "signature_version",
    "ts",
}
_TERMINAL_RUN_STATUSES = {
    "abandoned",
    "cancelled",
    "collected",
    "complete",
    "completed",
    "reclaimed",
    "settled",
}


class RunLogError(ValueError):
    """Raised when a run log is unsafe, unknown, or internally inconsistent."""


class RunLogMigrationIncomplete(RunLogError):
    """Raised until an interrupted coordinated migration is explicitly recovered."""


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Safe immutable ownership metadata needed to resolve a recovery signer."""

    profile_id: uuid.UUID
    principal: Identity
    signature_version: int = SIGNATURE_VERSION


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    path: Path
    buyer_profile_id: uuid.UUID
    buyer_principal: Identity
    started_at: str | None
    last_event: str | None
    last_event_ts: str | None
    last_status: str | None
    recoverable: bool


def runs_dir() -> Path:
    """Return the directory holding per-run JSONL log files."""

    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "arkhai" / "buy-runs"


def _new_run_id() -> str:
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_principal(principal: Identity) -> dict[str, str]:
    return principal.model_dump(mode="json")


def _assert_secret_isolation(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_SECRET_FIELDS:
                raise RunLogError(
                    f"run logs must not contain credential or signer field {key!r}"
                )
            _assert_secret_isolation(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_secret_isolation(child)


def _legacy_addresses(value: Any) -> list[str]:
    addresses: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "buyer_address":
                if not isinstance(child, str):
                    raise RunLogError("legacy buyer_address must be text")
                addresses.append(child)
            else:
                addresses.extend(_legacy_addresses(child))
    elif isinstance(value, list):
        for child in value:
            addresses.extend(_legacy_addresses(child))
    return addresses


def _replace_legacy_identity(value: Any, principal: Identity) -> Any:
    if isinstance(value, Mapping):
        if "buyer_address" in value and "buyer_principal" in value:
            raise RunLogError("legacy record carries conflicting buyer identities")
        migrated: dict[str, Any] = {}
        for key, child in value.items():
            if key == "buyer_address":
                migrated["buyer_principal"] = _public_principal(principal)
            else:
                migrated[str(key)] = _replace_legacy_identity(child, principal)
        return migrated
    if isinstance(value, list):
        return [_replace_legacy_identity(child, principal) for child in value]
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    events: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunLogError(f"malformed run-log JSON at line {number}") from exc
        if not isinstance(value, dict):
            raise RunLogError(f"run-log line {number} is not an object")
        events.append(value)
    return events


def _encode_events(events: list[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(event, separators=(",", ":")).encode("utf-8") + b"\n"
        for event in events
    )


def _write_bytes_atomic(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_events_atomic(path: Path, events: list[dict[str, Any]]) -> None:
    _write_bytes_atomic(path, _encode_events(events))


def _parse_profile_id(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise RunLogError("run-log buyer_profile_id is malformed") from exc


def _validate_event_identity(
    event: dict[str, Any],
    *,
    run_id: str,
    expected: RunIdentity | None,
) -> RunIdentity:
    if event.get("run_id") != run_id:
        raise RunLogError("run-log event run_id does not match its file")
    if not isinstance(event.get("event"), str) or not event["event"]:
        raise RunLogError("run-log event name is missing")
    if event.get("log_version") != RUN_LOG_VERSION:
        raise RunLogError(f"unsupported run-log version {event.get('log_version')!r}")
    if event.get("signature_protocol") != REQUEST_PROTOCOL:
        raise RunLogError("unsupported run-log signature protocol")
    if event.get("signature_version") != SIGNATURE_VERSION:
        raise RunLogError("unsupported run-log signature version")
    try:
        principal = Identity.model_validate(event.get("buyer_principal"))
    except (TypeError, ValueError) as exc:
        raise RunLogError("run-log buyer_principal is malformed") from exc
    identity = RunIdentity(
        profile_id=_parse_profile_id(event.get("buyer_profile_id")),
        principal=principal,
    )
    if expected is not None and identity != expected:
        raise RunLogError("run-log events carry inconsistent buyer ownership")
    _assert_secret_isolation(event)
    if _legacy_addresses(event):
        raise RunLogError("versioned run log contains a legacy buyer_address")
    return identity


def _validate_current(
    events: list[dict[str, Any]],
    *,
    run_id: str,
) -> RunIdentity:
    if not events:
        raise RunLogError("run log is empty")
    identity: RunIdentity | None = None
    for event in events:
        identity = _validate_event_identity(
            event,
            run_id=run_id,
            expected=identity,
        )
    assert identity is not None
    return identity


def _legacy_principal(events: list[dict[str, Any]]) -> Identity:
    principals: set[Identity] = set()
    canonical_payloads = [
        event.get("buyer_principal")
        for event in events
        if event.get("buyer_principal") is not None
    ]
    if canonical_payloads:
        if len(canonical_payloads) != len(events):
            raise RunLogError("legacy run log is partially principal-versioned")
        try:
            principals.update(Identity.model_validate(value) for value in canonical_payloads)
        except (TypeError, ValueError) as exc:
            raise RunLogError("legacy run log contains malformed buyer principal") from exc
    addresses = _legacy_addresses(events)
    try:
        principals.update(
            Identity(scheme=IdentityScheme.EIP191, identifier=address)
            for address in addresses
        )
    except (TypeError, ValueError) as exc:
        raise RunLogError("legacy run log contains malformed buyer address") from exc
    if len(principals) != 1:
        raise RunLogError("legacy run log does not contain one exact buyer principal")
    return next(iter(principals))


def _unique_profile_id(store: ProfileStore, principal: Identity) -> uuid.UUID:
    matches = {
        profile.profile_id
        for profile in store.profiles
        for entry in profile.principal_history
        if entry.principal == principal
    }
    if len(matches) != 1:
        raise RunLogError(
            "run-log principal must match exactly one buyer profile history"
        )
    return next(iter(matches))


def _stage_migration_candidate(
    path: Path,
    events: list[dict[str, Any]],
    *,
    store: ProfileStore,
) -> list[dict[str, Any]]:
    if not events:
        raise RunLogError("run log is empty")
    run_id = path.stem
    for event in events:
        if event.get("run_id") != run_id:
            raise RunLogError("legacy run-log event run_id does not match its file")
    _assert_secret_isolation(events)
    principal = _legacy_principal(events)
    profile_id = _unique_profile_id(store, principal)
    migrated: list[dict[str, Any]] = []
    for event in events:
        converted = _replace_legacy_identity(event, principal)
        converted["log_version"] = RUN_LOG_VERSION
        converted["signature_protocol"] = REQUEST_PROTOCOL
        converted["signature_version"] = SIGNATURE_VERSION
        converted["buyer_profile_id"] = str(profile_id)
        converted["buyer_principal"] = _public_principal(principal)
        migrated.append(converted)
    _validate_current(migrated, run_id=run_id)
    return migrated


def _manifest_path(directory: Path) -> Path:
    return directory / _MIGRATION_MANIFEST


def assert_migration_resolved(directory: Path | None = None) -> None:
    """Reject runtime access while an interrupted migration manifest remains."""

    root = directory or runs_dir()
    if _manifest_path(root).exists():
        raise RunLogMigrationIncomplete(
            "buyer run-log migration is incomplete; run explicit migration recovery"
        )


def migrate_run_logs(
    repository: ProfileRepository,
    *,
    directory: Path | None = None,
    candidate_store: ProfileStore | None = None,
    expected_revision: int | None = None,
) -> tuple[str, ...]:
    """Atomically publish a candidate profile store and every version-3 run."""

    root = directory or runs_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert_migration_resolved(root)
    current_store = repository.load()
    if candidate_store is not None:
        if expected_revision is None or current_store.revision != expected_revision:
            raise RunLogError("profile-store migration revision is stale")
        if candidate_store.revision != current_store.revision + 1:
            raise RunLogError("profile-store migration candidate revision is invalid")
        migration_store = ProfileStore.model_validate(
            candidate_store.model_dump(mode="python")
        )
    else:
        if expected_revision is not None:
            raise RunLogError("expected_revision requires a profile-store candidate")
        migration_store = current_store

    staged: dict[Path, list[dict[str, Any]]] = {}
    for path in sorted(root.glob("*.jsonl")):
        events = _read_jsonl(path)
        versions = {event.get("log_version") for event in events}
        if versions == {RUN_LOG_VERSION}:
            _validate_current(events, run_id=path.stem)
            continue
        if any(version not in (None, 1, 2) for version in versions):
            raise RunLogError(f"unsupported or inconsistent run-log versions: {versions!r}")
        staged[path] = _stage_migration_candidate(
            path,
            events,
            store=migration_store,
        )
    if not staged and candidate_store is None:
        return ()

    replacements: list[tuple[str, Path, bytes]] = []
    if candidate_store is not None:
        replacements.append(
            (
                "profile_store",
                repository.path,
                json.dumps(
                    migration_store.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
        )
    replacements.extend(
        ("run_log", path, _encode_events(events))
        for path, events in staged.items()
    )

    backup_root = root / _MIGRATION_BACKUPS
    backup_root.mkdir(mode=0o700, exist_ok=False)
    entries: list[dict[str, Any]] = []
    try:
        for index, (kind, path, candidate_payload) in enumerate(replacements):
            existed = path.exists()
            original = path.read_bytes() if existed else b""
            backup = backup_root / f"{index:04d}-{path.name}"
            candidate = backup_root / f"{index:04d}-{path.name}.candidate"
            if existed:
                _write_bytes_atomic(backup, original)
            _write_bytes_atomic(candidate, candidate_payload)
            entries.append(
                {
                    "kind": kind,
                    "path": str(path.absolute()),
                    "backup": str(backup.absolute()),
                    "candidate": str(candidate.absolute()),
                    "existed": existed,
                    "original_sha256": (
                        hashlib.sha256(original).hexdigest() if existed else None
                    ),
                    "candidate_sha256": hashlib.sha256(candidate_payload).hexdigest(),
                }
            )
        manifest = {
            "schema_version": 1,
            "state": "prepared",
            "replaced": 0,
            "entries": entries,
        }
        _write_manifest(root, manifest)
        for index, entry in enumerate(entries, start=1):
            if entry["kind"] == "profile_store":
                repository.replace(
                    migration_store,
                    expected_revision=current_store.revision,
                )
            else:
                candidate_path = Path(entry["candidate"])
                target_path = Path(entry["path"])
                os.replace(candidate_path, target_path)
                _fsync_directory(target_path.parent)
            manifest["state"] = "replacing"
            manifest["replaced"] = index
            _write_manifest(root, manifest)
        if candidate_store is not None and repository.load() != migration_store:
            raise RunLogError("profile-store migration replacement validation failed")
        for path, expected in staged.items():
            actual = _read_jsonl(path)
            if actual != expected:
                raise RunLogError("run-log migration replacement validation failed")
            _validate_current(actual, run_id=path.stem)
        manifest["state"] = "complete"
        _write_manifest(root, manifest)
        _remove_migration_artifacts(root)
        return tuple(path.stem for path in staged)
    except BaseException:
        if _manifest_path(root).exists():
            _restore_from_manifest(root)
        else:
            shutil.rmtree(backup_root, ignore_errors=True)
        raise


def recover_run_log_migration(*, directory: Path | None = None) -> None:
    """Restore every retained original from an interrupted migration manifest."""

    root = directory or runs_dir()
    if not _manifest_path(root).exists():
        return
    _restore_from_manifest(root)


def _write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    _write_bytes_atomic(
        _manifest_path(root),
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    )


def _read_manifest(root: Path) -> dict[str, Any]:
    try:
        value = json.loads(_manifest_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunLogMigrationIncomplete("migration manifest is malformed") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("entries"), list)
    ):
        raise RunLogMigrationIncomplete("migration manifest is unsupported")
    return value


def _restore_from_manifest(root: Path) -> None:
    manifest = _read_manifest(root)
    for entry in manifest["entries"]:
        try:
            target = Path(entry["path"])
            existed = bool(entry.get("existed", True))
            if not existed:
                target.unlink(missing_ok=True)
                _fsync_directory(target.parent)
                continue
            backup = Path(entry["backup"])
            payload = backup.read_bytes()
        except (KeyError, OSError, TypeError) as exc:
            raise RunLogMigrationIncomplete(
                "migration original is unavailable for restoration"
            ) from exc
        if hashlib.sha256(payload).hexdigest() != entry.get("original_sha256"):
            raise RunLogMigrationIncomplete("migration original checksum changed")
        _write_bytes_atomic(target, payload)
    _remove_migration_artifacts(root)


def _remove_migration_artifacts(root: Path) -> None:
    _manifest_path(root).unlink(missing_ok=True)
    shutil.rmtree(root / _MIGRATION_BACKUPS, ignore_errors=False)
    _fsync_directory(root)


def _load_versioned(
    path: Path,
    *,
    run_id: str,
) -> tuple[list[dict[str, Any]], RunIdentity]:
    assert_migration_resolved(path.parent)
    events = _read_jsonl(path)
    if not events:
        raise RunLogError("run log is empty")
    versions = [event.get("log_version") for event in events]
    if any(version != RUN_LOG_VERSION for version in versions):
        raise RunLogError(
            "run log requires coordinated profile-bound version-3 migration"
        )
    return events, _validate_current(events, run_id=run_id)


class RunLog:
    """One versioned run log bound to a stable profile and exact principal."""

    def __init__(
        self,
        run_id: str,
        path: Path,
        identity: RunIdentity,
    ) -> None:
        self.run_id = run_id
        self.path = path
        self.profile_id = identity.profile_id
        self.principal = identity.principal
        self.signature_version = identity.signature_version

    @classmethod
    def start(
        cls,
        *,
        profile_id: uuid.UUID | str,
        principal: Identity,
        **input_fields: Any,
    ) -> RunLog:
        """Begin a fresh run without accepting or serializing signer material."""

        identity = RunIdentity(profile_id=_parse_profile_id(profile_id), principal=principal)
        run_id = _new_run_id()
        path = runs_dir() / f"{run_id}.jsonl"
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        log = cls(run_id, path, identity)
        log.event("run_started", **input_fields)
        return log

    @classmethod
    def open(
        cls,
        run_id: str,
        *,
        signer: Signer,
        profile_id: uuid.UUID | str,
    ) -> RunLog:
        """Open recovery only when the available exact profile signer owns it."""

        path = runs_dir() / f"{run_id}.jsonl"
        _, identity = _load_versioned(path, run_id=run_id)
        if signer.identity != identity.principal:
            raise RunLogError("available signer does not match run-log buyer principal")
        if _parse_profile_id(profile_id) != identity.profile_id:
            raise RunLogError("available profile does not match run-log buyer profile")
        return cls(run_id, path, identity)

    def event(self, event: str, **fields: Any) -> None:
        """Append one event while preserving profile and identity invariants."""

        overlap = _RESERVED_EVENT_FIELDS.intersection(fields)
        if overlap:
            raise RunLogError(
                "event fields may not replace run-log metadata: "
                + ", ".join(sorted(overlap))
            )
        _assert_secret_isolation(fields)
        record = {
            "ts": _now_iso(),
            "run_id": self.run_id,
            "event": event,
            "log_version": RUN_LOG_VERSION,
            "signature_protocol": REQUEST_PROTOCOL,
            "signature_version": self.signature_version,
            "buyer_profile_id": str(self.profile_id),
            "buyer_principal": _public_principal(self.principal),
            **fields,
        }
        try:
            encoded = json.dumps(record, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise RunLogError("run-log event is not JSON serializable") from exc
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def end(self, status: str, **fields: Any) -> None:
        self.event("run_ended", status=status, **fields)


def read_run_identity(run_id: str) -> RunIdentity:
    """Read only validated public ownership metadata for recovery resolution."""

    path = runs_dir() / f"{run_id}.jsonl"
    _, identity = _load_versioned(path, run_id=run_id)
    return identity


def read_run(
    run_id: str,
    *,
    signer: Signer | None = None,
    profile_id: uuid.UUID | str | None = None,
) -> list[dict[str, Any]]:
    """Read and validate one current profile-bound run log."""

    path = runs_dir() / f"{run_id}.jsonl"
    if not path.exists():
        return []
    events, identity = _load_versioned(path, run_id=run_id)
    if signer is not None and signer.identity != identity.principal:
        raise RunLogError("available signer does not match run-log buyer principal")
    if profile_id is not None and _parse_profile_id(profile_id) != identity.profile_id:
        raise RunLogError("available profile does not match run-log buyer profile")
    return events


def list_runs() -> list[RunSummary]:
    """Return validated run summaries, newest first by file modification time."""

    directory = runs_dir()
    if not directory.exists():
        return []
    assert_migration_resolved(directory)
    files: Iterable[Path] = sorted(
        directory.glob("*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    summaries: list[RunSummary] = []
    for path in files:
        events = read_run(path.stem)
        if not events:
            continue
        identity = _validate_current(events, run_id=path.stem)
        first = events[0]
        last = events[-1]
        last_status = last.get("status") if last.get("event") == "run_ended" else None
        summaries.append(
            RunSummary(
                run_id=path.stem,
                path=path,
                buyer_profile_id=identity.profile_id,
                buyer_principal=identity.principal,
                started_at=first.get("ts"),
                last_event=last.get("event"),
                last_event_ts=last.get("ts"),
                last_status=last_status,
                recoverable=last_status not in _TERMINAL_RUN_STATUSES,
            )
        )
    return summaries


def recoverable_run_ids(
    profile_id: uuid.UUID | str,
    *,
    principal: Identity | None = None,
) -> tuple[str, ...]:
    """Return exact run blockers for profile/principal retirement."""

    wanted = _parse_profile_id(profile_id)
    return tuple(
        summary.run_id
        for summary in list_runs()
        if summary.recoverable
        and summary.buyer_profile_id == wanted
        and (principal is None or summary.buyer_principal == principal)
    )


def last_successful_step(
    run_id: str,
    *,
    signer: Signer,
    profile_id: uuid.UUID | str | None = None,
) -> dict[str, Any] | None:
    """Return the last non-error stage event owned by the exact recovery signer."""

    for event in reversed(read_run(run_id, signer=signer, profile_id=profile_id)):
        if event.get("error"):
            continue
        if event.get("event") in ("run_started", "run_ended"):
            continue
        return event
    return None


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
