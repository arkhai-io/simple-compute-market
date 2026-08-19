"""Protected Stripe test-mode hosted settlement system driver."""

from __future__ import annotations

import argparse
from dataclasses import replace
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
)
from .evidence import (
    DiagnosticCode,
    DiagnosticEvidence,
    FundingEvidence,
    FundingProfile,
    HostedReleaseIdentityEvidence,
    IdentityEvidence,
    Interaction,
    LossEvidence,
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
    local_release_identity,
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
    EphemeralBuyerConfig,
    EphemeralMarketplaceConfig,
    EphemeralServiceEnv,
    LifecycleContractError,
    LifecycleConvergenceTimeout,
    MarketplaceLifecycleSession,
    ProcessUnavailable,
    StripeWebhookForwarder,
    parse_lifecycle_command,
    require_runtime_authority_identity,
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
    "funding_restart",
    "delayed_funding",
    "off_session_success",
    "requires_action",
    "ach_return",
    "post_collection_loss",
    "decline",
    "insufficient_funds",
    "authentication",
)
_FUNDING_PROFILES = ("card.v1", "us_bank_transfer.v1", "us_ach_debit.v1")
_INTERACTIONS = ("interactive", "saved_instrument")
_REFUND_SERVICING_INTERVAL_SECONDS = 7200.0


@dataclass
class _ExecutionState:
    stage: Stage = "authorization"
    operation_ref: str | None = None


@dataclass(frozen=True)
class _ScenarioResult:
    operation_ref: str
    funding: FundingEvidence
    collection: object | None = None
    refund: object | None = None
    payment_outcome: object | None = None
    recovery: RecoveryEvidence | None = None
    loss: LossEvidence | None = None


def run(args: argparse.Namespace) -> tuple[StripeTestEvidence, int]:
    # Provenance decides what the run may claim; it does not decide whether the
    # body may execute. Everything after this point is one code path.
    if args.release_mode == "local":
        release = local_release_identity(
            observed_marketplace_commit=args.observed_marketplace_commit,
            hosted_source_commit=args.hosted_source_commit,
            hosted_workflow_run_id=args.hosted_workflow_run_id,
            hosted_workflow_ref=args.hosted_workflow_ref,
            hosted_manifest_sha256=args.hosted_manifest_sha256,
            hosted_client_wheel_sha256=args.hosted_client_wheel_sha256,
            hosted_image_digest=args.hosted_image_digest,
            compose_env_path=args.compose_env,
        )
    else:
        release = require_release_identity(
            marketplace_commit=args.marketplace_commit,
            observed_marketplace_commit=args.observed_marketplace_commit,
            marketplace_workflow_run_id=args.marketplace_workflow_run_id,
            marketplace_workflow_ref=args.marketplace_workflow_ref,
            marketplace_manifest_sha256=args.marketplace_manifest_sha256,
            marketplace_image_digest=args.marketplace_image_digest,
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
            repository="arkhai-io/simple-compute-market",
            commit=release.marketplace_commit,
            workflow_run_id=release.marketplace_workflow_run_id,
            workflow_ref=release.marketplace_workflow_ref,
            manifest_sha256=release.marketplace_manifest_sha256,
            image_digest=release.marketplace_image_digest,
            image=release.marketplace_image,
            wheelhouse_sha256=release.marketplace_wheelhouse_sha256,
            settlement_config_schema_sha256=release.marketplace_schema_sha256,
            provenance_sha256=release.marketplace_provenance_sha256,
        ),
        hosted_release=HostedReleaseIdentityEvidence(
            repository="arkhai-io/stripe-settlement-service",
            source_commit=release.hosted_source_commit,
            workflow_run_id=release.hosted_workflow_run_id,
            workflow_ref=release.hosted_workflow_ref,
            manifest_sha256=release.hosted_manifest_sha256,
            client_wheel_sha256=release.hosted_client_wheel_sha256,
            image_digest=release.hosted_image_digest,
        ),
        run_ref=opaque_ref("run", run_identity),
        # Taken from what was bound, never from the argument: an invocation
        # cannot ask for a standing it did not earn.
        release_mode=release.mode,
    )
    scenario = cast(Scenario, args.scenario)
    funding_profile = cast(FundingProfile, args.funding_profile)
    interaction = cast(Interaction, args.interaction)
    provider = ProviderEvidence()
    execution = _ExecutionState()
    funding = FundingEvidence(
        profile=funding_profile,
        interaction=interaction,
        payer_profile_bound=False,  # type: ignore[arg-type]
        authorization_obligation_bound=False,  # type: ignore[arg-type]
        authorization_operation_scoped=False,  # type: ignore[arg-type]
        accepted_profile_preserved=False,  # type: ignore[arg-type]
        authoritative_funding_observed=False,
        transient_action_observed=False,
        delayed_state_observed=False,
    )
    try:
        _require_profile_scenario(funding_profile, interaction, scenario)
        secret = require_test_secret(os.environ.get("STRIPE_SECRET_KEY"))
        account_id = require_connected_account(os.environ.get("STRIPE_CONNECTED_ACCOUNT_ID"))
        webhook_url = require_loopback_webhook(args.webhook_url)
        buyer_identity_scheme = os.environ.get("HOSTED_SETTLEMENT_E2E_BUYER_IDENTITY_SCHEME", "")
        if buyer_identity_scheme not in {"eip191", "ed25519"}:
            raise AuthorizationUnavailable("protected buyer identity scheme is unavailable")
        runtime_authority = require_runtime_authority_identity(
            args.hosted_service_env_base,
            release_authority_address=release.hosted_authority_address,
        )
        stripe = StripeApi(secret, timeout=args.stripe_request_timeout)

        execution.stage = "account_readiness"
        account = stripe.retrieve_account(account_id)
        require_ready_account(account, account_id)
        binding_contract = _maintained_account_binding(
            storefront_config=args.storefront_config,
            authority_id=runtime_authority.authority_id,
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
            with (
                EphemeralMarketplaceConfig(
                    template=args.storefront_config,
                    account_ref=args.account_ref,
                    authority_id=runtime_authority.authority_id,
                    authority_scheme=runtime_authority.scheme,
                    authority_address=runtime_authority.identifier,
                    authority_environment=args.authority_environment,
                    manifest_digest=release.hosted_manifest_digest,
                    funding_profile=funding_profile,
                    shared_directory=args.compose_env.parent,
                ) as marketplace_config,
                EphemeralBuyerConfig(
                    template=args.buyer_config,
                    authority_id=runtime_authority.authority_id,
                    authority_scheme=runtime_authority.scheme,
                    authority_address=runtime_authority.identifier,
                    authority_environment=args.authority_environment,
                    authority_base_url=args.authority_url,
                    manifest_digest=release.hosted_manifest_digest,
                    buyer_identity_scheme=buyer_identity_scheme,
                    funding_profile=funding_profile,
                    shared_directory=args.compose_env.parent,
                ) as buyer_config,
            ):
                with EphemeralServiceEnv(
                    api_key=secret,
                    webhook_secret=webhook_secret,
                    authority_environment=args.authority_environment,
                    manifest_digest=release.hosted_manifest_digest,
                    release_authority_id=release.hosted_authority_id,
                    release_authority_address=release.hosted_authority_address,
                    release_repository="arkhai-io/stripe-settlement-service",
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
                                buyer_config=buyer_config,
                                marketplace_config=marketplace_config,
                                manifest_digest=release.hosted_manifest_digest,
                            ),
                            request_timeout=args.lifecycle_timeout,
                        ) as lifecycle:
                            result = _execute_scenario(
                                funding_profile=funding_profile,
                                interaction=interaction,
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
                                account_ref=args.account_ref,
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
                funding=result.funding,
                operation_ref=result.operation_ref,
                collection=result.collection,  # type: ignore[arg-type]
                refund=result.refund,  # type: ignore[arg-type]
                payment_outcome=result.payment_outcome,  # type: ignore[arg-type]
                recovery=result.recovery,
                loss=result.loss,
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
            elif execution.stage == "payer_profile":
                code = "payer_profile_unavailable"
            elif execution.stage == "payer_setup":
                code = "setup_action_unavailable"
            elif execution.stage in {"funding_authorization", "funding"}:
                code = "profile_prerequisite_unavailable"
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
            funding=funding,
            operation_ref=execution.operation_ref,
            diagnostic=DiagnosticEvidence(stage=execution.stage, code=code),
        ),
        1,
    )


def _require_profile_scenario(
    funding_profile: FundingProfile,
    interaction: Interaction,
    scenario: Scenario,
) -> None:
    if funding_profile == "us_bank_transfer.v1" and interaction != "interactive":
        raise AuthorizationRejected("push bank transfer must use interactive funding")
    if interaction == "saved_instrument" and funding_profile not in {
        "card.v1",
        "us_ach_debit.v1",
    }:
        raise AuthorizationRejected("saved funding requires a card or ACH profile")
    if scenario == "off_session_success" and (
        funding_profile not in {"card.v1", "us_ach_debit.v1"} or interaction != "saved_instrument"
    ):
        raise AuthorizationRejected("off-session scenarios require saved card or ACH funding")
    if scenario == "requires_action" and (
        funding_profile != "card.v1" or interaction != "saved_instrument"
    ):
        raise AuthorizationRejected("requires-action fallback requires saved card funding")
    if scenario in {"ach_return", "post_collection_loss"} and funding_profile != "us_ach_debit.v1":
        raise AuthorizationRejected("ACH loss scenarios require the ACH funding profile")
    if scenario in {"delayed_funding", "funding_restart"} and funding_profile == "card.v1":
        raise AuthorizationRejected(
            "delayed funding scenarios require an asynchronous bank profile"
        )
    if scenario in {"decline", "insufficient_funds", "authentication"} and (
        funding_profile != "card.v1" or interaction != "interactive"
    ):
        raise AuthorizationRejected("card outcome scenarios require interactive card funding")


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
    funding_profile: FundingProfile = "card.v1",
) -> BrowserPaymentResult:
    forwarder.pause()
    try:
        return browser.pay(
            checkout_url,
            outcome=outcome,
            funding_profile=funding_profile,
        )
    finally:
        forwarder.resume()


def _execute_scenario(
    *,
    scenario: Scenario,
    funding_profile: FundingProfile,
    interaction: Interaction,
    lifecycle: MarketplaceLifecycleSession,
    stripe: StripeApi,
    browser: ChromiumCheckout,
    forwarder: StripeWebhookForwarder,
    account_ref: str,
    stack: ComposeStack,
    connected_account_id: str,
    provider_timeout: float,
    poll_interval: float,
    execution: _ExecutionState,
) -> _ScenarioResult:
    execution.stage = "payer_profile"
    payer_fixture = lifecycle.request(
        "ensure_payer_profile_fixture",
        funding_profile=funding_profile,
        interaction=interaction,
    )
    setup_action = _validate_payer_fixture(
        payer_fixture,
        interaction=interaction,
    )
    if setup_action is not None:
        execution.stage = "browser_checkout"
        browser.complete_setup(
            setup_action["url"],
            funding_profile=funding_profile,
        )
        refreshed = lifecycle.request("complete_payer_setup")
        if _validate_payer_fixture(refreshed, interaction=interaction) is not None:
            raise LifecycleContractError("payer setup remained incomplete after browser consent")
    case = "refund" if scenario in {"reclaim", "worker_restart"} else "collection"
    execution.stage = "funding_authorization"
    prepared = lifecycle.request(
        f"prepare_{case}",
        funding_profile=funding_profile,
        interaction=interaction,
    )
    expected, action_kind, action_url = _prepared_effect(
        prepared,
        account_ref=account_ref,
        connected_account_id=connected_account_id,
        funding_profile=funding_profile,
    )
    operation_ref = opaque_ref("op", expected.marketplace_operation_id)
    execution.operation_ref = operation_ref
    if scenario == "api_restart":
        execution.stage = "recovery"
        stack.restart("api")

    delayed_observed = False
    if scenario in {"delayed_funding", "funding_restart", "ach_return", "post_collection_loss"}:
        execution.stage = "funding"
        pending = lifecycle.request(
            "observe_pending_funding",
            operation_ref=expected.marketplace_operation_id,
        )
        if (
            pending.get("funding_state") not in {"awaiting_payment", "pending"}
            or pending.get("fulfillment_started") is not False
            or pending.get("funding_profile") != funding_profile
        ):
            raise LifecycleContractError(
                "delayed funding did not remain pending before fulfillment"
            )
        delayed_observed = True
        if scenario == "funding_restart":
            execution.stage = "recovery"
            stack.restart("worker")

    payment: BrowserPaymentResult | None = None
    browser_outcome = _browser_outcome(scenario)
    if action_url is not None:
        execution.stage = "browser_checkout"
        if scenario == "missed_webhook":
            payment = _pay_with_forwarding_paused(
                forwarder,
                browser,
                action_url,
                outcome=browser_outcome,
                funding_profile=funding_profile,
            )
            execution.stage = "recovery"
            stack.restart("worker")
        else:
            payment = (
                browser.confirm(action_url)
                if action_kind == "confirmation"
                else browser.pay(
                    action_url,
                    outcome=browser_outcome,
                    funding_profile=funding_profile,
                )
            )
        if payment.checkout_session_id is not None:
            expected = replace(expected, checkout_session_id=payment.checkout_session_id)
    elif action_kind == "bank_instructions":
        execution.stage = "funding"
        stripe.fund_test_cash_balance(expected)
    elif interaction == "interactive":
        raise LifecycleContractError("interactive funding omitted its transient payer action")

    if scenario in {"decline", "insufficient_funds"}:
        execution.stage = "provider_inspection"
        payment_outcome = stripe.wait_for_payment_outcome(
            expected,
            cast(Literal["decline", "insufficient_funds"], scenario),
            timeout=provider_timeout,
            poll_interval=poll_interval,
        )
        return _ScenarioResult(
            operation_ref=operation_ref,
            funding=_funding_evidence(
                funding_profile,
                interaction,
                authoritative=False,
                action_observed=action_kind is not None,
                delayed=delayed_observed,
            ),
            payment_outcome=payment_outcome,
        )

    execution.stage = "funding"
    funded = lifecycle.request(
        "wait_authoritative_funding",
        operation_ref=expected.marketplace_operation_id,
    )
    _validate_authoritative_funding(funded, funding_profile=funding_profile)
    funding = _funding_evidence(
        funding_profile,
        interaction,
        authoritative=True,
        action_observed=action_kind is not None,
        delayed=delayed_observed,
    )
    if scenario == "authentication":
        execution.stage = "provider_inspection"
        return _ScenarioResult(
            operation_ref=operation_ref,
            funding=funding,
            payment_outcome=stripe.wait_for_payment_outcome(
                expected,
                "authentication",
                timeout=provider_timeout,
                poll_interval=poll_interval,
            ),
        )
    if scenario == "ach_return":
        execution.stage = "loss_boundary"
        induced = lifecycle.request(
            "induce_test_ach_return",
            operation_ref=expected.marketplace_operation_id,
        )
        if induced.get("available") is False:
            raise ProcessUnavailable(
                "protected producer exposes no exact ACH return test-mode helper"
            )
        observed_loss = lifecycle.request(
            "wait_authoritative_loss",
            operation_ref=expected.marketplace_operation_id,
        )
        if observed_loss.get("available") is False:
            raise ProcessUnavailable(
                "protected producer exposes no authoritative ACH loss projection"
            )
        loss = _loss_evidence(observed_loss, scenario)
        return _ScenarioResult(operation_ref=operation_ref, funding=funding, loss=loss)

    if scenario in {"reclaim", "worker_restart"}:
        if scenario == "worker_restart":
            execution.stage = "recovery"
            stack.restart("worker")
        execution.stage = "marketplace_lifecycle"
        _wait_until_reclaim_eligible(prepared)
        lifecycle.request(
            "request_eligible_pretransfer_refund",
            operation_ref=expected.marketplace_operation_id,
        )
        terminal = _terminal_projection(
            lifecycle.request(
                "wait_authoritative_refund",
                operation_ref=expected.marketplace_operation_id,
            ),
            collection=False,
        )
        execution.stage = "provider_inspection"
        refund = stripe.wait_for_refund(
            expected, terminal, timeout=provider_timeout, poll_interval=poll_interval
        )
        lifecycle.request(
            "recover_eligible_pretransfer_refund",
            operation_ref=expected.marketplace_operation_id,
        )
        if (
            stripe.wait_for_refund(
                expected, terminal, timeout=provider_timeout, poll_interval=poll_interval
            )
            != refund
        ):
            raise ProviderInvariantError("repeated refund recovery changed the original effect")
        recovery = (
            RecoveryEvidence(
                kind="worker_restart",
                process="worker",
                original_operation_preserved=True,
                checkout_count=int(expected.checkout_session_id is not None),
                terminal_effect_count=1,
            )
            if scenario == "worker_restart"
            else None
        )
        return _ScenarioResult(
            operation_ref=operation_ref,
            funding=funding,
            refund=refund,
            recovery=recovery,
        )

    execution.stage = "marketplace_lifecycle"
    lifecycle.request(
        "complete_portable_vm_fulfillment",
        operation_ref=expected.marketplace_operation_id,
    )
    terminal = _terminal_projection(
        lifecycle.request(
            "wait_authoritative_collection",
            operation_ref=expected.marketplace_operation_id,
        ),
        collection=True,
    )
    execution.stage = "provider_inspection"
    collection = stripe.wait_for_collection(
        expected, terminal, timeout=provider_timeout, poll_interval=poll_interval
    )
    recovery = None
    if scenario in {"missed_webhook", "api_restart", "funding_restart"}:
        process = (
            "webhook_forwarder"
            if scenario == "missed_webhook"
            else ("api" if scenario == "api_restart" else "worker")
        )
        recovery = RecoveryEvidence(
            kind=scenario,
            process=process,
            original_operation_preserved=True,
            checkout_count=int(expected.checkout_session_id is not None),
            terminal_effect_count=1,
        )
    loss = None
    if scenario == "post_collection_loss":
        execution.stage = "loss_boundary"
        induced = lifecycle.request(
            "induce_test_post_collection_loss",
            operation_ref=expected.marketplace_operation_id,
        )
        if induced.get("available") is False:
            raise ProcessUnavailable(
                "protected producer exposes no exact post-collection loss test helper"
            )
        observed_loss = lifecycle.request(
            "wait_authoritative_loss",
            operation_ref=expected.marketplace_operation_id,
        )
        if observed_loss.get("available") is False:
            raise ProcessUnavailable(
                "protected producer exposes no authoritative post-collection loss projection"
            )
        loss = _loss_evidence(observed_loss, scenario)
    return _ScenarioResult(
        operation_ref=operation_ref,
        funding=funding,
        collection=collection,
        recovery=recovery,
        loss=loss,
    )


def _wait_until_reclaim_eligible(prepared: dict[str, Any]) -> None:
    eligible_at = prepared.get("reclaim_eligible_at_unix")
    if not isinstance(eligible_at, int) or isinstance(eligible_at, bool):
        raise LifecycleContractError("refund lifecycle omitted its eligibility deadline")
    delay = eligible_at - time.time() + 1
    if delay > 0:
        time.sleep(delay)


def _prepared_effect(
    value: dict[str, Any],
    *,
    connected_account_id: str,
    account_ref: str,
    funding_profile: FundingProfile,
) -> tuple[ExpectedEffect, str | None, str | None]:
    if value.get("available") is False:
        raise ProcessUnavailable("selected hosted funding profile is unavailable")
    public_value = dict(value)
    action = public_value.pop("payer_action", None)
    _reject_private_fields(public_value)
    if any(value.get(field) is not True for field in ("discovered", "negotiated", "materialized")):
        raise LifecycleContractError("marketplace lifecycle milestones are incomplete")
    if (
        value.get("accepted_mechanism") != "fiat.stripe.v1"
        or value.get("accepted_funding_profile") != funding_profile
        or value.get("destination_account_ref") != account_ref
        or value.get("condition_profile") != "portable"
        or value.get("parties_authoritative") is not True
        or value.get("funding_authorization_bound") is not True
        or value.get("funding_authorization_operation_scoped") is not True
    ):
        raise LifecycleContractError("materialization drifted from immutable accepted terms")
    operation_ref = value.get("operation_ref")
    marketplace_operation_id = value.get("marketplace_operation_id")
    amount = value.get("amount")
    currency = value.get("currency")
    transfer_group = value.get("transfer_group")
    accepted_negotiation_id = value.get("accepted_negotiation_id")
    obligation_id = value.get("obligation_id")
    condition_hash = value.get("accepted_condition_hash")
    # The action is transient and was removed before scanning persistable fields.
    if (
        not all(
            isinstance(item, str) and item
            for item in (
                operation_ref,
                marketplace_operation_id,
                transfer_group,
                accepted_negotiation_id,
                obligation_id,
                condition_hash,
            )
        )
        or not isinstance(amount, int)
        or isinstance(amount, bool)
        or amount <= 0
        or not isinstance(currency, str)
        or len(currency) != 3
        or currency != currency.lower()
    ):
        raise LifecycleContractError("marketplace materialization response is incomplete")
    action_kind: str | None = None
    action_url: str | None = None
    if action is not None:
        if not isinstance(action, dict):
            raise LifecycleContractError("payer action projection is malformed")
        action_kind = action.get("kind")
        action_url = action.get("url")
        if action_kind not in {"payment", "confirmation", "bank_instructions"}:
            raise LifecycleContractError("payer action kind is unsupported")
        if action_url is not None and not isinstance(action_url, str):
            raise LifecycleContractError("payer action URL is malformed")
        if action_kind == "bank_instructions" and action_url is not None:
            raise LifecycleContractError(
                "bank instructions must not be represented as an action URL"
            )
    assert isinstance(operation_ref, str)
    assert isinstance(marketplace_operation_id, str)
    assert isinstance(transfer_group, str)
    assert isinstance(amount, int)
    assert isinstance(currency, str)
    return (
        ExpectedEffect(
            operation_ref=operation_ref,
            marketplace_operation_id=marketplace_operation_id,
            funding_profile=funding_profile,
            checkout_session_id=None,
            amount=amount,
            currency=currency,
            destination_account=connected_account_id,
            transfer_group=transfer_group,
        ),
        action_kind,
        action_url,
    )


def _validate_payer_fixture(
    value: dict[str, Any],
    *,
    interaction: Interaction,
) -> dict[str, Any] | None:
    if value.get("available") is False:
        raise ProcessUnavailable("hosted payer profile fixture is unavailable")
    public = dict(value)
    setup_action = public.pop("setup_action", None)
    _reject_private_fields(public)
    if (
        value.get("selected_owner_bound") is not True
        or value.get("historical_owner_recoverable") is not True
        or value.get("opaque_binding_persisted") is not True
        or value.get("action_persisted") is not False
    ):
        raise LifecycleContractError("payer fixture is not bound to the selected marketplace owner")
    if interaction != "saved_instrument" or value.get("saved_instrument_ready") is True:
        if setup_action is not None:
            raise LifecycleContractError("ready payer fixture returned a stale setup action")
        return None
    if (
        not isinstance(setup_action, dict)
        or setup_action.get("kind") != "setup"
        or not isinstance(setup_action.get("url"), str)
        or not setup_action["url"].startswith("https://")
        or not isinstance(setup_action.get("expires_at_unix"), int)
        or setup_action["expires_at_unix"] <= int(time.time())
    ):
        raise ProcessUnavailable(
            "saved instrument setup requires a current Stripe test-mode browser action"
        )
    return setup_action


def _validate_authoritative_funding(
    value: dict[str, Any], *, funding_profile: FundingProfile
) -> None:
    _reject_private_fields(value)
    if (
        value.get("funding_state") != "funded"
        or value.get("funding_profile") != funding_profile
        or value.get("authoritative_retrieval") is not True
        or value.get("accepted_identity_preserved") is not True
        or value.get("fulfillment_started") is not False
    ):
        raise LifecycleContractError("funding gate was not authoritative or fulfillment-safe")


def _funding_evidence(
    profile: FundingProfile,
    interaction: Interaction,
    *,
    authoritative: bool,
    action_observed: bool,
    delayed: bool,
) -> FundingEvidence:
    return FundingEvidence(
        profile=profile,
        interaction=interaction,
        payer_profile_bound=True,
        authorization_obligation_bound=True,
        authorization_operation_scoped=True,
        accepted_profile_preserved=True,
        authoritative_funding_observed=authoritative,
        transient_action_observed=action_observed,
        delayed_state_observed=delayed,
    )


def _loss_evidence(value: dict[str, Any], scenario: Scenario) -> LossEvidence:
    _reject_private_fields(value)
    if (
        scenario not in {"ach_return", "post_collection_loss"}
        or value.get("accepted_operation_preserved") is not True
        or value.get("loss_kind") != scenario
    ):
        raise LifecycleContractError("funding loss did not preserve the accepted operation")
    fulfillment_blocked = value.get("fulfillment_blocked")
    operator_incident = value.get("operator_incident_observed")
    if not isinstance(fulfillment_blocked, bool) or not isinstance(operator_incident, bool):
        raise LifecycleContractError("funding loss projection is incomplete")
    if scenario == "ach_return" and not fulfillment_blocked:
        raise LifecycleContractError("pre-collection ACH return did not block fulfillment")
    if scenario == "post_collection_loss" and not operator_incident:
        raise LifecycleContractError("post-collection loss did not open an operator incident")
    return LossEvidence(
        kind=scenario,
        accepted_operation_preserved=True,
        fulfillment_blocked=fulfillment_blocked,
        operator_incident_observed=operator_incident,
    )


def _terminal_projection(value: dict[str, Any], *, collection: bool) -> TerminalProjection:
    _reject_private_fields(value)
    marketplace_state = value.get("marketplace_state")
    authority_state = value.get("authority_state")
    fulfillment_state = value.get("fulfillment_state")
    effect_operation_ref = value.get("effect_operation_ref")
    if not all(
        isinstance(item, str) and item
        for item in (
            marketplace_state,
            authority_state,
            fulfillment_state,
            effect_operation_ref,
        )
    ):
        raise LifecycleContractError("authoritative terminal state is incomplete")
    expected_marketplace = "collected" if collection else "reclaimed"
    expected_authority = "collected" if collection else "refunded"
    if marketplace_state != expected_marketplace or authority_state != expected_authority:
        raise LifecycleContractError("authority did not reach the expected terminal state")
    assert isinstance(marketplace_state, str)
    assert isinstance(authority_state, str)
    assert isinstance(fulfillment_state, str)
    assert isinstance(effect_operation_ref, str)
    return TerminalProjection(
        marketplace_state,
        authority_state,
        fulfillment_state,
        effect_operation_ref,
    )


def _reject_private_fields(value: object) -> None:
    forbidden = {
        "payer_profile_ref",
        "instrument_ref",
        "customer_id",
        "payment_method_id",
        "client_secret",
        "provider_payload",
        "mandate",
        "bank_instructions",
        "card_details",
    }
    if isinstance(value, dict):
        if forbidden.intersection(value):
            raise LifecycleContractError("private hosted/provider material crossed the marketplace")
        for child in value.values():
            _reject_private_fields(child)
    elif isinstance(value, list):
        for child in value:
            _reject_private_fields(child)


def _browser_outcome(scenario: Scenario) -> CheckoutOutcome:
    if scenario in {"decline", "insufficient_funds", "authentication"}:
        return cast(CheckoutOutcome, scenario)
    return "success"


def _lifecycle_environment(
    args: argparse.Namespace,
    *,
    buyer_config: Path,
    marketplace_config: Path,
    manifest_digest: str,
) -> dict[str, str]:
    return {
        "HOSTED_SETTLEMENT_E2E_MARKETPLACE_FACTORY": args.marketplace_factory,
        "HOSTED_SETTLEMENT_E2E_BUYER_CONFIG": str(buyer_config),
        "HOSTED_SETTLEMENT_E2E_STOREFRONT_CONFIG": str(marketplace_config),
        "HOSTED_STOREFRONT_URL": args.storefront_url,
        "HOSTED_REGISTRY_URL": args.registry_url,
        "HOSTED_PROVISIONING_URL": args.provisioning_url,
        "HOSTED_SETTLEMENT_AUTHORITY_URL": args.authority_url,
        "HOSTED_SETTLEMENT_E2E_ACCOUNT_REF": args.account_ref,
        "HOSTED_SETTLEMENT_E2E_PRODUCTION_MANIFEST_DIGEST": manifest_digest,
        "HOSTED_SETTLEMENT_E2E_FUNDING_PROFILE": args.funding_profile,
        "HOSTED_SETTLEMENT_E2E_INTERACTION": args.interaction,
        "HOSTED_SETTLEMENT_E2E_SCENARIO": args.scenario,
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
    parser.add_argument("--marketplace-commit", default="")
    parser.add_argument("--observed-marketplace-commit", required=True)
    parser.add_argument(
        "--release-mode",
        choices=("attested", "local"),
        default="attested",
        help="attested binds a released consumer to a released producer; "
        "local runs the same body for development and can never qualify.",
    )
    parser.add_argument("--marketplace-workflow-run-id", default="")
    parser.add_argument("--marketplace-workflow-ref", default="")
    parser.add_argument("--marketplace-manifest-sha256", default="")
    parser.add_argument("--marketplace-image-digest", default="")
    parser.add_argument("--run-identity", required=True)
    parser.add_argument("--scenario", choices=_SCENARIOS, required=True)
    parser.add_argument("--funding-profile", choices=_FUNDING_PROFILES, required=True)
    parser.add_argument("--interaction", choices=_INTERACTIONS, required=True)
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
