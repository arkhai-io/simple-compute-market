"""API-credit callbacks for the shared hosted settlement route service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from functools import partial
from typing import Any

from market_core.schemas import SettlementObligation
from market_identity import Identity
from market_settlement_runtime import (
    AuthorizedSettlementRequest,
    HostedAcceptedAgreement,
    HostedSettlementRouteCallbacks,
    HostedSettlementRouteService,
)

from apicredits_storefront.settlement_composition import (
    cleanup_hosted_settlement,
    ensure_hosted_fulfillment,
    hosted_settlement_projection,
    load_api_credit_hosted_agreement,
    reconcile_before_reclaim,
)


def build_api_credit_hosted_route_service(
    *,
    composition: Any,
    sqlite_client: Any,
    authorize_request: Callable[
        [Any, str, str, Identity, Mapping[str, Any] | None],
        Awaitable[Any],
    ],
) -> HostedSettlementRouteService:
    """Bind accepted API-credit and issuance hooks to common route mechanics."""

    async def prepare(
        agreement_ref: str,
        obligation_ref: str,
        _record: Any | None,
    ) -> HostedAcceptedAgreement:
        agreement = await load_api_credit_hosted_agreement(
            sqlite_client=sqlite_client,
            agreement_ref=agreement_ref,
            obligation_ref=obligation_ref,
            expected_claimant=composition.local_principal,
        )
        return HostedAcceptedAgreement(
            agreement_ref=agreement.agreement_ref,
            obligation_ref=agreement.obligation_ref,
            buyer_principal=agreement.buyer_principal,
            obligation=SettlementObligation.model_validate(agreement.obligation),
            mechanism_params={
                "funding_profile": agreement.option.params["funding_profile"],
            },
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

    return HostedSettlementRouteService(
        repository=composition.repository,
        runtime=composition.runtime,
        callbacks=HostedSettlementRouteCallbacks(
            prepare=prepare,
            authorize=authorize,
            reserve=reserve,
            fulfill=partial(
                ensure_hosted_fulfillment,
                composition=composition,
                sqlite_client=sqlite_client,
            ),
            project=partial(
                hosted_settlement_projection,
                composition=composition,
            ),
            cleanup=partial(
                cleanup_hosted_settlement,
                composition=composition,
                sqlite_client=sqlite_client,
            ),
            before_reclaim=partial(
                reconcile_before_reclaim,
                composition=composition,
                sqlite_client=sqlite_client,
            ),
        ),
        mechanism_id="fiat.stripe.v1",
        wake=composition.worker.wake,
    )


__all__ = ["build_api_credit_hosted_route_service"]
