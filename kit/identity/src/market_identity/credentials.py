"""Explicit buyer credential providers with no fallback or raw-value provider."""

from __future__ import annotations

import base64
import importlib
import os
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from market_identity.models import IdentityScheme
from market_identity.profiles import CredentialProviderKind, CredentialReference
from market_identity.registry import SecretMaterial

_MAX_SECRET_BYTES = 16 * 1024


class CredentialProviderError(RuntimeError):
    """A normalized provider failure that never includes secret material."""

    def __init__(
        self,
        reference: CredentialReference,
        operation: str,
        reason: str,
    ) -> None:
        self.provider = reference.provider
        self.reference_fingerprint = reference.fingerprint
        self.operation = operation
        self.reason = reason
        super().__init__(
            f"credential provider {reference.provider.value} could not {operation} "
            f"reference {reference.fingerprint}: {reason}"
        )


@runtime_checkable
class CredentialProvider(Protocol):
    """One exact credential backend selected by a tagged reference."""

    kind: CredentialProviderKind

    def load(self, reference: CredentialReference) -> bytes:
        """Load the exact referenced secret bytes without fallback or normalization."""

    def generate(
        self,
        reference: CredentialReference,
        *,
        scheme: IdentityScheme,
    ) -> None:
        """Generate a new secret exclusively at the exact reference."""

    def delete(self, reference: CredentialReference) -> None:
        """Delete the exact reference after provider-specific revalidation."""


class CredentialProviderRegistry:
    """Closed exact dispatch for approved credential providers."""

    def __init__(self, providers: tuple[CredentialProvider, ...] = ()) -> None:
        self._providers: dict[CredentialProviderKind, CredentialProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: CredentialProvider) -> None:
        if not isinstance(provider.kind, CredentialProviderKind):
            raise TypeError("credential provider kind is not approved")
        if provider.kind in self._providers:
            raise ValueError(f"credential provider {provider.kind.value} is already registered")
        self._providers[provider.kind] = provider

    def provider(self, reference: CredentialReference) -> CredentialProvider:
        try:
            return self._providers[reference.provider]
        except KeyError as exc:
            raise CredentialProviderError(
                reference,
                "resolve",
                "selected provider is unavailable",
            ) from exc

    def load(self, reference: CredentialReference) -> bytes:
        return self.provider(reference).load(reference)

    def generate(
        self,
        reference: CredentialReference,
        *,
        scheme: IdentityScheme,
    ) -> None:
        self.provider(reference).generate(reference, scheme=scheme)

    def delete(self, reference: CredentialReference) -> None:
        self.provider(reference).delete(reference)

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(kind.value for kind in self._providers))


class KeyringCredentialProvider:
    """OS keyring adapter imported lazily only when this provider is selected."""

    kind = CredentialProviderKind.KEYRING

    def load(self, reference: CredentialReference) -> bytes:
        service, entry = _keyring_parts(reference)
        keyring = self._backend(reference, "load")
        try:
            value = keyring.get_password(service, entry)
        except BaseException as exc:
            raise CredentialProviderError(reference, "load", "backend error") from exc
        if not value:
            raise CredentialProviderError(reference, "load", "entry is missing")
        return value.encode("utf-8")

    def generate(
        self,
        reference: CredentialReference,
        *,
        scheme: IdentityScheme,
    ) -> None:
        if scheme is not IdentityScheme.ED25519:
            raise CredentialProviderError(
                reference,
                "generate",
                "only Ed25519 generation is supported",
            )
        service, entry = _keyring_parts(reference)
        keyring = self._backend(reference, "generate")
        try:
            if keyring.get_password(service, entry) is not None:
                raise CredentialProviderError(
                    reference,
                    "generate",
                    "entry already exists",
                )
            value = _new_ed25519_seed()
            keyring.set_password(service, entry, value)
        except CredentialProviderError:
            raise
        except BaseException as exc:
            raise CredentialProviderError(reference, "generate", "backend error") from exc

    def delete(self, reference: CredentialReference) -> None:
        service, entry = _keyring_parts(reference)
        keyring = self._backend(reference, "delete")
        try:
            if keyring.get_password(service, entry) is None:
                raise CredentialProviderError(reference, "delete", "entry is missing")
            keyring.delete_password(service, entry)
        except CredentialProviderError:
            raise
        except BaseException as exc:
            raise CredentialProviderError(reference, "delete", "backend error") from exc

    @staticmethod
    def _backend(reference: CredentialReference, operation: str):
        try:
            keyring = importlib.import_module("keyring")
            backend = keyring.get_keyring()
            priority = getattr(backend, "priority", 0)
            if callable(priority):
                priority = priority()
            if not isinstance(priority, (int, float)) or priority <= 0:
                raise RuntimeError("unusable backend")
            return keyring
        except BaseException as exc:
            raise CredentialProviderError(
                reference,
                operation,
                "no usable OS keyring backend",
            ) from exc


class SecretFileCredentialProvider:
    """No-follow, owner-only regular-file credential storage."""

    kind = CredentialProviderKind.SECRET_FILE

    def load(self, reference: CredentialReference) -> bytes:
        fd = _open_secret_file(reference, operation="load")
        try:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_SECRET_BYTES:
                    raise CredentialProviderError(
                        reference,
                        "load",
                        "secret exceeds bounded size",
                    )
                chunks.append(chunk)
            payload = b"".join(chunks)
            if not payload:
                raise CredentialProviderError(reference, "load", "secret is empty")
            return payload
        finally:
            os.close(fd)

    def generate(
        self,
        reference: CredentialReference,
        *,
        scheme: IdentityScheme,
    ) -> None:
        if scheme is not IdentityScheme.ED25519:
            raise CredentialProviderError(
                reference,
                "generate",
                "only Ed25519 generation is supported",
            )
        path = Path(reference.locator)
        _validate_parent(path, reference, "generate")
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        if not getattr(os, "O_NOFOLLOW", 0):
            raise CredentialProviderError(
                reference,
                "generate",
                "platform lacks no-follow file support",
            )
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise CredentialProviderError(
                reference,
                "generate",
                "secret file already exists",
            ) from exc
        except OSError as exc:
            raise CredentialProviderError(
                reference,
                "generate",
                "secret file cannot be created safely",
            ) from exc
        try:
            os.fchmod(fd, 0o600)
            payload = _new_ed25519_seed().encode("ascii")
            written = 0
            while written < len(payload):
                written += os.write(fd, payload[written:])
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                path.unlink()
            except OSError:
                pass
            raise
        else:
            os.close(fd)
            _fsync_directory(path.parent)

    def delete(self, reference: CredentialReference) -> None:
        path = Path(reference.locator)
        fd = _open_secret_file(reference, operation="delete")
        try:
            opened = os.fstat(fd)
            try:
                current = path.stat(follow_symlinks=False)
            except OSError as exc:
                raise CredentialProviderError(
                    reference,
                    "delete",
                    "secret file changed before deletion",
                ) from exc
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise CredentialProviderError(
                    reference,
                    "delete",
                    "secret file changed before deletion",
                )
            try:
                path.unlink()
            except OSError as exc:
                raise CredentialProviderError(
                    reference,
                    "delete",
                    "secret file cannot be deleted safely",
                ) from exc
        finally:
            os.close(fd)
        _fsync_directory(path.parent)


class EnvironmentCredentialProvider:
    """Read-only exact environment-name credential injection."""

    kind = CredentialProviderKind.ENVIRONMENT

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else os.environ

    def load(self, reference: CredentialReference) -> bytes:
        value = self._environ.get(reference.locator)
        if not value:
            raise CredentialProviderError(
                reference,
                "load",
                "exact environment variable is missing",
            )
        return value.encode("utf-8")

    def generate(
        self,
        reference: CredentialReference,
        *,
        scheme: IdentityScheme,
    ) -> None:
        raise CredentialProviderError(
            reference,
            "generate",
            "environment provider is read-only",
        )

    def delete(self, reference: CredentialReference) -> None:
        raise CredentialProviderError(
            reference,
            "delete",
            "environment provider is read-only",
        )


def default_credential_registry(
    *,
    environ: Mapping[str, str] | None = None,
) -> CredentialProviderRegistry:
    """Return all approved providers without initializing any external backend."""

    return CredentialProviderRegistry(
        (
            KeyringCredentialProvider(),
            SecretFileCredentialProvider(),
            EnvironmentCredentialProvider(environ),
        )
    )


def _keyring_parts(reference: CredentialReference) -> tuple[str, str]:
    if reference.provider is not CredentialProviderKind.KEYRING:
        raise CredentialProviderError(reference, "resolve", "provider kind mismatch")
    service, entry = reference.locator.split("/", 1)
    return service, entry


def _open_secret_file(reference: CredentialReference, *, operation: str) -> int:
    if reference.provider is not CredentialProviderKind.SECRET_FILE:
        raise CredentialProviderError(reference, operation, "provider kind mismatch")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise CredentialProviderError(
            reference,
            operation,
            "platform lacks no-follow file support",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow
    try:
        fd = os.open(reference.locator, flags)
    except OSError as exc:
        raise CredentialProviderError(
            reference,
            operation,
            "secret file is missing or unsafe",
        ) from exc
    try:
        status = os.fstat(fd)
        if not stat.S_ISREG(status.st_mode):
            raise CredentialProviderError(
                reference,
                operation,
                "secret file must be regular",
            )
        if status.st_uid != os.getuid():
            raise CredentialProviderError(
                reference,
                operation,
                "secret file must be owned by current user",
            )
        if stat.S_IMODE(status.st_mode) & 0o077:
            raise CredentialProviderError(
                reference,
                operation,
                "secret file must have owner-only permissions",
            )
        if status.st_size > _MAX_SECRET_BYTES:
            raise CredentialProviderError(
                reference,
                operation,
                "secret exceeds bounded size",
            )
        return fd
    except BaseException:
        os.close(fd)
        raise


def _validate_parent(
    path: Path,
    reference: CredentialReference,
    operation: str,
) -> None:
    try:
        status = path.parent.stat()
    except OSError as exc:
        raise CredentialProviderError(
            reference,
            operation,
            "secret directory is missing",
        ) from exc
    if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.getuid():
        raise CredentialProviderError(
            reference,
            operation,
            "secret directory must be current-user owned",
        )
    if stat.S_IMODE(status.st_mode) & 0o022:
        raise CredentialProviderError(
            reference,
            operation,
            "secret directory must deny group/other writes",
        )


def _new_ed25519_seed() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
