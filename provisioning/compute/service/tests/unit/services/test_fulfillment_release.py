from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_fulfillment import FulfillmentBase, SettlementRecord, SettlementRecordState
from compute_provisioning_service.services.fulfillment_release import (
    FulfillmentReleaseBridge,
)


@pytest.mark.asyncio
async def test_bridge_starts_owned_teardown_for_active_aggregate():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    FulfillmentBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(SettlementRecord(
            capacity_reservation_id="reservation-1",
            fulfillment_id="fulfillment-1",
            owner_principal="seller-a",
            market="vms",
            scheduling_requirements={"resource_kind": "compute.gpu", "dimensions": {"gpu_count": 1}},
            settlement_resource_id="resource-1",
            pool_id="default",
            provider="ansible",
            provider_metadata={},
            state=SettlementRecordState.active.value,
        ))
        db.commit()
    repository = SimpleNamespace(get=lambda db, reservation_id: db.get(SettlementRecord, reservation_id))
    service = SimpleNamespace(begin_teardown=AsyncMock())
    bridge = FulfillmentReleaseBridge(
        session_factory=factory,
        repository=repository,
        fulfillment_service=service,
    )

    assert await bridge.ensure_teardown("reservation-1") is True
    service.begin_teardown.assert_awaited_once_with(
        fulfillment_id="fulfillment-1", owner_principal="seller-a"
    )
    assert await bridge.ensure_teardown("missing") is False
