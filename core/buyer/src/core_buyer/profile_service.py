"""Core-owned buyer profile lifecycle, signer resolution, and legacy import."""

from __future__ import annotations

import os
import tomllib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from market_config.config_loader import get_dotted, load_user_config

from market_identity import (
    PROFILE_ROTATION_AUTHORITY,
    AuthorityBindingState,
    AuthorityPayerBinding,
    BuyerProfile,
    CredentialProviderError,
    CredentialProviderRegistry,
    CredentialReference,
    Identity,
    IdentityScheme,
    PrincipalState,
    ProfileRepository,
    ProfileStore,
    ProfileStoreError,
    RotationIntent,
    Signer,
    add_profile,
    create_signer,
    default_credential_registry,
    delete_profile,
    new_profile,
    profile_credential_references,
    retire_principal,
    retire_profile,
    rotate_profile,
    select_profile,
    sign_rotation,
    set_authority_binding,
)

from core_buyer.run_log import migrate_run_logs, recoverable_run_ids, runs_dir

PROFILE_STORE_ENV = "ARKHAI_BUYER_PROFILE_STORE"


class ProfileServiceError(RuntimeError):
    """A safe, actionable core profile operation failure."""


class GeneratedCredentialCleanupRequired(ProfileServiceError):
    """Metadata failed and the provider could not remove a generated entry."""


@dataclass(frozen=True, slots=True)
class ProfileOperationResult:
    profile: BuyerProfile
    selected: bool
    created: bool

    def redacted(self) -> dict[str, Any]:
        return self.profile.redacted(selected=self.selected) | {"created": self.created}


@dataclass(frozen=True, slots=True)
class LegacyImportPreview:
    source: Path
    profile_name: str
    principal: Identity
    credential_reference: CredentialReference
    profile_id: uuid.UUID
    already_imported: bool
    selected: bool

    def redacted(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "profile_name": self.profile_name,
            "principal": self.principal.model_dump(mode="json"),
            "credential_reference": self.credential_reference.redacted(),
            "profile_id": str(self.profile_id),
            "already_imported": self.already_imported,
            "selected": self.selected,
        }


@dataclass(frozen=True, slots=True)
class ProfileDeletionResult:
    profile_id: uuid.UUID
    deleted_credential_references: tuple[dict[str, str], ...]

    def redacted(self) -> dict[str, Any]:
        return {
            "profile_id": str(self.profile_id),
            "deleted": True,
            "deleted_credential_references": list(
                self.deleted_credential_references
            ),
        }


def profile_store_path(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the strict XDG metadata path or one explicit absolute override."""

    values = environ if environ is not None else os.environ
    override = values.get(PROFILE_STORE_ENV)
    if override:
        path = Path(override)
        if not path.is_absolute():
            raise ProfileServiceError(
                f"{PROFILE_STORE_ENV} must be an absolute profile-store path"
            )
        return path
    configured = get_dotted(load_user_config(), "BuyerProfile.store_path")
    if configured not in (None, ""):
        path = Path(str(configured))
        if not path.is_absolute():
            raise ProfileServiceError(
                "BuyerProfile.store_path must be an absolute profile-store path"
            )
        return path
    xdg = values.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return (base / "arkhai" / "buyer" / "profiles.json").absolute()


class BuyerProfileService:
    """Combines identity-kit storage/providers with buyer run retention."""

    def __init__(
        self,
        repository: ProfileRepository | None = None,
        providers: CredentialProviderRegistry | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        run_logs_directory: Path | None = None,
    ) -> None:
        self.repository = repository or ProfileRepository(profile_store_path(environ))
        self.providers = providers or default_credential_registry(environ=environ)
        resolved_runs = run_logs_directory or runs_dir(environ)
        if not resolved_runs.is_absolute():
            raise ProfileServiceError("buyer run-log directory must be absolute")
        self.run_logs_directory = resolved_runs

    def list_profiles(self) -> tuple[dict[str, Any], ...]:
        store = self.repository.load()
        return tuple(
            profile.redacted(selected=profile.profile_id == store.selected_profile_id)
            for profile in store.profiles
        )

    def show(self, profile: str | uuid.UUID) -> dict[str, Any]:
        store = self.repository.load()
        value = self._profile(store, profile)
        return value.redacted(selected=value.profile_id == store.selected_profile_id)

    def create(
        self,
        *,
        name: str,
        credential_reference: CredentialReference,
        scheme: IdentityScheme = IdentityScheme.ED25519,
        generate: bool,
        select: bool | None = None,
        declared_principal: Identity | None = None,
    ) -> ProfileOperationResult:
        current = self.repository.load()
        self._assert_name_available(current, name)
        generated = False
        try:
            if generate:
                self.providers.generate(credential_reference, scheme=scheme)
                generated = True
            signer = self._resolve_signer(credential_reference, scheme)
            if declared_principal is not None and signer.identity != declared_principal:
                raise ProfileServiceError(
                    "credential-derived principal does not match declared principal"
                )
            profile = new_profile(
                name=name,
                principal=signer.identity,
                credential_reference=credential_reference,
            )
            candidate = add_profile(current, profile, select=select)
            written = self.repository.replace(
                candidate,
                expected_revision=current.revision,
            )
        except BaseException:
            if generated:
                self._cleanup_generated(credential_reference)
            raise
        created = written.profile(profile.profile_id)
        return ProfileOperationResult(
            profile=created,
            selected=written.selected_profile_id == created.profile_id,
            created=True,
        )

    def preview_legacy_import(
        self,
        *,
        source: Path,
        name: str,
        credential_reference: CredentialReference,
    ) -> LegacyImportPreview:
        principal = _read_legacy_principal(source)
        signer = self._resolve_signer(credential_reference, principal.scheme)
        if signer.identity != principal:
            raise ProfileServiceError(
                "credential-derived principal does not match legacy Identity principal"
            )
        store = self.repository.load()
        exact = self._exact_existing(
            store,
            name=name,
            principal=principal,
            credential_reference=credential_reference,
        )
        if exact is not None:
            return LegacyImportPreview(
                source=source,
                profile_name=name,
                principal=principal,
                credential_reference=credential_reference,
                profile_id=exact.profile_id,
                already_imported=True,
                selected=store.selected_profile_id == exact.profile_id,
            )
        self._assert_name_available(store, name)
        staged = new_profile(
            name=name,
            principal=principal,
            credential_reference=credential_reference,
        )
        add_profile(store, staged)
        return LegacyImportPreview(
            source=source,
            profile_name=name,
            principal=principal,
            credential_reference=credential_reference,
            profile_id=staged.profile_id,
            already_imported=False,
            selected=not store.profiles,
        )

    def import_legacy(
        self,
        *,
        source: Path,
        name: str,
        credential_reference: CredentialReference,
        check: bool,
        select: bool | None = None,
    ) -> LegacyImportPreview:
        preview = self.preview_legacy_import(
            source=source,
            name=name,
            credential_reference=credential_reference,
        )
        if check or preview.already_imported:
            return preview
        current = self.repository.load()
        self._assert_name_available(current, name)
        profile = new_profile(
            name=name,
            principal=preview.principal,
            credential_reference=credential_reference,
        ).model_copy(update={"profile_id": preview.profile_id})
        candidate = add_profile(current, profile, select=select)
        migrate_run_logs(
            self.repository,
            candidate_store=candidate,
            expected_revision=current.revision,
            directory=self.run_logs_directory,
        )
        written = self.repository.load()
        imported = written.profile(profile.profile_id)
        return LegacyImportPreview(
            source=source,
            profile_name=name,
            principal=preview.principal,
            credential_reference=credential_reference,
            profile_id=imported.profile_id,
            already_imported=False,
            selected=written.selected_profile_id == imported.profile_id,
        )

    def select(self, profile: str | uuid.UUID) -> dict[str, Any]:
        current = self.repository.load()
        value = self._profile(current, profile)
        candidate = select_profile(current, value.profile_id)
        if candidate is current:
            return value.redacted(selected=True)
        written = self.repository.replace(
            candidate,
            expected_revision=current.revision,
        )
        return written.profile(value.profile_id).redacted(selected=True)

    def rotate(
        self,
        profile: str | uuid.UUID,
        *,
        replacement_reference: CredentialReference,
        replacement_scheme: IdentityScheme = IdentityScheme.ED25519,
        generate: bool,
        overlap_seconds: int = 0,
    ) -> ProfileOperationResult:
        current = self.repository.load()
        value = self._profile(current, profile)
        primary = value.history_entry(value.primary_principal)
        current_signer = self._resolve_signer(
            primary.credential_reference,
            value.primary_principal.scheme,
        )
        generated = False
        try:
            if generate:
                self.providers.generate(
                    replacement_reference,
                    scheme=replacement_scheme,
                )
                generated = True
            replacement_signer = self._resolve_signer(
                replacement_reference,
                replacement_scheme,
            )
            now = datetime.now(timezone.utc)
            intent = RotationIntent(
                current=current_signer.identity,
                replacement=replacement_signer.identity,
                subject=str(value.profile_id),
                authority=PROFILE_ROTATION_AUTHORITY,
                nonce=uuid.uuid4().hex,
                overlap_seconds=overlap_seconds,
                expires_at=int((now + timedelta(minutes=5)).timestamp()),
            )
            candidate = rotate_profile(
                current,
                value.profile_id,
                request=sign_rotation(
                    current_signer=current_signer,
                    replacement_signer=replacement_signer,
                    intent=intent,
                ),
                replacement_credential=replacement_reference,
                now=now,
            )
            written = self.repository.replace(
                candidate,
                expected_revision=current.revision,
            )
        except BaseException:
            if generated:
                self._cleanup_generated(replacement_reference)
            raise
        rotated = written.profile(value.profile_id)
        return ProfileOperationResult(
            profile=rotated,
            selected=written.selected_profile_id == rotated.profile_id,
            created=False,
        )

    def ensure_principal_retirable(
        self,
        profile: str | uuid.UUID,
        principal: Identity,
    ) -> None:
        """Validate recovery retention without changing profile metadata."""

        current = self.repository.load()
        value = self._profile(current, profile)
        retire_principal(
            current,
            value.profile_id,
            principal,
            recoverable_run_ids=recoverable_run_ids(
                value.profile_id,
                principal=principal,
                directory=self.run_logs_directory,
            ),
        )


    def retire_principal(
        self,
        profile: str | uuid.UUID,
        principal: Identity,
    ) -> dict[str, Any]:
        current = self.repository.load()
        value = self._profile(current, profile)
        blockers = recoverable_run_ids(
            value.profile_id,
            principal=principal,
            directory=self.run_logs_directory,
        )
        candidate = retire_principal(
            current,
            value.profile_id,
            principal,
            recoverable_run_ids=blockers,
        )
        if candidate is current:
            return value.redacted(selected=value.profile_id == current.selected_profile_id)
        written = self.repository.replace(
            candidate,
            expected_revision=current.revision,
        )
        return written.profile(value.profile_id).redacted(
            selected=written.selected_profile_id == value.profile_id
        )

    def retire(self, profile: str | uuid.UUID) -> dict[str, Any]:
        current = self.repository.load()
        value = self._profile(current, profile)
        blockers = recoverable_run_ids(
            value.profile_id,
            directory=self.run_logs_directory,
        )
        candidate = retire_profile(
            current,
            value.profile_id,
            recoverable_run_ids=blockers,
        )
        if candidate is current:
            return value.redacted(selected=False)
        written = self.repository.replace(
            candidate,
            expected_revision=current.revision,
        )
        return written.profile(value.profile_id).redacted(selected=False)

    def delete(
        self,
        profile: str | uuid.UUID,
        *,
        confirm_history_release: bool,
        delete_credentials: bool,
    ) -> ProfileDeletionResult:
        current = self.repository.load()
        value = self._profile(current, profile)
        blockers = recoverable_run_ids(
            value.profile_id,
            directory=self.run_logs_directory,
        )
        references = tuple(
            entry.credential_reference for entry in value.principal_history
        )
        candidate = delete_profile(
            current,
            value.profile_id,
            recoverable_run_ids=blockers,
            confirm_history_release=confirm_history_release,
        )
        written = self.repository.replace(
            candidate,
            expected_revision=current.revision,
        )
        deleted: list[dict[str, str]] = []
        if delete_credentials:
            remaining = {
                (reference.provider, reference.locator)
                for reference in profile_credential_references(written)
            }
            for reference in references:
                if (reference.provider, reference.locator) in remaining:
                    raise ProfileServiceError(
                        "credential reference remains shared by another profile"
                    )
                self.providers.delete(reference)
                deleted.append(reference.redacted())
        return ProfileDeletionResult(
            profile_id=value.profile_id,
            deleted_credential_references=tuple(deleted),
        )

    def resolve_fresh_signer(self) -> tuple[BuyerProfile, Signer]:
        store = self.repository.load()
        profile = store.selected()
        entry = profile.history_entry(profile.primary_principal)
        if entry.state is not PrincipalState.PRIMARY:
            raise ProfileServiceError("selected profile primary history is invalid")
        signer = self._resolve_signer(
            entry.credential_reference,
            profile.primary_principal.scheme,
        )
        if signer.identity != profile.primary_principal:
            raise ProfileServiceError(
                "credential-derived principal does not match selected profile"
            )
        return profile, signer

    def resolve_recovery_signer(
        self,
        *,
        profile_id: uuid.UUID | str,
        principal: Identity,
    ) -> tuple[BuyerProfile, Signer]:
        store = self.repository.load()
        profile = store.profile(profile_id)
        entry = profile.history_entry(principal)
        if entry.state is PrincipalState.RETIRED:
            raise ProfileServiceError("recorded profile principal is retired")
        signer = self._resolve_signer(entry.credential_reference, principal.scheme)
        if signer.identity != principal:
            raise ProfileServiceError(
                "credential-derived principal does not match recorded run principal"
            )
        return profile, signer

    def authority_payer_binding(
        self,
        profile_id: str | uuid.UUID,
        *,
        authority_id: str,
        environment: str,
        principal: Identity,
    ) -> AuthorityPayerBinding:
        """Resolve an active opaque binding for a retained recorded signer."""

        profile = self.repository.load().profile(profile_id)
        binding = next(
            (
                item
                for item in profile.authority_payer_bindings
                if item.authority_id == authority_id
                and item.environment == environment
            ),
            None,
        )
        try:
            history = profile.history_entry(principal)
        except ProfileStoreError:
            history = None
        if (
            binding is None
            or binding.state is not AuthorityBindingState.ACTIVE
            or history is None
            or history.state is PrincipalState.RETIRED
        ):
            raise ProfileServiceError(
                "buyer profile has no active payer binding for this authority"
            )
        if binding.bound_principal == principal:
            return binding
        return binding.model_copy(update={"bound_principal": principal})

    def set_authority_payer_binding(
        self,
        profile_id: str | uuid.UUID,
        binding: AuthorityPayerBinding,
    ) -> BuyerProfile:
        """Atomically replace one authority/environment opaque payer binding."""

        current = self.repository.load()
        profile = current.profile(profile_id)
        candidate = set_authority_binding(
            current,
            profile.profile_id,
            binding,
        )
        written = self.repository.replace(
            candidate,
            expected_revision=current.revision,
        )
        return written.profile(profile.profile_id)

    def _resolve_signer(
        self,
        reference: CredentialReference,
        scheme: IdentityScheme,
    ) -> Signer:
        try:
            secret = self.providers.load(reference)
            return create_signer(scheme, secret)
        except CredentialProviderError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ProfileServiceError(
                f"credential {reference.fingerprint} cannot construct {scheme.value} signer"
            ) from exc

    def _cleanup_generated(self, reference: CredentialReference) -> None:
        try:
            self.providers.delete(reference)
        except Exception:
            raise GeneratedCredentialCleanupRequired(
                "generated credential cleanup is required for reference "
                f"{reference.fingerprint}"
            ) from None

    @staticmethod
    def _profile(store: ProfileStore, profile: str | uuid.UUID) -> BuyerProfile:
        try:
            return store.profile(profile)
        except ProfileStoreError:
            if isinstance(profile, str):
                return store.profile_named(profile)
            raise

    @staticmethod
    def _assert_name_available(store: ProfileStore, name: str) -> None:
        try:
            store.profile_named(name)
        except ProfileStoreError:
            return
        raise ProfileServiceError("buyer profile name already exists")

    @staticmethod
    def _exact_existing(
        store: ProfileStore,
        *,
        name: str,
        principal: Identity,
        credential_reference: CredentialReference,
    ) -> BuyerProfile | None:
        try:
            profile = store.profile_named(name)
        except ProfileStoreError:
            profile = None
        if profile is not None:
            try:
                entry = profile.history_entry(principal)
            except ProfileStoreError as exc:
                raise ProfileServiceError(
                    "buyer profile name conflicts with another principal"
                ) from exc
            if entry.credential_reference != credential_reference:
                raise ProfileServiceError(
                    "buyer profile name conflicts with another credential reference"
                )
            return profile
        for candidate in store.profiles:
            for entry in candidate.principal_history:
                if entry.principal == principal and entry.state is not PrincipalState.RETIRED:
                    raise ProfileServiceError(
                        "legacy principal already belongs to another active profile"
                    )
        return None


def _read_legacy_principal(source: Path) -> Identity:
    try:
        payload = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProfileServiceError("legacy buyer config cannot be read safely") from exc
    identity = payload.get("Identity")
    if not isinstance(identity, dict) or set(identity) != {"scheme", "identifier"}:
        raise ProfileServiceError(
            "legacy config must contain exactly Identity.scheme and Identity.identifier"
        )
    try:
        return Identity(
            scheme=IdentityScheme(identity["scheme"]),
            identifier=identity["identifier"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfileServiceError("legacy Identity principal is malformed") from exc
