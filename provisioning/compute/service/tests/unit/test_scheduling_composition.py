from __future__ import annotations

import pytest
from dependency_injector import providers

from compute_provisioning_service.container import Container
from compute_provisioning_service.db.database import (
    create_db_engine,
    create_session_factory,
    run_migrations,
)
from market_fulfillment import (
    PhysicalSettlementRequest,
    SettlementRepository,
)
from market_resource_pools import PoolCreate, ResourcePoolService


class _ProviderHandler:
    provider = "ansible"

    def validate_config(self, config):
        return dict(config)

    def validate_config_problems(self, config):
        return dict(config), ()

    def read_config(self, _db, _pool_id):
        return {}

    def replace_config(self, _db, _pool_id, _config):
        return None

    def delete_config(self, _db, _pool_id):
        return None


def _container(tmp_path, *, repository=None):
    engine = create_db_engine(
        f"sqlite:///{tmp_path / 'compute.db'}",
        is_sqlite=True,
    )
    run_migrations(engine)
    session_factory = create_session_factory(engine)
    pools = ResourcePoolService(
        session_factory,
        {"ansible": _ProviderHandler()},
    )
    container = Container()
    container.db_engine.override(providers.Object(engine))
    container.session_factory.override(providers.Object(session_factory))
    container.resource_pool_service.override(providers.Object(pools))
    if repository is not None:
        container.settlement_repository.override(providers.Object(repository))
    return container, session_factory, pools


def _prepare(container, session_factory, pools):
    pools.create_pool(PoolCreate(
        id="pool-a",
        label="Pool A",
        provider="ansible",
        enabled=True,
        provider_config={},
    ))
    ledger = container.capacity_ledger_service()
    for resource_id in ("resource-a", "resource-b"):
        ledger.register_resource(
            resource_id=resource_id,
            resource_type="compute.gpu",
            total_units=4,
            pool_id="pool-a",
        )
    reserved = ledger.reserve(
        claim={"gpu_count": 1},
        deal_ref={"market": "vms"},
    )
    assert reserved is not None
    repository = container.settlement_repository()
    with session_factory() as db:
        repository.save_cursor_in_session(
            db,
            "compute.gpu",
            last_pool_id="pool-a",
            last_resource_by_pool={"pool-a": "resource-a"},
        )
        db.commit()
    return ledger, reserved["capacity_reservation_id"]


def _request(capacity_reservation_id: str) -> PhysicalSettlementRequest:
    return PhysicalSettlementRequest(
        capacity_reservation_id=capacity_reservation_id,
        market="vms",
        requirements={"resource_kind": "compute.gpu"},
    )


def test_composed_scheduler_commits_rebind_cursor_and_assignment(tmp_path) -> None:
    container, session_factory, pools = _container(tmp_path)
    ledger, reservation_id = _prepare(container, session_factory, pools)

    selected = container.physical_settlement_scheduler().schedule_resource(
        _request(reservation_id),
    )

    assert selected.settlement_resource_id == "resource-b"
    with session_factory() as db:
        assert ledger.backing_resource_id_in_session(db, reservation_id) == "resource-b"
        assert container.settlement_repository().get(db, reservation_id) is not None
        cursor = container.settlement_repository().get_cursor_in_session(
            db,
            "compute.gpu",
        )
        assert cursor.last_resource_by_pool["pool-a"] == "resource-b"


class _ExplodingRepository(SettlementRepository):
    def schedule(self, *args, **kwargs):
        raise RuntimeError("controlled settlement persistence failure")


def test_composed_scheduler_rolls_back_site_and_fulfillment_mutations(tmp_path) -> None:
    repository = _ExplodingRepository()
    container, session_factory, pools = _container(
        tmp_path,
        repository=repository,
    )
    ledger, reservation_id = _prepare(container, session_factory, pools)

    with pytest.raises(RuntimeError, match="controlled"):
        container.physical_settlement_scheduler().schedule_resource(
            _request(reservation_id),
        )

    with session_factory() as db:
        assert ledger.backing_resource_id_in_session(db, reservation_id) == "resource-a"
        reservation = ledger.lock_reservation(db, reservation_id)
        assert reservation is not None
        assert reservation.settlement_resource_id is None
        assert repository.get(db, reservation_id) is None
        cursor = repository.get_cursor_in_session(db, "compute.gpu")
        assert cursor.last_resource_by_pool["pool-a"] == "resource-a"
