from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

import core_buyer.run_log as run_log_module
from core_buyer.profile_service import (
    BuyerProfileService,
    GeneratedCredentialCleanupRequired,
    ProfileServiceError,
)
from core_buyer.run_log import RunLog
from market_identity import (
    AuthorityBindingState,
    AuthorityPayerBinding,
    CredentialProviderKind,
    CredentialReference,
    Ed25519Signer,
    EnvironmentCredentialProvider,
    IdentityScheme,
    ProfileRepository,
    SecretFileCredentialProvider,
    default_credential_registry,
)


def _seed(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _reference(name: str) -> CredentialReference:
    return CredentialReference(
        provider=CredentialProviderKind.ENVIRONMENT,
        locator=name,
    )


def _service(tmp_path: Path, environ: dict[str, str]) -> BuyerProfileService:
    return BuyerProfileService(
        ProfileRepository((tmp_path / "profiles.json").absolute()),
        default_credential_registry(environ=environ),
        run_logs_directory=(tmp_path / "runs").absolute(),
    )


def test_create_select_show_and_json_projection_are_secret_free(tmp_path: Path) -> None:
    canary = _seed(b"a" * 32)
    service = _service(tmp_path, {"BUYER_SEED": canary})
    result = service.create(
        name="primary",
        credential_reference=_reference("BUYER_SEED"),
        generate=False,
    )
    assert result.created is True
    assert result.selected is True
    shown = service.show(str(result.profile.profile_id))
    encoded = json.dumps(shown)
    assert canary not in encoded
    assert "BUYER_SEED" not in encoded
    assert shown["selected"] is True
    assert service.select("primary")["profile_id"] == str(result.profile.profile_id)


def test_create_mismatch_and_duplicate_leave_no_partial_profile(tmp_path: Path) -> None:
    service = _service(tmp_path, {"BUYER_SEED": _seed(b"a" * 32)})
    signer = Ed25519Signer(b"a" * 32)
    service.create(
        name="primary",
        credential_reference=_reference("BUYER_SEED"),
        generate=False,
        declared_principal=signer.identity,
    )
    with pytest.raises(ProfileServiceError, match="name already exists"):
        service.create(
            name="primary",
            credential_reference=_reference("BUYER_SEED"),
            generate=False,
        )
    assert len(service.list_profiles()) == 1
    with pytest.raises(ProfileServiceError, match="does not match declared"):
        service.create(
            name="mismatch",
            credential_reference=_reference("BUYER_SEED"),
            generate=False,
            declared_principal=Ed25519Signer(b"b" * 32).identity,
        )
    assert len(service.list_profiles()) == 1


def test_generated_file_secret_is_cleaned_when_metadata_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_directory = tmp_path / "secrets"
    secret_directory.mkdir(mode=0o700)
    reference = CredentialReference(
        provider=CredentialProviderKind.SECRET_FILE,
        locator=str((secret_directory / "seed").absolute()),
    )
    repository = ProfileRepository((tmp_path / "profiles.json").absolute())
    service = BuyerProfileService(
        repository,
        default_credential_registry(environ={}),
        run_logs_directory=(tmp_path / "runs").absolute(),
    )

    def fail_replace(*_args, **_kwargs):
        raise OSError("metadata replacement failed")

    monkeypatch.setattr(repository, "replace", fail_replace)
    with pytest.raises(OSError):
        service.create(
            name="buyer",
            credential_reference=reference,
            generate=True,
        )
    assert not Path(reference.locator).exists()


def test_cleanup_failure_returns_only_bounded_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Provider:
        kind = CredentialProviderKind.SECRET_FILE

        def load(self, reference):
            return _seed(b"a" * 32).encode("ascii")

        def generate(self, reference, *, scheme):
            return None

        def delete(self, reference):
            raise RuntimeError("PRIVATE-CANARY")

    from market_identity import CredentialProviderRegistry

    repository = ProfileRepository((tmp_path / "profiles.json").absolute())
    service = BuyerProfileService(
        repository,
        CredentialProviderRegistry((Provider(),)),
        run_logs_directory=(tmp_path / "runs").absolute(),
    )
    reference = CredentialReference(
        provider=CredentialProviderKind.SECRET_FILE,
        locator=str((tmp_path / "seed").absolute()),
    )
    monkeypatch.setattr(repository, "replace", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(GeneratedCredentialCleanupRequired) as error:
        service.create(
            name="buyer",
            credential_reference=reference,
            generate=True,
        )
    assert "PRIVATE-CANARY" not in str(error.value)
    assert reference.locator not in str(error.value)


def test_legacy_import_preview_write_and_exact_retry_preserve_source(
    tmp_path: Path,
) -> None:
    signer = Ed25519Signer(b"a" * 32)
    source = tmp_path / "legacy.toml"
    original = (
        "[Identity]\n"
        "scheme = \"ed25519\"\n"
        f"identifier = \"{signer.identity.identifier}\"\n"
    )
    source.write_text(original, encoding="utf-8")
    service = _service(tmp_path, {"BUYER_SEED": _seed(b"a" * 32)})
    preview = service.import_legacy(
        source=source,
        name="imported",
        credential_reference=_reference("BUYER_SEED"),
        check=True,
    )
    assert preview.already_imported is False
    assert service.list_profiles() == ()
    written = service.import_legacy(
        source=source,
        name="imported",
        credential_reference=_reference("BUYER_SEED"),
        check=False,
    )
    retried = service.import_legacy(
        source=source,
        name="imported",
        credential_reference=_reference("BUYER_SEED"),
        check=False,
    )
    assert retried.already_imported is True
    assert retried.profile_id == written.profile_id
    assert source.read_text(encoding="utf-8") == original


def test_legacy_import_mismatch_mutates_nothing(tmp_path: Path) -> None:
    source = tmp_path / "legacy.toml"
    source.write_text(
        "[Identity]\nscheme = \"ed25519\"\n"
        f"identifier = \"{Ed25519Signer(b'b' * 32).identity.identifier}\"\n",
        encoding="utf-8",
    )
    service = _service(tmp_path, {"BUYER_SEED": _seed(b"a" * 32)})
    with pytest.raises(ProfileServiceError, match="does not match legacy"):
        service.import_legacy(
            source=source,
            name="imported",
            credential_reference=_reference("BUYER_SEED"),
            check=False,
        )
    assert service.list_profiles() == ()


def test_rotation_fresh_promotion_retained_recovery_and_retirement_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_log_module, "runs_dir", lambda: tmp_path / "runs")
    old = Ed25519Signer(b"a" * 32)
    new = Ed25519Signer(b"b" * 32)
    service = _service(
        tmp_path,
        {"OLD_SEED": _seed(b"a" * 32), "NEW_SEED": _seed(b"b" * 32)},
    )
    created = service.create(
        name="buyer",
        credential_reference=_reference("OLD_SEED"),
        generate=False,
    )
    run = RunLog.start(
        profile_id=created.profile.profile_id,
        principal=old.identity,
        domain="vms.compute",
    )
    rotated = service.rotate(
        "buyer",
        replacement_reference=_reference("NEW_SEED"),
        generate=False,
        overlap_seconds=60,
    )
    assert rotated.profile.primary_principal == new.identity
    assert service.resolve_fresh_signer()[1].identity == new.identity
    assert service.resolve_recovery_signer(
        profile_id=created.profile.profile_id,
        principal=old.identity,
    )[1].identity == old.identity
    with pytest.raises(Exception, match=run.run_id):
        service.retire_principal("buyer", old.identity)
    run.end("completed")
    retired = service.retire_principal("buyer", old.identity)
    assert next(
        entry
        for entry in retired["principal_history"]
        if entry["principal"] == old.identity.model_dump(mode="json")
    )["state"] == "retired"


def test_selected_one_profile_retirement_then_confirmed_metadata_delete(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, {"BUYER_SEED": _seed(b"a" * 32)})
    created = service.create(
        name="buyer",
        credential_reference=_reference("BUYER_SEED"),
        generate=False,
    )
    retired = service.retire("buyer")
    assert retired["state"] == "retired"
    assert retired["selected"] is False
    with pytest.raises(Exception, match="confirmation-required"):
        service.delete(
            "buyer",
            confirm_history_release=False,
            delete_credentials=False,
        )
    result = service.delete(
        str(created.profile.profile_id),
        confirm_history_release=True,
        delete_credentials=False,
    )
    assert result.profile_id == created.profile.profile_id
    assert service.list_profiles() == ()

def test_authority_payer_binding_update_is_owner_only_and_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signer = Ed25519Signer(b"a" * 32)
    service = _service(tmp_path, {"BUYER_SEED": _seed(b"a" * 32)})
    created = service.create(
        name="buyer",
        credential_reference=_reference("BUYER_SEED"),
        generate=False,
    )
    binding = AuthorityPayerBinding(
        authority_id="authority-main",
        environment="production",
        binding_ref="payer_binding_opaque",
        bound_principal=signer.identity,
        state=AuthorityBindingState.ACTIVE,
    )
    updated = service.set_authority_payer_binding(
        created.profile.profile_id,
        binding,
    )
    assert updated.authority_payer_bindings == (binding,)

    def conflict(*_args, **_kwargs):
        raise RuntimeError("simulated compare-and-swap conflict")

    monkeypatch.setattr(service.repository, "replace", conflict)
    with pytest.raises(RuntimeError, match="compare-and-swap"):
        service.set_authority_payer_binding(
            created.profile.profile_id,
            binding.model_copy(update={"state": AuthorityBindingState.RETIRED}),
        )
    assert service.repository.load().profile(
        created.profile.profile_id
    ).authority_payer_bindings == (binding,)


def test_historical_signer_uses_active_binding_transiently_until_retired(
    tmp_path: Path,
) -> None:
    old = Ed25519Signer(b"a" * 32)
    new = Ed25519Signer(b"b" * 32)
    service = _service(
        tmp_path,
        {
            "BUYER_SEED": _seed(b"a" * 32),
            "NEW_SEED": _seed(b"b" * 32),
        },
    )
    created = service.create(
        name="buyer",
        credential_reference=_reference("BUYER_SEED"),
        generate=False,
    )
    binding = AuthorityPayerBinding(
        authority_id="authority-main",
        environment="production",
        binding_ref="payer_binding_opaque",
        bound_principal=old.identity,
        state=AuthorityBindingState.ACTIVE,
    )
    service.set_authority_payer_binding(created.profile.profile_id, binding)
    rotated = service.rotate(
        created.profile.profile_id,
        replacement_reference=_reference("NEW_SEED"),
        generate=False,
        overlap_seconds=0,
    )
    service.set_authority_payer_binding(
        rotated.profile.profile_id,
        binding.model_copy(update={"bound_principal": new.identity}),
    )

    historical = service.authority_payer_binding(
        rotated.profile.profile_id,
        authority_id="authority-main",
        environment="production",
        principal=old.identity,
    )
    assert historical.bound_principal == old.identity
    assert (
        service.repository.load()
        .profile(rotated.profile.profile_id)
        .authority_payer_bindings[0]
        .bound_principal
        == new.identity
    )

    service.retire_principal(rotated.profile.profile_id, old.identity)
    with pytest.raises(ProfileServiceError, match="no active payer binding"):
        service.authority_payer_binding(
            rotated.profile.profile_id,
            authority_id="authority-main",
            environment="production",
            principal=old.identity,
        )
