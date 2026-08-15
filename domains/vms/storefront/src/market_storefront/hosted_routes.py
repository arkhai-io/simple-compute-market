"""VM domain callbacks for the shared hosted settlement route service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from market_core.schemas import SettlementObligation
from market_identity import Identity
from market_settlement_runtime import (
    AuthorizedSettlementRequest,
    HostedAcceptedAgreement,
    HostedSettlementRouteCallbacks,
    HostedSettlementRouteService,
)

from market_storefront.settlement_composition import (
    ensure_hosted_fulfillment,
    hosted_settlement_projection,
    load_hosted_agreement,
    truncate_lease_for_terminal_settlement,
)


def build_vm_hosted_route_service(
    *,
    composition: Any,
    sqlite_client: Any,
    authorize_request: Callable[
        [Any, str, str, Identity, Mapping[str, Any] | None],
        Awaitable[Any],
    ],
) -> HostedSettlementRouteService:
    """Bind VM accepted-state and provisioning hooks to common mechanics."""

    async def prepare(
        agreement_ref: str,
        obligation_ref: str,
        record: Any | None,
    ) -> HostedAcceptedAgreement:
        agreement = await load_hosted_agreement(
            sqlite_client=sqlite_client,
            negotiation_id=agreement_ref,
            obligation_ref=obligation_ref,
            expected_claimant=composition.local_principal,
            allow_legacy_recovery=(
                record is not None
                and record.mechanism_params.get("legacy_recovery")
                == "hosted-card.v1"
            ),
        )
        mechanism_params: dict[str, Any] = {
            "funding_profile": agreement.funding_profile.value,
        }
        if agreement.legacy_recovery:
            mechanism_params["legacy_recovery"] = "hosted-card.v1"
        return HostedAcceptedAgreement(
            agreement_ref=agreement.negotiation_id,
            obligation_ref=agreement.obligation_ref,
            buyer_principal=agreement.buyer_principal,
            obligation=SettlementObligation.model_validate(agreement.obligation),
            mechanism_params=mechanism_params,
        )

    async def authorize(
        request_context: Any,
        operation: str,
        resource_id: str,
        expected_principal: Identity,
        body: Mapping[str, Any] | None,
    ) -> AuthorizedSettlementRequest:
        auth = await authorize_request(
            request_context,
            operation,
            resource_id,
            expected_principal,
            body,
        )
        return AuthorizedSettlementRequest(
            exact_retry=bool(auth.exact_retry),
            recorded_outcome=auth.recorded_outcome,
        )

    async def reserve(
        agreement: HostedAcceptedAgreement,
        funding_authorization_ref: str,
    ) -> Any:
        records = await composition.runtime.register_plan(
            agreement_ref=agreement.agreement_ref,
            obligations=[agreement.obligation.model_dump(mode="json")],
        )
        return await composition.runtime.bind_mechanism_params(
            records[0].obligation_ref,
            {
                **agreement.mechanism_params,
                "funding_authorization_ref": funding_authorization_ref,
            },
            local_principal=agreement.buyer_principal,
        )

    async def fulfill(record: Any, worker_id: str) -> Any:
        return await ensure_hosted_fulfillment(
            composition=composition,
            sqlite_client=sqlite_client,
            record=record,
            worker_id=worker_id,
        )

    async def project(
        record: Any,
        transient_action: Any | None,
        transient_receipt: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        return await hosted_settlement_projection(
            composition=composition,
            record=record,
            transient_action=transient_action,
            transient_receipt=transient_receipt,
        )

    async def cleanup(agreement_ref: str, reason: str) -> None:
        await truncate_lease_for_terminal_settlement(
            agreement_ref=agreement_ref,
            reason=reason,
            sqlite_client=sqlite_client,
        )

    return HostedSettlementRouteService(
        repository=composition.repository,
        runtime=composition.runtime,
        callbacks=HostedSettlementRouteCallbacks(
            prepare=prepare,
            authorize=authorize,
            reserve=reserve,
            fulfill=fulfill,
            project=project,
            cleanup=cleanup,
        ),
        mechanism_id="fiat.stripe.v1",
        wake=composition.worker.wake,
    )
