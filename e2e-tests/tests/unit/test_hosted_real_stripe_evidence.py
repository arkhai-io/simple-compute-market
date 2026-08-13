from __future__ import annotations

import json
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from src.hosted_real_stripe.evidence import (
    CollectionEvidence,
    EvidenceValidationError,
    HostedReleaseIdentityEvidence,
    IdentityEvidence,
    MarketplaceIdentityEvidence,
    ProviderEvidence,
    StripeTestEvidence,
    opaque_ref,
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
DIGEST = "sha256:" + "b" * 64
IMAGE = "sha256:" + "c" * 64
WHEEL = "sha256:" + "e" * 64


def _identities() -> IdentityEvidence:
    return IdentityEvidence(
        marketplace=MarketplaceIdentityEvidence(
            repository="arkhai/simple-market-service", commit=COMMIT
        ),
        hosted_release=HostedReleaseIdentityEvidence(
            repository="arkhai/hosted-settlement-service",
            source_commit=HOSTED_COMMIT,
            workflow_run_id="123456",
            workflow_ref=".github/workflows/release.yml@main",
            manifest_sha256=DIGEST,
            client_wheel_sha256=WHEEL,
            image_digest=IMAGE,
        ),
        run_ref=opaque_ref("run", "trusted-run-identity"),
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
    compose_env = tmp_path / "hosted.env"
    compose_env.write_text(
        "\n".join(
            (
                "HOSTED_SETTLEMENT_VERIFIED_IMAGE=registry.example/authority@" + IMAGE,
                "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256=" + DIGEST,
                "HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256=" + WHEEL,
                "HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR=/verified/release",
                "HOSTED_SETTLEMENT_VERIFIED_SOURCE_COMMIT=" + HOSTED_COMMIT,
                "HOSTED_SETTLEMENT_VERIFIED_REPOSITORY=arkhai/hosted-settlement-service",
                "HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF=.github/workflows/release.yml@main",
                "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_DIGEST=" + DIGEST,
                "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ID=hosted-authority",
                "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_SCHEME=eip191",
                "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ADDRESS=0x" + "1" * 40,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    identity = require_release_identity(
        marketplace_commit=COMMIT,
        observed_marketplace_commit=COMMIT,
        hosted_source_commit=HOSTED_COMMIT,
        hosted_workflow_run_id="123456",
        hosted_workflow_ref=".github/workflows/release.yml@main",
        hosted_manifest_sha256=DIGEST,
        hosted_client_wheel_sha256=WHEEL,
        hosted_image_digest=IMAGE,
        compose_env_path=compose_env,
    )
    assert identity.hosted_image_digest == IMAGE
    with pytest.raises(ReleaseIdentityRejected):
        require_release_identity(
            marketplace_commit=COMMIT,
            observed_marketplace_commit="f" * 40,
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


def test_evidence_is_allowlisted_private_and_rejects_provider_values(tmp_path: Path) -> None:
    collection = _collection()
    report = StripeTestEvidence(
        identities=_identities(),
        provider=ProviderEvidence(connected_account_ready=True, loopback_webhook_verified=True),
        scenario="collection",
        result="passed",
        stage="complete",
        operation_ref=collection.operation_ref,
        collection=collection,
    )
    output = tmp_path / "evidence.json"
    write_evidence(output, report)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "arkhai.hosted-settlement-stripe-test-evidence.v2"
    assert payload["lane"] == "stripe-test"
    assert (
        payload["identities"]["marketplace"]["repository"]
        != payload["identities"]["hosted_release"]["repository"]
    )
    assert "simulat" not in output.read_text(encoding="utf-8").lower()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    unsafe = replace(report, operation_ref="acct_provider_identifier")
    with pytest.raises(EvidenceValidationError):
        write_evidence(tmp_path / "unsafe.json", unsafe)
