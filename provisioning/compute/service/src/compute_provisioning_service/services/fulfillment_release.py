"""Bridge lease expiry into provisioning-owned fulfillment teardown."""

from __future__ import annotations

from typing import Any

from market_fulfillment import SettlementRecordState


class FulfillmentReleaseBridge:
    def __init__(
        self,
        *,
        session_factory: Any,
        repository: Any,
        fulfillment_service: Any,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository
        self._fulfillment_service = fulfillment_service

    async def ensure_teardown(self, capacity_reservation_id: str) -> bool:
        """Return whether fulfillment owns release, starting teardown if ready."""
        with self._session_factory() as db:
            record = self._repository.get(db, capacity_reservation_id)
            if record is None:
                return False
            state = str(record.state)
            fulfillment_id = record.fulfillment_id
            owner_principal = str(record.owner_principal)
        if fulfillment_id and state in {
            SettlementRecordState.active.value,
            SettlementRecordState.teardown_failed.value,
        }:
            await self._fulfillment_service.begin_teardown(
                fulfillment_id=str(fulfillment_id),
                owner_principal=owner_principal,
            )
        return True
