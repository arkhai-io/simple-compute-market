"""Strict local buyer-profile metadata and its atomic JSON repository."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from market_identity.canonical import canonical_rotation_bytes
from market_identity.models import Identity, RotationRequest
from market_identity.verification import verify_rotation

PROFILE_STORE_VERSION = 1
PROFILE_ROTATION_AUTHORITY = "arkhai.local-buyer-profile.v1"
_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,63}$")
_ENVIRONMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_ENV_LOCATOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_KEYRING_LOCATOR = re.compile(r"^[A-Za-z0-9_.-]{1,128}/[A-Za-z0-9_.:@-]{1,256}$")
_FORBIDDEN_BINDING_MARKERS = (
    "client_secret",
    "paymentmethod",
    "payment_method",
    "mandate",
    "bank_account",
    "card_number",
    "action_url",
    "checkout_url",
)
_FORBIDDEN_BINDING_PREFIXES = (
    "cus_",
    "pm_",
    "pi_",
    "seti_",
    "ch_",
    "src_",
    "ba_",
)


class ProfileModel(BaseModel):
    """Closed immutable base for local profile metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CredentialProviderKind(str, Enum):
    """The complete approved credential-provider vocabulary."""

    KEYRING = "keyring.v1"
    SECRET_FILE = "secret_file.v1"
    ENVIRONMENT = "environment.v1"


CredentialProviderField = Annotated[CredentialProviderKind, Field(strict=False)]


class CredentialReference(ProfileModel):
    """A provider tag plus bounded provider-owned locator, never a secret."""

    provider: CredentialProviderField
    locator: str = Field(min_length=1, max_length=4096)

    @field_validator("locator")
    @classmethod
    def validate_locator(cls, value: str, info: ValidationInfo) -> str:
        if "\x00" in value or value != value.strip():
            raise ValueError(f"{info.field_name} is not a bounded locator")
        return value

    @model_validator(mode="after")
    def validate_provider_locator(self) -> CredentialReference:
        if self.provider is CredentialProviderKind.ENVIRONMENT:
            if not _ENV_LOCATOR.fullmatch(self.locator):
                raise ValueError("environment locator must be one exact variable name")
        elif self.provider is CredentialProviderKind.SECRET_FILE:
            path = Path(self.locator)
            if not path.is_absolute() or len(path.parts) < 2:
                raise ValueError("secret-file locator must be an absolute path")
            if any(part in ("", ".", "..") for part in path.parts[1:]):
                raise ValueError("secret-file locator must be normalized")
        elif not _KEYRING_LOCATOR.fullmatch(self.locator):
            raise ValueError("keyring locator must be service/entry")
        return self

    @property
    def fingerprint(self) -> str:
        payload = f"{self.provider.value}\x00{self.locator}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def redacted(self) -> dict[str, str]:
        return {"provider": self.provider.value, "reference": self.fingerprint}

    def __repr__(self) -> str:
        return (
            "CredentialReference(provider="
            f"{self.provider.value!r}, reference={self.fingerprint!r})"
        )


class PrincipalState(str, Enum):
    PRIMARY = "primary"
    RETAINED = "retained"
    RETIRED = "retired"


PrincipalStateField = Annotated[PrincipalState, Field(strict=False)]


class ProfileState(str, Enum):
    ACTIVE = "active"
    RETIRED = "retired"


ProfileStateField = Annotated[ProfileState, Field(strict=False)]


class AuthorityBindingState(str, Enum):
    ACTIVE = "active"
    ROTATION_PENDING = "rotation_pending"
    RETIRED = "retired"


AuthorityBindingStateField = Annotated[AuthorityBindingState, Field(strict=False)]


class ProfilePrincipal(ProfileModel):
    """One canonical principal and its exact retained credential reference."""

    principal: Identity
    credential_reference: CredentialReference
    state: PrincipalStateField
    added_at: str = Field(min_length=20, max_length=64)
    overlap_until: str | None = Field(default=None, min_length=20, max_length=64)
    rotation_nonce: str | None = Field(default=None, min_length=1, max_length=128)
    rotation_intent_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_rotation_metadata(self) -> ProfilePrincipal:
        values = (self.overlap_until, self.rotation_nonce, self.rotation_intent_hash)
        if self.state is PrincipalState.PRIMARY and any(value is not None for value in values):
            raise ValueError("primary principal cannot carry predecessor rotation metadata")
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("rotation metadata must be complete")
        return self

    def redacted(self) -> dict[str, Any]:
        value = self.model_dump(mode="json", exclude={"credential_reference"})
        value["credential_reference"] = self.credential_reference.redacted()
        return value


class AuthorityPayerBinding(ProfileModel):
    """Provider-neutral opaque hosted payer ownership metadata."""

    authority_id: str = Field(min_length=1, max_length=256)
    environment: str = Field(min_length=1, max_length=64)
    binding_ref: str = Field(min_length=8, max_length=512)
    bound_principal: Identity
    state: AuthorityBindingStateField = AuthorityBindingState.ACTIVE

    @field_validator("authority_id")
    @classmethod
    def validate_authority(cls, value: str) -> str:
        if not _TOKEN.fullmatch(value):
            raise ValueError("authority_id must be a bounded public token")
        return value

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        if not _ENVIRONMENT.fullmatch(value):
            raise ValueError("environment must be a bounded public token")
        return value

    @field_validator("binding_ref")
    @classmethod
    def reject_provider_values(cls, value: str) -> str:
        lowered = value.lower()
        if (
            value != value.strip()
            or "\x00" in value
            or "://" in value
            or any(marker in lowered for marker in _FORBIDDEN_BINDING_MARKERS)
            or any(lowered.startswith(prefix) for prefix in _FORBIDDEN_BINDING_PREFIXES)
        ):
            raise ValueError("binding_ref must be an opaque provider-neutral reference")
        return value


class BuyerProfile(ProfileModel):
    """One durable local buyer identity aggregate."""

    profile_id: uuid.UUID
    name: str = Field(min_length=1, max_length=64)
    state: ProfileStateField = ProfileState.ACTIVE
    primary_principal: Identity
    principal_history: tuple[ProfilePrincipal, ...] = Field(min_length=1)
    authority_payer_bindings: tuple[AuthorityPayerBinding, ...] = ()
    created_at: str = Field(min_length=20, max_length=64)
    updated_at: str = Field(min_length=20, max_length=64)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _PROFILE_NAME.fullmatch(value):
            raise ValueError("profile name must be a bounded display name")
        return value

    @model_validator(mode="after")
    def validate_aggregate(self) -> BuyerProfile:
        principal_keys = [_identity_key(item.principal) for item in self.principal_history]
        if len(principal_keys) != len(set(principal_keys)):
            raise ValueError("profile principal history contains duplicates")
        primary = [
            item
            for item in self.principal_history
            if item.state is PrincipalState.PRIMARY
        ]
        if self.state is ProfileState.ACTIVE:
            if len(primary) != 1 or primary[0].principal != self.primary_principal:
                raise ValueError("active profile must have exactly one matching primary")
        elif primary:
            raise ValueError("retired profile cannot retain a primary principal")
        binding_keys = [
            (binding.authority_id, binding.environment)
            for binding in self.authority_payer_bindings
        ]
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("authority/environment binding must be unique")
        known_principals = set(principal_keys)
        for binding in self.authority_payer_bindings:
            if _identity_key(binding.bound_principal) not in known_principals:
                raise ValueError("authority binding principal is not in profile history")
            if (
                binding.state is not AuthorityBindingState.RETIRED
                and self.state is ProfileState.RETIRED
            ):
                raise ValueError("retired profile cannot retain an active binding")
        return self

    def history_entry(self, principal: Identity) -> ProfilePrincipal:
        for entry in self.principal_history:
            if entry.principal == principal:
                return entry
        raise ProfileStoreError("principal is not present in the profile history")

    def redacted(self, *, selected: bool = False) -> dict[str, Any]:
        value = self.model_dump(
            mode="json",
            exclude={"principal_history": {"__all__": {"credential_reference"}}},
        )
        value["principal_history"] = [item.redacted() for item in self.principal_history]
        value["selected"] = selected
        return value


class ProfileStore(ProfileModel):
    """The complete versioned buyer-profile metadata document."""

    schema_version: Literal[PROFILE_STORE_VERSION] = PROFILE_STORE_VERSION
    revision: int = Field(ge=0)
    selected_profile_id: uuid.UUID | None = None
    profiles: tuple[BuyerProfile, ...] = ()

    @model_validator(mode="after")
    def validate_store(self) -> ProfileStore:
        ids = [profile.profile_id for profile in self.profiles]
        names = [profile.name.casefold() for profile in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("profile IDs must be globally unique")
        if len(names) != len(set(names)):
            raise ValueError("profile names must be globally unique")
        if self.selected_profile_id is not None:
            selected = [
                profile
                for profile in self.profiles
                if profile.profile_id == self.selected_profile_id
            ]
            if len(selected) != 1 or selected[0].state is not ProfileState.ACTIVE:
                raise ValueError("selected profile must identify one active profile")
        active_principals: list[tuple[str, str]] = []
        for profile in self.profiles:
            if profile.state is not ProfileState.ACTIVE:
                continue
            active_principals.extend(
                _identity_key(item.principal)
                for item in profile.principal_history
                if item.state is not PrincipalState.RETIRED
            )
        if len(active_principals) != len(set(active_principals)):
            raise ValueError("an active principal may belong to only one profile")
        return self

    @classmethod
    def empty(cls) -> ProfileStore:
        return cls(revision=0)

    def profile(self, profile: uuid.UUID | str) -> BuyerProfile:
        wanted = _profile_id(profile)
        for candidate in self.profiles:
            if candidate.profile_id == wanted:
                return candidate
        raise ProfileStoreError("buyer profile does not exist")

    def profile_named(self, name: str) -> BuyerProfile:
        for candidate in self.profiles:
            if candidate.name.casefold() == name.casefold():
                return candidate
        raise ProfileStoreError("buyer profile does not exist")

    def selected(self) -> BuyerProfile:
        if self.selected_profile_id is None:
            raise ProfileStoreError(
                "no active buyer profile is selected; create, import, or select one"
            )
        return self.profile(self.selected_profile_id)

    def redacted(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "selected_profile_id": (
                str(self.selected_profile_id)
                if self.selected_profile_id is not None
                else None
            ),
            "profiles": [
                profile.redacted(selected=profile.profile_id == self.selected_profile_id)
                for profile in self.profiles
            ],
        }


class ProfileStoreError(ValueError):
    """Raised for unsafe, conflicting, or malformed profile metadata."""


class ProfileRevisionConflict(ProfileStoreError):
    """Raised when a caller attempts to replace a stale store revision."""


class ProfileRetentionError(ProfileStoreError):
    """Raised when recoverable history or an authority binding blocks lifecycle work."""

    def __init__(self, message: str, *, blockers: Iterable[str] = ()) -> None:
        self.blockers = tuple(sorted(set(blockers)))
        suffix = f": {', '.join(self.blockers)}" if self.blockers else ""
        super().__init__(message + suffix)


class ProfileRepository:
    """Serialized, revisioned, fsynced atomic access to one profile document."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute():
            raise ValueError("profile-store path must be absolute")
        self.path = path
        self.lock_path = path.with_name(f".{path.name}.lock")

    def load(self) -> ProfileStore:
        if not self.path.exists():
            return ProfileStore.empty()
        return self._load_existing()

    def replace(self, candidate: ProfileStore, *, expected_revision: int) -> ProfileStore:
        self._ensure_directory()
        lock_fd = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            current = self._load_existing() if self.path.exists() else ProfileStore.empty()
            if current.revision != expected_revision:
                raise ProfileRevisionConflict(
                    f"profile-store revision changed from {expected_revision} "
                    f"to {current.revision}"
                )
            if candidate.revision != expected_revision + 1:
                raise ProfileRevisionConflict(
                    "candidate revision must be exactly one greater than current"
                )
            validated = ProfileStore.model_validate(candidate.model_dump(mode="python"))
            self._write_atomic(validated)
            return validated
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def update(
        self,
        transform: Callable[[ProfileStore], ProfileStore],
        *,
        expected_revision: int | None = None,
    ) -> ProfileStore:
        self._ensure_directory()
        lock_fd = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            current = self._load_existing() if self.path.exists() else ProfileStore.empty()
            if expected_revision is not None and current.revision != expected_revision:
                raise ProfileRevisionConflict(
                    f"profile-store revision changed from {expected_revision} "
                    f"to {current.revision}"
                )
            candidate = transform(current)
            if candidate.revision != current.revision + 1:
                raise ProfileRevisionConflict("profile-store update did not advance revision")
            validated = ProfileStore.model_validate(candidate.model_dump(mode="python"))
            self._write_atomic(validated)
            return validated
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def _ensure_directory(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = self.path.parent.stat()
        if directory.st_uid != os.getuid():
            raise ProfileStoreError("profile-store directory must be owned by current user")
        if stat.S_IMODE(directory.st_mode) & 0o022:
            raise ProfileStoreError("profile-store directory must deny group/other writes")

    def _load_existing(self) -> ProfileStore:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not nofollow:
            raise ProfileStoreError("platform does not support no-follow profile reads")
        try:
            fd = os.open(self.path, flags | nofollow)
        except (OSError, ValueError) as exc:
            raise ProfileStoreError("profile store cannot be opened safely") from exc
        try:
            status = os.fstat(fd)
            if not stat.S_ISREG(status.st_mode):
                raise ProfileStoreError("profile store must be a regular file")
            if status.st_uid != os.getuid():
                raise ProfileStoreError("profile store must be owned by current user")
            if stat.S_IMODE(status.st_mode) & 0o077:
                raise ProfileStoreError("profile store must have owner-only permissions")
            if status.st_size > 4 * 1024 * 1024:
                raise ProfileStoreError("profile store exceeds the bounded size")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(fd)
        try:
            payload = b"".join(chunks)
            return ProfileStore.model_validate_json(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ProfileStoreError("profile store is malformed or unsupported") from exc

    def _write_atomic(self, candidate: ProfileStore) -> None:
        payload = json.dumps(
            candidate.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


def new_profile(
    *,
    name: str,
    principal: Identity,
    credential_reference: CredentialReference,
    now: datetime | None = None,
) -> BuyerProfile:
    instant = _iso(now)
    entry = ProfilePrincipal(
        principal=principal,
        credential_reference=credential_reference,
        state=PrincipalState.PRIMARY,
        added_at=instant,
    )
    return BuyerProfile(
        profile_id=uuid.uuid4(),
        name=name,
        primary_principal=principal,
        principal_history=(entry,),
        created_at=instant,
        updated_at=instant,
    )


def add_profile(
    store: ProfileStore,
    profile: BuyerProfile,
    *,
    select: bool | None = None,
) -> ProfileStore:
    if select is None:
        select = not store.profiles
    selected = profile.profile_id if select else store.selected_profile_id
    return _next_store(store, profiles=(*store.profiles, profile), selected=selected)


def rename_profile(
    store: ProfileStore,
    profile_id: uuid.UUID | str,
    name: str,
    *,
    now: datetime | None = None,
) -> ProfileStore:
    profile = store.profile(profile_id)
    replacement = profile.model_copy(update={"name": name, "updated_at": _iso(now)})
    return _replace_profile(store, replacement)


def select_profile(store: ProfileStore, profile_id: uuid.UUID | str) -> ProfileStore:
    profile = store.profile(profile_id)
    if profile.state is not ProfileState.ACTIVE:
        raise ProfileStoreError("retired buyer profile cannot be selected")
    if store.selected_profile_id == profile.profile_id:
        return store
    return _next_store(store, profiles=store.profiles, selected=profile.profile_id)


def rotate_profile(
    store: ProfileStore,
    profile_id: uuid.UUID | str,
    *,
    request: RotationRequest,
    replacement_credential: CredentialReference,
    now: datetime | None = None,
) -> ProfileStore:
    profile = store.profile(profile_id)
    if profile.state is not ProfileState.ACTIVE:
        raise ProfileStoreError("retired buyer profile cannot rotate")
    if request.intent.subject != str(profile.profile_id):
        raise ProfileStoreError("rotation subject does not match profile ID")
    if request.intent.authority != PROFILE_ROTATION_AUTHORITY:
        raise ProfileStoreError("rotation authority does not match local profile contract")
    if request.intent.current != profile.primary_principal:
        raise ProfileStoreError("rotation current principal is not the profile primary")
    timestamp = now or datetime.now(timezone.utc)
    result = verify_rotation(request, now=int(timestamp.timestamp()))
    if not result.current_valid or not result.replacement_valid or result.expired:
        raise ProfileStoreError("rotation requires valid current and replacement proofs")
    for candidate in store.profiles:
        for entry in candidate.principal_history:
            if (
                entry.principal == request.intent.replacement
                and entry.state is not PrincipalState.RETIRED
                and candidate.profile_id != profile.profile_id
            ):
                raise ProfileStoreError("replacement principal belongs to another profile")
    digest = hashlib.sha256(canonical_rotation_bytes(request.intent)).hexdigest()
    overlap_until = _iso(timestamp + timedelta(seconds=request.intent.overlap_seconds))
    history: list[ProfilePrincipal] = []
    replacement_found = False
    for entry in profile.principal_history:
        if entry.principal == profile.primary_principal:
            history.append(
                entry.model_copy(
                    update={
                        "state": PrincipalState.RETAINED,
                        "overlap_until": overlap_until,
                        "rotation_nonce": request.intent.nonce,
                        "rotation_intent_hash": digest,
                    }
                )
            )
        elif entry.principal == request.intent.replacement:
            replacement_found = True
            if entry.state is not PrincipalState.RETIRED:
                raise ProfileStoreError("replacement principal is already retained")
            history.append(
                entry.model_copy(
                    update={
                        "credential_reference": replacement_credential,
                        "state": PrincipalState.PRIMARY,
                        "overlap_until": None,
                        "rotation_nonce": None,
                        "rotation_intent_hash": None,
                    }
                )
            )
        else:
            history.append(entry)
    if not replacement_found:
        history.append(
            ProfilePrincipal(
                principal=request.intent.replacement,
                credential_reference=replacement_credential,
                state=PrincipalState.PRIMARY,
                added_at=_iso(timestamp),
            )
        )
    replacement = profile.model_copy(
        update={
            "primary_principal": request.intent.replacement,
            "principal_history": tuple(history),
            "updated_at": _iso(timestamp),
        }
    )
    return _replace_profile(store, replacement)


def retire_principal(
    store: ProfileStore,
    profile_id: uuid.UUID | str,
    principal: Identity,
    *,
    recoverable_run_ids: Iterable[str] = (),
    now: datetime | None = None,
) -> ProfileStore:
    profile = store.profile(profile_id)
    entry = profile.history_entry(principal)
    if entry.state is PrincipalState.PRIMARY:
        raise ProfileRetentionError("primary principal cannot be retired")
    if entry.state is PrincipalState.RETIRED:
        return store
    blockers = list(recoverable_run_ids)
    blockers.extend(
        f"binding:{binding.authority_id}/{binding.environment}"
        for binding in profile.authority_payer_bindings
        if binding.bound_principal == principal
        and binding.state is not AuthorityBindingState.RETIRED
    )
    if blockers:
        raise ProfileRetentionError("principal remains required", blockers=blockers)
    history = tuple(
        item.model_copy(update={"state": PrincipalState.RETIRED})
        if item.principal == principal
        else item
        for item in profile.principal_history
    )
    replacement = profile.model_copy(
        update={"principal_history": history, "updated_at": _iso(now)}
    )
    return _replace_profile(store, replacement)


def retire_profile(
    store: ProfileStore,
    profile_id: uuid.UUID | str,
    *,
    recoverable_run_ids: Iterable[str] = (),
    now: datetime | None = None,
) -> ProfileStore:
    profile = store.profile(profile_id)
    if profile.state is ProfileState.RETIRED:
        return store
    blockers = list(recoverable_run_ids)
    blockers.extend(
        f"binding:{binding.authority_id}/{binding.environment}"
        for binding in profile.authority_payer_bindings
        if binding.state is not AuthorityBindingState.RETIRED
    )
    if blockers:
        raise ProfileRetentionError("buyer profile remains required", blockers=blockers)
    history = tuple(
        item.model_copy(
            update={
                "state": PrincipalState.RETIRED,
                "overlap_until": item.overlap_until,
            }
        )
        for item in profile.principal_history
    )
    replacement = profile.model_copy(
        update={
            "state": ProfileState.RETIRED,
            "principal_history": history,
            "updated_at": _iso(now),
        }
    )
    selected = (
        None
        if store.selected_profile_id == profile.profile_id
        else store.selected_profile_id
    )
    return _replace_profile(store, replacement, selected=selected)


def delete_profile(
    store: ProfileStore,
    profile_id: uuid.UUID | str,
    *,
    recoverable_run_ids: Iterable[str] = (),
    confirm_history_release: bool = False,
) -> ProfileStore:
    profile = store.profile(profile_id)
    blockers = list(recoverable_run_ids)
    blockers.extend(
        f"binding:{binding.authority_id}/{binding.environment}"
        for binding in profile.authority_payer_bindings
        if binding.state is not AuthorityBindingState.RETIRED
    )
    if profile.state is not ProfileState.RETIRED:
        blockers.append("profile:active")
    if store.selected_profile_id == profile.profile_id:
        blockers.append("profile:selected")
    if not confirm_history_release:
        blockers.append("principal-history:confirmation-required")
    if blockers:
        raise ProfileRetentionError("buyer profile cannot be deleted", blockers=blockers)
    return _next_store(
        store,
        profiles=tuple(
            candidate
            for candidate in store.profiles
            if candidate.profile_id != profile.profile_id
        ),
        selected=store.selected_profile_id,
    )


def set_authority_binding(
    store: ProfileStore,
    profile_id: uuid.UUID | str,
    binding: AuthorityPayerBinding,
    *,
    now: datetime | None = None,
) -> ProfileStore:
    profile = store.profile(profile_id)
    if profile.state is not ProfileState.ACTIVE:
        raise ProfileStoreError("retired buyer profile cannot accept a binding")
    profile.history_entry(binding.bound_principal)
    bindings = [
        existing
        for existing in profile.authority_payer_bindings
        if (existing.authority_id, existing.environment)
        != (binding.authority_id, binding.environment)
    ]
    bindings.append(binding)
    replacement = profile.model_copy(
        update={
            "authority_payer_bindings": tuple(bindings),
            "updated_at": _iso(now),
        }
    )
    return _replace_profile(store, replacement)


def profile_credential_references(store: ProfileStore) -> tuple[CredentialReference, ...]:
    unique: dict[tuple[str, str], CredentialReference] = {}
    for profile in store.profiles:
        for principal in profile.principal_history:
            reference = principal.credential_reference
            unique[(reference.provider.value, reference.locator)] = reference
    return tuple(unique[key] for key in sorted(unique))


def _replace_profile(
    store: ProfileStore,
    replacement: BuyerProfile,
    *,
    selected: uuid.UUID | None | object = ...,
) -> ProfileStore:
    profiles = tuple(
        replacement if profile.profile_id == replacement.profile_id else profile
        for profile in store.profiles
    )
    selected_id = store.selected_profile_id if selected is ... else selected
    return _next_store(store, profiles=profiles, selected=selected_id)


def _next_store(
    store: ProfileStore,
    *,
    profiles: tuple[BuyerProfile, ...],
    selected: uuid.UUID | None,
) -> ProfileStore:
    return ProfileStore(
        revision=store.revision + 1,
        selected_profile_id=selected,
        profiles=profiles,
    )


def _identity_key(identity: Identity) -> tuple[str, str]:
    return identity.scheme.value, identity.identifier


def _profile_id(value: uuid.UUID | str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    except (TypeError, ValueError) as exc:
        raise ProfileStoreError("buyer profile ID is malformed") from exc


def _iso(value: datetime | None) -> str:
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).isoformat()
