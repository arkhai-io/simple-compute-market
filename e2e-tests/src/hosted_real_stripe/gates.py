"""Fail-closed authorization and immutable-release gates for real Stripe evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/:~-]*@(?P<digest>sha256:[0-9a-f]{64})$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ACCOUNT = re.compile(r"^acct_[A-Za-z0-9]+$")


class AuthorizationUnavailable(RuntimeError):
    """Required protected-lane authorization was not supplied."""


class AuthorizationRejected(RuntimeError):
    """Supplied authorization could enable a live or untrusted run."""


class ReleaseIdentityRejected(RuntimeError):
    """The ordinary hosted release is not pinned to immutable identities."""


@dataclass(frozen=True)
class ReleaseIdentity:
    marketplace_commit: str
    hosted_source_commit: str
    hosted_workflow_run_id: str
    hosted_manifest_sha256: str
    hosted_image: str
    hosted_image_digest: str


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


def require_release_identity(
    *,
    marketplace_commit: str,
    hosted_source_commit: str,
    hosted_workflow_run_id: str,
    hosted_manifest_sha256: str,
    compose_env_path: Path,
) -> ReleaseIdentity:
    if not _COMMIT.fullmatch(marketplace_commit):
        raise ReleaseIdentityRejected("marketplace source must be an exact 40-hex commit")
    if not _COMMIT.fullmatch(hosted_source_commit) or not hosted_workflow_run_id.isdigit():
        raise ReleaseIdentityRejected("hosted producer source and workflow run must be exact")
    if not _DIGEST.fullmatch(hosted_manifest_sha256):
        raise ReleaseIdentityRejected("hosted manifest must be an exact sha256 digest")
    values = _read_generated_compose_env(compose_env_path)
    image = values.get("HOSTED_SETTLEMENT_VERIFIED_IMAGE", "")
    match = _IMAGE.fullmatch(image)
    if match is None:
        raise ReleaseIdentityRejected("hosted image must be repository@sha256:digest")
    generated_manifest = values.get("HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256")
    if generated_manifest != hosted_manifest_sha256:
        raise ReleaseIdentityRejected("generated Compose input does not match the trusted manifest")
    return ReleaseIdentity(
        marketplace_commit=marketplace_commit,
        hosted_source_commit=hosted_source_commit,
        hosted_workflow_run_id=hosted_workflow_run_id,
        hosted_manifest_sha256=hosted_manifest_sha256,
        hosted_image=image,
        hosted_image_digest=match.group("digest"),
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


def require_ready_account(account: dict[str, object], expected_id: str) -> None:
    """Require Stripe test mode and an application-controlled Express account."""
    controller = account.get("controller")
    controller_data = controller if isinstance(controller, dict) else {}
    dashboard = controller_data.get("stripe_dashboard")
    dashboard_data = dashboard if isinstance(dashboard, dict) else {}
    account_type = account.get("type")
    controller_compatible = (
        controller_data.get("requirement_collection") == "application"
        and dashboard_data.get("type") == "express"
    ) or account_type == "express"
    ready = (
        account.get("id") == expected_id
        and account.get("livemode") is False
        and account.get("charges_enabled") is True
        and account.get("payouts_enabled") is True
        and account.get("details_submitted") is True
        and controller_compatible
    )
    if not ready:
        raise AuthorizationUnavailable("connected test account is not controller-compatible and ready")


def _read_generated_compose_env(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseIdentityRejected("verified Compose environment is unavailable") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ReleaseIdentityRejected("verified Compose environment is malformed")
        key, value = stripped.split("=", 1)
        if key not in {
            "HOSTED_SETTLEMENT_VERIFIED_IMAGE",
            "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256",
        }:
            raise ReleaseIdentityRejected("verified Compose environment contains a non-allowlisted key")
        if key in values:
            raise ReleaseIdentityRejected("verified Compose environment contains a duplicate key")
        values[key] = value
    return values
