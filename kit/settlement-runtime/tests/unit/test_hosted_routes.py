from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_core.schemas import SettlementObligation
from market_identity import Ed25519Signer
from market_settlement_runtime import (
    AuthorizedSettlementRequest,
    HostedAcceptedAgreement,
    HostedSettlementRouteCallbacks,
    HostedSettlementRouteError,
    HostedSettlementRouteService,
    HostedSettlementStart,
    SettlementObligationRecord,
    SettlementOperationOutcome,
)

BUYER = Ed25519Signer(b"\x72" * 32).identity
SELLER = Ed25519Signer(b"\x73" * 32).identity
OBLIGATION = SettlementObligation(
    payer="buyer",
    claimant="seller",
    payer_principal=BUYER.model_dump(mode="json"),
    claimant_principal=SELLER.model_dump(mode="json"),
    amount=100,
    asset="usd",
    expiration_unix=2_000_000_000,
    mechanism="fiat.test.v1",
)
RECORD = SettlementObligationRecord.from_obligation(
    agreement_ref="negotiation-1",
    obligation_index=0,
    obligation=OBLIGATION.model_dump(mode="json"),
).model_copy(
    update={
        "mechanism_ref": "settlement-1",
        "mechanism_status": "ready",
        "mechanism_state": {"status": "funded"},
    }
)
AGREEMENT = HostedAcceptedAgreement(
    agreement_ref="negotiation-1",
    obligation_ref=RECORD.obligation_ref,
    buyer_principal=BUYER,
    obligation=OBLIGATION,
    mechanism_params={"profile": "test.v1"},
)


def _service(
    *,
    record: SettlementObligationRecord = RECORD,
    auth: AuthorizedSettlementRequest | None = None,
    reclaim_status: str = "succeeded",
):
    repository = SimpleNamespace(
        load_settlement_obligation_by_mechanism_ref=AsyncMock(
            return_value=record.model_dump(mode="json")
        ),
        load_settlement_obligation=AsyncMock(
            return_value=record.model_dump(mode="json")
        ),
    )
    runtime = SimpleNamespace(
        materialize=AsyncMock(
            return_value=SettlementOperationOutcome(
                obligation_ref=record.obligation_ref,
                operation="materialize",
                status="succeeded",
                receipt={"safe": "receipt"},
            )
        ),
        reconcile_status=AsyncMock(
            return_value=SettlementOperationOutcome(
                obligation_ref=record.obligation_ref,
                operation="status",
                status="succeeded",
            )
        ),
        reclaim=AsyncMock(
            return_value=SettlementOperationOutcome(
                obligation_ref=record.obligation_ref,
                operation="reclaim",
                status=reclaim_status,
            )
        ),
    )
    prepare = AsyncMock(return_value=AGREEMENT)
    authorize = AsyncMock(
        return_value=auth or AuthorizedSettlementRequest(exact_retry=False)
    )
    reserve = AsyncMock(return_value=record)
    fulfill = AsyncMock(return_value=record)
    project = AsyncMock(
        return_value={
            "settlement_ref": "settlement-1",
            "obligation_ref": record.obligation_ref,
            "status": "ready",
        }
    )
    cleanup = AsyncMock()
    wake = AsyncMock()
    service = HostedSettlementRouteService(
        repository=repository,
        runtime=runtime,
        callbacks=HostedSettlementRouteCallbacks(
            prepare=prepare,
            authorize=authorize,
            reserve=reserve,
            fulfill=fulfill,
            project=project,
            cleanup=cleanup,
        ),
        mechanism_id="fiat.test.v1",
        wake=wake,
        worker_id=lambda operation: operation,
    )
    return service, SimpleNamespace(
        repository=repository,
        runtime=runtime,
        prepare=prepare,
        authorize=authorize,
        reserve=reserve,
        fulfill=fulfill,
        project=project,
        cleanup=cleanup,
        wake=wake,
    )


@pytest.mark.asyncio
async def test_start_passes_only_safe_reference_to_domain_reservation() -> None:
    service, calls = _service()
    start = HostedSettlementStart(
        negotiation_id="negotiation-1",
        obligation_ref=RECORD.obligation_ref,
        funding_authorization_ref="authorization-safe-1",
    )

    response = await service.start(object(), start)

    assert response["status"] == "ready"
    calls.reserve.assert_awaited_once_with(AGREEMENT, "authorization-safe-1")
    calls.runtime.materialize.assert_awaited_once()
    calls.fulfill.assert_awaited_once()


@pytest.mark.asyncio
async def test_exact_retry_returns_recorded_response_before_effect() -> None:
    replay = {
        "settlement_ref": "settlement-1",
        "obligation_ref": RECORD.obligation_ref,
        "status": "funding",
    }
    service, calls = _service(
        auth=AuthorizedSettlementRequest(
            exact_retry=True,
            recorded_outcome=(200, replay),
        )
    )

    response = await service.start(
        object(),
        HostedSettlementStart(
            negotiation_id="negotiation-1",
            obligation_ref=RECORD.obligation_ref,
            funding_authorization_ref="authorization-safe-1",
        ),
    )

    assert response == replay
    calls.reserve.assert_not_awaited()
    calls.runtime.materialize.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_fulfills_only_authoritative_ready_record() -> None:
    funding = RECORD.model_copy(
        update={"mechanism_status": "funding", "mechanism_state": {"status": "funding"}}
    )
    service, calls = _service(record=funding)

    await service.status(object(), "settlement-1")

    calls.fulfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_reclaim_busy_preserves_domain_and_cleanup() -> None:
    service, calls = _service(reclaim_status="busy")

    with pytest.raises(HostedSettlementRouteError) as exc_info:
        await service.reclaim(object(), "settlement-1")

    assert exc_info.value.status_code == 409
    calls.cleanup.assert_not_awaited()
