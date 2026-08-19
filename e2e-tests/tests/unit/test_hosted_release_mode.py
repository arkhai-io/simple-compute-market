"""Provenance classifies a run; it does not decide whether the body may run."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.hosted_real_stripe.driver import _parser
from src.hosted_real_stripe.evidence import (
    HostedReleaseIdentityEvidence,
    IdentityEvidence,
    MarketplaceIdentityEvidence,
)
from src.hosted_real_stripe.gates import (
    LOCAL_COORDINATE,
    AuthorizationRejected,
    AuthorizationUnavailable,
    ReleaseIdentityRejected,
    local_release_identity,
    require_connected_account,
    require_loopback_webhook,
    require_release_identity,
    require_test_secret,
)

DIGEST = "sha256:" + "a" * 64
IMAGE = "sha256:" + "c" * 64
WHEEL = "sha256:" + "d" * 64
MARKET_DIGEST = "sha256:" + "e" * 64
MARKET_IMAGE = "sha256:" + "f" * 64
HOSTED_COMMIT = "a" * 40
TRUSTED_COMMIT = "c" * 40
OBSERVED_COMMIT = "b" * 40
MARKET_REF = ".github/workflows/publish.yml@refs/tags/v0.2.0"

_HOSTED_ENV = (
    "HOSTED_SETTLEMENT_VERIFIED_IMAGE=registry.example/authority@" + IMAGE,
    "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256=" + DIGEST,
    "HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256=" + WHEEL,
    "HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR=/verified/release",
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
    "HOSTED_SETTLEMENT_VERIFIED_CONFORMANCE_SHA256=" + DIGEST,
    "HOSTED_SETTLEMENT_VERIFIED_MIGRATIONS_SHA256=" + DIGEST,
    "HOSTED_SETTLEMENT_VERIFIED_OPENAPI_SHA256=" + DIGEST,
    "HOSTED_SETTLEMENT_VERIFIED_PROVENANCE_SHA256=" + DIGEST,
    "HOSTED_SETTLEMENT_VERIFIED_SERVICE_WHEEL_SHA256=" + DIGEST,
    "HOSTED_SETTLEMENT_VERIFIED_FUNDING_PROFILES=card.v1,us_bank_transfer.v1,us_ach_debit.v1",
    "HOSTED_SETTLEMENT_VERIFIED_CAPABILITIES=scheme-tagged-identities.v1,"
    "account-owner-admission.v1,account-owner-rotation.v1,"
    "account-owner-retirement.v1,signer-injected-client.v1,"
    "provider-neutral-seller-onboarding.v1,conditional-escrow.v2,"
    "stripe-connect-separate-charges-transfers.v2,portable-attestation.v1,"
    "eas-arbiter.v1,payer-profile.v1,funding-authorization.v1,"
    "funding-profile.card.v1,funding-profile.us_bank_transfer.v1,"
    "funding-profile.us_ach_debit.v1,normalized-funding-reversal.v1,"
    "operator-recovery-redaction.v1",
)


#: A locally rendered environment is structurally complete -- every allowlisted
#: key is present -- and simply has nothing to say for the coordinates a local
#: build has no released source for.
_LOCAL_MARKETPLACE = {
    "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_PROVENANCE_SHA256": "",
    "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_SCHEMA_SHA256": "",
    "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_WHEELHOUSE_SHA256": "",
    "HOSTED_MARKETPLACE_VERIFIED_IMAGE": "",
    "HOSTED_MARKETPLACE_VERIFIED_MANIFEST_SHA256": "",
    "HOSTED_MARKETPLACE_VERIFIED_REPOSITORY": "arkhai-io/simple-compute-market",
    "HOSTED_MARKETPLACE_VERIFIED_SOURCE_COMMIT": "",
    "HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_REF": "",
    "HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_RUN_ID": "",
}


def _compose_env(tmp_path: Path, **marketplace: str) -> Path:
    values = {**_LOCAL_MARKETPLACE, **marketplace}
    path = tmp_path / "hosted.env"
    lines = [*_HOSTED_ENV, *(f"{key}={value}" for key, value in values.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _local(tmp_path: Path, *, observed: str = OBSERVED_COMMIT, **overrides):
    arguments = {
        "observed_marketplace_commit": observed,
        "hosted_source_commit": HOSTED_COMMIT,
        "hosted_workflow_run_id": "123456",
        "hosted_workflow_ref": ".github/workflows/release.yml@main",
        "hosted_manifest_sha256": DIGEST,
        "hosted_client_wheel_sha256": WHEEL,
        "hosted_image_digest": IMAGE,
        "compose_env_path": _compose_env(tmp_path),
    }
    arguments.update(overrides)
    return local_release_identity(**arguments)


def test_a_development_run_records_its_own_commit_and_says_it_is_local(tmp_path) -> None:
    identity = _local(tmp_path)

    assert identity.mode == "local"
    assert identity.marketplace_commit == OBSERVED_COMMIT
    # No attested marketplace coordinate exists for a locally built stack, and
    # the record says so rather than inventing or omitting one.
    assert identity.marketplace_image_digest == LOCAL_COORDINATE
    assert identity.marketplace_manifest_sha256 == LOCAL_COORDINATE
    assert identity.marketplace_workflow_run_id == LOCAL_COORDINATE


def test_a_development_run_binds_the_released_producer_exactly(tmp_path) -> None:
    """Only the marketplace half is locally built; the producer is still signed."""

    identity = _local(tmp_path)

    assert identity.hosted_image_digest == IMAGE
    assert identity.hosted_manifest_sha256 == DIGEST
    assert identity.hosted_authority_scheme == "eip191"

    with pytest.raises(ReleaseIdentityRejected):
        _local(tmp_path, hosted_image_digest="sha256:" + "0" * 64)
    with pytest.raises(ReleaseIdentityRejected):
        _local(tmp_path, hosted_source_commit="f" * 40)
    with pytest.raises(ReleaseIdentityRejected):
        _local(tmp_path, hosted_workflow_run_id="not-a-run")


def test_a_development_run_still_needs_a_real_working_tree_commit(tmp_path) -> None:
    with pytest.raises(ReleaseIdentityRejected):
        _local(tmp_path, observed="not-a-commit")


def _attested_env(tmp_path: Path) -> Path:
    return _compose_env(
        tmp_path,
        HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_PROVENANCE_SHA256=DIGEST,
        HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_SCHEMA_SHA256=DIGEST,
        HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_WHEELHOUSE_SHA256=DIGEST,
        HOSTED_MARKETPLACE_VERIFIED_IMAGE="registry.example/marketplace@" + MARKET_IMAGE,
        HOSTED_MARKETPLACE_VERIFIED_MANIFEST_SHA256=MARKET_DIGEST,
        HOSTED_MARKETPLACE_VERIFIED_SOURCE_COMMIT=TRUSTED_COMMIT,
        HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_REF=MARKET_REF,
        HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_RUN_ID="654321",
    )


def _attested(tmp_path: Path, **overrides):
    arguments = {
        "marketplace_commit": TRUSTED_COMMIT,
        "observed_marketplace_commit": TRUSTED_COMMIT,
        "marketplace_workflow_run_id": "654321",
        "marketplace_workflow_ref": MARKET_REF,
        "marketplace_manifest_sha256": MARKET_DIGEST,
        "marketplace_image_digest": MARKET_IMAGE,
        "hosted_source_commit": HOSTED_COMMIT,
        "hosted_workflow_run_id": "123456",
        "hosted_workflow_ref": ".github/workflows/release.yml@main",
        "hosted_manifest_sha256": DIGEST,
        "hosted_client_wheel_sha256": WHEEL,
        "hosted_image_digest": IMAGE,
        "compose_env_path": _attested_env(tmp_path),
    }
    arguments.update(overrides)
    return require_release_identity(**arguments)


def test_an_attested_run_is_recorded_as_attested(tmp_path) -> None:
    assert _attested(tmp_path).mode == "attested"


def test_a_protected_run_fails_closed_rather_than_downgrading(tmp_path) -> None:
    """A branch cannot become evidence by failing the commit check."""

    with pytest.raises(ReleaseIdentityRejected):
        _attested(tmp_path, observed_marketplace_commit=OBSERVED_COMMIT)


def test_safety_gates_are_not_mode_aware() -> None:
    """They take no mode, so no run can be configured out of them."""

    with pytest.raises(AuthorizationRejected):
        require_test_secret("sk_live_private")
    with pytest.raises(AuthorizationUnavailable):
        require_test_secret(None)
    with pytest.raises(AuthorizationRejected):
        require_loopback_webhook("https://authority.example/webhooks/stripe")
    with pytest.raises(AuthorizationRejected):
        require_connected_account("not-an-account")


def test_the_driver_defaults_to_attested_and_accepts_local() -> None:
    parser = _parser()
    base = [
        "--compose-env", "compose.env",
        "--hosted-manifest-sha256", DIGEST,
        "--hosted-client-wheel-sha256", WHEEL,
        "--hosted-image-digest", IMAGE,
        "--hosted-source-commit", HOSTED_COMMIT,
        "--hosted-workflow-run-id", "123456",
        "--hosted-workflow-ref", ".github/workflows/release.yml@main",
        "--observed-marketplace-commit", OBSERVED_COMMIT,
        "--run-identity", "trusted-run-identity",
        "--scenario", "collection",
        "--funding-profile", "card.v1",
        "--interaction", "interactive",
        "--evidence", "evidence.json",
        "--account-ref", "acct_1TestAccount",
        "--authority-environment", "hosted-stripe-test",
    ]

    assert parser.parse_args(base).release_mode == "attested"
    assert parser.parse_args([*base, "--release-mode", "local"]).release_mode == "local"
    with pytest.raises(SystemExit):
        parser.parse_args([*base, "--release-mode", "attested-ish"])


def test_evidence_knows_which_runs_may_be_cited() -> None:
    marketplace = MarketplaceIdentityEvidence(
        repository="arkhai-io/simple-compute-market",
        commit=TRUSTED_COMMIT,
        workflow_run_id="654321",
        workflow_ref=MARKET_REF,
        manifest_sha256=MARKET_DIGEST,
        image_digest=MARKET_IMAGE,
        image="registry.example/marketplace@" + MARKET_IMAGE,
        wheelhouse_sha256=DIGEST,
        settlement_config_schema_sha256=DIGEST,
        provenance_sha256=DIGEST,
    )
    hosted = HostedReleaseIdentityEvidence(
        repository="arkhai-io/stripe-settlement-service",
        source_commit=HOSTED_COMMIT,
        workflow_run_id="123456",
        workflow_ref=".github/workflows/release.yml@main",
        manifest_sha256=DIGEST,
        client_wheel_sha256=WHEEL,
        image_digest=IMAGE,
    )
    attested = IdentityEvidence(
        marketplace=marketplace, hosted_release=hosted, run_ref="run_abc"
    )

    assert attested.release_mode == "attested"
    assert attested.qualifies is True
    assert not IdentityEvidence(
        marketplace=marketplace,
        hosted_release=hosted,
        run_ref="run_abc",
        release_mode="local",
    ).qualifies


def test_a_development_run_can_read_what_a_protected_run_must_not(tmp_path) -> None:
    """The staged output that names the failure is exactly what leaks."""

    import sys

    from src.hosted_real_stripe.runtime import MarketplaceLifecycleSession, ProcessUnavailable

    # Writes to stderr and exits at once, which is how a bridge that dies on
    # startup behaves: stdout reaches EOF before stderr has been drained.
    command = [
        sys.executable,
        "-c",
        (
            "import sys; print('a payer profile could not be created', file=sys.stderr);"
            "sys.stderr.flush()"
        ),
    ]

    protected = MarketplaceLifecycleSession(command, cwd=tmp_path, request_timeout=10.0)
    protected.start()
    try:
        with pytest.raises(ProcessUnavailable) as refused:
            protected.request("ensure_payer_profile_fixture")
    finally:
        protected.stop()
    assert "payer profile could not be created" not in str(refused.value)

    development = MarketplaceLifecycleSession(
        command,
        cwd=tmp_path,
        request_timeout=10.0,
        retain_diagnostics=True,
    )
    development.start()
    try:
        with pytest.raises(ProcessUnavailable) as disclosed:
            development.request("ensure_payer_profile_fixture")
    finally:
        development.stop()
    assert "payer profile could not be created" in str(disclosed.value)


def test_only_a_development_run_prints_the_failure_behind_the_code(capsys) -> None:
    """Nothing but the proven mode may turn the disclosure on."""

    from src.hosted_real_stripe.driver import _disclose
    from src.hosted_real_stripe.runtime import ProcessUnavailable

    cause = RuntimeError("the storefront never registered a payer profile")
    caught = ProcessUnavailable("marketplace lifecycle state was unavailable")
    caught.__cause__ = cause

    _disclose(caught, mode="attested", stage="payer_profile", code="payer_profile_unavailable")
    assert capsys.readouterr().err == ""

    _disclose(caught, mode="local", stage="payer_profile", code="payer_profile_unavailable")
    printed = capsys.readouterr().err
    assert "payer_profile -> payer_profile_unavailable" in printed
    assert "marketplace lifecycle state was unavailable" in printed
    # The cause chain is what a stage-level code otherwise throws away.
    assert "the storefront never registered a payer profile" in printed


def test_the_driver_asks_for_the_tail_only_when_the_run_is_local() -> None:
    """The session is constructed from the proven mode, not from the flag."""

    source = (
        Path(__file__).resolve().parents[2] / "src" / "hosted_real_stripe" / "driver.py"
    ).read_text(encoding="utf-8")

    assert 'retain_diagnostics=release.mode == "local"' in source


def test_a_run_does_not_inherit_the_previous_run_authority_state() -> None:
    """One run, one authority database — a second bind is a hard conflict."""

    source = (
        Path(__file__).resolve().parents[2] / "src" / "hosted_real_stripe" / "runtime.py"
    ).read_text(encoding="utf-8")

    assert '"down", "--remove-orphans", "--volumes"' in source
