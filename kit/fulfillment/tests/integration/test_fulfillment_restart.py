"""Library integration test: status and result reads after a restart.

A fresh orchestrator composed over the same file-backed SQLite database reads
fulfillment status and result from durable state alone.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_core import VersionedEnvelope
from market_fulfillment import (
    FulfillmentOrchestrator,
    ProviderRegistry,
    SettlementRecordState,
)
from market_fulfillment.db import (
    Base as FulfillmentBase,
    ProvisionedResource,
    SettlementRecord,
)
from market_fulfillment.fulfillment_persistence import SqlAlchemyFulfillmentUnitOfWork


class _ProviderMock(MagicMock):
    """A mock provider that, like every real one, declares its host need."""

    needs_host = True


def _provider():
    provider = _ProviderMock()
    # A bare MagicMock returns a truthy Mock for any attribute, which the
    # orchestrator would read as a job id.
    provider.resolve_executor_job_id.return_value = None
    provider.fetch_credentials = AsyncMock(
        return_value=VersionedEnvelope(
            kind="vm.fulfillment.result.v1",
            schema_version=1,
            payload={"credentials": [{"role": "tenant", "password": "s3cr3t"}]},
        )
    )
    return provider


@pytest.mark.asyncio
async def test_fresh_service_composition_reads_status_and_result_from_same_file_database(tmp_path):
    """A new composition reconstructs status/result reads from durable state only."""
    database = tmp_path / "fulfillment-result-restart.db"
    database_url = f"sqlite:///{database}"

    first_engine = create_engine(database_url)
    FulfillmentBase.metadata.create_all(bind=first_engine)
    first_factory = sessionmaker(bind=first_engine)
    with first_factory() as db:
        db.add(
            SettlementRecord(
                capacity_reservation_id="reservation-restart-1",
                fulfillment_id="fulfillment-restart-1",
                market="vms",
                scheduling_requirements={"resource_kind": "vm"},
                settlement_resource_id="host-1",
                pool_id="pool-1",
                provider="ansible",
                resource_attributes={},
                resource_host_id="host-1",
                fulfillment_request=VersionedEnvelope(
                    kind="vm.fulfillment.request",
                    schema_version=1,
                    payload={"vm_target": "vm-1"},
                ).model_dump(mode="json"),
                provider_metadata={"current_job_id": "job-restart-1"},
                state=SettlementRecordState.active.value,
            )
        )
        db.add(
            ProvisionedResource(
                provisioned_resource_id="provisioned-restart-1",
                capacity_reservation_id="reservation-restart-1",
                fulfillment_id="fulfillment-restart-1",
                status="active",
            )
        )
        db.commit()
    first_engine.dispose()

    second_engine = create_engine(database_url)
    second_factory = sessionmaker(bind=second_engine)
    provider = _provider()
    restarted = FulfillmentOrchestrator(
        provider_registry=ProviderRegistry({"ansible": provider}),
        unit_of_work=SqlAlchemyFulfillmentUnitOfWork(
            session_factory=second_factory,
            pool_service=MagicMock(),
        ),
    )

    status = restarted.get_fulfillment_status("fulfillment-restart-1")
    result = await restarted.get_fulfillment_result("fulfillment-restart-1")

    assert status.fulfillment_id == "fulfillment-restart-1"
    assert status.capacity_reservation_id == "reservation-restart-1"
    assert status.state == SettlementRecordState.active.value
    assert result.payload["fulfillment_id"] == "fulfillment-restart-1"
    assert result.payload["provisioned_resources"] == [
        {
            "provisioned_resource_id": "provisioned-restart-1",
            "status": "active",
        }
    ]
    provider.fetch_credentials.assert_awaited_once()
    second_engine.dispose()
