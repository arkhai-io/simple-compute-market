from __future__ import annotations

import json
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from src.hosted_real_stripe.evidence import (
    CollectionEvidence,
    EvidenceValidationError,
    IdentityEvidence,
    ProviderEvidence,
    RealStripeEvidence,
    RefundEvidence,
    UnavailableEvidence,
    write_evidence,
)
from src.hosted_real_stripe.gates import (
    AuthorizationRejected,
    AuthorizationUnavailable,
    ReleaseIdentityRejected,
    require_loopback_webhook,
    require_ready_account,
    require_release_identity,
    require_test_secret,
)
from src.hosted_real_stripe.runtime import EphemeralServiceEnv

COMMIT = "a" * 40
HOSTED_COMMIT = "d" * 40
HOSTED_RUN_ID = "123456"
MANIFEST = "sha256:" + "b" * 64
IMAGE_DIGEST = "sha256:" + "c" * 64


def _identities() -> IdentityEvidence:
    return IdentityEvidence(
        marketplace_repository="arkhai/simple-market-service",
        marketplace_commit=COMMIT,
        hosted_repository="arkhai/hosted-settlement-service",
        hosted_source_commit=HOSTED_COMMIT,
        hosted_workflow_run_id=HOSTED_RUN_ID,
        hosted_manifest_sha256=MANIFEST,
        hosted_image_digest=IMAGE_DIGEST,
    )


def _collection() -> CollectionEvidence:
    return CollectionEvidence(
        operation_ref="market-operation-001",
        checkout_count=1,
        transfer_count=1,
        amount=1250,
        currency="usd",
        destination_matches=True,
        transfer_group_matches=True,
        source_transaction_matches=True,
        operation_metadata_matches=True,
        marketplace_state="collected",
        authority_state="collected",
        fulfillment_state="ready",
    )


def test_test_mode_gate_rejects_missing_live_and_malformed_credentials() -> None:
    with pytest.raises(AuthorizationUnavailable):
        require_test_secret(None)
    for value in ("sk_live_private", "rk_live_private", "sk_test_bad value", "not-a-key"):
        with pytest.raises(AuthorizationRejected):
            require_test_secret(value)
    assert require_test_secret("sk_test_private") == "sk_test_private"
    assert require_test_secret("rk_test_restricted") == "rk_test_restricted"


def test_release_gate_requires_exact_generated_manifest_and_digest_image(tmp_path: Path) -> None:
    compose_env = tmp_path / "hosted.env"
    compose_env.write_text(
        "HOSTED_SETTLEMENT_VERIFIED_IMAGE=registry.example/authority@" + IMAGE_DIGEST + "\n"
        "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256=" + MANIFEST + "\n",
        encoding="utf-8",
    )
    identity = require_release_identity(
        marketplace_commit=COMMIT,
        hosted_source_commit=HOSTED_COMMIT,
        hosted_workflow_run_id=HOSTED_RUN_ID,
        hosted_manifest_sha256=MANIFEST,
        compose_env_path=compose_env,
    )
    assert identity.hosted_image_digest == IMAGE_DIGEST

    compose_env.write_text(
        "HOSTED_SETTLEMENT_VERIFIED_IMAGE=registry.example/authority:latest\n"
        "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256=" + MANIFEST + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ReleaseIdentityRejected):
        require_release_identity(
            marketplace_commit=COMMIT,
            hosted_source_commit=HOSTED_COMMIT,
            hosted_workflow_run_id=HOSTED_RUN_ID,
            hosted_manifest_sha256=MANIFEST,
            compose_env_path=compose_env,
        )


def test_account_gate_requires_test_mode_ready_controller_compatible_account() -> None:
    account = {
        "id": "acct_protected",
        "livemode": False,
        "charges_enabled": True,
        "payouts_enabled": True,
        "details_submitted": True,
        "controller": {
            "requirement_collection": "application",
            "stripe_dashboard": {"type": "express"},
        },
    }
    require_ready_account(account, "acct_protected")
    for field in ("charges_enabled", "payouts_enabled", "details_submitted"):
        with pytest.raises(AuthorizationUnavailable):
            require_ready_account({**account, field: False}, "acct_protected")
    with pytest.raises(AuthorizationUnavailable):
        require_ready_account({**account, "livemode": True}, "acct_protected")


def test_webhook_forwarding_is_loopback_only() -> None:
    assert (
        require_loopback_webhook("http://127.0.0.1:18080/webhooks/stripe")
        == "http://127.0.0.1:18080/webhooks/stripe"
    )
    for value in (
        "https://authority.example/webhooks/stripe",
        "http://0.0.0.0:18080/webhooks/stripe",
        "http://localhost:18080/admin",
        "http://localhost/webhooks/stripe",
    ):
        with pytest.raises(AuthorizationRejected):
            require_loopback_webhook(value)


def test_report_is_external_allowlisted_and_contains_no_provider_identifiers(tmp_path: Path) -> None:
    report = RealStripeEvidence(
        identities=_identities(),
        provider=ProviderEvidence(connected_account_ready=True),
        outcome="passed",
        collection=_collection(),
        refund=RefundEvidence(outcome="not_requested"),
    )
    output = tmp_path / "evidence.json"
    write_evidence(output, report)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema",
        "lane",
        "identities",
        "provider",
        "outcome",
        "collection",
        "refund",
        "unavailable",
        "failure",
    }
    assert payload["schema"] == "arkhai.hosted-settlement-real-stripe-evidence.v1"
    assert payload["lane"] == "external"
    assert payload["provider"] == {
        "name": "stripe",
        "mode": "test",
        "connected_account_ready": True,
    }
    assert "simulated" not in output.read_text(encoding="utf-8").lower()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_json_schema_exposes_only_the_report_allowlist() -> None:
    schema_path = (
        Path(__file__).parents[2] / "src/hosted_real_stripe/evidence.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "schema",
        "lane",
        "identities",
        "provider",
        "outcome",
        "collection",
        "refund",
        "unavailable",
        "failure",
    }
    assert schema["properties"]["lane"] == {"const": "external"}
    assert schema["properties"]["provider"]["properties"]["mode"] == {"const": "test"}


@pytest.mark.parametrize(
    "operation_ref",
    (
        "sk_test_forbidden",
        "whsec_forbidden",
        "acct_forbidden",
        "cs_forbidden",
        "https://checkout.stripe.com/c/pay/test",
    ),
)
def test_report_rejects_secrets_urls_and_provider_ids(
    tmp_path: Path, operation_ref: str
) -> None:
    collection = replace(_collection(), operation_ref=operation_ref)
    report = RealStripeEvidence(
        identities=_identities(),
        provider=ProviderEvidence(connected_account_ready=True),
        outcome="passed",
        collection=collection,
    )
    with pytest.raises(EvidenceValidationError):
        write_evidence(tmp_path / "evidence.json", report)


def test_unavailable_external_evidence_cannot_masquerade_as_success(tmp_path: Path) -> None:
    report = RealStripeEvidence(
        identities=_identities(),
        provider=ProviderEvidence(),
        outcome="unavailable",
        unavailable=UnavailableEvidence(
            phase="authorization", code="credentials_missing"
        ),
    )
    output = tmp_path / "evidence.json"
    write_evidence(output, report)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["outcome"] == "unavailable"
    assert payload["collection"] is None
    assert payload["unavailable"] == {
        "phase": "authorization",
        "code": "credentials_missing",
    }


def test_authority_secret_env_is_ephemeral_mode_0600_and_ordinary_contract_only(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.env"
    base.write_text("HOSTED_SETTLEMENT_DATABASE_URL=sqlite:////data/db.sqlite\n", encoding="utf-8")
    env = EphemeralServiceEnv(
        api_key="sk_test_private",
        webhook_secret="whsec_private",
        base_path=base,
    )
    with env as path:
        contents = path.read_text(encoding="utf-8")
        assert "HOSTED_SETTLEMENT_PROVIDER_KIND=stripe" in contents
        assert "HOSTED_SETTLEMENT_STRIPE_MODE=test" in contents
        assert "HOSTED_SETTLEMENT_STRIPE_SECRET_KEY=sk_test_private" in contents
        assert "HOSTED_SETTLEMENT_STRIPE_WEBHOOK_SECRET=whsec_private" in contents
        assert "CONNECTED_ACCOUNT" not in contents
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.exists()
