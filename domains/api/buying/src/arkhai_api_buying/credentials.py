"""Where a buyer keeps a delivered bearer credential, and the run log that never records its secret.

See openspec/specs/buyer-orchestration/spec.md#requirement-buyer-evidence-is-separate-from-private-delivery.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core_buyer.run_log import RunIdentity, RunLog, RunLogError, runs_dir

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class CredentialStoreError(RuntimeError):
    """The store refused or failed an operation; the message never carries a secret."""


class CredentialStore(Protocol):
    """Keeps one run's delivered credential; ``save`` returns a reference naming ``scheme``."""

    scheme: str

    def save(self, run_id: str, credentials: Mapping[str, Any]) -> str: ...

    def load(self, reference: str) -> dict[str, Any] | None: ...


def _checked_run_id(run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id):
        raise CredentialStoreError(f"run id {run_id!r} is not a plain file name")
    return run_id


class FileCredentialStore:
    """One ``0600`` JSON file per run in a ``0700`` directory beside the run logs."""

    scheme = "file"

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        # Resolved per call: the buyer's XDG state root is read when a command runs.
        return self._directory or runs_dir().parent / "buy-credentials"

    def _path(self, run_id: str) -> Path:
        return self.directory / f"{_checked_run_id(run_id)}.json"

    def _private_directory(self) -> Path:
        directory = self.directory
        if directory.is_symlink():
            raise CredentialStoreError(f"credential directory {directory} is a symbolic link")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        return directory

    def save(self, run_id: str, credentials: Mapping[str, Any]) -> str:
        path = self._path(run_id)
        directory = self._private_directory()
        if path.is_symlink():
            raise CredentialStoreError(f"credential file {path} is a symbolic link")
        payload = json.dumps({"run_id": run_id, "credentials": dict(credentials)}).encode()
        fd, temporary_name = tempfile.mkstemp(dir=directory, prefix=f".{path.name}.", suffix=".tmp")
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return f"{self.scheme}:{run_id}"

    def load(self, reference: str) -> dict[str, Any] | None:
        scheme, _, run_id = reference.partition(":")
        if scheme != self.scheme:
            raise CredentialStoreError(f"reference {reference!r} is not held by the {self.scheme} store")
        path = self._path(run_id)
        if self.directory.is_symlink():
            raise CredentialStoreError(f"credential directory {self.directory} is a symbolic link")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CredentialStoreError(f"credential file {path} cannot be opened safely") from exc
        try:
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise CredentialStoreError(f"credential file {path} is not a regular file")
                credentials = json.loads(stream.read())["credentials"]
            if not isinstance(credentials, dict):
                raise TypeError("credentials is not an object")
        except (OSError, ValueError, KeyError, TypeError):
            raise CredentialStoreError(f"credential file {path} is unreadable") from None
        return credentials


def _public_credentials(credentials: Mapping[str, Any]) -> dict[str, Any]:
    return {key: public_fields(value) for key, value in credentials.items() if key != "secret"}


def public_fields(value: Any) -> Any:
    """``value`` with every ``tenant_credentials`` mapping, at any depth, stripped of its secret."""
    if isinstance(value, Mapping):
        return {
            key: _public_credentials(child)
            if key == "tenant_credentials" and isinstance(child, Mapping)
            else public_fields(child)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [public_fields(child) for child in value]
    return value


class DeliveryRunLog(RunLog):
    """A run log whose events never record a delivered credential's secret."""

    @classmethod
    def of(cls, log: RunLog) -> DeliveryRunLog:
        return cls(
            log.run_id,
            log.path,
            RunIdentity(
                profile_id=log.profile_id,
                principal=log.principal,
                signature_version=log.signature_version,
            ),
        )

    def event(self, event: str, **fields: Any) -> None:
        super().event(event, **public_fields(fields))


UNSAVED_EXIT = 8
"""The exit status of a run whose delivered secret the store could not save."""

_RECORDED = ("key_id", "base_url", "balance")


@dataclass(frozen=True)
class Delivery:
    """A delivered credential and where it was kept; ``reference`` is ``None`` when nothing was saved."""

    credentials: Mapping[str, Any]
    reference: str | None
    unsaved: bool = False


def record_delivery(
    log: RunLog, credentials: Any, store: CredentialStore,
) -> Delivery | None:
    """Save a delivered secret and record its non-secret fields and reference."""
    if not isinstance(credentials, Mapping) or not credentials:
        return None
    fields = {key: credentials[key] for key in _RECORDED if credentials.get(key) is not None}
    if not credentials.get("secret"):
        log.event("credentials_delivered", **fields)
        return Delivery(credentials, None)
    try:
        reference = store.save(log.run_id, credentials)
    except (CredentialStoreError, OSError) as exc:
        # The disk that refused the store may refuse the run log too; the key
        # must still reach the buyer's terminal.
        try:
            log.event("credentials_unsaved", **fields, error=type(exc).__name__)
        except (RunLogError, OSError):
            pass
        return Delivery(credentials, None, unsaved=True)
    log.event("credentials_delivered", **fields, delivery_ref=reference)
    return Delivery(credentials, reference)


def end_run(log: RunLog, delivery: Delivery | None, status: str, **fields: Any) -> None:
    """End the run; a run whose key went unsaved still reaches the panel if its log cannot be written."""
    try:
        log.end(status, **fields)
    except (RunLogError, OSError):
        if delivery is None or not delivery.unsaved:
            raise
