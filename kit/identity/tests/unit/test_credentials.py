from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_identity import (
    CredentialProviderError,
    CredentialProviderKind,
    CredentialProviderRegistry,
    CredentialReference,
    Ed25519Signer,
    EnvironmentCredentialProvider,
    IdentityScheme,
    KeyringCredentialProvider,
    SecretFileCredentialProvider,
    create_signer,
    default_credential_registry,
)
from conftest import ED25519_SEED


def _encoded_seed() -> str:
    import base64

    return base64.urlsafe_b64encode(ED25519_SEED).rstrip(b"=").decode("ascii")


def _file_reference(path: Path) -> CredentialReference:
    return CredentialReference(
        provider=CredentialProviderKind.SECRET_FILE,
        locator=str(path.absolute()),
    )


def test_registry_dispatches_only_exact_selected_provider() -> None:
    calls: list[str] = []

    class Provider:
        kind = CredentialProviderKind.ENVIRONMENT

        def load(self, reference: CredentialReference) -> str:
            calls.append(reference.locator)
            return _encoded_seed()

        def generate(self, reference: CredentialReference, *, scheme: IdentityScheme) -> None:
            raise AssertionError("not selected")

        def delete(self, reference: CredentialReference) -> None:
            raise AssertionError("not selected")

    reference = CredentialReference(
        provider=CredentialProviderKind.ENVIRONMENT,
        locator="EXACT_BUYER_SEED",
    )
    registry = CredentialProviderRegistry((Provider(),))
    assert registry.load(reference) == _encoded_seed()
    assert calls == ["EXACT_BUYER_SEED"]
    missing = CredentialReference(
        provider=CredentialProviderKind.KEYRING,
        locator="arkhai/buyer",
    )
    with pytest.raises(CredentialProviderError, match="selected provider is unavailable"):
        registry.load(missing)
    assert calls == ["EXACT_BUYER_SEED"]


def test_default_registry_does_not_import_keyring_for_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported: list[str] = []
    original = importlib.import_module

    def observing_import(name: str, package: str | None = None):
        imported.append(name)
        if name == "keyring":
            raise AssertionError("keyring must remain lazy")
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", observing_import)
    reference = CredentialReference(
        provider=CredentialProviderKind.ENVIRONMENT,
        locator="BUYER_SEED",
    )
    registry = default_credential_registry(environ={"BUYER_SEED": _encoded_seed()})
    assert registry.load(reference) == _encoded_seed()
    assert "keyring" not in imported


def test_environment_provider_reads_one_exact_name_without_fallback() -> None:
    provider = EnvironmentCredentialProvider(
        {
            "BUYER_SEED": _encoded_seed(),
            "ARKHAI_IDENTITY_CREDENTIAL": "legacy-canary",
        }
    )
    reference = CredentialReference(
        provider=CredentialProviderKind.ENVIRONMENT,
        locator="BUYER_SEED",
    )
    secret = provider.load(reference)
    assert create_signer(IdentityScheme.ED25519, secret).identity == Ed25519Signer(
        ED25519_SEED
    ).identity
    missing = reference.model_copy(update={"locator": "MISSING_SEED"})
    with pytest.raises(CredentialProviderError) as error:
        provider.load(missing)
    assert "legacy-canary" not in str(error.value)
    with pytest.raises(CredentialProviderError, match="read-only"):
        provider.generate(reference, scheme=IdentityScheme.ED25519)
    with pytest.raises(CredentialProviderError, match="read-only"):
        provider.delete(reference)


@pytest.mark.parametrize(
    ("provider", "locator"),
    (
        (CredentialProviderKind.ENVIRONMENT, "contains-dash"),
        (CredentialProviderKind.SECRET_FILE, "relative/secret"),
        (CredentialProviderKind.KEYRING, "missing-separator"),
    ),
)
def test_reference_locator_is_strict(
    provider: CredentialProviderKind,
    locator: str,
) -> None:
    with pytest.raises(ValueError):
        CredentialReference(provider=provider, locator=locator)


def test_secret_file_exact_read_generate_delete_and_permissions(tmp_path: Path) -> None:
    directory = tmp_path / "secrets"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    reference = _file_reference(directory / "buyer.seed")
    provider = SecretFileCredentialProvider()
    provider.generate(reference, scheme=IdentityScheme.ED25519)
    assert oct(Path(reference.locator).stat().st_mode & 0o777) == "0o600"
    secret = provider.load(reference)
    assert create_signer(IdentityScheme.ED25519, secret).identity.scheme is (
        IdentityScheme.ED25519
    )
    provider.delete(reference)
    assert not Path(reference.locator).exists()
    with pytest.raises(CredentialProviderError, match="missing or unsafe"):
        provider.load(reference)


def test_secret_file_preserves_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "seed"
    path.write_bytes(ED25519_SEED)
    path.chmod(0o600)
    provider = SecretFileCredentialProvider()
    assert provider.load(_file_reference(path)) == ED25519_SEED


@pytest.mark.parametrize("mode", (0o604, 0o640, 0o660, 0o666))
def test_secret_file_rejects_every_group_or_other_permission(
    tmp_path: Path,
    mode: int,
) -> None:
    path = tmp_path / "seed"
    path.write_text(_encoded_seed(), encoding="utf-8")
    path.chmod(mode)
    with pytest.raises(CredentialProviderError, match="owner-only"):
        SecretFileCredentialProvider().load(_file_reference(path))


def test_secret_file_rejects_symlink_and_non_regular_file(tmp_path: Path) -> None:
    target = tmp_path / "seed"
    target.write_text(_encoded_seed(), encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "seed-link"
    link.symlink_to(target)
    provider = SecretFileCredentialProvider()
    with pytest.raises(CredentialProviderError, match="missing or unsafe"):
        provider.load(_file_reference(link))
    directory_reference = _file_reference(tmp_path)
    with pytest.raises(CredentialProviderError, match="regular"):
        provider.load(directory_reference)


def test_secret_file_revalidates_inode_before_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "seed"
    path.write_text(_encoded_seed(), encoding="utf-8")
    path.chmod(0o600)
    real_stat = Path.stat

    def changed_stat(self: Path, *args, **kwargs):
        status = real_stat(self, *args, **kwargs)
        if self == path and kwargs.get("follow_symlinks") is False:
            return SimpleNamespace(
                st_dev=status.st_dev,
                st_ino=status.st_ino + 1,
                st_mode=status.st_mode,
                st_uid=status.st_uid,
                st_size=status.st_size,
            )
        return status

    monkeypatch.setattr(Path, "stat", changed_stat)
    with pytest.raises(CredentialProviderError, match="changed before deletion"):
        SecretFileCredentialProvider().delete(_file_reference(path))
    assert path.exists()


def test_secret_file_rejects_non_current_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "seed"
    path.write_text(_encoded_seed(), encoding="utf-8")
    path.chmod(0o600)
    real_fstat = os.fstat

    def foreign_owner(fd: int):
        status = real_fstat(fd)
        return SimpleNamespace(
            st_mode=status.st_mode,
            st_uid=os.getuid() + 1,
            st_size=status.st_size,
        )

    monkeypatch.setattr(os, "fstat", foreign_owner)
    with pytest.raises(CredentialProviderError, match="owned by current user"):
        SecretFileCredentialProvider().load(_file_reference(path))


def test_generation_failure_cleans_partial_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "secrets"
    directory.mkdir(mode=0o700)
    reference = _file_reference(directory / "seed")

    def fail_write(_fd: int, _payload: bytes) -> int:
        raise OSError("secret-canary backend detail")

    monkeypatch.setattr(os, "write", fail_write)
    with pytest.raises(OSError) as error:
        SecretFileCredentialProvider().generate(
            reference,
            scheme=IdentityScheme.ED25519,
        )
    assert "secret-canary backend detail" in str(error.value)
    assert not Path(reference.locator).exists()


def test_keyring_load_generate_delete_with_usable_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values: dict[tuple[str, str], str] = {}

    class Keyring:
        @staticmethod
        def get_keyring():
            return SimpleNamespace(priority=1)

        @staticmethod
        def get_password(service: str, entry: str) -> str | None:
            return values.get((service, entry))

        @staticmethod
        def set_password(service: str, entry: str, value: str) -> None:
            values[(service, entry)] = value

        @staticmethod
        def delete_password(service: str, entry: str) -> None:
            del values[(service, entry)]

    monkeypatch.setattr(importlib, "import_module", lambda name: Keyring)
    reference = CredentialReference(
        provider=CredentialProviderKind.KEYRING,
        locator="arkhai.market/buyer-profile",
    )
    provider = KeyringCredentialProvider()
    provider.generate(reference, scheme=IdentityScheme.ED25519)
    assert create_signer(IdentityScheme.ED25519, provider.load(reference)).identity.scheme is (
        IdentityScheme.ED25519
    )
    with pytest.raises(CredentialProviderError, match="already exists"):
        provider.generate(reference, scheme=IdentityScheme.ED25519)
    provider.delete(reference)
    with pytest.raises(CredentialProviderError, match="entry is missing"):
        provider.load(reference)


def test_keyring_unavailable_and_backend_exception_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = CredentialReference(
        provider=CredentialProviderKind.KEYRING,
        locator="arkhai.market/buyer-profile",
    )
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: SimpleNamespace(
            get_keyring=lambda: SimpleNamespace(priority=0),
        ),
    )
    with pytest.raises(CredentialProviderError, match="no usable OS keyring"):
        KeyringCredentialProvider().load(reference)

    canary = "PRIVATE-SEED-CANARY"

    class FailingKeyring:
        @staticmethod
        def get_keyring():
            return SimpleNamespace(priority=1)

        @staticmethod
        def get_password(_service: str, _entry: str) -> str:
            raise RuntimeError(canary)

    monkeypatch.setattr(importlib, "import_module", lambda name: FailingKeyring)
    with pytest.raises(CredentialProviderError) as error:
        KeyringCredentialProvider().load(reference)
    assert canary not in str(error.value)
    assert canary not in repr(error.value)


def test_reference_and_provider_errors_never_repr_secret_values() -> None:
    canary = "PRIVATE-SEED-CANARY"
    reference = CredentialReference(
        provider=CredentialProviderKind.ENVIRONMENT,
        locator="BUYER_SEED",
    )
    error = CredentialProviderError(reference, "load", "backend error")
    for value in (repr(reference), str(error), repr(error), repr(default_credential_registry())):
        assert canary not in value
        assert _encoded_seed() not in value
