"""Fail-closed authorization, release, account, and loopback gates."""

from __future__ import annotations

import hashlib
import json
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
_RELEASE_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class AuthorizationUnavailable(RuntimeError):
    """Required protected-lane authorization was not supplied."""


class AuthorizationRejected(RuntimeError):
    """Supplied authorization could enable a live or untrusted run."""


class LaneExcluded(RuntimeError):
    """This run declines to attempt a lane that is otherwise runnable.

    Carries the code the report publishes, because the reason is the whole
    point: a lane withheld for want of a human reads nothing like one
    withheld for want of behaviour that does not exist yet.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    #: What the bound producer serves. Read from the release, so a
    #: scenario's prerequisites can be checked against it by name.
    hosted_contract: "HostedContract"


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


@dataclass(frozen=True)
class HostedContract:
    """What the bound producer serves, as the release itself states it."""

    release_version: str
    api_version: str
    schema_version: str
    funding_profiles: tuple[str, ...]
    capabilities: frozenset[str]


def _require_hosted_contract(values: dict[str, str]) -> HostedContract:
    """Assert the composed authority serves the contract the run bound.

    This used to be a literal release version, a literal schema, and two
    literal tuples, compared against the generated environment. A harness that
    names one contract in its own source can admit exactly that release: the
    next one reads as a corrupt environment rather than as a newer contract,
    and a real mismatch reads the same way. The expectation comes from the
    release the run bound instead -- for a released producer that artifact's
    hash is covered by the signed manifest, so the trust root is unchanged.
    """

    release_version = values.get("HOSTED_SETTLEMENT_VERIFIED_RELEASE_VERSION", "")
    release_dir = values.get("HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR", "")
    if not _RELEASE_VERSION.fullmatch(release_version) or not release_dir:
        raise ReleaseIdentityRejected("generated Compose input names no bound release")
    path = Path(release_dir) / f"conformance-v{release_version}.json"
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseIdentityRejected(
            f"the bound release states no contract at {path.name}"
        ) from exc
    expected_sha = values.get("HOSTED_SETTLEMENT_VERIFIED_CONFORMANCE_SHA256", "")
    if expected_sha and expected_sha != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise ReleaseIdentityRejected(
            "the staged contract artifact is not the one the release signed"
        )
    identity_contract = document.get("identity_contract")
    identity_contract = identity_contract if isinstance(identity_contract, dict) else {}
    bound = HostedContract(
        release_version=release_version,
        api_version=str(document.get("api_version", "")),
        schema_version=str(document.get("schema_version", "")),
        funding_profiles=tuple(
            str(value) for value in (document.get("funding_profiles") or ())
        ),
        capabilities=frozenset(
            str(value) for value in (identity_contract.get("capabilities") or ())
        ),
    )
    # The producer generates its artifacts for one version and refuses to
    # generate them for another, so a release whose contract names a different
    # API than the release it belongs to is describing something else.
    if bound.api_version != release_version or not bound.capabilities:
        raise ReleaseIdentityRejected(
            "the bound release's contract artifact describes a different release"
        )
    observed = (
        (
            "API version",
            values.get("HOSTED_SETTLEMENT_VERIFIED_API_VERSION", ""),
            bound.api_version,
        ),
        (
            "schema version",
            values.get("HOSTED_SETTLEMENT_VERIFIED_SCHEMA_VERSION", ""),
            bound.schema_version,
        ),
        (
            "funding profiles",
            values.get("HOSTED_SETTLEMENT_VERIFIED_FUNDING_PROFILES", ""),
            ",".join(bound.funding_profiles),
        ),
        (
            "capabilities",
            frozenset(
                values.get("HOSTED_SETTLEMENT_VERIFIED_CAPABILITIES", "").split(",")
            ),
            bound.capabilities,
        ),
    )
    for name, rendered, expected in observed:
        if rendered != expected:
            raise ReleaseIdentityRejected(
                f"the composed authority does not serve the bound release's {name}"
            )
    return bound


#: The producer coordinates a locally built authority has no released source
#: for, and which a released one always has. Read as a set: all present is a
#: released producer, all empty is a local one, and anything between is an
#: environment that cannot say which it is.
_HOSTED_PROVENANCE_KEYS = (
    "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ADDRESS",
    "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ID",
    "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_SCHEME",
    "HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256",
    "HOSTED_SETTLEMENT_VERIFIED_CONFORMANCE_SHA256",
    "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256",
    "HOSTED_SETTLEMENT_VERIFIED_MIGRATIONS_SHA256",
    "HOSTED_SETTLEMENT_VERIFIED_OPENAPI_SHA256",
    "HOSTED_SETTLEMENT_VERIFIED_PROVENANCE_SHA256",
    "HOSTED_SETTLEMENT_VERIFIED_SERVICE_WHEEL_SHA256",
    "HOSTED_SETTLEMENT_VERIFIED_SOURCE_COMMIT",
    "HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF",
)


@dataclass(frozen=True)
class HostedHalf:
    released: bool
    image: str
    manifest_digest: str
    authority_id: str
    authority_scheme: str
    authority_address: str
    contract: HostedContract


def _hosted_half_is_released(values: dict[str, str]) -> bool:
    filled = [bool(values.get(key)) for key in _HOSTED_PROVENANCE_KEYS]
    if all(filled):
        return True
    if not any(filled):
        return False
    raise ReleaseIdentityRejected(
        "a producer half is either released or locally built, not partly both"
    )


def _require_hosted_half(
    values: dict[str, str],
    *,
    allow_local: bool,
    hosted_source_commit: str,
    hosted_workflow_run_id: str,
    hosted_workflow_ref: str,
    hosted_manifest_sha256: str,
    hosted_client_wheel_sha256: str,
    hosted_image_digest: str,
) -> HostedHalf:
    """Bind the producer, released or locally built, and say which it was.

    Only the provenance half branches. What the authority serves is asserted
    identically either way, against the contract the bound release states.
    """

    released = _hosted_half_is_released(values)
    if not released and not allow_local:
        raise ReleaseIdentityRejected(
            "a protected run binds a released producer, never a locally built one"
        )
    if values.get("HOSTED_SETTLEMENT_VERIFIED_REPOSITORY") != "arkhai-io/stripe-settlement-service":
        raise ReleaseIdentityRejected("signed release repository is not the hosted producer")
    contract = _require_hosted_contract(values)
    image = values.get("HOSTED_SETTLEMENT_VERIFIED_IMAGE", "")
    manifest_digest = values.get("HOSTED_SETTLEMENT_VERIFIED_MANIFEST_DIGEST", "")
    if not released:
        supplied = (
            hosted_source_commit,
            hosted_workflow_run_id,
            hosted_workflow_ref,
            hosted_manifest_sha256,
            hosted_client_wheel_sha256,
            hosted_image_digest,
        )
        if any(supplied):
            raise ReleaseIdentityRejected(
                "a locally built producer has no released coordinates to pin"
            )
        # An image built here has an image id, not a registry digest, and
        # inventing one would make a development environment look attested by
        # inspection. Compose still refuses a service with no image, so a local
        # environment names the one it actually runs.
        if not image or "@" in image:
            raise ReleaseIdentityRejected(
                "a locally built producer must name the image it runs"
            )
        if not _DIGEST.fullmatch(manifest_digest):
            raise ReleaseIdentityRejected(
                "a locally built producer must state the build the authority reports"
            )
        return HostedHalf(
            released=False,
            image=image,
            manifest_digest=manifest_digest,
            authority_id=LOCAL_COORDINATE,
            authority_scheme=LOCAL_COORDINATE,
            authority_address=LOCAL_COORDINATE,
            contract=contract,
        )
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
    if values.get("HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF") != hosted_workflow_ref:
        raise ReleaseIdentityRejected("signed release workflow does not match the trusted workflow")
    hosted_artifact_digests = (
        values.get("HOSTED_SETTLEMENT_VERIFIED_CONFORMANCE_SHA256", ""),
        values.get("HOSTED_SETTLEMENT_VERIFIED_MIGRATIONS_SHA256", ""),
        values.get("HOSTED_SETTLEMENT_VERIFIED_OPENAPI_SHA256", ""),
        values.get("HOSTED_SETTLEMENT_VERIFIED_PROVENANCE_SHA256", ""),
        values.get("HOSTED_SETTLEMENT_VERIFIED_SERVICE_WHEEL_SHA256", ""),
    )
    if not all(_DIGEST.fullmatch(value) for value in hosted_artifact_digests):
        raise ReleaseIdentityRejected("generated Compose input is not the exact expanded contract")
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
    return HostedHalf(
        released=True,
        image=image,
        manifest_digest=manifest_digest,
        authority_id=authority_id,
        authority_scheme=authority_scheme,
        authority_address=authority_address,
        contract=contract,
    )


def require_hosted_capabilities(
    contract: HostedContract, required: frozenset[str]
) -> None:
    """Name the prerequisite before the run reaches for it.

    A scenario that needs a capability the bound release does not declare fails
    somewhere inside the provider otherwise, after it has already mutated
    something, and reports that instead of the reason.
    """

    missing = sorted(required - contract.capabilities)
    if missing:
        raise AuthorizationUnavailable(
            "the bound hosted release does not declare " + ", ".join(missing)
        )


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
    hosted = _require_hosted_half(
        values,
        allow_local=False,
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
        hosted_manifest_digest=hosted.manifest_digest,
        hosted_client_wheel_sha256=hosted_client_wheel_sha256,
        hosted_image=hosted.image,
        hosted_image_digest=hosted_image_digest,
        hosted_authority_id=hosted.authority_id,
        hosted_authority_scheme=hosted.authority_scheme,
        hosted_authority_address=hosted.authority_address,
        hosted_contract=hosted.contract,
    )


def _observed_or_local(values: dict[str, str], key: str) -> str:
    """A locally built stack has no released coordinate; say which, don't invent."""

    return values.get(key) or LOCAL_COORDINATE


def local_release_identity(
    *,
    observed_marketplace_commit: str,
    hosted_source_commit: str = "",
    hosted_workflow_run_id: str = "",
    hosted_workflow_ref: str = "",
    hosted_manifest_sha256: str = "",
    hosted_client_wheel_sha256: str = "",
    hosted_image_digest: str = "",
    compose_env_path: Path,
) -> ReleaseIdentity:
    """Bind what a development stack can actually prove, and say so.

    Either half may be a release or a local build, in any combination. A
    released half is validated exactly as a protected run validates it, and its
    coordinates are supplied; a locally built half has none to supply, and
    records a self-describing placeholder in their place. The result is marked
    as a development run either way and can never be cited as protected
    evidence.
    """

    if not _COMMIT.fullmatch(observed_marketplace_commit):
        raise ReleaseIdentityRejected("a development run must record its exact working-tree commit")
    values = _read_generated_compose_env(compose_env_path)
    hosted = _require_hosted_half(
        values,
        allow_local=True,
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
        hosted_source_commit=hosted_source_commit or LOCAL_COORDINATE,
        hosted_workflow_run_id=hosted_workflow_run_id or LOCAL_COORDINATE,
        hosted_workflow_ref=hosted_workflow_ref or LOCAL_COORDINATE,
        hosted_manifest_sha256=hosted_manifest_sha256 or LOCAL_COORDINATE,
        hosted_manifest_digest=hosted.manifest_digest,
        hosted_client_wheel_sha256=hosted_client_wheel_sha256 or LOCAL_COORDINATE,
        hosted_image=hosted.image,
        hosted_image_digest=hosted_image_digest or LOCAL_COORDINATE,
        hosted_authority_id=hosted.authority_id,
        hosted_authority_scheme=hosted.authority_scheme,
        hosted_authority_address=hosted.authority_address,
        hosted_contract=hosted.contract,
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
