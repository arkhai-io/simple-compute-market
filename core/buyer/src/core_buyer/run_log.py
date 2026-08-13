"""Versioned append-only logs for buyer runs and recovery."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_identity import REQUEST_PROTOCOL, Identity, IdentityScheme, Signer

RUN_LOG_VERSION = 2
_FORBIDDEN_SECRET_FIELDS = {
    "admin_api_key",
    "api_key",
    "buyer_private_key",
    "config_snapshot",
    "database_url",
    "identity_credential",
    "private_key",
    "provider_secret",
    "resolved_config",
    "settlement_config",
    "signer",
    "signer_secret",
    "webhook_secret",
}
_RESERVED_EVENT_FIELDS = {
    "event",
    "log_version",
    "buyer_principal",
    "run_id",
    "signature_protocol",
    "ts",
}


class RunLogError(ValueError):
    """Raised when a run log is unsafe, unknown, or internally inconsistent."""


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
                    f"run logs must not contain signer secret field {key!r}"
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


def _write_events_atomic(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            for event in events:
                stream.write(json.dumps(event, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _validate_event_identity(
    event: dict[str, Any],
    *,
    run_id: str,
    expected: Identity | None,
) -> Identity:
    if event.get("run_id") != run_id:
        raise RunLogError("run-log event run_id does not match its file")
    if not isinstance(event.get("event"), str) or not event["event"]:
        raise RunLogError("run-log event name is missing")
    if event.get("log_version") != RUN_LOG_VERSION:
        raise RunLogError(f"unsupported run-log version {event.get('log_version')!r}")
    if event.get("signature_protocol") != REQUEST_PROTOCOL:
        raise RunLogError("unsupported run-log signature protocol")
    try:
        principal = Identity.model_validate(event.get("buyer_principal"))
    except (TypeError, ValueError) as exc:
        raise RunLogError("run-log buyer_principal is malformed") from exc
    if expected is not None and principal != expected:
        raise RunLogError("run-log events carry inconsistent buyer principals")
    _assert_secret_isolation(event)
    if _legacy_addresses(event):
        raise RunLogError("versioned run log contains a legacy buyer_address")
    return principal


def _validate_current(
    events: list[dict[str, Any]],
    *,
    run_id: str,
) -> Identity:
    if not events:
        raise RunLogError("run log is empty")
    principal: Identity | None = None
    for event in events:
        principal = _validate_event_identity(
            event,
            run_id=run_id,
            expected=principal,
        )
    assert principal is not None
    return principal


def _migrate_legacy(
    path: Path,
    events: list[dict[str, Any]],
    *,
    run_id: str,
) -> tuple[list[dict[str, Any]], Identity]:
    for event in events:
        if any(
            field in event
            for field in (
                "buyer_principal",
                "signature_protocol",
                "signature_version",
            )
        ):
            raise RunLogError("legacy run log is partially or unsafely versioned")
    _assert_secret_isolation(events)
    addresses = _legacy_addresses(events)
    if not addresses:
        raise RunLogError("legacy run log has no buyer_address to migrate")
    try:
        principals = {
            Identity(scheme=IdentityScheme.EIP191, identifier=address)
            for address in addresses
        }
    except (TypeError, ValueError) as exc:
        raise RunLogError("legacy run log contains a malformed buyer_address") from exc
    if len(principals) != 1:
        raise RunLogError("legacy run log contains conflicting buyer addresses")
    principal = next(iter(principals))
    migrated: list[dict[str, Any]] = []
    for event in events:
        if event.get("run_id") != run_id:
            raise RunLogError("legacy run-log event run_id does not match its file")
        converted = _replace_legacy_identity(event, principal)
        converted["log_version"] = RUN_LOG_VERSION
        converted["signature_protocol"] = REQUEST_PROTOCOL
        converted["buyer_principal"] = _public_principal(principal)
        migrated.append(converted)
    _validate_current(migrated, run_id=run_id)
    _write_events_atomic(path, migrated)
    return migrated, principal


def _load_versioned(
    path: Path, *, run_id: str
) -> tuple[list[dict[str, Any]], Identity]:
    events = _read_jsonl(path)
    if not events:
        raise RunLogError("run log is empty")
    versions = [event.get("log_version") for event in events]
    if all(version is None for version in versions):
        return _migrate_legacy(path, events, run_id=run_id)
    if any(version != RUN_LOG_VERSION for version in versions):
        raise RunLogError(f"unsupported or inconsistent run-log versions: {versions!r}")
    return events, _validate_current(events, run_id=run_id)


class RunLog:
    """One versioned run log bound to a canonical public buyer principal."""

    def __init__(self, run_id: str, path: Path, principal: Identity) -> None:
        self.run_id = run_id
        self.path = path
        self.principal = principal

    @classmethod
    def start(cls, *, principal: Identity, **input_fields: Any) -> RunLog:
        """Begin a fresh run without accepting or serializing signer material."""

        run_id = _new_run_id()
        path = runs_dir() / f"{run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        log = cls(run_id, path, principal)
        log.event("run_started", **input_fields)
        return log

    @classmethod
    def open(cls, run_id: str, *, signer: Signer) -> RunLog:
        """Open a recovery log only when the available signer owns it."""

        path = runs_dir() / f"{run_id}.jsonl"
        _, principal = _load_versioned(path, run_id=run_id)
        if signer.identity != principal:
            raise RunLogError("available signer does not match run-log buyer principal")
        return cls(run_id, path, principal)

    def event(self, event: str, **fields: Any) -> None:
        """Append one event while preserving version and identity invariants."""

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
            "buyer_principal": _public_principal(self.principal),
            **fields,
        }
        try:
            encoded = json.dumps(record, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise RunLogError("run-log event is not JSON serializable") from exc
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(encoded + "\n")

    def end(self, status: str, **fields: Any) -> None:
        self.event("run_ended", status=status, **fields)


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    path: Path
    started_at: str | None
    last_event: str | None
    last_event_ts: str | None
    last_status: str | None


def read_run(run_id: str, *, signer: Signer | None = None) -> list[dict[str, Any]]:
    """Read, validate, and when needed atomically migrate one run log."""

    path = runs_dir() / f"{run_id}.jsonl"
    if not path.exists():
        return []
    events, principal = _load_versioned(path, run_id=run_id)
    if signer is not None and signer.identity != principal:
        raise RunLogError("available signer does not match run-log buyer principal")
    return events


def list_runs() -> list[RunSummary]:
    """Return validated run summaries, newest first by file modification time."""

    directory = runs_dir()
    if not directory.exists():
        return []
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
        first = events[0]
        last = events[-1]
        summaries.append(
            RunSummary(
                run_id=path.stem,
                path=path,
                started_at=first.get("ts"),
                last_event=last.get("event"),
                last_event_ts=last.get("ts"),
                last_status=(
                    last.get("status") if last.get("event") == "run_ended" else None
                ),
            )
        )
    return summaries


def last_successful_step(
    run_id: str,
    *,
    signer: Signer,
) -> dict[str, Any] | None:
    """Return the last non-error stage event owned by the available signer."""

    for event in reversed(read_run(run_id, signer=signer)):
        if event.get("error"):
            continue
        if event.get("event") in ("run_started", "run_ended"):
            continue
        return event
    return None
