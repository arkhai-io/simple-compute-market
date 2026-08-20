from __future__ import annotations

import hashlib
import base64
import json
import stat
from dataclasses import replace
from pathlib import Path

import pytest
from market_identity import Ed25519Signer

from src.hosted_real_stripe.evidence import (
    CollectionEvidence,
    EvidenceValidationError,
    FundingEvidence,
    HostedReleaseIdentityEvidence,
    IdentityEvidence,
    MarketplaceIdentityEvidence,
    ProviderEvidence,
    StripeTestEvidence,
    opaque_ref,
    verify_evidence_signature,
    write_evidence,
)
from src.hosted_real_stripe.gates import (
    AuthorizationRejected,
    AuthorizationUnavailable,
    ReleaseIdentityRejected,
    require_loopback_webhook,
    require_ready_account,
    require_release_identity,
    require_run_identity,
    require_test_secret,
)

COMMIT = "a" * 40
HOSTED_COMMIT = "d" * 40
CAPABILITIES = (
    "scheme-tagged-identities.v1",
    "account-owner-admission.v1",
    "account-owner-rotation.v1",
    "account-owner-retirement.v1",
    "signer-injected-client.v1",
    "provider-neutral-seller-onboarding.v1",
    "conditional-escrow.v2",
    "stripe-connect-separate-charges-transfers.v2",
    "portable-attestation.v1",
    "eas-arbiter.v1",
    "payer-profile.v1",
    "funding-authorization.v1",
    "funding-profile.card.v1",
    "funding-profile.us_bank_transfer.v1",
    "funding-profile.us_ach_debit.v1",
    "normalized-funding-reversal.v1",
    "operator-recovery-redaction.v1",
)
DIGEST = "sha256:" + "b" * 64
IMAGE = "sha256:" + "c" * 64
WHEEL = "sha256:" + "e" * 64
MARKET_DIGEST = "sha256:" + "f" * 64
MARKET_IMAGE = "sha256:" + "0" * 64


def _identities() -> IdentityEvidence:
    return IdentityEvidence(
        marketplace=MarketplaceIdentityEvidence(
            repository="arkhai-io/simple-compute-market",
            commit=COMMIT,
            workflow_run_id="654321",
            workflow_ref=".github/workflows/publish.yml@refs/tags/v0.2.0",
            manifest_sha256=MARKET_DIGEST,
            image_digest=MARKET_IMAGE,
            image="ghcr.io/arkhai-io/simple-compute-market@" + MARKET_IMAGE,
            wheelhouse_sha256="sha256:" + "1" * 64,
            settlement_config_schema_sha256="sha256:" + "2" * 64,
            provenance_sha256="sha256:" + "3" * 64,
        ),
        hosted_release=HostedReleaseIdentityEvidence(
            repository="arkhai-io/stripe-settlement-service",
            source_commit=HOSTED_COMMIT,
            workflow_run_id="123456",
            workflow_ref=".github/workflows/release.yml@main",
            manifest_sha256=DIGEST,
            client_wheel_sha256=WHEEL,
            image_digest=IMAGE,
        ),
        run_ref=opaque_ref("run", "trusted-run-identity"),
    )


def _funding() -> FundingEvidence:
    return FundingEvidence(
        profile="card.v1",
        interaction="interactive",
        payer_profile_bound=True,
        authorization_obligation_bound=True,
        authorization_operation_scoped=True,
        accepted_profile_preserved=True,
        authoritative_funding_observed=True,
        transient_action_observed=True,
        delayed_state_observed=False,
    )


def _collection() -> CollectionEvidence:
    operation = opaque_ref("op", "marketplace-operation")
    return CollectionEvidence(
        operation_ref=operation,
        checkout_count=1,
        payment_intent_count=1,
        charge_count=1,
        transfer_count=1,
        amount=1250,
        currency="usd",
        destination_matches=True,
        transfer_group_matches=True,
        source_transaction_matches=True,
        operation_metadata_matches=True,
        marketplace_state="collected",
        authority_state="collected",
        fulfillment_state="fulfilled",
    )


def test_protected_gates_reject_live_credentials_and_non_loopback_webhooks() -> None:
    with pytest.raises(AuthorizationUnavailable):
        require_test_secret(None)
    with pytest.raises(AuthorizationRejected):
        require_test_secret("sk_live_private")
    assert require_test_secret("rk_test_restricted") == "rk_test_restricted"
    assert require_loopback_webhook("http://127.0.0.1:18080/webhooks/stripe").startswith(
        "http://127.0.0.1:"
    )
    with pytest.raises(AuthorizationRejected):
        require_loopback_webhook("https://authority.example/webhooks/stripe")
    assert require_run_identity("trusted-run-identity") == "trusted-run-identity"


def test_release_gate_binds_all_signed_and_observed_identities(tmp_path: Path) -> None:
    # The contract a run asserts is read from the release it bound, so the
    # release's own artifact has to be where the environment says it is.
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    conformance = json.dumps(
        {
            "api_version": "0.2.1",
            "schema_version": 5,
            "funding_profiles": ["card.v1", "us_bank_transfer.v1", "us_ach_debit.v1"],
            "identity_contract": {"capabilities": list(CAPABILITIES)},
        }
    ).encode()
    (release_dir / "conformance-v0.2.1.json").write_bytes(conformance)
    conformance_sha = "sha256:" + hashlib.sha256(conformance).hexdigest()
    compose_env = tmp_path / "hosted.env"
    compose_env.write_text(
        "\n".join(
            (
                "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_PROVENANCE_SHA256=" + DIGEST,
                "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_SCHEMA_SHA256=" + DIGEST,
                "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_WHEELHOUSE_SHA256=" + DIGEST,
                "HOSTED_MARKETPLACE_VERIFIED_IMAGE=registry.example/marketplace@" + MARKET_IMAGE,
                "HOSTED_MARKETPLACE_VERIFIED_MANIFEST_SHA256=" + MARKET_DIGEST,
                "HOSTED_MARKETPLACE_VERIFIED_REPOSITORY=arkhai-io/simple-compute-market",
                "HOSTED_MARKETPLACE_VERIFIED_SOURCE_COMMIT=" + COMMIT,
                "HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_REF=.github/workflows/publish.yml@refs/tags/v0.2.0",
                "HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_RUN_ID=654321",
                "HOSTED_SETTLEMENT_VERIFIED_IMAGE=registry.example/authority@" + IMAGE,
                "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256=" + DIGEST,
                "HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256=" + WHEEL,
                "HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR=" + str(release_dir),
                "HOSTED_SETTLEMENT_VERIFIED_SOURCE_COMMIT=" + HOSTED_COMMIT,
                "HOSTED_SETTLEMENT_VERIFIED_REPOSITORY=arkhai-io/stripe-settlement-service",
                "HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF=.github/workflows/release.yml@main",
                "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_DIGEST=" + DIGEST,
                "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ID=hosted-authority",
                "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_SCHEME=eip191",
                "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ADDRESS=0x" + "1" * 40,
                "HOSTED_SETTLEMENT_VERIFIED_API_VERSION=0.2.1",
                "HOSTED_SETTLEMENT_VERIFIED_SCHEMA_VERSION=5",
                "HOSTED_SETTLEMENT_VERIFIED_RELEASE_VERSION=0.2.1",
                "HOSTED_SETTLEMENT_VERIFIED_CONFORMANCE_SHA256=" + conformance_sha,
                "HOSTED_SETTLEMENT_VERIFIED_MIGRATIONS_SHA256=" + DIGEST,
                "HOSTED_SETTLEMENT_VERIFIED_OPENAPI_SHA256=" + DIGEST,
                "HOSTED_SETTLEMENT_VERIFIED_PROVENANCE_SHA256=" + DIGEST,
                "HOSTED_SETTLEMENT_VERIFIED_SERVICE_WHEEL_SHA256=" + DIGEST,
                "HOSTED_SETTLEMENT_VERIFIED_FUNDING_PROFILES=card.v1,us_bank_transfer.v1,us_ach_debit.v1",
                "HOSTED_SETTLEMENT_VERIFIED_CAPABILITIES=" + ",".join(CAPABILITIES),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    identity = require_release_identity(
        marketplace_commit=COMMIT,
        observed_marketplace_commit=COMMIT,
        marketplace_workflow_run_id="654321",
        marketplace_workflow_ref=".github/workflows/publish.yml@refs/tags/v0.2.0",
        marketplace_manifest_sha256=MARKET_DIGEST,
        marketplace_image_digest=MARKET_IMAGE,
        hosted_source_commit=HOSTED_COMMIT,
        hosted_workflow_run_id="123456",
        hosted_workflow_ref=".github/workflows/release.yml@main",
        hosted_manifest_sha256=DIGEST,
        hosted_client_wheel_sha256=WHEEL,
        hosted_image_digest=IMAGE,
        compose_env_path=compose_env,
    )
    assert identity.hosted_image_digest == IMAGE
    assert identity.marketplace_image == ("registry.example/marketplace@" + MARKET_IMAGE)
    with pytest.raises(ReleaseIdentityRejected):
        require_release_identity(
            marketplace_commit=COMMIT,
            observed_marketplace_commit="f" * 40,
            marketplace_workflow_run_id="654321",
            marketplace_workflow_ref=".github/workflows/publish.yml@refs/tags/v0.2.0",
            marketplace_manifest_sha256=MARKET_DIGEST,
            marketplace_image_digest=MARKET_IMAGE,
            hosted_source_commit=HOSTED_COMMIT,
            hosted_workflow_run_id="123456",
            hosted_workflow_ref=".github/workflows/release.yml@main",
            hosted_manifest_sha256=DIGEST,
            hosted_client_wheel_sha256=WHEEL,
            hosted_image_digest=IMAGE,
            compose_env_path=compose_env,
        )


def test_account_gate_requires_ready_application_controlled_test_account() -> None:
    account = {
        "id": "acct_protected",
        "livemode": False,
        "charges_enabled": True,
        "payouts_enabled": True,
        "details_submitted": True,
        "capabilities": {"card_payments": "active", "transfers": "active"},
        "requirements": {"currently_due": [], "past_due": [], "disabled_reason": None},
        "controller": {
            "fees": {"payer": "application"},
            "is_controller": True,
            "losses": {"payments": "application"},
            "requirement_collection": "stripe",
            "stripe_dashboard": {"type": "express"},
            "type": "application",
        },
    }
    require_ready_account(account, "acct_protected")
    with pytest.raises(AuthorizationUnavailable):
        require_ready_account({**account, "payouts_enabled": False}, "acct_protected")


def test_account_gate_accepts_transfer_only_application_controlled_account() -> None:
    require_ready_account(
        {
            "id": "acct_protected",
            "livemode": None,
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
            "capabilities": {"transfers": "active"},
            "requirements": {"currently_due": [], "past_due": [], "disabled_reason": None},
            "controller": {
                "fees": {"payer": "application"},
                "is_controller": True,
                "losses": {"payments": "application"},
                "requirement_collection": "stripe",
                "stripe_dashboard": {"type": "express"},
                "type": "application",
            },
        },
        "acct_protected",
    )


def test_evidence_is_allowlisted_private_signed_and_rejects_provider_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed = bytes(range(32))
    signer = Ed25519Signer(seed)
    monkeypatch.setenv(
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_SCHEME",
        "ed25519",
    )
    monkeypatch.setenv(
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_IDENTIFIER",
        signer.identity.identifier,
    )
    monkeypatch.setenv(
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_CREDENTIAL",
        base64.urlsafe_b64encode(seed).rstrip(b"=").decode(),
    )
    collection = _collection()
    report = StripeTestEvidence(
        identities=_identities(),
        provider=ProviderEvidence(connected_account_ready=True, loopback_webhook_verified=True),
        scenario="collection",
        result="passed",
        stage="complete",
        funding=_funding(),
        operation_ref=collection.operation_ref,
        collection=collection,
    )
    output = tmp_path / "evidence.json"
    write_evidence(output, report)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "arkhai.hosted-settlement-stripe-test-evidence.v4"
    assert payload["lane"] == "stripe-test"
    assert (
        payload["identities"]["marketplace"]["repository"]
        != payload["identities"]["hosted_release"]["repository"]
    )
    assert payload["evidence_signature"]["signer"] == signer.identity.model_dump(mode="json")
    verify_evidence_signature(payload, expected_signer=signer.identity)
    modified = dict(payload)
    modified["stage"] = "funding"
    with pytest.raises(EvidenceValidationError, match="signature verification failed"):
        verify_evidence_signature(modified, expected_signer=signer.identity)
    assert "simulat" not in output.read_text(encoding="utf-8").lower()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    unsafe = replace(report, operation_ref="acct_provider_identifier")
    with pytest.raises(EvidenceValidationError):
        write_evidence(tmp_path / "unsafe.json", unsafe)

    leaked = replace(
        report,
        identities=replace(
            report.identities,
            marketplace=replace(
                report.identities.marketplace,
                workflow_ref="https://checkout.stripe.com/action",
            ),
        ),
    )
    with pytest.raises(EvidenceValidationError):
        write_evidence(tmp_path / "leaked.json", leaked)


# ---------------------------------------------------------------------------
# A development run records what it ran
# ---------------------------------------------------------------------------

LOCAL = "local"
BUILD_DIGEST = "sha256:" + "7" * 64


def _local_hosted(**overrides) -> HostedReleaseIdentityEvidence:
    """The producer half exactly as the binding gate leaves it for a build."""

    base = dict(
        repository="arkhai-io/stripe-settlement-service",
        source_commit=LOCAL,
        workflow_run_id=LOCAL,
        workflow_ref=LOCAL,
        manifest_sha256=LOCAL,
        client_wheel_sha256=LOCAL,
        image_digest=LOCAL,
        image="localhost/arkhai-hosted-settlement-service:0.3.0",
        manifest_digest=BUILD_DIGEST,
    )
    base.update(overrides)
    return HostedReleaseIdentityEvidence(**base)


def _development_report(hosted: HostedReleaseIdentityEvidence) -> StripeTestEvidence:
    collection = _collection()
    identities = replace(
        _identities(),
        hosted_release=hosted,
        release_mode="local",
        marketplace=replace(
            _identities().marketplace,
            image="localhost/arkhai:storefront",
        ),
    )
    return StripeTestEvidence(
        identities=identities,
        provider=ProviderEvidence(connected_account_ready=True, loopback_webhook_verified=True),
        scenario="collection",
        result="passed",
        stage="complete",
        funding=_funding(),
        operation_ref=collection.operation_ref,
        collection=collection,
    )


def _signing_env(monkeypatch) -> None:
    seed = bytes(range(32))
    signer = Ed25519Signer(seed)
    monkeypatch.setenv("HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_SCHEME", "ed25519")
    monkeypatch.setenv(
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_IDENTIFIER", signer.identity.identifier
    )
    monkeypatch.setenv(
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_CREDENTIAL",
        base64.urlsafe_b64encode(seed).rstrip(b"=").decode(),
    )


def test_a_development_run_records_the_build_it_ran(tmp_path: Path, monkeypatch) -> None:
    """A run the binding gate admitted must be able to record itself.

    Refusing here discards the whole run: the scenario has already executed,
    and the report is the only thing that says what it found.
    """

    _signing_env(monkeypatch)
    output = tmp_path / "evidence.json"
    write_evidence(output, _development_report(_local_hosted()))
    payload = json.loads(output.read_text(encoding="utf-8"))
    hosted = payload["identities"]["hosted_release"]
    assert payload["identities"]["release_mode"] == "local"
    assert hosted["source_commit"] == LOCAL
    assert hosted["image"] == "localhost/arkhai-hosted-settlement-service:0.3.0"
    assert hosted["manifest_digest"] == BUILD_DIGEST


def test_a_half_that_is_partly_released_and_partly_local_is_refused(
    tmp_path: Path, monkeypatch
) -> None:
    """No admitted run produces that combination, so recording one is a defect."""

    _signing_env(monkeypatch)
    report = _development_report(_local_hosted(source_commit=HOSTED_COMMIT))
    with pytest.raises(EvidenceValidationError, match="partly both"):
        write_evidence(tmp_path / "evidence.json", report)


def test_a_locally_built_producer_that_names_no_image_is_refused(
    tmp_path: Path, monkeypatch
) -> None:
    """Six markers name no producer, and two builds would be indistinguishable."""

    _signing_env(monkeypatch)
    with pytest.raises(EvidenceValidationError, match="name the image"):
        write_evidence(
            tmp_path / "evidence.json", _development_report(_local_hosted(image=""))
        )
    with pytest.raises(EvidenceValidationError, match="build the authority reported"):
        write_evidence(
            tmp_path / "evidence.json",
            _development_report(_local_hosted(manifest_digest="")),
        )


def test_an_attested_producer_half_is_still_required_to_be_exact(
    tmp_path: Path, monkeypatch
) -> None:
    """Admitting builds must not weaken what a release has to prove."""

    _signing_env(monkeypatch)
    collection = _collection()
    hosted = replace(_identities().hosted_release, workflow_run_id="not-a-run-id")
    report = StripeTestEvidence(
        identities=replace(_identities(), hosted_release=hosted),
        provider=ProviderEvidence(connected_account_ready=True, loopback_webhook_verified=True),
        scenario="collection",
        result="passed",
        stage="complete",
        funding=_funding(),
        operation_ref=collection.operation_ref,
        collection=collection,
    )
    with pytest.raises(EvidenceValidationError, match="source, workflow, and run must be exact"):
        write_evidence(tmp_path / "evidence.json", report)
