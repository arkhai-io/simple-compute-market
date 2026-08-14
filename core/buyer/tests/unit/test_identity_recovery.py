from __future__ import annotations

import json
from pathlib import Path

import pytest
from core_buyer.buyer_config import (
    IdentityConfig,
    resolve_buyer_signer,
    resolve_identity_config,
    resolve_identity_credential,
)
from core_buyer.deal_helpers import (
    accepted_settlement_mechanism,
    load_deal_context,
    load_negotiation_resume_point,
    settlement_acceptance_fields,
)
from core_buyer.run_log import (
    RUN_LOG_VERSION,
    RunLog,
    RunLogError,
    read_run,
    runs_dir,
)
from market_identity import REQUEST_PROTOCOL, Ed25519Signer, TrustedIdentitySet


def _state_dir(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    directory = runs_dir()
    directory.mkdir(parents=True)
    return directory


def _trust(signer: Ed25519Signer) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=(signer.identity,))


def test_ed25519_run_log_and_resume_need_no_wallet(monkeypatch, tmp_path) -> None:
    _state_dir(monkeypatch, tmp_path)
    signer = Ed25519Signer(b"\x11" * 32)
    publisher = Ed25519Signer(b"\x18" * 32)
    log = RunLog.start(
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
    events = read_run(log.run_id, signer=signer)

    assert point.buyer_principal == signer.identity
    assert point.publisher_principals == _trust(publisher)
    assert point.negotiation_id == "neg-1"
    assert events[0]["log_version"] == RUN_LOG_VERSION
    assert events[0]["signature_protocol"] == REQUEST_PROTOCOL
    assert events[0]["buyer_principal"] == signer.identity.model_dump(mode="json")
    assert "buyer_address" not in json.dumps(events)


def test_hosted_recovery_preserves_settlement_reference(monkeypatch, tmp_path) -> None:
    _state_dir(monkeypatch, tmp_path)
    buyer = Ed25519Signer(b"\x19" * 32)
    publisher = Ed25519Signer(b"\x1a" * 32)
    log = RunLog.start(
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
    log.event(
        "settlement_started",
        settlement_ref="settlement-2",
    )

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


def test_resume_refreshes_and_persists_retired_publisher_set(
    monkeypatch,
    tmp_path,
) -> None:
    _state_dir(monkeypatch, tmp_path)
    buyer = Ed25519Signer(b"\x1c" * 32)
    old = Ed25519Signer(b"\x1d" * 32)
    replacement = Ed25519Signer(b"\x1e" * 32)
    log = RunLog.start(
        principal=buyer.identity,
        seller_url="http://seller",
        listing_id="listing-3",
        publisher_id="publisher-3",
        source_registry_url="http://registry",
        source_registry_authority="registry",
        publisher_principals=_trust(old).model_dump(mode="json"),
        initial_price=10,
        max_price=12,
    )
    log.event(
        "negotiation_round",
        round=0,
        our_message={"action": "initial"},
        their_reply={"negotiation_id": "neg-3", "action": "counter"},
    )

    point = load_negotiation_resume_point(
        log.run_id,
        signer=buyer,
        refresh_publisher_principals=lambda *_binding: _trust(replacement),
    )
    events = read_run(log.run_id, signer=buyer)

    assert point.publisher_principals == _trust(replacement)
    assert events[-1]["event"] == "publisher_trust_refreshed"
    assert events[-1]["publisher_principals"] == _trust(replacement).model_dump(
        mode="json"
    )


def test_recovery_rejects_another_valid_signer(monkeypatch, tmp_path) -> None:
    _state_dir(monkeypatch, tmp_path)
    owner = Ed25519Signer(b"\x12" * 32)
    other = Ed25519Signer(b"\x13" * 32)
    log = RunLog.start(principal=owner.identity, command="market buy")

    with pytest.raises(RunLogError, match="does not match"):
        RunLog.open(log.run_id, signer=other)
    with pytest.raises(RunLogError, match="does not match"):
        read_run(log.run_id, signer=other)


def test_signer_secret_fields_are_never_serialized(monkeypatch, tmp_path) -> None:
    _state_dir(monkeypatch, tmp_path)
    signer = Ed25519Signer(b"\x14" * 32)

    with pytest.raises(RunLogError, match="signer secret field"):
        RunLog.start(
            principal=signer.identity,
            buyer_private_key="must-not-be-written",
        )

    assert not list(runs_dir().glob("*.jsonl"))
    config_repr = repr(IdentityConfig(principal=signer.identity))
    assert "private" not in config_repr.lower()
    assert "credential" not in config_repr.lower()


def test_run_log_rejects_resolved_settlement_config_snapshots(
    monkeypatch,
    tmp_path,
) -> None:
    _state_dir(monkeypatch, tmp_path)
    signer = Ed25519Signer(b"\x15" * 32)

    with pytest.raises(RunLogError, match="signer secret field"):
        RunLog.start(
            principal=signer.identity,
            settlement_config={
                "priority": ["fiat.stripe.v1"],
                "stripe": {"provider_secret": "must-not-be-written"},
            },
        )

    assert not list(runs_dir().glob("*.jsonl"))


def test_legacy_eip191_address_migrates_atomically(monkeypatch, tmp_path) -> None:
    directory = _state_dir(monkeypatch, tmp_path)
    run_id = "legacy-run"
    address = "0xAAbbccDDeeFf0011223344556677889900AaBbCc"
    path = directory / f"{run_id}.jsonl"
    legacy = [
        {
            "ts": "2026-01-01T00:00:00+00:00",
            "run_id": run_id,
            "event": "run_started",
            "buyer_address": address,
            "seller_url": "http://seller",
        },
        {
            "ts": "2026-01-01T00:00:01+00:00",
            "run_id": run_id,
            "event": "negotiation_round",
            "our_message": {"buyer_address": address, "action": "exit"},
        },
    ]
    path.write_text("".join(json.dumps(event) + "\n" for event in legacy))

    migrated = read_run(run_id)
    persisted = [json.loads(line) for line in path.read_text().splitlines()]

    assert migrated == persisted
    assert {event["log_version"] for event in migrated} == {RUN_LOG_VERSION}
    assert {event["signature_protocol"] for event in migrated} == {REQUEST_PROTOCOL}
    assert migrated[0]["buyer_principal"] == {
        "scheme": "eip191",
        "identifier": address.lower(),
    }
    assert (
        migrated[1]["our_message"]["buyer_principal"] == migrated[0]["buyer_principal"]
    )
    assert "buyer_address" not in path.read_text()
    assert not list(directory.glob("*.tmp"))


def test_malformed_legacy_population_fails_without_rewrite(
    monkeypatch, tmp_path
) -> None:
    directory = _state_dir(monkeypatch, tmp_path)
    run_id = "unsafe-run"
    path = directory / f"{run_id}.jsonl"
    original = (
        json.dumps(
            {
                "run_id": run_id,
                "event": "run_started",
                "buyer_address": "not-an-address",
            }
        )
        + "\n"
    )
    path.write_text(original)

    with pytest.raises(RunLogError, match="malformed buyer_address"):
        read_run(run_id)

    assert path.read_text() == original


def test_unknown_or_partially_migrated_versions_fail_closed(
    monkeypatch, tmp_path
) -> None:
    directory = _state_dir(monkeypatch, tmp_path)
    signer = Ed25519Signer(b"\x15" * 32)
    run_id = "unknown-run"
    path = directory / f"{run_id}.jsonl"
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "event": "run_started",
                "log_version": 99,
                "signature_protocol": REQUEST_PROTOCOL,
                "buyer_principal": signer.identity.model_dump(mode="json"),
            }
        )
        + "\n"
    )

    with pytest.raises(RunLogError, match="unsupported or inconsistent"):
        read_run(run_id)


def test_partially_versioned_legacy_log_is_not_guessed(monkeypatch, tmp_path) -> None:
    directory = _state_dir(monkeypatch, tmp_path)
    run_id = "partial-run"
    path = directory / f"{run_id}.jsonl"
    original = (
        json.dumps(
            {
                "run_id": run_id,
                "event": "run_started",
                "buyer_address": "0x" + "ab" * 20,
                "signature_protocol": "unknown",
            }
        )
        + "\n"
    )
    path.write_text(original)

    with pytest.raises(RunLogError, match="partially or unsafely versioned"):
        read_run(run_id)

    assert path.read_text() == original


def test_configured_principal_must_match_resolved_credential() -> None:
    expected = Ed25519Signer(b"\x16" * 32)
    config = IdentityConfig(principal=expected.identity)

    assert resolve_buyer_signer(config, b"\x16" * 32).identity == expected.identity
    with pytest.raises(ValueError, match="does not match"):
        resolve_buyer_signer(config, b"\x17" * 32)


def test_public_identity_and_secret_credential_resolve_separately() -> None:
    signer = Ed25519Signer(b"\x1b" * 32)
    config = resolve_identity_config(
        override_scheme="ed25519",
        override_identifier=signer.identity.identifier,
    )

    assert config.principal == signer.identity
    assert (
        resolve_identity_credential({"ARKHAI_IDENTITY_CREDENTIAL": "secret-only-value"})
        == "secret-only-value"
    )
    with pytest.raises(RuntimeError, match="ARKHAI_IDENTITY_CREDENTIAL"):
        resolve_identity_credential({})
