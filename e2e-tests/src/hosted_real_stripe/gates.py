"""Fail-closed authorization, release, account, and loopback gates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/:~-]*@(?P<digest>sha256:[0-9a-f]{64})$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ACCOUNT = re.compile(r"^acct_[A-Za-z0-9]+$")
_RUN_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
_WORKFLOW_REF = re.compile(r"^[A-Za-z0-9.][A-Za-z0-9._/@:-]{7,255}$")
_AUTHORITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
_EIP191_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_FUNDING_PROFILES = ("card.v1", "us_bank_transfer.v1", "us_ach_debit.v1")
_CAPABILITIES = (
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


class AuthorizationUnavailable(RuntimeError):
    """Required protected-lane authorization was not supplied."""


class AuthorizationRejected(RuntimeError):
    """Supplied authorization could enable a live or untrusted run."""


class ReleaseIdentityRejected(RuntimeError):
    """The consumer or hosted release is not pinned to immutable identities."""


class WebhookRouteUnavailable(RuntimeError):
    """The required loopback webhook route could not be verified."""


#: What a completed run's evidence may claim. Derived from what was actually
#: bound, never from an argument, so no invocation can claim unearned
#: attestation.
ReleaseMode = Literal["attested", "local"]

#: Recorded in place of an attested coordinate that a development stack has no
#: released source for. Self-describing on sight in any report.
LOCAL_COORDINATE = "local"


@dataclass(frozen=True)
class ReleaseIdentity:
    mode: ReleaseMode
    marketplace_commit: str
    marketplace_workflow_run_id: str
    marketplace_workflow_ref: str
    marketplace_manifest_sha256: str
    marketplace_image_digest: str
    marketplace_image: str
    marketplace_wheelhouse_sha256: str
    marketplace_schema_sha256: str
    marketplace_provenance_sha256: str
    hosted_source_commit: str
    hosted_workflow_run_id: str
    hosted_workflow_ref: str
    hosted_manifest_sha256: str
    hosted_manifest_digest: str
    hosted_client_wheel_sha256: str
    hosted_image: str
    hosted_image_digest: str
    hosted_authority_id: str
    hosted_authority_scheme: str
    hosted_authority_address: str


def require_test_secret(secret: str | None) -> str:
    if not secret:
        raise AuthorizationUnavailable("Stripe test credential is unavailable")
    if secret.startswith(("sk_live_", "rk_live_")):
        raise AuthorizationRejected("live Stripe credentials are prohibited")
    if not secret.startswith(("sk_test_", "rk_test_")) or any(char.isspace() for char in secret):
        raise AuthorizationRejected("a protected Stripe test-mode credential is required")
    return secret


def require_connected_account(account_id: str | None) -> str:
    if not account_id:
        raise AuthorizationUnavailable("connected test account is unavailable")
    if not _ACCOUNT.fullmatch(account_id):
        raise AuthorizationRejected("connected account identity has an invalid form")
    return account_id


def require_run_identity(run_identity: str) -> str:
    if not _RUN_IDENTITY.fullmatch(run_identity):
        raise ReleaseIdentityRejected("protected run identity must be exact and bounded")
    return run_identity


def _require_hosted_half(
    values: dict[str, str],
    *,
    hosted_source_commit: str,
    hosted_workflow_run_id: str,
    hosted_workflow_ref: str,
    hosted_manifest_sha256: str,
    hosted_client_wheel_sha256: str,
    hosted_image_digest: str,
) -> tuple[str, str, str, str, str]:
    """Bind the released producer, identically in every mode.

    A development run still consumes the signed hosted release -- only the
    marketplace half is locally built -- so nothing here relaxes.
    """

    if (
        not _COMMIT.fullmatch(hosted_source_commit)
        or not hosted_workflow_run_id.isdigit()
        or not _WORKFLOW_REF.fullmatch(hosted_workflow_ref)
    ):
        raise ReleaseIdentityRejected("hosted producer source, workflow, and run must be exact")
    for value in (hosted_manifest_sha256, hosted_client_wheel_sha256, hosted_image_digest):
        if not _DIGEST.fullmatch(value):
            raise ReleaseIdentityRejected(
                "consumer and hosted release digests must be exact sha256 identities"
            )
    image = values.get("HOSTED_SETTLEMENT_VERIFIED_IMAGE", "")
    match = _IMAGE.fullmatch(image)
    if match is None or match.group("digest") != hosted_image_digest:
        raise ReleaseIdentityRejected("hosted image does not match the trusted digest")
    if values.get("HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256") != hosted_manifest_sha256:
        raise ReleaseIdentityRejected("generated Compose input does not match the trusted manifest")
    if values.get("HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256") != hosted_client_wheel_sha256:
        raise ReleaseIdentityRejected(
            "generated Compose input does not match the trusted client wheel"
        )
    if values.get("HOSTED_SETTLEMENT_VERIFIED_SOURCE_COMMIT") != hosted_source_commit:
        raise ReleaseIdentityRejected("signed release source does not match the trusted commit")
    if values.get("HOSTED_SETTLEMENT_VERIFIED_REPOSITORY") != "arkhai-io/stripe-settlement-service":
        raise ReleaseIdentityRejected("signed release repository is not the hosted producer")
    if values.get("HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF") != hosted_workflow_ref:
        raise ReleaseIdentityRejected("signed release workflow does not match the trusted workflow")
    hosted_artifact_digests = (
        values.get("HOSTED_SETTLEMENT_VERIFIED_CONFORMANCE_SHA256", ""),
        values.get("HOSTED_SETTLEMENT_VERIFIED_MIGRATIONS_SHA256", ""),
        values.get("HOSTED_SETTLEMENT_VERIFIED_OPENAPI_SHA256", ""),
        values.get("HOSTED_SETTLEMENT_VERIFIED_PROVENANCE_SHA256", ""),
        values.get("HOSTED_SETTLEMENT_VERIFIED_SERVICE_WHEEL_SHA256", ""),
    )
    if (
        values.get("HOSTED_SETTLEMENT_VERIFIED_RELEASE_VERSION") != "0.2.1"
        or values.get("HOSTED_SETTLEMENT_VERIFIED_API_VERSION") != "0.2.1"
        or values.get("HOSTED_SETTLEMENT_VERIFIED_SCHEMA_VERSION") != "5"
        or tuple(values.get("HOSTED_SETTLEMENT_VERIFIED_FUNDING_PROFILES", "").split(","))
        != _FUNDING_PROFILES
        or tuple(values.get("HOSTED_SETTLEMENT_VERIFIED_CAPABILITIES", "").split(","))
        != _CAPABILITIES
        or not all(_DIGEST.fullmatch(value) for value in hosted_artifact_digests)
    ):
        raise ReleaseIdentityRejected("generated Compose input is not the exact expanded contract")
    manifest_digest = values["HOSTED_SETTLEMENT_VERIFIED_MANIFEST_DIGEST"]
    authority_id = values["HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ID"]
    authority_scheme = values["HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_SCHEME"]
    authority_address = values["HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ADDRESS"]
    if (
        not _DIGEST.fullmatch(manifest_digest)
        or not _AUTHORITY_ID.fullmatch(authority_id)
        or authority_scheme != "eip191"
        or not _EIP191_ADDRESS.fullmatch(authority_address)
    ):
        raise ReleaseIdentityRejected("signed hosted authority coordinates are invalid")
    return image, manifest_digest, authority_id, authority_scheme, authority_address


def require_release_identity(
    *,
    marketplace_commit: str,
    observed_marketplace_commit: str,
    marketplace_workflow_run_id: str,
    marketplace_workflow_ref: str,
    marketplace_manifest_sha256: str,
    marketplace_image_digest: str,
    hosted_source_commit: str,
    hosted_workflow_run_id: str,
    hosted_workflow_ref: str,
    hosted_manifest_sha256: str,
    hosted_client_wheel_sha256: str,
    hosted_image_digest: str,
    compose_env_path: Path,
) -> ReleaseIdentity:
    """Bind a released consumer to a released producer, or refuse.

    Every check a protected run has always made, unchanged. Failing here fails
    the run: a protected invocation never quietly downgrades to a development
    one.
    """

    if (
        not _COMMIT.fullmatch(marketplace_commit)
        or observed_marketplace_commit != marketplace_commit
        or not marketplace_workflow_run_id.isdigit()
        or not _WORKFLOW_REF.fullmatch(marketplace_workflow_ref)
    ):
        raise ReleaseIdentityRejected("marketplace release identity must match the trusted commit")
    for value in (marketplace_manifest_sha256, marketplace_image_digest):
        if not _DIGEST.fullmatch(value):
            raise ReleaseIdentityRejected(
                "consumer and hosted release digests must be exact sha256 identities"
            )
    values = _read_generated_compose_env(compose_env_path)
    marketplace_image = values.get("HOSTED_MARKETPLACE_VERIFIED_IMAGE", "")
    marketplace_image_match = _IMAGE.fullmatch(marketplace_image)
    if (
        marketplace_image_match is None
        or marketplace_image_match.group("digest") != marketplace_image_digest
        or values.get("HOSTED_MARKETPLACE_VERIFIED_MANIFEST_SHA256")
        != marketplace_manifest_sha256
        or values.get("HOSTED_MARKETPLACE_VERIFIED_REPOSITORY")
        != "arkhai-io/simple-compute-market"
        or values.get("HOSTED_MARKETPLACE_VERIFIED_SOURCE_COMMIT") != marketplace_commit
        or values.get("HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_REF")
        != marketplace_workflow_ref
        or values.get("HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_RUN_ID")
        != marketplace_workflow_run_id
    ):
        raise ReleaseIdentityRejected(
            "activated marketplace image does not match the attested consumer release"
        )
    marketplace_artifact_digests = (
        values.get("HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_WHEELHOUSE_SHA256", ""),
        values.get("HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_SCHEMA_SHA256", ""),
        values.get("HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_PROVENANCE_SHA256", ""),
    )
    if not all(_DIGEST.fullmatch(value) for value in marketplace_artifact_digests):
        raise ReleaseIdentityRejected(
            "attested marketplace wheelhouse, schema, and provenance must be exact"
        )
    (
        image,
        manifest_digest,
        authority_id,
        authority_scheme,
        authority_address,
    ) = _require_hosted_half(
        values,
        hosted_source_commit=hosted_source_commit,
        hosted_workflow_run_id=hosted_workflow_run_id,
        hosted_workflow_ref=hosted_workflow_ref,
        hosted_manifest_sha256=hosted_manifest_sha256,
        hosted_client_wheel_sha256=hosted_client_wheel_sha256,
        hosted_image_digest=hosted_image_digest,
    )
    return ReleaseIdentity(
        mode="attested",
        marketplace_commit=marketplace_commit,
        marketplace_workflow_run_id=marketplace_workflow_run_id,
        marketplace_workflow_ref=marketplace_workflow_ref,
        marketplace_manifest_sha256=marketplace_manifest_sha256,
        marketplace_image_digest=marketplace_image_digest,
        marketplace_image=marketplace_image,
        marketplace_wheelhouse_sha256=marketplace_artifact_digests[0],
        marketplace_schema_sha256=marketplace_artifact_digests[1],
        marketplace_provenance_sha256=marketplace_artifact_digests[2],
        hosted_source_commit=hosted_source_commit,
        hosted_workflow_run_id=hosted_workflow_run_id,
        hosted_workflow_ref=hosted_workflow_ref,
        hosted_manifest_sha256=hosted_manifest_sha256,
        hosted_manifest_digest=manifest_digest,
        hosted_client_wheel_sha256=hosted_client_wheel_sha256,
        hosted_image=image,
        hosted_image_digest=hosted_image_digest,
        hosted_authority_id=authority_id,
        hosted_authority_scheme=authority_scheme,
        hosted_authority_address=authority_address,
    )


def _observed_or_local(values: dict[str, str], key: str) -> str:
    """A locally built stack has no released coordinate; say which, don't invent."""

    return values.get(key) or LOCAL_COORDINATE


def local_release_identity(
    *,
    observed_marketplace_commit: str,
    hosted_source_commit: str,
    hosted_workflow_run_id: str,
    hosted_workflow_ref: str,
    hosted_manifest_sha256: str,
    hosted_client_wheel_sha256: str,
    hosted_image_digest: str,
    compose_env_path: Path,
) -> ReleaseIdentity:
    """Bind what a development stack can actually prove, and say so.

    The producer half is validated exactly as a protected run validates it: a
    development run consumes the same signed hosted release. Only the
    marketplace half is locally built, so it records the working tree's real
    commit and a self-describing placeholder wherever a released coordinate has
    no local counterpart. The result is marked as a development run and can
    never be cited as protected evidence.
    """

    if not _COMMIT.fullmatch(observed_marketplace_commit):
        raise ReleaseIdentityRejected("a development run must record its exact working-tree commit")
    values = _read_generated_compose_env(compose_env_path)
    (
        image,
        manifest_digest,
        authority_id,
        authority_scheme,
        authority_address,
    ) = _require_hosted_half(
        values,
        hosted_source_commit=hosted_source_commit,
        hosted_workflow_run_id=hosted_workflow_run_id,
        hosted_workflow_ref=hosted_workflow_ref,
        hosted_manifest_sha256=hosted_manifest_sha256,
        hosted_client_wheel_sha256=hosted_client_wheel_sha256,
        hosted_image_digest=hosted_image_digest,
    )
    return ReleaseIdentity(
        mode="local",
        marketplace_commit=observed_marketplace_commit,
        marketplace_workflow_run_id=_observed_or_local(
            values, "HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_RUN_ID"
        ),
        marketplace_workflow_ref=_observed_or_local(
            values, "HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_REF"
        ),
        marketplace_manifest_sha256=_observed_or_local(
            values, "HOSTED_MARKETPLACE_VERIFIED_MANIFEST_SHA256"
        ),
        marketplace_image_digest=_observed_or_local(
            values, "HOSTED_MARKETPLACE_VERIFIED_IMAGE_DIGEST"
        ),
        marketplace_image=_observed_or_local(values, "HOSTED_MARKETPLACE_VERIFIED_IMAGE"),
        marketplace_wheelhouse_sha256=_observed_or_local(
            values, "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_WHEELHOUSE_SHA256"
        ),
        marketplace_schema_sha256=_observed_or_local(
            values, "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_SCHEMA_SHA256"
        ),
        marketplace_provenance_sha256=_observed_or_local(
            values, "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_PROVENANCE_SHA256"
        ),
        hosted_source_commit=hosted_source_commit,
        hosted_workflow_run_id=hosted_workflow_run_id,
        hosted_workflow_ref=hosted_workflow_ref,
        hosted_manifest_sha256=hosted_manifest_sha256,
        hosted_manifest_digest=manifest_digest,
        hosted_client_wheel_sha256=hosted_client_wheel_sha256,
        hosted_image=image,
        hosted_image_digest=hosted_image_digest,
        hosted_authority_id=authority_id,
        hosted_authority_scheme=authority_scheme,
        hosted_authority_address=authority_address,
    )


def require_loopback_webhook(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != "/webhooks/stripe"
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise AuthorizationRejected("webhook forwarding must target the loopback Stripe route")
    try:
        port = parsed.port
    except ValueError as exc:
        raise AuthorizationRejected("webhook forwarding port is invalid") from exc
    if port is None:
        raise AuthorizationRejected("webhook forwarding must use an explicit loopback port")
    return url


def verify_loopback_webhook_endpoint(
    url: str,
    *,
    opener: Callable[..., object] = urlopen,
    timeout: float = 5.0,
) -> None:
    """Prove the mapped route exists and rejects an invalid signed event."""

    request = Request(
        require_loopback_webhook(url),
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": "t=0,v1=invalid",
        },
    )
    try:
        response = opener(request, timeout=timeout)
    except HTTPError as exc:
        if exc.code in {400, 401, 403, 422}:
            return
        raise WebhookRouteUnavailable("loopback webhook route was not mapped") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise WebhookRouteUnavailable("loopback webhook route was unavailable") from exc
    close = getattr(response, "close", None)
    if callable(close):
        close()
    raise AuthorizationRejected("webhook route accepted an invalid signature")


def require_ready_account(account: dict[str, object], expected_id: str) -> None:
    """Require the allowlisted Stripe test account and transaction capabilities."""

    controller = account.get("controller")
    controller_data = controller if isinstance(controller, dict) else {}
    dashboard = controller_data.get("stripe_dashboard")
    dashboard_data = dashboard if isinstance(dashboard, dict) else {}
    account_type = account.get("type")
    capabilities = account.get("capabilities")
    capability_data = capabilities if isinstance(capabilities, dict) else {}
    requirements = account.get("requirements")
    requirement_data = requirements if isinstance(requirements, dict) else {}
    controller_compatible = (
        dashboard_data.get("type") == "express"
        and controller_data.get("type") == "application"
        and controller_data.get("is_controller") is True
        and isinstance(controller_data.get("fees"), dict)
        and isinstance(controller_data.get("losses"), dict)
    ) or account_type == "express"
    ready = (
        account.get("id") == expected_id
        and account.get("livemode") in (None, False)
        and account.get("charges_enabled") is True
        and account.get("payouts_enabled") is True
        and account.get("details_submitted") is True
        and capability_data.get("card_payments") in (None, "active")
        and capability_data.get("transfers") == "active"
        and requirement_data.get("currently_due") in (None, [])
        and requirement_data.get("past_due") in (None, [])
        and not requirement_data.get("disabled_reason")
        and controller_compatible
    )
    if not ready:
        raise AuthorizationUnavailable(
            "connected test account is not controller-compatible and ready"
        )


def _read_generated_compose_env(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseIdentityRejected("verified Compose environment is unavailable") from exc
    values: dict[str, str] = {}
    allowed = {
        "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_PROVENANCE_SHA256",
        "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_SCHEMA_SHA256",
        "HOSTED_MARKETPLACE_VERIFIED_ARTIFACT_WHEELHOUSE_SHA256",
        "HOSTED_MARKETPLACE_VERIFIED_IMAGE",
        "HOSTED_MARKETPLACE_VERIFIED_MANIFEST_SHA256",
        "HOSTED_MARKETPLACE_VERIFIED_REPOSITORY",
        "HOSTED_MARKETPLACE_VERIFIED_SOURCE_COMMIT",
        "HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_REF",
        "HOSTED_MARKETPLACE_VERIFIED_WORKFLOW_RUN_ID",
        "HOSTED_SETTLEMENT_VERIFIED_IMAGE",
        "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256",
        "HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256",
        "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_DIGEST",
        "HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR",
        "HOSTED_SETTLEMENT_VERIFIED_SOURCE_COMMIT",
        "HOSTED_SETTLEMENT_VERIFIED_REPOSITORY",
        "HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF",
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ID",
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_SCHEME",
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ADDRESS",
        "HOSTED_SETTLEMENT_VERIFIED_API_VERSION",
        "HOSTED_SETTLEMENT_VERIFIED_SCHEMA_VERSION",
        "HOSTED_SETTLEMENT_VERIFIED_FUNDING_PROFILES",
        "HOSTED_SETTLEMENT_VERIFIED_CAPABILITIES",
        "HOSTED_SETTLEMENT_VERIFIED_CONFORMANCE_SHA256",
        "HOSTED_SETTLEMENT_VERIFIED_MIGRATIONS_SHA256",
        "HOSTED_SETTLEMENT_VERIFIED_OPENAPI_SHA256",
        "HOSTED_SETTLEMENT_VERIFIED_PROVENANCE_SHA256",
        "HOSTED_SETTLEMENT_VERIFIED_RELEASE_VERSION",
        "HOSTED_SETTLEMENT_VERIFIED_SERVICE_WHEEL_SHA256",
    }
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ReleaseIdentityRejected("verified Compose environment is malformed")
        key, value = stripped.split("=", 1)
        if key not in allowed:
            raise ReleaseIdentityRejected(
                "verified Compose environment contains a non-allowlisted key"
            )
        if key in values:
            raise ReleaseIdentityRejected("verified Compose environment contains a duplicate key")
        values[key] = value
    if set(values) != allowed:
        raise ReleaseIdentityRejected("verified Compose environment is incomplete")
    return values
