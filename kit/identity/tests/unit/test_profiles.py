from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from market_identity import (
    PROFILE_ROTATION_AUTHORITY,
    AuthorityBindingState,
    AuthorityPayerBinding,
    CredentialProviderKind,
    CredentialReference,
    Ed25519Signer,
    ProfileRepository,
    ProfileRetentionError,
    ProfileRevisionConflict,
    ProfileState,
    ProfileStore,
    ProfileStoreError,
    RotationIntent,
    add_profile,
    delete_profile,
    new_profile,
    rename_profile,
    retire_principal,
    retire_profile,
    rotate_profile,
    select_profile,
    set_authority_binding,
    sign_rotation,
)

_NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def _reference(name: str = "BUYER_SEED") -> CredentialReference:
    return CredentialReference(
        provider=CredentialProviderKind.ENVIRONMENT,
        locator=name,
    )


def _profile(name: str = "buyer", seed: bytes = b"a" * 32):
    signer = Ed25519Signer(seed)
    return new_profile(
        name=name,
        principal=signer.identity,
        credential_reference=_reference(),
        now=_NOW,
    )


def _repository(tmp_path: Path) -> ProfileRepository:
    directory = tmp_path / "data" / "arkhai" / "buyer"
    directory.mkdir(parents=True, mode=0o700)
    directory.chmod(0o700)
    return ProfileRepository((directory / "profiles.json").absolute())


def _rename_worker(path: str, profile_id: str, index: int) -> int:
    repository = ProfileRepository(Path(path))
    repository.update(
        lambda store: rename_profile(store, profile_id, f"buyer-{index}", now=_NOW)
    )
    return index


def test_fresh_store_uses_random_opaque_stable_profile_id(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    assert repository.load() == ProfileStore.empty()
    profile = _profile()
    assert isinstance(profile.profile_id, uuid.UUID)
    assert str(profile.profile_id) not in {
        profile.name,
        profile.primary_principal.identifier,
        profile.principal_history[0].credential_reference.locator,
    }
    written = repository.replace(
        add_profile(repository.load(), profile),
        expected_revision=0,
    )
    selected = select_profile(written, profile.profile_id)
    selected = rename_profile(selected, profile.profile_id, "renamed", now=_NOW)
    restarted = repository.replace(selected, expected_revision=1)
    assert repository.load().profile_named("renamed").profile_id == profile.profile_id
    assert restarted.selected_profile_id == profile.profile_id
    assert oct(repository.path.stat().st_mode & 0o777) == "0o600"


def test_random_profile_ids_are_not_deterministic() -> None:
    first = _profile()
    second = _profile()
    assert first.profile_id != second.profile_id


@pytest.mark.parametrize("conflict", ("id", "name", "principal"))
def test_duplicate_profile_metadata_is_rejected(conflict: str) -> None:
    first = _profile("first", b"a" * 32)
    second = _profile("second", b"b" * 32)
    if conflict == "id":
        second = second.model_copy(update={"profile_id": first.profile_id})
    elif conflict == "name":
        second = second.model_copy(update={"name": "FIRST"})
    else:
        second = second.model_copy(
            update={
                "primary_principal": first.primary_principal,
                "principal_history": first.principal_history,
            }
        )
    with pytest.raises(ValidationError):
        ProfileStore(revision=1, profiles=(first, second))


def test_invalid_history_and_binding_are_rejected() -> None:
    profile = _profile()
    duplicate = profile.principal_history[0]
    with pytest.raises(ValidationError):
        profile.model_copy(
            update={"principal_history": (duplicate, duplicate)}
        ).model_validate(
            profile.model_copy(
                update={"principal_history": (duplicate, duplicate)}
            ).model_dump(mode="python")
        )
    other = Ed25519Signer(b"z" * 32).identity
    with pytest.raises(ValidationError):
        AuthorityPayerBinding(
            authority_id="authority",
            environment="test",
            binding_ref="cus_provider_value",
            bound_principal=other,
        )
    binding = AuthorityPayerBinding(
        authority_id="authority",
        environment="test",
        binding_ref="opaque-profile-4f319726",
        bound_principal=other,
    )
    with pytest.raises(ValidationError):
        profile.model_copy(
            update={"authority_payer_bindings": (binding,)}
        ).model_validate(
            profile.model_copy(
                update={"authority_payer_bindings": (binding,)}
            ).model_dump(mode="python")
        )


def test_selection_requires_an_active_known_profile() -> None:
    store = add_profile(ProfileStore.empty(), _profile())
    profile = store.selected()
    retired = retire_profile(store, profile.profile_id)
    assert retired.selected_profile_id is None
    assert retired.profile(profile.profile_id).state is ProfileState.RETIRED
    with pytest.raises(ProfileStoreError, match="no active buyer profile"):
        retired.selected()
    with pytest.raises(ProfileStoreError, match="retired"):
        select_profile(retired, profile.profile_id)


def test_revision_conflict_leaves_store_unchanged(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    initial = repository.replace(
        add_profile(ProfileStore.empty(), _profile()),
        expected_revision=0,
    )
    stale = rename_profile(initial, initial.selected().profile_id, "stale", now=_NOW)
    current = repository.update(
        lambda store: rename_profile(
            store,
            store.selected().profile_id,
            "current",
            now=_NOW,
        )
    )
    with pytest.raises(ProfileRevisionConflict):
        repository.replace(stale, expected_revision=1)
    assert repository.load() == current


@pytest.mark.parametrize(
    "payload",
    (
        "not-json",
        "[]",
        '{"schema_version":99,"revision":0,"selected_profile_id":null,"profiles":[]}',
        '{"schema_version":1,"revision":0,"profiles":[],"unknown":true}',
        '{"schema_version":1,"revision":0,"selected_profile_id":"broken","profiles":[]}',
    ),
)
def test_malformed_unknown_or_partial_store_is_rejected(
    tmp_path: Path,
    payload: str,
) -> None:
    repository = _repository(tmp_path)
    repository.path.write_text(payload, encoding="utf-8")
    repository.path.chmod(0o600)
    with pytest.raises(ProfileStoreError, match="malformed or unsupported"):
        repository.load()


def test_store_rejects_unsafe_permissions_and_symlink(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.path.write_text(
        json.dumps(ProfileStore.empty().model_dump(mode="json")),
        encoding="utf-8",
    )
    repository.path.chmod(0o640)
    with pytest.raises(ProfileStoreError, match="owner-only"):
        repository.load()
    repository.path.unlink()
    target = repository.path.with_name("target.json")
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    repository.path.symlink_to(target)
    with pytest.raises(ProfileStoreError, match="opened safely"):
        repository.load()


def test_interrupted_atomic_replace_preserves_previous_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    previous = repository.replace(
        add_profile(ProfileStore.empty(), _profile()),
        expected_revision=0,
    )

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("deterministic replacement interruption")

    monkeypatch.setattr("market_identity.profiles.os.replace", fail_replace)
    with pytest.raises(OSError):
        repository.replace(
            rename_profile(previous, previous.selected().profile_id, "next", now=_NOW),
            expected_revision=1,
        )
    assert repository.load() == previous
    assert not tuple(repository.path.parent.glob(".profiles.json.*.tmp"))


def test_multiprocess_updates_are_serialized(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    initial = repository.replace(
        add_profile(ProfileStore.empty(), _profile()),
        expected_revision=0,
    )
    with ProcessPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                _rename_worker,
                (str(repository.path), str(repository.path)),
                (str(initial.selected_profile_id), str(initial.selected_profile_id)),
                (1, 2),
            )
        )
    assert sorted(results) == [1, 2]
    assert repository.load().revision == 3


def test_dual_proof_rotation_promotes_new_primary_and_retains_old() -> None:
    current = Ed25519Signer(b"a" * 32)
    replacement = Ed25519Signer(b"b" * 32)
    profile = new_profile(
        name="buyer",
        principal=current.identity,
        credential_reference=_reference("OLD_SEED"),
        now=_NOW,
    )
    store = add_profile(ProfileStore.empty(), profile)
    intent = RotationIntent(
        current=current.identity,
        replacement=replacement.identity,
        subject=str(profile.profile_id),
        authority=PROFILE_ROTATION_AUTHORITY,
        nonce="rotation-1",
        overlap_seconds=3600,
        expires_at=int(_NOW.timestamp()) + 60,
    )
    rotated = rotate_profile(
        store,
        profile.profile_id,
        request=sign_rotation(
            current_signer=current,
            replacement_signer=replacement,
            intent=intent,
        ),
        replacement_credential=_reference("NEW_SEED"),
        now=_NOW,
    )
    value = rotated.profile(profile.profile_id)
    assert value.primary_principal == replacement.identity
    assert value.history_entry(current.identity).state.value == "retained"
    assert value.history_entry(replacement.identity).state.value == "primary"
    assert value.history_entry(current.identity).rotation_intent_hash is not None


def test_principal_retirement_reports_run_and_binding_blockers() -> None:
    current = Ed25519Signer(b"a" * 32)
    replacement = Ed25519Signer(b"b" * 32)
    profile = new_profile(
        name="buyer",
        principal=current.identity,
        credential_reference=_reference("OLD_SEED"),
        now=_NOW,
    )
    store = add_profile(ProfileStore.empty(), profile)
    intent = RotationIntent(
        current=current.identity,
        replacement=replacement.identity,
        subject=str(profile.profile_id),
        authority=PROFILE_ROTATION_AUTHORITY,
        nonce="rotation-1",
        overlap_seconds=0,
        expires_at=int(_NOW.timestamp()) + 60,
    )
    store = rotate_profile(
        store,
        profile.profile_id,
        request=sign_rotation(
            current_signer=current,
            replacement_signer=replacement,
            intent=intent,
        ),
        replacement_credential=_reference("NEW_SEED"),
        now=_NOW,
    )
    store = set_authority_binding(
        store,
        profile.profile_id,
        AuthorityPayerBinding(
            authority_id="hosted-authority",
            environment="test",
            binding_ref="opaque-binding-827af330",
            bound_principal=current.identity,
            state=AuthorityBindingState.ROTATION_PENDING,
        ),
        now=_NOW,
    )
    with pytest.raises(ProfileRetentionError) as error:
        retire_principal(
            store,
            profile.profile_id,
            current.identity,
            recoverable_run_ids=("run-1",),
            now=_NOW,
        )
    assert error.value.blockers == (
        "binding:hosted-authority/test",
        "run-1",
    )


def test_retirement_clears_one_profile_selection_and_deletion_is_confirmed() -> None:
    profile = _profile()
    store = add_profile(ProfileStore.empty(), profile)
    retired = retire_profile(store, profile.profile_id, now=_NOW)
    assert retired.selected_profile_id is None
    with pytest.raises(ProfileRetentionError, match="confirmation-required"):
        delete_profile(retired, profile.profile_id)
    deleted = delete_profile(
        retired,
        profile.profile_id,
        confirm_history_release=True,
    )
    assert deleted.profiles == ()


def test_profile_and_reference_reprs_are_redacted() -> None:
    canary = "CANARY_SECRET_VARIABLE"
    profile = new_profile(
        name="buyer",
        principal=Ed25519Signer(b"a" * 32).identity,
        credential_reference=_reference(canary),
        now=_NOW,
    )
    projection = profile.redacted(selected=True)
    encoded = json.dumps(projection)
    assert canary not in encoded
    assert canary not in repr(profile.principal_history[0].credential_reference)
    assert projection["selected"] is True
    assert projection["principal_history"][0]["credential_reference"]["provider"] == (
        "environment.v1"
    )
