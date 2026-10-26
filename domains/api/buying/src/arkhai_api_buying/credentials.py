"""Where a buyer keeps a delivered bearer credential, and the run log that never records its secret.

See openspec/specs/buyer-orchestration/spec.md#requirement-buyer-evidence-is-separate-from-private-delivery.
"""

from __future__ import annotations

import errno
import json
import os
import re
import secrets
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core_buyer.negotiation_client import AuthenticatedHTTPError
from core_buyer.run_log import RunIdentity, RunLog, RunLogError, runs_dir

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class CredentialStoreError(RuntimeError):
    """The store refused or failed an operation; the message never carries a secret."""


class CredentialStore(Protocol):
    """Keeps one run's delivered credential under a reference that names ``scheme``."""

    scheme: str

    def reference(self, run_id: str) -> str: ...

    def location(self, reference: str) -> str: ...

    def save(self, run_id: str, credentials: Mapping[str, Any]) -> str: ...

    def load(self, reference: str) -> dict[str, Any] | None: ...


def _checked_run_id(run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id):
        raise CredentialStoreError(f"run id {run_id!r} is not a plain file name")
    return run_id


def _open_component(parent: int, name: str, path: Path, *, create: bool) -> int | None:
    try:
        return os.open(name, _DIRECTORY, dir_fd=parent)
    except FileNotFoundError:
        if not create:
            return None
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise CredentialStoreError(f"{path} is a symbolic link or not a directory") from None
        raise CredentialStoreError(f"{path} cannot be opened") from None
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
    except FileExistsError:
        pass
    except OSError:
        raise CredentialStoreError(f"{path} cannot be created") from None
    return _open_component(parent, name, path, create=False)


class FileCredentialStore:
    """One ``0600`` JSON file per run in a ``0700`` directory beside the run logs.

    Every directory from ``/`` down is opened relative to its parent without
    following links and checked before it is used, so swapping a component for
    a link between the check and the write cannot redirect it. Directories
    above the store must be the user's or root's and closed to others' writes
    (or sticky); the store's own directories must be the user's.
    """

    scheme = "file"

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        # Resolved per call: the buyer's XDG state root is read when a command runs.
        return self._directory or runs_dir().parent / "buy-credentials"

    def _layout(self) -> tuple[Path, tuple[str, ...]]:
        """The trusted prefix, resolved once, and the store's own components below it."""
        if self._directory is not None:
            return Path(os.path.realpath(self._directory.parent)), (self._directory.name,)
        arkhai = runs_dir().parent
        return Path(os.path.realpath(arkhai.parent)), (arkhai.name, "buy-credentials")

    def _open_directory(self, *, create: bool) -> int | None:
        prefix, own = self._layout()
        uid = os.getuid()
        fd = os.open("/", _DIRECTORY)
        path = Path("/")
        try:
            for index, name in enumerate((*prefix.parts[1:], *own)):
                path = path / name
                child = _open_component(fd, name, path, create=create)
                os.close(fd)
                fd = -1
                if child is None:
                    return None
                fd = child
                info = os.fstat(fd)
                if index >= len(prefix.parts) - 1:
                    if info.st_uid != uid:
                        raise CredentialStoreError(f"{path} is not owned by this user")
                    if info.st_mode & 0o022:
                        raise CredentialStoreError(f"{path} is writable by another user")
                elif info.st_uid not in (0, uid) or (
                    info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX
                ):
                    raise CredentialStoreError(f"{path} is writable by another user")
            if stat.S_IMODE(os.fstat(fd).st_mode) & 0o077:
                try:
                    os.fchmod(fd, 0o700)
                except OSError:
                    raise CredentialStoreError(f"{path} cannot be made private") from None
            opened, fd = fd, -1
            return opened
        finally:
            if fd >= 0:
                os.close(fd)

    def reference(self, run_id: str) -> str:
        return f"{self.scheme}:{_checked_run_id(run_id)}"

    def _run_id(self, reference: str) -> str:
        scheme, _, run_id = reference.partition(":")
        if scheme != self.scheme:
            raise CredentialStoreError(f"reference {reference!r} is not held by the {self.scheme} store")
        return _checked_run_id(run_id)

    def location(self, reference: str) -> str:
        return str(self.directory / f"{self._run_id(reference)}.json")

    def save(self, run_id: str, credentials: Mapping[str, Any]) -> str:
        reference = self.reference(run_id)
        name = f"{run_id}.json"
        payload = json.dumps({"run_id": run_id, "credentials": dict(credentials)}).encode()
        directory = self._open_directory(create=True)
        assert directory is not None
        temporary = f".{name}.{secrets.token_hex(8)}.tmp"
        try:
            try:
                existing = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                existing = None
            if existing is not None and stat.S_ISLNK(existing.st_mode):
                raise CredentialStoreError(f"credential file {self.location(reference)} is a symbolic link")
            fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                dir_fd=directory,
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
            except BaseException:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except OSError:
                    pass
                raise
            try:
                os.fsync(directory)
            except OSError:
                # The record is already in place under its name.
                pass
            self._sweep(directory, name)
        finally:
            os.close(directory)
        return reference

    @staticmethod
    def _sweep(directory: int, name: str) -> None:
        """Remove temporary records an interrupted save of ``name`` left behind."""
        for entry in os.listdir(directory):
            if entry.startswith(f".{name}.") and entry.endswith(".tmp"):
                try:
                    os.unlink(entry, dir_fd=directory)
                except OSError:
                    pass

    def load(self, reference: str) -> dict[str, Any] | None:
        run_id = self._run_id(reference)
        location = self.location(reference)
        directory = self._open_directory(create=False)
        if directory is None:
            return None
        try:
            try:
                fd = os.open(f"{run_id}.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                return None
            except OSError:
                raise CredentialStoreError(f"credential file {location} cannot be opened safely") from None
        finally:
            os.close(directory)
        try:
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise CredentialStoreError(f"credential file {location} is not a regular file")
                if info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise CredentialStoreError(
                        f"credential file {location} is not private to this user"
                    )
                credentials = json.loads(stream.read())["credentials"]
            if not isinstance(credentials, dict):
                raise TypeError("credentials is not an object")
        except CredentialStoreError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise CredentialStoreError(f"credential file {location} is unreadable") from None
        return credentials


_SECRET_TEXT = re.compile(r"""(["']secret["']\s*:\s*)(["'])(?:(?!\2).)*\2?""")


def public_text(text: str, known: Iterable[str] = ()) -> str:
    """``text`` with any quoted ``secret`` value, and each ``known`` secret, replaced."""
    text = _SECRET_TEXT.sub(r"\1\2[redacted]\2", text)
    for secret in known:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def error_text(exc: BaseException, known: Iterable[str] = ()) -> str:
    """What a buyer may log or print of ``exc``: a seller's error body is never quoted."""
    if isinstance(exc, AuthenticatedHTTPError):
        marker = f" -> authenticated HTTP {exc.status_code}"
        head, found, _body = str(exc).partition(marker)
        return public_text(head + marker if found else f"authenticated HTTP {exc.status_code}", known)
    return public_text(str(exc), known)


def _public_credentials(credentials: Mapping[str, Any], known: Iterable[str]) -> dict[str, Any]:
    return {key: public_fields(value, known) for key, value in credentials.items() if key != "secret"}


def public_fields(value: Any, known: Iterable[str] = ()) -> Any:
    """``value`` with every ``tenant_credentials`` stripped of its secret and every string redacted."""
    known = tuple(known)
    if isinstance(value, Mapping):
        return {
            key: _public_credentials(child, known)
            if key == "tenant_credentials" and isinstance(child, Mapping)
            else public_fields(child, known)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [public_fields(child, known) for child in value]
    if isinstance(value, str):
        return public_text(value, known)
    return value


def delivered_secrets(value: Any) -> set[str]:
    """Every ``tenant_credentials`` secret ``value`` carries, at any depth."""
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "tenant_credentials" and isinstance(child, Mapping):
                secret = child.get("secret")
                if isinstance(secret, str) and secret:
                    found.add(secret)
            found |= delivered_secrets(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            found |= delivered_secrets(child)
    return found


class DeliveryRunLog(RunLog):
    """A run log whose events never record a delivered credential's secret, structured or in text."""

    def __init__(self, run_id: str, path: Path, identity: RunIdentity) -> None:
        super().__init__(run_id, path, identity)
        self.secrets: set[str] = set()

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
        delivered = delivered_secrets(fields)
        self.secrets |= delivered
        try:
            super().event(event, **public_fields(fields, self.secrets))
        except (RunLogError, OSError):
            # A body carrying the key must not stop the flow before the key is
            # saved and shown; the delivery's own record reports a failing log.
            if not delivered:
                raise


UNSAVED_EXIT = 8
"""The exit status of a run whose delivered secret the store could not save."""

UNRECORDED_EXIT = 9
"""The exit status of a run whose key was saved but whose run log could not record it."""

_RECORDED = ("key_id", "base_url", "balance")


@dataclass(frozen=True)
class Delivery:
    """A delivered credential and where it was kept; ``reference`` is ``None`` when nothing was saved."""

    credentials: Mapping[str, Any]
    reference: str | None
    location: str | None = None
    unsaved: bool = False
    unrecorded: bool = False


def record_delivery(
    log: RunLog, credentials: Any, store: CredentialStore,
) -> Delivery | None:
    """Save a delivered secret and record its non-secret fields and reference.

    A run-log write that fails here never hides the key: the disk that refused
    one write may refuse the next, and the key must still reach the terminal.
    """
    if not isinstance(credentials, Mapping) or not credentials:
        return None
    fields = {key: credentials[key] for key in _RECORDED if credentials.get(key) is not None}
    if not credentials.get("secret"):
        log.event("credentials_delivered", **fields)
        return Delivery(credentials, None)
    try:
        reference = store.save(log.run_id, credentials)
    except (CredentialStoreError, OSError) as exc:
        try:
            log.event("credentials_unsaved", **fields, error=type(exc).__name__)
        except (RunLogError, OSError):
            pass
        return Delivery(credentials, None, unsaved=True)
    location = store.location(reference)
    try:
        log.event("credentials_delivered", **fields, delivery_ref=reference)
    except (RunLogError, OSError):
        return Delivery(credentials, reference, location, unrecorded=True)
    return Delivery(credentials, reference, location)


def end_run(log: RunLog, delivery: Delivery | None, status: str, **fields: Any) -> Delivery | None:
    """End the run; a run that delivered a secret still reaches the panel if its log cannot be written."""
    try:
        log.end(status, **fields)
    except (RunLogError, OSError):
        if delivery is None or delivery.reference is None and not delivery.unsaved:
            raise
        if delivery.reference is not None:
            return Delivery(delivery.credentials, delivery.reference, delivery.location, unrecorded=True)
    return delivery
