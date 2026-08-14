"""Protected Stripe test-mode hosted settlement system driver."""

from __future__ import annotations

import argparse
import json
import os
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence, cast

from hosted_settlement_client import sign_account_owner_admission
from market_hosted_settlement.adapter import MarketplaceSignerAdapter
from market_identity import create_signer

from .browser import (
    CheckoutContractError,
    CheckoutOutcome,
    BrowserPaymentResult,
    ChromiumCheckout,
    ChromiumUnavailable,
    checkout_session_id,
)
from .evidence import (
    DiagnosticCode,
    DiagnosticEvidence,
    HostedReleaseIdentityEvidence,
    IdentityEvidence,
    MarketplaceIdentityEvidence,
    ProviderEvidence,
    RecoveryEvidence,
    ResultClass,
    Scenario,
    Stage,
    StripeTestEvidence,
    opaque_ref,
    write_evidence,
)
from .gates import (
    AuthorizationRejected,
    AuthorizationUnavailable,
    ReleaseIdentityRejected,
    WebhookRouteUnavailable,
    require_connected_account,
    require_loopback_webhook,
    require_ready_account,
    require_release_identity,
    require_run_identity,
    require_test_secret,
    verify_loopback_webhook_endpoint,
)
from .runtime import (
    ComposeStack,
    EphemeralMarketplaceConfig,
    EphemeralServiceEnv,
    LifecycleContractError,
    LifecycleConvergenceTimeout,
    MarketplaceLifecycleSession,
    ProcessUnavailable,
    StripeWebhookForwarder,
    parse_lifecycle_command,
)
from .stripe_api import (
    ExpectedEffect,
    ProviderConvergenceTimeout,
    ProviderInvariantError,
    StripeApi,
    StripeUnavailable,
    TerminalProjection,
)

_SCENARIOS = (
    "collection",
    "reclaim",
    "missed_webhook",
    "api_restart",
    "worker_restart",
    "decline",
    "insufficient_funds",
    "authentication",
)
_REFUND_SERVICING_INTERVAL_SECONDS = 7200.0


@dataclass
class _ExecutionState:
    stage: Stage = "authorization"
    operation_ref: str | None = None


@dataclass(frozen=True)
class _ScenarioResult:
    operation_ref: str
    collection: object | None = None
    refund: object | None = None
    payment_outcome: object | None = None
    recovery: RecoveryEvidence | None = None


def run(args: argparse.Namespace) -> tuple[StripeTestEvidence, int]:
    release = require_release_identity(
        marketplace_commit=args.marketplace_commit,
        observed_marketplace_commit=args.observed_marketplace_commit,
        hosted_source_commit=args.hosted_source_commit,
        hosted_workflow_run_id=args.hosted_workflow_run_id,
        hosted_workflow_ref=args.hosted_workflow_ref,
        hosted_manifest_sha256=args.hosted_manifest_sha256,
        hosted_client_wheel_sha256=args.hosted_client_wheel_sha256,
        hosted_image_digest=args.hosted_image_digest,
        compose_env_path=args.compose_env,
    )
    run_identity = require_run_identity(args.run_identity)
    identities = IdentityEvidence(
        marketplace=MarketplaceIdentityEvidence(
            repository="arkhai/simple-market-service",
            commit=release.marketplace_commit,
        ),
        hosted_release=HostedReleaseIdentityEvidence(
            repository="arkhai/hosted-settlement-service",
            source_commit=release.hosted_source_commit,
            workflow_run_id=release.hosted_workflow_run_id,
            workflow_ref=release.hosted_workflow_ref,
            manifest_sha256=release.hosted_manifest_sha256,
            client_wheel_sha256=release.hosted_client_wheel_sha256,
            image_digest=release.hosted_image_digest,
        ),
        run_ref=opaque_ref("run", run_identity),
    )
    scenario = cast(Scenario, args.scenario)
    provider = ProviderEvidence()
    execution = _ExecutionState()
    try:
        secret = require_test_secret(os.environ.get("STRIPE_SECRET_KEY"))
        account_id = require_connected_account(os.environ.get("STRIPE_CONNECTED_ACCOUNT_ID"))
        webhook_url = require_loopback_webhook(args.webhook_url)
        stripe = StripeApi(secret, timeout=args.stripe_request_timeout)

        execution.stage = "account_readiness"
        account = stripe.retrieve_account(account_id)
        require_ready_account(account, account_id)
        binding_contract = _maintained_account_binding(
            storefront_config=args.storefront_config,
            authority_id=release.hosted_authority_id,
            account_ref=args.account_ref,
            provider_account_id=account_id,
            run_identity=run_identity,
        )
        provider = ProviderEvidence(connected_account_ready=True)

        execution.stage = "browser_preflight"
        browser = ChromiumCheckout(timeout_ms=args.browser_timeout_ms)
        browser.require_available()

        execution.stage = "webhook_forwarding"
        forwarder = StripeWebhookForwarder(api_key=secret, forward_to=webhook_url)
        webhook_secret = forwarder.start(timeout=args.webhook_ready_timeout)
        try:
            with EphemeralMarketplaceConfig(
                template=args.storefront_config,
                account_ref=args.account_ref,
                authority_id=release.hosted_authority_id,
                authority_scheme=release.hosted_authority_scheme,
                authority_address=release.hosted_authority_address,
                authority_environment=args.authority_environment,
                manifest_digest=release.hosted_manifest_digest,
                shared_directory=args.compose_env.parent,
            ) as marketplace_config:
                with EphemeralServiceEnv(
                    api_key=secret,
                    webhook_secret=webhook_secret,
                    manifest_digest=release.hosted_manifest_digest,
                    release_authority_id=release.hosted_authority_id,
                    release_authority_address=release.hosted_authority_address,
                    release_repository="arkhai/hosted-settlement-service",
                    release_workflow_ref=release.hosted_workflow_ref,
                    release_source_commit=release.hosted_source_commit,
                    base_path=args.hosted_service_env_base,
                    shared_directory=args.compose_env.parent,
                ) as authority_env:
                    execution.stage = "hosted_release"
                    with ComposeStack(
                        compose_env=args.compose_env,
                        compose_files=args.compose_file,
                        cwd=args.repo_root,
                        executable=args.container_cli,
                    ) as stack:
                        stack.start(
                            authority_env_path=authority_env,
                            marketplace_config_path=marketplace_config,
                            storefront_servicing_interval_seconds=(
                                _REFUND_SERVICING_INTERVAL_SECONDS
                                if scenario in {"reclaim", "worker_restart"}
                                else None
                            ),
                        )
                        execution.stage = "account_readiness"
                        stack.bind_existing_account(
                            account_ref=args.account_ref,
                            binding_contract=binding_contract,
                        )
                        execution.stage = "webhook_forwarding"
                        verify_loopback_webhook_endpoint(
                            webhook_url,
                            timeout=args.webhook_probe_timeout,
                        )
                        provider = ProviderEvidence(
                            connected_account_ready=True,
                            loopback_webhook_verified=True,
                        )
                        execution.stage = "marketplace_lifecycle"
                        command = parse_lifecycle_command(
                            os.environ.get("HOSTED_STRIPE_TEST_LIFECYCLE_COMMAND_JSON")
                        )
                        with MarketplaceLifecycleSession(
                            command,
                            cwd=args.repo_root,
                            environment=_lifecycle_environment(
                                args,
                                marketplace_config=marketplace_config,
                                manifest_digest=release.hosted_manifest_digest,
                            ),
                            request_timeout=args.lifecycle_timeout,
                        ) as lifecycle:
                            result = _execute_scenario(
                                scenario=scenario,
                                lifecycle=lifecycle,
                                stripe=stripe,
                                browser=browser,
                                forwarder=forwarder,
                                stack=stack,
                                connected_account_id=account_id,
                                provider_timeout=args.provider_timeout,
                                poll_interval=args.poll_interval,
                                execution=execution,
                            )
        finally:
            forwarder.stop()
        return (
            StripeTestEvidence(
                identities=identities,
                provider=provider,
                scenario=scenario,
                result="passed",
                stage="complete",
                operation_ref=result.operation_ref,
                collection=result.collection,  # type: ignore[arg-type]
                refund=result.refund,  # type: ignore[arg-type]
                payment_outcome=result.payment_outcome,  # type: ignore[arg-type]
                recovery=result.recovery,
            ),
            0,
        )
    except ReleaseIdentityRejected:
        raise
    except AuthorizationUnavailable:
        classification: ResultClass = (
            "account" if execution.stage == "account_readiness" else "environment"
        )
        code: DiagnosticCode = (
            "account_not_ready" if execution.stage == "account_readiness" else "credentials_missing"
        )
    except AuthorizationRejected:
        classification, code = "environment", "authorization_rejected"
    except StripeUnavailable:
        classification, code = "environment", "stripe_unavailable"
    except WebhookRouteUnavailable:
        classification, code = "environment", "webhook_route_unavailable"
    except ChromiumUnavailable:
        classification, code = "environment", "chromium_unavailable"
    except ProcessUnavailable:
        if execution.stage == "account_readiness":
            classification, code = "account", "account_not_ready"
        else:
            classification = "environment"
            if execution.stage == "webhook_forwarding":
                code = "stripe_cli_unavailable"
            elif execution.stage == "hosted_release":
                code = "hosted_release_unavailable"
            else:
                code = "marketplace_unavailable"
    except (LifecycleConvergenceTimeout, ProviderConvergenceTimeout):
        classification, code = "timeout", "convergence_timeout"
    except CheckoutContractError:
        classification, code = "product", "checkout_contract_rejected"
    except LifecycleContractError:
        classification, code = "product", "lifecycle_contract_rejected"
    except ProviderInvariantError:
        classification, code = "product", "provider_invariant_failed"

    return (
        StripeTestEvidence(
            identities=identities,
            provider=provider,
            scenario=scenario,
            result=classification,
            stage=execution.stage,
            operation_ref=execution.operation_ref,
            diagnostic=DiagnosticEvidence(stage=execution.stage, code=code),
        ),
        1,
    )


def _maintained_account_binding(
    *,
    storefront_config: Path,
    authority_id: str,
    account_ref: str,
    provider_account_id: str,
    run_identity: str,
) -> str:
    credential = os.environ.get("HOSTED_SETTLEMENT_E2E_STOREFRONT_IDENTITY_CREDENTIAL")
    if not credential:
        raise AuthorizationUnavailable("storefront account-owner credential is unavailable")
    try:
        parsed = tomllib.loads(storefront_config.read_text(encoding="utf-8"))
        identity = parsed["Identity"]["principal"]
        scheme = identity["scheme"]
        identifier = identity["identifier"]
        if not isinstance(scheme, str) or not isinstance(identifier, str):
            raise ValueError("storefront identity is invalid")
        signer = create_signer(scheme, credential)
        if signer.identity.identifier != identifier:
            raise ValueError("storefront credential does not match configured identity")
        admission = sign_account_owner_admission(
            signer=MarketplaceSignerAdapter(signer),
            authority_id=authority_id,
            account_ref=account_ref,
            nonce=opaque_ref("op", f"account-admission:{run_identity}"),
            valid_until_unix=int(time.time()) + 3600,
        )
    except (KeyError, OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise AuthorizationRejected("storefront account-owner authorization is invalid") from exc
    return json.dumps(
        {
            "provider_account_id": provider_account_id,
            "admission": admission.model_dump(mode="json"),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _pay_with_forwarding_paused(
    forwarder: StripeWebhookForwarder,
    browser: ChromiumCheckout,
    checkout_url: str,
    *,
    outcome: CheckoutOutcome,
) -> BrowserPaymentResult:
    forwarder.pause()
    try:
        return browser.pay(checkout_url, outcome=outcome)
    finally:
        forwarder.resume()


def _execute_scenario(
    *,
    scenario: Scenario,
    lifecycle: MarketplaceLifecycleSession,
    stripe: StripeApi,
    browser: ChromiumCheckout,
    forwarder: StripeWebhookForwarder,
    stack: ComposeStack,
    connected_account_id: str,
    provider_timeout: float,
    poll_interval: float,
    execution: _ExecutionState,
) -> _ScenarioResult:
    case = "refund" if scenario in {"reclaim", "worker_restart"} else "collection"
    prepared = lifecycle.request(f"prepare_{case}")
    expected, checkout_url = _prepared_effect(
        prepared,
        connected_account_id=connected_account_id,
    )
    operation_ref = opaque_ref("op", expected.operation_ref)
    execution.operation_ref = operation_ref

    if scenario == "api_restart":
        execution.stage = "recovery"
        stack.restart("api")
    browser_outcome = _browser_outcome(scenario)
    execution.stage = "browser_checkout"
    if scenario == "missed_webhook":
        payment = _pay_with_forwarding_paused(
            forwarder,
            browser,
            checkout_url,
            outcome=browser_outcome,
        )
        execution.stage = "recovery"
        stack.restart("worker")
    else:
        payment = browser.pay(checkout_url, outcome=browser_outcome)
    checkout_url = ""
    if payment.checkout_session_id != expected.checkout_session_id:
        raise LifecycleContractError("browser completed a different Checkout session")

    if scenario in {"decline", "insufficient_funds", "authentication"}:
        execution.stage = "provider_inspection"
        payment_outcome = stripe.wait_for_payment_outcome(
            expected,
            cast(Literal["decline", "insufficient_funds", "authentication"], scenario),
            timeout=provider_timeout,
            poll_interval=poll_interval,
        )
        return _ScenarioResult(
            operation_ref=operation_ref,
            payment_outcome=payment_outcome,
        )

    execution.stage = "marketplace_lifecycle"
    lifecycle.request("wait_authoritative_funding", operation_ref=expected.operation_ref)
    if scenario in {"reclaim", "worker_restart"}:
        if scenario == "worker_restart":
            execution.stage = "recovery"
            stack.restart("worker")
        execution.stage = "marketplace_lifecycle"
        _wait_until_reclaim_eligible(prepared)
        lifecycle.request(
            "request_eligible_pretransfer_refund",
            operation_ref=expected.operation_ref,
        )
        terminal = _terminal_projection(
            lifecycle.request(
                "wait_authoritative_refund",
                operation_ref=expected.operation_ref,
            ),
            collection=False,
        )
        execution.stage = "provider_inspection"
        refund = stripe.wait_for_refund(
            expected,
            terminal,
            timeout=provider_timeout,
            poll_interval=poll_interval,
        )
        execution.stage = "recovery"
        lifecycle.request(
            "recover_eligible_pretransfer_refund",
            operation_ref=expected.operation_ref,
        )
        repeated = stripe.wait_for_refund(
            expected,
            terminal,
            timeout=provider_timeout,
            poll_interval=poll_interval,
        )
        if repeated != refund:
            raise ProviderInvariantError("repeated refund recovery changed the original effect")
        recovery = (
            RecoveryEvidence(
                kind="worker_restart",
                process="worker",
                original_operation_preserved=True,
                checkout_count=1,
                terminal_effect_count=1,
            )
            if scenario == "worker_restart"
            else None
        )
        return _ScenarioResult(
            operation_ref=operation_ref,
            refund=refund,
            recovery=recovery,
        )

    execution.stage = "marketplace_lifecycle"
    lifecycle.request(
        "complete_portable_vm_fulfillment",
        operation_ref=expected.operation_ref,
    )
    terminal = _terminal_projection(
        lifecycle.request(
            "wait_authoritative_collection",
            operation_ref=expected.operation_ref,
        ),
        collection=True,
    )
    execution.stage = "provider_inspection"
    collection = stripe.wait_for_collection(
        expected,
        terminal,
        timeout=provider_timeout,
        poll_interval=poll_interval,
    )
    recovery = None
    if scenario == "missed_webhook":
        recovery = RecoveryEvidence(
            kind="missed_webhook",
            process="webhook_forwarder",
            original_operation_preserved=True,
            checkout_count=1,
            terminal_effect_count=1,
        )
    elif scenario == "api_restart":
        recovery = RecoveryEvidence(
            kind="api_restart",
            process="api",
            original_operation_preserved=True,
            checkout_count=1,
            terminal_effect_count=1,
        )
    return _ScenarioResult(
        operation_ref=operation_ref,
        collection=collection,
        recovery=recovery,
    )


def _wait_until_reclaim_eligible(prepared: dict[str, Any]) -> None:
    eligible_at = prepared.get("reclaim_eligible_at_unix")
    if not isinstance(eligible_at, int) or isinstance(eligible_at, bool):
        raise LifecycleContractError("refund lifecycle omitted its eligibility deadline")
    delay = eligible_at - time.time() + 1
    if delay > 0:
        time.sleep(delay)


def _prepared_effect(
    value: dict[str, Any], *, connected_account_id: str
) -> tuple[ExpectedEffect, str]:
    if any(value.get(field) is not True for field in ("discovered", "negotiated", "materialized")):
        raise LifecycleContractError("marketplace lifecycle milestones are incomplete")
    if value.get("accepted_mechanism") != "fiat.stripe.v1":
        raise LifecycleContractError("marketplace accepted the wrong settlement mechanism")
    if value.get("condition_profile") != "portable":
        raise LifecycleContractError("Stripe test lane requires a portable condition")
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
            checkout_session_id=checkout_session_id(checkout_url),
            amount=amount,
            currency=currency,
            destination_account=connected_account_id,
            transfer_group=transfer_group,
        ),
        checkout_url,
    )


def _terminal_projection(value: dict[str, Any], *, collection: bool) -> TerminalProjection:
    marketplace_state = value.get("marketplace_state")
    authority_state = value.get("authority_state")
    fulfillment_state = value.get("fulfillment_state")
    if not all(
        isinstance(item, str) and item
        for item in (marketplace_state, authority_state, fulfillment_state)
    ):
        raise LifecycleContractError("authoritative terminal state is incomplete")
    assert isinstance(marketplace_state, str)
    assert isinstance(authority_state, str)
    assert isinstance(fulfillment_state, str)
    expected_marketplace = "collected" if collection else "reclaimed"
    expected_authority = "collected" if collection else "refunded"
    if marketplace_state != expected_marketplace or authority_state != expected_authority:
        raise LifecycleContractError("authority did not reach the expected terminal state")
    return TerminalProjection(marketplace_state, authority_state, fulfillment_state)


def _browser_outcome(scenario: Scenario) -> CheckoutOutcome:
    if scenario in {"decline", "insufficient_funds", "authentication"}:
        return cast(CheckoutOutcome, scenario)
    return "success"


def _lifecycle_environment(
    args: argparse.Namespace,
    *,
    marketplace_config: Path,
    manifest_digest: str,
) -> dict[str, str]:
    return {
        "HOSTED_SETTLEMENT_E2E_MARKETPLACE_FACTORY": args.marketplace_factory,
        "HOSTED_SETTLEMENT_E2E_BUYER_CONFIG": str(args.buyer_config),
        "HOSTED_SETTLEMENT_E2E_STOREFRONT_CONFIG": str(marketplace_config),
        "HOSTED_STOREFRONT_URL": args.storefront_url,
        "HOSTED_REGISTRY_URL": args.registry_url,
        "HOSTED_PROVISIONING_URL": args.provisioning_url,
        "HOSTED_SETTLEMENT_AUTHORITY_URL": args.authority_url,
        "HOSTED_SETTLEMENT_E2E_ACCOUNT_REF": args.account_ref,
        "HOSTED_SETTLEMENT_E2E_PRODUCTION_MANIFEST_DIGEST": manifest_digest,
        "HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT": str(args.lifecycle_timeout),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--compose-env", type=Path, required=True)
    parser.add_argument("--hosted-manifest-sha256", required=True)
    parser.add_argument("--hosted-client-wheel-sha256", required=True)
    parser.add_argument("--hosted-image-digest", required=True)
    parser.add_argument("--hosted-source-commit", required=True)
    parser.add_argument("--hosted-workflow-run-id", required=True)
    parser.add_argument("--hosted-workflow-ref", required=True)
    parser.add_argument("--marketplace-commit", required=True)
    parser.add_argument("--observed-marketplace-commit", required=True)
    parser.add_argument("--run-identity", required=True)
    parser.add_argument("--scenario", choices=_SCENARIOS, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--hosted-service-env-base", type=Path)
    parser.add_argument("--container-cli", default="docker")
    parser.add_argument("--webhook-url", default="http://127.0.0.1:18080/webhooks/stripe")
    parser.add_argument("--webhook-ready-timeout", type=float, default=30.0)
    parser.add_argument("--webhook-probe-timeout", type=float, default=5.0)
    parser.add_argument("--browser-timeout-ms", type=int, default=90_000)
    parser.add_argument("--stripe-request-timeout", type=float, default=30.0)
    parser.add_argument("--provider-timeout", type=float, default=180.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--lifecycle-timeout", type=float, default=180.0)
    parser.add_argument(
        "--marketplace-factory",
        default="tests.e2e.roles.scenarios.vms.hosted.network:create_protected_marketplace",
    )
    parser.add_argument(
        "--buyer-config",
        type=Path,
        default=Path("e2e-tests/config/hosted-buyer.toml"),
    )
    parser.add_argument(
        "--storefront-config",
        type=Path,
        default=Path("e2e-tests/config/hosted-storefront.toml"),
    )
    parser.add_argument("--storefront-url", default="http://127.0.0.1:18081")
    parser.add_argument("--registry-url", default="http://127.0.0.1:8080")
    parser.add_argument("--provisioning-url", default="http://127.0.0.1:8081")
    parser.add_argument("--authority-url", default="http://127.0.0.1:18080")
    parser.add_argument("--account-ref", required=True)
    parser.add_argument("--authority-environment", required=True)
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
        return 1
    write_evidence(args.evidence, report)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
