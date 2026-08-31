from __future__ import annotations

import base64
import hashlib
import json
import uuid
from pathlib import Path

import pytest

import core_buyer.buyer_config as buyer_config_module
import core_buyer.run_log as run_log_module
from core_buyer.buyer_config import BuyerProfileResolver, ResolvedBuyerIdentity
from core_buyer.deal_helpers import (
    accepted_settlement_mechanism,
    load_deal_context,
    load_negotiation_resume_point,
    settlement_acceptance_fields,
)
from core_buyer.profile_service import BuyerProfileService, ProfileServiceError
from core_buyer.run_log import (
    RUN_LOG_VERSION,
    SIGNATURE_VERSION,
    RunLog,
    RunLogError,
    RunLogMigrationIncomplete,
    assert_migration_resolved,
    migrate_run_logs,
    read_run,
    read_run_identity,
    recover_run_log_migration,
    runs_dir,
)
from market_identity import (
    REQUEST_PROTOCOL,
    CredentialProviderKind,
    CredentialReference,
    Ed25519Signer,
    Identity,
    IdentityScheme,
    ProfileRepository,
    ProfileStore,
    TrustedIdentitySet,
    add_profile,
    default_credential_registry,
    new_profile,
)


def _state_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    directory = runs_dir()
    directory.mkdir(parents=True)
    return directory


def _trust(signer: Ed25519Signer) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=(signer.identity,))


def _encoded(seed: bytes) -> str:
    return base64.urlsafe_b64encode(seed).rstrip(b"=").decode("ascii")


def _profile_repository(
    tmp_path: Path,
    *principals: tuple[str, Ed25519Signer],
) -> tuple[ProfileRepository, dict[str, uuid.UUID]]:
    repository = ProfileRepository((tmp_path / "profiles.json").absolute())
    store = ProfileStore.empty()
    ids: dict[str, uuid.UUID] = {}
    for name, signer in principals:
        profile = new_profile(
            name=name,
            principal=signer.identity,
            credential_reference=CredentialReference(
                provider=CredentialProviderKind.ENVIRONMENT,
                locator=f"{name.upper()}_SEED",
            ),
        )
        ids[name] = profile.profile_id
        store = add_profile(store, profile, select=not store.profiles)
    repository.replace(store, expected_revision=0)
    return repository, ids


def test_ed25519_run_log_v3_and_resume_need_no_wallet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _state_dir(monkeypatch, tmp_path)
    profile_id = uuid.uuid4()
    signer = Ed25519Signer(b"\x11" * 32)
    publisher = Ed25519Signer(b"\x18" * 32)
    log = RunLog.start(
        profile_id=profile_id,
        principal=signer.identity,
        seller_url="http://seller",
        listing_id="listing-1",
        publisher_principals=_trust(publisher).model_dump(mode="json"),
        publisher_id="publisher-1",
        source_registry_url="http://registry",
        source_registry_authority="registry",
        initial_price=10,
        max_price=12,
    )
    log.event(
        "negotiation_round",
        round=0,
        our_message={"action": "initial", "proposal": {"fields": {"amount": 10}}},
        their_reply={
            "negotiation_id": "neg-1",
            "action": "counter",
            "proposal": {"fields": {"amount": 12}},
        },
    )
    point = load_negotiation_resume_point(
        log.run_id,
        signer=signer,
        refresh_publisher_principals=lambda *_binding: _trust(publisher),
    )
    events = read_run(log.run_id, signer=signer, profile_id=profile_id)
    assert point.buyer_principal == signer.identity
    assert point.negotiation_id == "neg-1"
    assert events[0]["log_version"] == RUN_LOG_VERSION
    assert events[0]["signature_protocol"] == REQUEST_PROTOCOL
    assert events[0]["signature_version"] == SIGNATURE_VERSION
    assert events[0]["buyer_profile_id"] == str(profile_id)
    assert events[0]["buyer_principal"] == signer.identity.model_dump(mode="json")
    assert "buyer_address" not in json.dumps(events)


def test_hosted_recovery_preserves_every_settlement_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _state_dir(monkeypatch, tmp_path)
    buyer = Ed25519Signer(b"\x19" * 32)
    publisher = Ed25519Signer(b"\x1a" * 32)
    log = RunLog.start(
        profile_id=uuid.uuid4(),
        publisher_id="publisher-2",
        source_registry_url="http://registry",
        source_registry_authority="registry",
        principal=buyer.identity,
        seller_url="http://seller",
        listing_id="listing-2",
        publisher_principals=_trust(publisher).model_dump(mode="json"),
    )
    acceptance = settlement_acceptance_fields(
        negotiation_id="neg-2",
        selection={
            "mechanism": "fiat.stripe.v1",
            "option_id": "a" * 64,
            "expiration_unix": 2_000_000_000,
        },
        plan={
            "obligations": [
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "amount": "20",
                    "asset": "usd",
                    "expiration_unix": 2_000_000_000,
                    "mechanism": "fiat.stripe.v1",
                    "params": {"condition_profile": "vm"},
                }
            ]
        },
    )
    log.event(
        "negotiation_completed",
        status="agreed",
        seller_url="http://seller",
        publisher_id="publisher-2",
        source_registry_url="http://registry",
        source_registry_authority="registry",
        listing_id="listing-2",
        negotiation_id="neg-2",
        agreed_amount=20,
        publisher_principals=_trust(publisher).model_dump(mode="json"),
        **acceptance,
    )
    log.event("settlement_started", settlement_ref="settlement-2")
    context = load_deal_context(
        log.run_id,
        signer=buyer,
        refresh_publisher_principals=lambda *_binding: _trust(publisher),
    )
    assert context.publisher_principals == _trust(publisher)
    assert context.settlement_ref == "settlement-2"
    assert context.escrow_uid is None
    assert accepted_settlement_mechanism(context) == "fiat.stripe.v1"
    assert context.settlement_operation_identities == tuple(
        acceptance["settlement_operation_identities"]
    )


def test_recovery_rejects_another_signer_or_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _state_dir(monkeypatch, tmp_path)
    owner = Ed25519Signer(b"\x12" * 32)
    other = Ed25519Signer(b"\x13" * 32)
    profile_id = uuid.uuid4()
    log = RunLog.start(
        profile_id=profile_id,
        principal=owner.identity,
        command="market buy",
    )
    with pytest.raises(RunLogError, match="signer does not match"):
        RunLog.open(log.run_id, signer=other, profile_id=profile_id)
    with pytest.raises(RunLogError, match="profile does not match"):
        RunLog.open(log.run_id, signer=owner, profile_id=uuid.uuid4())
    with pytest.raises(RunLogError, match="signer does not match"):
        read_run(log.run_id, signer=other)


@pytest.mark.parametrize(
    "field",
    (
        "buyer_private_key",
        "credential",
        "credential_reference",
        "credential_provider",
        "environment_value",
        "mnemonic",
        "provider_locator",
        "seed",
        "settlement_config",
    ),
)
def test_run_logs_reject_secret_and_provider_carriers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    _state_dir(monkeypatch, tmp_path)
    signer = Ed25519Signer(b"\x14" * 32)
    with pytest.raises(RunLogError, match="credential or signer field"):
        RunLog.start(
            profile_id=uuid.uuid4(),
            principal=signer.identity,
            **{field: "PRIVATE-SEED-CANARY"},
        )
    assert not list(runs_dir().glob("*.jsonl"))


def test_resolved_identity_repr_is_public_only() -> None:
    signer = Ed25519Signer(b"\x16" * 32)
    resolved = ResolvedBuyerIdentity(
        profile_id=uuid.uuid4(),
        principal=signer.identity,
        signer=signer,
        source="fresh",
    )
    assert resolved.safe_context()["buyer_principal"].startswith("ed25519:")
    assert "signer=" not in repr(resolved)
    assert _encoded(b"\x16" * 32) not in repr(resolved)


def test_fresh_resolver_tracks_selection_while_recovery_uses_recorded_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_logs_directory = _state_dir(monkeypatch, tmp_path)
    old = Ed25519Signer(b"a" * 32)
    other = Ed25519Signer(b"b" * 32)
    environment = {"OLD_SEED": _encoded(b"a" * 32), "OTHER_SEED": _encoded(b"b" * 32)}
    service = BuyerProfileService(
        ProfileRepository((tmp_path / "profiles.json").absolute()),
        default_credential_registry(environ=environment),
        run_logs_directory=run_logs_directory,
    )
    first = service.create(
        name="first",
        credential_reference=CredentialReference(
            provider=CredentialProviderKind.ENVIRONMENT,
            locator="OLD_SEED",
        ),
        generate=False,
    )
    second = service.create(
        name="second",
        credential_reference=CredentialReference(
            provider=CredentialProviderKind.ENVIRONMENT,
            locator="OTHER_SEED",
        ),
        generate=False,
        select=False,
    )
    monkeypatch.setattr(buyer_config_module, "reject_legacy_buyer_identity_config", lambda: None)
    resolver = BuyerProfileResolver(service)
    assert resolver.fresh().principal == old.identity
    run = RunLog.start(
        profile_id=first.profile.profile_id,
        principal=old.identity,
        domain="vms.compute",
    )
    service.select(second.profile.profile_id)
    assert resolver.fresh().principal == other.identity
    recovered = resolver.recovery(run.run_id)
    assert recovered.profile_id == first.profile.profile_id
    assert recovered.principal == old.identity
    assert recovered.source == "recovery"


def test_recovery_fails_for_missing_or_mismatched_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_logs_directory = _state_dir(monkeypatch, tmp_path)
    signer = Ed25519Signer(b"a" * 32)
    service = BuyerProfileService(
        ProfileRepository((tmp_path / "profiles.json").absolute()),
        default_credential_registry(environ={"BUYER_SEED": _encoded(b"b" * 32)}),
        run_logs_directory=run_logs_directory,
    )
    profile = new_profile(
        name="buyer",
        principal=signer.identity,
        credential_reference=CredentialReference(
            provider=CredentialProviderKind.ENVIRONMENT,
            locator="BUYER_SEED",
        ),
    )
    service.repository.replace(
        add_profile(ProfileStore.empty(), profile),
        expected_revision=0,
    )
    with pytest.raises(ProfileServiceError, match="does not match recorded"):
        service.resolve_recovery_signer(
            profile_id=profile.profile_id,
            principal=signer.identity,
        )
    with pytest.raises(Exception, match="does not exist"):
        service.resolve_recovery_signer(
            profile_id=uuid.uuid4(),
            principal=signer.identity,
        )


def test_populated_v1_and_v2_multi_run_migration_preserves_identifiers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _state_dir(monkeypatch, tmp_path)
    ed = Ed25519Signer(b"x" * 32)
    address = "0xAAbbccDDeeFf0011223344556677889900AaBbCc"
    canonical_eip = Identity(scheme=IdentityScheme.EIP191, identifier=address)
    eip_profile = new_profile(
        name="eip",
        principal=canonical_eip,
        credential_reference=CredentialReference(
            provider=CredentialProviderKind.ENVIRONMENT,
            locator="EIP_SEED",
        ),
    )
    ed_profile = new_profile(
        name="ed",
        principal=ed.identity,
        credential_reference=CredentialReference(
            provider=CredentialProviderKind.ENVIRONMENT,
            locator="ED_SEED",
        ),
    )
    repository = ProfileRepository((tmp_path / "profiles.json").absolute())
    store = add_profile(ProfileStore.empty(), eip_profile)
    store = add_profile(store, ed_profile, select=False)
    repository.replace(store, expected_revision=0)
    v1_id = "v1-populated"
    v2_id = "v2-populated"
    v1 = {
        "ts": "2026-01-01T00:00:00+00:00",
        "run_id": v1_id,
        "event": "run_started",
        "buyer_address": address,
        "negotiation_id": "neg-v1",
        "deal_id": "deal-v1",
        "settlement_ref": "settlement-v1",
        "operation_id": "operation-v1",
    }
    v2 = {
        "ts": "2026-01-01T00:00:00+00:00",
        "run_id": v2_id,
        "event": "run_started",
        "log_version": 2,
        "signature_protocol": REQUEST_PROTOCOL,
        "buyer_principal": ed.identity.model_dump(mode="json"),
        "negotiation_id": "neg-v2",
        "deal_id": "deal-v2",
        "settlement_ref": "settlement-v2",
        "operation_id": "operation-v2",
    }
    (directory / f"{v1_id}.jsonl").write_text(json.dumps(v1) + "\n")
    (directory / f"{v2_id}.jsonl").write_text(json.dumps(v2) + "\n")
    migrated = migrate_run_logs(repository)
    assert migrated == (v1_id, v2_id)
    assert read_run_identity(v1_id).profile_id == eip_profile.profile_id
    assert read_run_identity(v2_id).profile_id == ed_profile.profile_id
    assert read_run(v1_id)[0]["negotiation_id"] == "neg-v1"
    assert read_run(v2_id)[0]["operation_id"] == "operation-v2"
    assert migrate_run_logs(repository) == ()


def test_ambiguous_migration_rewrites_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _state_dir(monkeypatch, tmp_path)
    signer = Ed25519Signer(b"a" * 32)
    first = new_profile(
        name="first",
        principal=signer.identity,
        credential_reference=CredentialReference(
            provider=CredentialProviderKind.ENVIRONMENT,
            locator="FIRST_SEED",
        ),
    )
    retired = first.model_copy(
        update={
            "profile_id": uuid.uuid4(),
            "name": "retired-copy",
            "state": "retired",
            "principal_history": tuple(
                entry.model_copy(update={"state": "retired"})
                for entry in first.principal_history
            ),
        }
    )
    repository = ProfileRepository((tmp_path / "profiles.json").absolute())
    repository.replace(
        ProfileStore(revision=1, selected_profile_id=first.profile_id, profiles=(first, retired)),
        expected_revision=0,
    )
    path = directory / "ambiguous.jsonl"
    original = json.dumps(
        {
            "run_id": "ambiguous",
            "event": "run_started",
            "log_version": 2,
            "signature_protocol": REQUEST_PROTOCOL,
            "buyer_principal": signer.identity.model_dump(mode="json"),
        }
    ) + "\n"
    path.write_text(original)
    with pytest.raises(RunLogError, match="exactly one"):
        migrate_run_logs(repository)
    assert path.read_text() == original


def test_failure_after_first_replacement_restores_every_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _state_dir(monkeypatch, tmp_path)
    signer = Ed25519Signer(b"a" * 32)
    repository, _ids = _profile_repository(tmp_path, ("buyer", signer))
    originals: dict[Path, str] = {}
    for run_id in ("first", "second"):
        path = directory / f"{run_id}.jsonl"
        original = json.dumps(
            {
                "run_id": run_id,
                "event": "run_started",
                "log_version": 2,
                "signature_protocol": REQUEST_PROTOCOL,
                "buyer_principal": signer.identity.model_dump(mode="json"),
                "operation_id": f"operation-{run_id}",
            }
        ) + "\n"
        path.write_text(original)
        originals[path] = original
    real_replace = run_log_module.os.replace
    candidate_replacements = 0

    def fail_second_candidate(source, destination):
        nonlocal candidate_replacements
        if str(source).endswith(".candidate"):
            candidate_replacements += 1
            if candidate_replacements == 2:
                raise OSError("deterministic second replacement failure")
        return real_replace(source, destination)

    monkeypatch.setattr(run_log_module.os, "replace", fail_second_candidate)
    with pytest.raises(OSError, match="second replacement"):
        migrate_run_logs(repository)
    assert {path: path.read_text() for path in originals} == originals
    assert not (directory / ".profile-migration-v3.json").exists()


def test_incomplete_manifest_blocks_startup_until_explicit_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _state_dir(monkeypatch, tmp_path)
    path = directory / "run.jsonl"
    original = b'{"run_id":"run","event":"run_started","buyer_address":"0x1111111111111111111111111111111111111111"}\n'
    replacement = b'{"run_id":"run","event":"run_started","log_version":3}\n'
    backup_root = directory / ".profile-migration-v3.backups"
    backup_root.mkdir(mode=0o700)
    backup = backup_root / "0000-run.jsonl"
    backup.write_bytes(original)
    path.write_bytes(replacement)
    manifest = {
        "schema_version": 1,
        "state": "replacing",
        "replaced": 1,
        "entries": [
            {
                "path": str(path.absolute()),
                "backup": str(backup.absolute()),
                "candidate": str((backup_root / "candidate").absolute()),
                "original_sha256": hashlib.sha256(original).hexdigest(),
                "candidate_sha256": hashlib.sha256(replacement).hexdigest(),
            }
        ],
    }
    (directory / ".profile-migration-v3.json").write_text(json.dumps(manifest))
    with pytest.raises(RunLogMigrationIncomplete, match="incomplete"):
        assert_migration_resolved(directory)
    with pytest.raises(RunLogMigrationIncomplete, match="incomplete"):
        read_run("run")
    recover_run_log_migration(directory=directory)
    assert path.read_bytes() == original
    assert not (directory / ".profile-migration-v3.json").exists()
