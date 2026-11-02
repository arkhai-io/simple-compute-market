"""Authenticated site intent reports, separate from capacity-return callbacks."""

import asyncio
import logging

from market_deal_servicing import EndSession
from market_deal_servicing.evidence import in_transaction
from compute_provisioning_contracts import LEASE_ENDED_CALLBACK, LeaseEndedEvent, SignedLeaseEndedReport
from fastapi import APIRouter, HTTPException, Request
from market_deal_lifecycle_contracts.models import DeliveryView

from market_storefront import container

logger = logging.getLogger(__name__)
router = APIRouter(tags=["lifecycle"])


@router.post(LEASE_ENDED_CALLBACK["path"], response_model=DeliveryView)
async def lease_ended(capacity_reservation_id: str, request: Request) -> DeliveryView:
    if not getattr(request.state, "service_peer_authenticated", False):
        raise HTTPException(status_code=401, detail="Site service-peer authentication required")
    lifecycle = getattr(container.resolved_settlement_composition, "lifecycle", None)
    if lifecycle is None:
        raise HTTPException(status_code=503, detail="Delivery lifecycle is unavailable")
    body = await request.body()
    try:
        report = SignedLeaseEndedReport.model_validate_json(body)
        event = LeaseEndedEvent.model_validate_json(report.payload)
        if event.capacity_reservation_id != capacity_reservation_id:
            raise ValueError("report reservation differs from callback path")
        negotiation_id = await asyncio.to_thread(lifecycle.reservation_deal, capacity_reservation_id, event.site_id)
        await asyncio.to_thread(lifecycle.ingress.site_report, negotiation_id, body=body, headers=dict(request.headers))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown committed reservation") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Delivery intent is durable before any physical or financial I/O. A
    # transient site failure must not discard an acknowledged signed report.
    try:
        await lifecycle.end.drive_physical(negotiation_id)
    except Exception:
        logger.exception("VM report physical end awaits recovery for %s", negotiation_id)
    return await in_transaction(lifecycle.path, lambda conn: EndSession(conn).view(negotiation_id))
