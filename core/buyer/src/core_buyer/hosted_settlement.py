"""Schema-opaque buyer transport for storefront-mediated hosted settlement."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core_buyer.action_policy import BuyerActionHandler, BuyerActionPolicy
from core_buyer.orchestrator import BuyConfig, BuyResult
from market_settlement_runtime import derive_obligation_ref
from market_identity import Identity, Signer, TrustedIdentitySet

from core_buyer.orchestrator import DEFAULT_HTTP_TIMEOUT
from core_buyer.orchestration import (
    DEFAULT_SETTLEMENT_POLL_INTERVAL,
    DEFAULT_SETTLEMENT_TIMEOUT,
    _signed_json,
    make_publisher_trust_resolver,
)

HostedProjection = dict[str, Any]
ActionHandler = Callable[[Mapping[str, Any]], None]
PollHandler = Callable[[int, Mapping[str, Any]], None]

_STABLE_PUBLIC_STATUSES = frozenset(
    {
        "ready",
        "collected",
        "reclaimed",
        "expired",
        "failed",
        "manual_required",
    }
)


@dataclass(frozen=True, slots=True)
class HostedSettlementTransport:
    """Sign and verify the provider-neutral storefront settlement lifecycle.

    The transport knows only accepted marketplace identifiers, the safe
    operation-scoped authorization reference, marketplace identities, and the
    storefront public lifecycle. Domain terms and provider models stay outside
    this boundary.
    """

    seller_url: str
    principal: Identity
    signer: Signer
    resolve_seller_principals: Callable[[], TrustedIdentitySet]
    request_timeout: float = DEFAULT_HTTP_TIMEOUT

    def start(
        self,
        *,
        negotiation_id: str,
        obligation_ref: str,
        funding_authorization_ref: str,
    ) -> HostedProjection:
        """Start one seller-accepted obligation without commercial overrides."""
        return _signed_json(
            self.seller_url.rstrip("/") + "/api/v1/settlements",
            {
                "negotiation_id": negotiation_id,
                "obligation_ref": obligation_ref,
                "funding_authorization_ref": funding_authorization_ref,
            },
            signer=self.signer,
            principal=self.principal,
            method="POST",
            operation="settlement_start",
            resource=obligation_ref,
            timeout=self.request_timeout,
            resolve_response_principals=self.resolve_seller_principals,
        )

    def status(self, *, settlement_ref: str) -> HostedProjection:
        """Retrieve the current provider-neutral public projection."""
        return _signed_json(
            self.seller_url.rstrip("/") + f"/api/v1/settlements/{settlement_ref}",
            None,
            signer=self.signer,
            principal=self.principal,
            method="GET",
            operation="settlement_status",
            resource=settlement_ref,
            timeout=self.request_timeout,
            resolve_response_principals=self.resolve_seller_principals,
        )

    def reclaim(self, *, settlement_ref: str) -> HostedProjection:
        """Request reclaim for one eligible accepted obligation."""
        return _signed_json(
            self.seller_url.rstrip("/")
            + f"/api/v1/settlements/{settlement_ref}/reclaim",
            None,
            signer=self.signer,
            principal=self.principal,
            method="POST",
            operation="settlement_reclaim",
            resource=settlement_ref,
            timeout=self.request_timeout,
            resolve_response_principals=self.resolve_seller_principals,
        )

    def wait(
        self,
        *,
        settlement_ref: str,
        poll_interval: float = DEFAULT_SETTLEMENT_POLL_INTERVAL,
        total_timeout: float = DEFAULT_SETTLEMENT_TIMEOUT,
        on_poll: PollHandler | None = None,
        on_action: ActionHandler | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> HostedProjection:
        """Poll until a stable public state while keeping actions transient."""
        deadline = monotonic() + total_timeout
        attempts = 0
        while True:
            attempts += 1
            body = self.status(settlement_ref=settlement_ref)
            action = body.get("action")
            if isinstance(action, Mapping) and on_action is not None:
                on_action(action)
            if on_poll is not None:
                on_poll(attempts, body)
            if body.get("status") in _STABLE_PUBLIC_STATUSES:
                return body
            if monotonic() >= deadline:
                raise TimeoutError(
                    "Hosted settlement did not reach a stable public status "
                    f"within {total_timeout}s"
                )
            sleep(poll_interval)

    def resume(
        self,
        *,
        settlement_ref: str,
        poll_interval: float = DEFAULT_SETTLEMENT_POLL_INTERVAL,
        total_timeout: float = DEFAULT_SETTLEMENT_TIMEOUT,
        on_poll: PollHandler | None = None,
        on_action: ActionHandler | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> HostedProjection:
        """Resume the exact accepted operation by authoritative status polling."""
        return self.wait(
            settlement_ref=settlement_ref,
            poll_interval=poll_interval,
            total_timeout=total_timeout,
            on_poll=on_poll,
            on_action=on_action,
            sleep=sleep,
            monotonic=monotonic,
        )


def make_hosted_settle_hook(
    *,
    config: BuyConfig,
    prepare_authorization: Callable[[str, Mapping[str, Any]], Any],
    poll_interval: float,
    total_timeout: float,
    sleep: Callable[[float], None],
    action_policy: BuyerActionPolicy,
    open_url: Callable[[str], Any],
    print_url: Callable[[str], Any],
    confirm: Callable[[int, dict[str, Any]], bool] | None = None,
) -> Callable[[Any, Callable[[str, dict[str, Any]], None]], BuyResult]:
    """Drive one accepted hosted plan through the shared signed transport."""

    def _hook(negotiation: Any, on_event: Callable[[str, dict[str, Any]], None]) -> BuyResult:
        outcome = negotiation.outcome
        match = negotiation.match
        if outcome is None or match is None or outcome.settlement_plan is None:
            raise ValueError("hosted settlement requires an accepted settlement plan")
        obligations = outcome.settlement_plan.obligations
        if len(obligations) != 1 or obligations[0].mechanism != "fiat.stripe.v1":
            raise ValueError("hosted settlement requires one fiat.stripe.v1 obligation")
        obligation = obligations[0].model_dump(mode="json")
        if confirm is not None and not confirm(int(obligation["amount"]), match):
            return BuyResult(
                status="exited",
                negotiation_id=outcome.negotiation_id,
                seller_url=str(match.get("storefront_url") or ""),
                agreed_amount=outcome.agreed_amount,
                reason="user_declined",
                rounds=outcome.rounds,
                attempts=negotiation.attempts,
            )
        negotiation_id = outcome.negotiation_id or ""
        obligation_ref = derive_obligation_ref(negotiation_id, 0, obligation)
        authorization = prepare_authorization(obligation_ref, obligation)
        authorization_ref = getattr(authorization, "funding_authorization_ref", None)
        if not isinstance(authorization_ref, str) or not authorization_ref:
            raise ValueError("funding authority returned no safe authorization reference")
        profile = getattr(getattr(authorization, "funding_profile", None), "value", None)
        on_event(
            "funding_authorized",
            {
                "obligation_ref": obligation_ref,
                "funding_profile": profile,
                "funding_authorization_ref": authorization_ref,
                "expires_at_unix": getattr(authorization, "expires_at_unix", None),
            },
        )
        seller_url = str(match.get("storefront_url") or "")
        if not seller_url:
            raise ValueError("listing is missing required storefront_url")
        transport = HostedSettlementTransport(
            seller_url=seller_url,
            principal=config.principal,
            signer=config.signer,
            resolve_seller_principals=make_publisher_trust_resolver(
                config=config,
                listing=match,
                on_update=lambda stage, payload: on_event(stage, payload),
            ),
        )
        started = transport.start(
            negotiation_id=negotiation_id,
            obligation_ref=obligation_ref,
            funding_authorization_ref=authorization_ref,
        )
        settlement_ref = started.get("settlement_ref")
        if not isinstance(settlement_ref, str) or not settlement_ref:
            raise RuntimeError("storefront returned no opaque hosted settlement reference")
        action_handler = BuyerActionHandler(
            action_policy,
            open_url=open_url,
            print_url=print_url,
            on_required=lambda metadata: on_event(
                "hosted_checkout_required",
                {
                    "settlement_ref": settlement_ref,
                    "action_policy": action_policy.value,
                    **metadata.as_event(),
                },
            ),
        )
        initial_action = started.get("action")
        public_action = initial_action if isinstance(initial_action, Mapping) else {}
        on_event(
            "settlement_started",
            {
                "settlement_ref": settlement_ref,
                "status": started.get("status"),
                "action_kind": public_action.get("kind"),
                "action_expires_at_unix": public_action.get("expires_at_unix"),
            },
        )
        if public_action:
            action_handler.handle(public_action)
        try:
            final = transport.wait(
                settlement_ref=settlement_ref,
                poll_interval=poll_interval,
                total_timeout=total_timeout,
                on_action=action_handler.handle,
                on_poll=lambda attempt, body: on_event(
                    "hosted_settlement_poll",
                    {
                        "attempt": attempt,
                        "settlement_ref": settlement_ref,
                        "status": body.get("status"),
                        "action_kind": (body.get("action") or {}).get("kind"),
                        "action_expires_at_unix": (body.get("action") or {}).get(
                            "expires_at_unix"
                        ),
                    },
                ),
                sleep=sleep,
            )
        except TimeoutError as exc:
            return BuyResult(
                status="timeout",
                negotiation_id=negotiation_id,
                seller_url=seller_url,
                agreed_amount=outcome.agreed_amount,
                escrow_uid=settlement_ref,
                reason=str(exc),
                rounds=outcome.rounds,
                attempts=negotiation.attempts,
            )
        succeeded = final.get("status") in {"ready", "collected"}
        result = final.get("result")
        public_result = dict(result) if isinstance(result, Mapping) else {}
        credentials = final.get("tenant_credentials")
        return BuyResult(
            status="ready" if succeeded else "failed",
            negotiation_id=negotiation_id,
            seller_url=seller_url,
            agreed_amount=outcome.agreed_amount,
            escrow_uid=settlement_ref,
            fulfillment_uid=(
                str(public_result["fulfillment_id"])
                if public_result.get("fulfillment_id") is not None
                else None
            ),
            tenant_credentials=(
                dict(credentials) if isinstance(credentials, Mapping) else None
            ),
            reason=None if succeeded else "hosted_settlement_not_completed",
            rounds=outcome.rounds,
            attempts=negotiation.attempts,
        )

    return _hook
