"""Capacity-definitions documents: validation and planned reconciliation."""

from __future__ import annotations

import textwrap

import pytest
from market_resource_pools.db import Base as ResourcePoolBase
from market_resource_pools.db import DEFAULT_POOL_ID, ResourcePool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_site import (
    CapacityDeclaration,
    CapacityDefinitionsOutcome,
    parse_capacity_definitions,
    reconcile_capacity_definitions_in_session,
)
from market_site.capacity_definitions import (
    _cross_entry_problems,
    _load_entries,
    _validate_entry,
)
from market_site.db import Base
from market_site.ledger import CapacityLedgerService


def _ledger() -> CapacityLedgerService:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    ResourcePoolBase.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db, db.begin():
        for pool_id in (DEFAULT_POOL_ID, "pool-b"):
            db.add(
                ResourcePool(
                    id=pool_id,
                    label=pool_id,
                    provider="test",
                    enabled=True,
                    policy_tags={"deliverable_modes": ["vm"]},
                )
            )
    return CapacityLedgerService(
        session_factory,
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
    )


def _reconcile(
    ledger: CapacityLedgerService, document: str, *, commit: bool = True
) -> CapacityDefinitionsOutcome:
    """Reconcile as an applying caller does: commit only a valid outcome."""
    with ledger.serialized(), ledger._session_factory() as db:
        outcome = reconcile_capacity_definitions_in_session(
            db, ledger, textwrap.dedent(document)
        )
        if outcome.valid and commit:
            db.commit()
        else:
            db.rollback()
    return outcome


def _codes(problems) -> set[tuple[str, str]]:
    return {(problem.path, problem.code) for problem in problems}


_ONE_HOST = """
    resources:
      - resource_id: compute-kvm1
        pool_id: default
        resource_type: compute.gpu
        resource_subtype: h200
        host_id: kvm1
        capacity: {gpu_count: 8, ram_gb: 2048}
        attributes: {gpu_model: H200, region: us-west}
"""


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------


def test_a_well_formed_document_parses_into_whole_declarations():
    definitions, problems = parse_capacity_definitions(textwrap.dedent(_ONE_HOST))

    assert problems == ()
    assert definitions == (
        CapacityDeclaration(
            resource_id="compute-kvm1",
            pool_id="default",
            resource_type="compute.gpu",
            resource_subtype="h200",
            host_id="kvm1",
            capacity={"gpu_count": 8, "ram_gb": 2048},
            attributes={"gpu_model": "H200", "region": "us-west"},
        ),
    )


def test_every_problem_in_a_document_is_reported_together():
    _, problems = parse_capacity_definitions(
        textwrap.dedent(
            """
            version: 2
            resources:
              - resource_id: a
                pool_id: default
                capacity: {gpu_count: 1}
                total_units: 1
                host_id: kvm1
              - resource_id: b
                pool_id: default
                resource_type: compute.gpu
                capacity: {gpu_count: -1, ram_gb: yes}
                attributes: {host_id: kvm9, gpu_model: H200}
                enabled: "true"
                host_id: kvm1
              - resource_id: a
                pool_id: default
                resource_type: compute.gpu
                capacity: {}
              - not-a-mapping
            """
        )
    )

    assert _codes(problems) == {
        ("version", "unknown_field"),
        ("resources[0].resource_type", "required_field"),
        ("resources[0].total_units", "unknown_field"),
        ("resources[1].capacity.gpu_count", "invalid_amount"),
        ("resources[1].capacity.ram_gb", "invalid_amount"),
        ("resources[1].attributes", "reserved_attribute"),
        ("resources[1].enabled", "invalid_type"),
        ("resources[1].host_id", "duplicate_host_id"),
        ("resources[2].resource_id", "duplicate_resource_id"),
        ("resources[2].capacity", "required_field"),
        ("resources[3]", "invalid_type"),
    }


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ("resources: [", ("$", "invalid_yaml")),
        ("- just a list", ("$", "invalid_type")),
        ("resources: {}", ("resources", "invalid_type")),
    ],
)
def test_a_document_without_a_resources_list_is_refused(document, expected):
    definitions, problems = parse_capacity_definitions(document)

    assert definitions == ()
    assert expected in _codes(problems)


def test_an_empty_resources_list_is_valid_and_declares_nothing():
    assert parse_capacity_definitions("resources: []") == ((), ())


def test_loading_reports_root_problems_and_returns_the_entries():
    entries, problems = _load_entries("resources: [{a: 1}]\nextra: true\n")

    assert entries == [{"a": 1}]
    assert _codes(problems) == {("extra", "unknown_field")}
    assert _load_entries("resources: 3")[0] is None


def test_an_entry_is_validated_strictly():
    """A quoted number or boolean is the wrong type, not a value to coerce."""
    declaration, problems = _validate_entry(4, {
        "resource_id": "r",
        "pool_id": "default",
        "resource_type": "compute.gpu",
        "capacity": {"gpu_count": "8"},
        "enabled": "true",
    })

    assert declaration is None
    assert _codes(problems) == {
        ("resources[4].capacity.gpu_count", "invalid_amount"),
        ("resources[4].enabled", "invalid_type"),
    }


def test_a_valid_entry_is_a_declaration_with_no_problems():
    declaration, problems = _validate_entry(0, {
        "resource_id": "r",
        "pool_id": "default",
        "resource_type": "compute.gpu",
        "capacity": {"gpu_count": 8.0},
    })

    assert problems == []
    assert declaration == CapacityDeclaration(
        resource_id="r", pool_id="default", resource_type="compute.gpu",
        capacity={"gpu_count": 8},
    )


def test_duplicates_are_found_even_beside_other_problems():
    problems = _cross_entry_problems([
        {"resource_id": "a", "host_id": "h"},
        "not-a-mapping",
        {"resource_id": "a", "host_id": "h", "capacity": {}},
        {"resource_id": "", "host_id": None},
    ])

    assert _codes(problems) == {
        ("resources[2].resource_id", "duplicate_resource_id"),
        ("resources[2].host_id", "duplicate_host_id"),
    }


# ----------------------------------------------------------------------
# Reconciliation
# ----------------------------------------------------------------------


def test_a_first_import_creates_and_a_reimport_writes_nothing():
    ledger = _ledger()

    first = _reconcile(ledger, _ONE_HOST)
    _, version_after_first = ledger.events_after(0)
    second = _reconcile(ledger, _ONE_HOST + "\n# reformatted\n")
    _, version_after_second = ledger.events_after(0)

    assert first.valid and first.diff.created == ["compute-kvm1"]
    assert second.valid
    assert second.diff.unchanged == ["compute-kvm1"]
    assert second.diff.created == second.diff.updated == []
    assert version_after_second == version_after_first


def test_an_entry_omitting_optional_fields_clears_them():
    ledger = _ledger()
    _reconcile(ledger, _ONE_HOST)

    outcome = _reconcile(
        ledger,
        """
        resources:
          - resource_id: compute-kvm1
            pool_id: default
            resource_type: compute.gpu
            capacity: {gpu_count: 8, ram_gb: 2048}
        """,
    )

    assert outcome.diff.updated == ["compute-kvm1"]
    (resource,) = ledger.list_resources()
    assert resource["host_id"] is None
    assert resource["resource_subtype"] is None
    assert resource["attributes"] == {}


def test_declarations_the_document_does_not_name_are_retained():
    ledger = _ledger()
    ledger.register_resource(
        resource_id="api-registered", pool_id="default", total_units=2, enabled=False
    )

    _reconcile(ledger, _ONE_HOST)

    by_id = {row["resource_id"]: row for row in ledger.list_resources()}
    assert set(by_id) == {"api-registered", "compute-kvm1"}
    assert by_id["api-registered"]["enabled"] is False


def test_an_unknown_pool_is_reported_and_nothing_is_applied():
    ledger = _ledger()

    outcome = _reconcile(
        ledger,
        _ONE_HOST
        + """
      - resource_id: compute-kvm2
        pool_id: no-such-pool
        resource_type: compute.gpu
        capacity: {gpu_count: 1}
""",
    )

    assert _codes(outcome.problems) == {("resources[1].pool_id", "unknown_pool")}
    assert ledger.list_resources() == []


def test_stored_state_refusals_leave_earlier_entries_unapplied():
    """A host another declaration already names, and a pool move under a
    live obligation, are registration's refusals; both are reported, and
    the entry before them is not applied."""
    ledger = _ledger()
    ledger.register_resource(
        resource_id="holder", pool_id="default", total_units=1, host_id="kvm2"
    )
    ledger.register_resource(resource_id="held", pool_id="default", total_units=4)
    reserved = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1, "resource_id": "held"},
        deal_ref={},
    )
    assert reserved is not None

    outcome = _reconcile(
        ledger,
        _ONE_HOST
        + """
      - resource_id: newcomer
        pool_id: default
        resource_type: compute.gpu
        host_id: kvm2
        capacity: {gpu_count: 1}
      - resource_id: held
        pool_id: pool-b
        resource_type: compute.gpu
        capacity: {gpu_count: 4}
""",
    )

    assert _codes(outcome.problems) == {
        ("resources[1]", "conflict"),
        ("resources[2]", "conflict"),
    }
    assert outcome.diff.created == ["compute-kvm1"]
    assert {row["resource_id"] for row in ledger.list_resources()} == {"holder", "held"}


def test_a_dry_run_reports_the_plan_and_writes_nothing():
    ledger = _ledger()

    outcome = _reconcile(ledger, _ONE_HOST, commit=False)

    assert outcome.valid
    assert outcome.diff.created == ["compute-kvm1"]
    assert ledger.list_resources() == []
    assert ledger.events_after(0)[0] == []


def test_a_structurally_invalid_document_touches_no_stored_state():
    ledger = _ledger()

    outcome = _reconcile(ledger, "resources:\n  - resource_id: x\n")

    assert not outcome.valid
    assert outcome.diff.created == []
    assert ledger.list_resources() == []
