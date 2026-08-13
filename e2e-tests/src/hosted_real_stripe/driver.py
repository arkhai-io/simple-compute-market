"""Authorized driver for external Stripe test-mode hosted settlement evidence."""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .browser import CheckoutContractError, ChromiumCheckout, ChromiumUnavailable
from .evidence import (
    FailureEvidence,
    IdentityEvidence,
    ProviderEvidence,
    RealStripeEvidence,
    RefundEvidence,
    UnavailableEvidence,
    write_evidence,
)
from .gates import (
    AuthorizationRejected,
    AuthorizationUnavailable,
    ReleaseIdentityRejected,
    require_connected_account,
    require_loopback_webhook,
    require_ready_account,
    require_release_identity,
    require_test_secret,
)
from .runtime import (
    ComposeStack,
    EphemeralServiceEnv,
    LifecycleContractError,
    MarketplaceLifecycleSession,
    ProcessUnavailable,
    StripeWebhookForwarder,
    parse_lifecycle_command,
)
from .stripe_api import (
    ExpectedEffect,
    ProviderInvariantError,
    StripeApi,
    StripeUnavailable,
    TerminalProjection,
)


@dataclass(frozen=True)
class LaneUnavailable(Exception):
    phase: str
    code: str


@dataclass(frozen=True)
class LaneFailed(Exception):
    phase: str
    code: str


def run(args: argparse.Namespace) -> tuple[RealStripeEvidence, int]:
    identity = require_release_identity(
        marketplace_commit=args.marketplace_commit,
        hosted_source_commit=args.hosted_source_commit,
        hosted_workflow_run_id=args.hosted_workflow_run_id,
        hosted_manifest_sha256=args.hosted_manifest_sha256,
        compose_env_path=args.compose_env,
    )
    identities = IdentityEvidence(
        marketplace_repository="arkhai/simple-market-service",
        marketplace_commit=identity.marketplace_commit,
        hosted_repository="arkhai/hosted-settlement-service",
        hosted_source_commit=identity.hosted_source_commit,
        hosted_workflow_run_id=identity.hosted_workflow_run_id,
        hosted_manifest_sha256=identity.hosted_manifest_sha256,
        hosted_image_digest=identity.hosted_image_digest,
    )
    provider = ProviderEvidence(connected_account_ready=False)
    try:
        secret = require_test_secret(os.environ.get("STRIPE_SECRET_KEY"))
        account_id = require_connected_account(os.environ.get("STRIPE_CONNECTED_ACCOUNT_ID"))
        webhook_url = require_loopback_webhook(args.webhook_url)
        stripe = StripeApi(secret)
        try:
            account = stripe.retrieve_account(account_id)
        except StripeUnavailable as exc:
            raise LaneUnavailable("account_readiness", "account_unavailable") from exc
        try:
            require_ready_account(account, account_id)
        except AuthorizationUnavailable as exc:
            raise LaneUnavailable("account_readiness", "account_not_ready") from exc
        provider = ProviderEvidence(connected_account_ready=True)
        command = parse_lifecycle_command(os.environ.get("HOSTED_REAL_STRIPE_LIFECYCLE_COMMAND_JSON"))
        started_at = int(time.time()) - 10

        forwarder = StripeWebhookForwarder(api_key=secret, forward_to=webhook_url)
        try:
            webhook_secret = forwarder.start(timeout=args.webhook_ready_timeout)
        except ProcessUnavailable as exc:
            code = "stripe_cli_unavailable" if "CLI" in str(exc) else "webhook_unavailable"
            raise LaneUnavailable("webhook_forwarding", code) from exc
        try:
            with EphemeralServiceEnv(
                api_key=secret,
                webhook_secret=webhook_secret,
                base_path=args.hosted_service_env_base,
            ) as authority_env:
                with ComposeStack(
                    compose_env=args.compose_env,
                    compose_files=args.compose_file,
                    cwd=args.repo_root,
                    executable=args.container_cli,
                ) as stack:
                    try:
                        stack.start(authority_env_path=authority_env)
                    except ProcessUnavailable as exc:
                        raise LaneUnavailable(
                            "hosted_release", "hosted_release_unavailable"
                        ) from exc
                    with MarketplaceLifecycleSession(command, cwd=args.repo_root) as lifecycle:
                        collection, refund = _drive_lifecycle(
                            lifecycle=lifecycle,
                            stripe=stripe,
                            browser=ChromiumCheckout(timeout_ms=args.browser_timeout_ms),
                            connected_account_id=account_id,
                            created_after=started_at,
                            attempt_refund=not args.skip_refund,
                        )
        finally:
            forwarder.stop()
        return (
            RealStripeEvidence(
                identities=identities,
                provider=provider,
                outcome="passed",
                collection=collection,
                refund=refund,
            ),
            0,
        )
    except AuthorizationUnavailable:
        return _unavailable(identities, provider, "authorization", "credentials_missing"), 2
    except AuthorizationRejected:
        return _failed(
            identities, provider, "authorization", "authorization_contract_rejected"
        ), 1
    except LaneUnavailable as exc:
        return _unavailable(identities, provider, exc.phase, exc.code), 2
    except LaneFailed as exc:
        return _failed(identities, provider, exc.phase, exc.code), 1
    except ChromiumUnavailable:
        return _unavailable(identities, provider, "browser_checkout", "chromium_unavailable"), 2
    except CheckoutContractError:
        return _failed(identities, provider, "browser_checkout", "checkout_contract_rejected"), 1
    except ProcessUnavailable:
        return _unavailable(
            identities, provider, "marketplace_lifecycle", "marketplace_lifecycle_unavailable"
        ), 2
    except LifecycleContractError:
        return _failed(
            identities, provider, "marketplace_lifecycle", "lifecycle_contract_rejected"
        ), 1
    except StripeUnavailable:
        return _unavailable(
            identities, provider, "provider_inspection", "provider_inspection_unavailable"
        ), 2
    except ProviderInvariantError:
        return _failed(
            identities, provider, "provider_inspection", "collection_invariant_failed"
        ), 1


def _drive_lifecycle(
    *,
    lifecycle: MarketplaceLifecycleSession,
    stripe: StripeApi,
    browser: ChromiumCheckout,
    connected_account_id: str,
    created_after: int,
    attempt_refund: bool,
):
    prepared = lifecycle.request("prepare_collection")
    expected, checkout_url = _prepared_effect(
        prepared,
        connected_account_id=connected_account_id,
        created_after=created_after,
    )
    browser.complete(checkout_url)
    checkout_url = ""
    lifecycle.request("wait_authoritative_funding", operation_ref=expected.operation_ref)
    lifecycle.request("complete_portable_vm_fulfillment", operation_ref=expected.operation_ref)
    terminal = _terminal_projection(
        lifecycle.request("wait_authoritative_collection", operation_ref=expected.operation_ref),
        collection=True,
    )
    collection = stripe.inspect_collection(expected, terminal)

    if not attempt_refund:
        return collection, RefundEvidence(outcome="not_requested")
    refund_prepared = lifecycle.request("prepare_refund")
    if refund_prepared.get("available") is False:
        return collection, _refund_unavailable()
    refund_expected, refund_url = _prepared_effect(
        refund_prepared,
        connected_account_id=connected_account_id,
        created_after=created_after,
    )
    try:
        browser.complete(refund_url)
        refund_url = ""
        lifecycle.request(
            "wait_authoritative_funding", operation_ref=refund_expected.operation_ref
        )
        lifecycle.request(
            "request_eligible_pretransfer_refund", operation_ref=refund_expected.operation_ref
        )
        refund_terminal = _terminal_projection(
            lifecycle.request(
                "wait_authoritative_refund", operation_ref=refund_expected.operation_ref
            ),
            collection=False,
        )
        refund = stripe.inspect_refund(refund_expected, refund_terminal)
    except (ChromiumUnavailable, ProcessUnavailable, StripeUnavailable):
        refund = _refund_unavailable()
    except ProviderInvariantError as exc:
        raise LaneFailed("refund", "refund_invariant_failed") from exc
    return collection, refund


def _prepared_effect(
    value: dict[str, Any], *, connected_account_id: str, created_after: int
) -> tuple[ExpectedEffect, str]:
    required_true = ("discovered", "negotiated", "materialized")
    if any(value.get(field) is not True for field in required_true):
        raise LifecycleContractError("marketplace lifecycle milestones are incomplete")
    if value.get("accepted_mechanism") != "fiat.stripe.v1":
        raise LifecycleContractError("marketplace accepted the wrong settlement mechanism")
    if value.get("condition_profile") != "portable":
        raise LifecycleContractError("real-provider lane requires a portable condition")
    operation_ref = value.get("operation_ref")
    checkout_url = value.get("checkout_url")
    amount = value.get("amount")
    currency = value.get("currency")
    transfer_group = value.get("transfer_group")
    if (
        not isinstance(operation_ref, str)
        or not isinstance(checkout_url, str)
        or not isinstance(amount, int)
        or isinstance(amount, bool)
        or amount <= 0
        or not isinstance(currency, str)
        or len(currency) != 3
        or currency != currency.lower()
        or not isinstance(transfer_group, str)
        or not transfer_group
    ):
        raise LifecycleContractError("marketplace materialization response is incomplete")
    return (
        ExpectedEffect(
            operation_ref=operation_ref,
            amount=amount,
            currency=currency,
            destination_account=connected_account_id,
            transfer_group=transfer_group,
            created_after=created_after,
        ),
        checkout_url,
    )


def _terminal_projection(value: dict[str, Any], *, collection: bool) -> TerminalProjection:
    marketplace_state = value.get("marketplace_state")
    authority_state = value.get("authority_state")
    fulfillment_state = value.get("fulfillment_state")
    if not all(isinstance(item, str) and item for item in (
        marketplace_state,
        authority_state,
        fulfillment_state,
    )):
        raise LifecycleContractError("authoritative terminal state is incomplete")
    assert isinstance(marketplace_state, str)
    assert isinstance(authority_state, str)
    assert isinstance(fulfillment_state, str)
    expected_authority = "collected" if collection else "refunded"
    if authority_state != expected_authority:
        raise LifecycleContractError("authority did not reach the expected terminal state")
    if fulfillment_state not in {"ready", "fulfilled", "completed"}:
        raise LifecycleContractError("portable VM fulfillment did not complete")
    return TerminalProjection(marketplace_state, authority_state, fulfillment_state)


def _refund_unavailable() -> RefundEvidence:
    return RefundEvidence(
        outcome="unavailable",
        unavailable=UnavailableEvidence(
            phase="refund", code="refund_externally_unavailable"
        ),
    )


def _unavailable(
    identities: IdentityEvidence, provider: ProviderEvidence, phase: str, code: str
) -> RealStripeEvidence:
    return RealStripeEvidence(
        identities=identities,
        provider=provider,
        outcome="unavailable",
        unavailable=UnavailableEvidence(phase=phase, code=code),  # type: ignore[arg-type]
    )


def _failed(
    identities: IdentityEvidence, provider: ProviderEvidence, phase: str, code: str
) -> RealStripeEvidence:
    return RealStripeEvidence(
        identities=identities,
        provider=provider,
        outcome="failed",
        failure=FailureEvidence(phase=phase, code=code),  # type: ignore[arg-type]
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--compose-env", type=Path, required=True)
    parser.add_argument("--hosted-manifest-sha256", required=True)
    parser.add_argument("--hosted-source-commit", required=True)
    parser.add_argument("--hosted-workflow-run-id", required=True)
    parser.add_argument("--marketplace-commit", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--hosted-service-env-base", type=Path)
    parser.add_argument("--container-cli", default="docker")
    parser.add_argument("--webhook-url", default="http://127.0.0.1:18080/webhooks/stripe")
    parser.add_argument("--webhook-ready-timeout", type=float, default=30.0)
    parser.add_argument("--browser-timeout-ms", type=int, default=90_000)
    parser.add_argument("--skip-refund", action="store_true")
    parser.add_argument(
        "--compose-file",
        action="append",
        type=Path,
        default=None,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.compose_file is None:
        args.compose_file = [
            args.repo_root / "domains" / "vms" / "compose.yml",
            args.repo_root / "compose.vms-fiat.yml",
            args.repo_root / "compose.hosted-settlement.yml",
        ]
    try:
        report, exit_code = run(args)
    except ReleaseIdentityRejected:
        # Without exact release identities there is no trustworthy report to
        # attach to a commit. Preflight must fail before this driver is invoked.
        return 1
    write_evidence(args.evidence, report)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
