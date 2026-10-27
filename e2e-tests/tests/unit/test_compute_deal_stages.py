"""The canonical compute deal's stage set is declared, ordered, and wired.

Read from source rather than collected, so a scenario module is checked without
its lane's settings or services. Each compute domain's scenario is one row of
``DOMAINS``; a domain that runs the shared stages adds its row.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.unit.stage_sources import (
    StateUse,
    base_names,
    class_named,
    classes,
    domain_stages,
    fields,
    is_stage,
    run_order,
    state_use,
    tree,
)

TESTS = Path(__file__).resolve().parents[1]
ROLES = TESTS / "e2e" / "roles"
SHARED = ROLES / "helpers" / "compute_deal_stages.py"
DOMAIN_DEAL = ROLES / "helpers" / "domain_deal.py"
STATE = "deal_state"


@dataclass(frozen=True)
class Domain:
    name: str
    scenario: Path
    #: The module and class of the state the domain's stages write.
    state_module: Path
    state_class: str


DOMAINS = (
    Domain(
        "vms",
        ROLES / "scenarios" / "vms" / "test_full_deal.py",
        ROLES / "scenarios" / "vms" / "conftest.py",
        "DealState",
    ),
    Domain(
        "bare_metal",
        ROLES / "scenarios" / "bare_metal" / "test_bare_metal_mock_deal.py",
        ROLES / "scenarios" / "bare_metal" / "conftest.py",
        "BareMetalDealState",
    ),
)


SHARED_TREE = tree(SHARED)
SHARED_STAGES = [node for node in classes(SHARED_TREE) if is_stage(node)]
SHARED_NAMES = [node.name for node in SHARED_STAGES]
COMPUTE_FIELDS = fields(class_named(SHARED_TREE, "ComputeDealState"))
DOMAIN_DEAL_FIELDS = fields(class_named(tree(DOMAIN_DEAL), "DomainDealState"))
SHARED_USE = state_use(SHARED_STAGES, state=STATE)


def _domain_own_stages(domain: Domain) -> list[ast.ClassDef]:
    return [
        node for node in domain_stages(domain.scenario)
        if not set(base_names(node)) & set(SHARED_NAMES)
    ]


def _scenario(domain: Domain) -> list[tuple[str, StateUse]]:
    return run_order(domain.scenario, SHARED_STAGES, state=STATE)


def test_the_shared_stages_are_not_collected_where_they_are_defined():
    assert SHARED_STAGES, "the shared module defines no stage"
    collected = [node.name for node in classes(SHARED_TREE) if node.name.startswith("Test")]
    assert collected == [], collected


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_a_domain_declares_every_shared_stage_once_in_order(domain: Domain):
    declared: list[str] = []
    for node in domain_stages(domain.scenario):
        shared = [name for name in base_names(node) if name in SHARED_NAMES]
        if not shared:
            continue
        (base,) = shared
        assert node.name == "Test" + base, (
            f"{domain.name} declares {base} as {node.name}; the stage's ID and "
            "test names come from its name"
        )
        assert len(node.body) == 1 and isinstance(node.body[0], ast.Pass), (
            f"{domain.name}'s {node.name} has a body of its own; a shared stage's "
            "body is defined once, and a domain's part goes through its driver"
        )
        declared.append(base)
    assert declared == SHARED_NAMES, (
        f"{domain.name} declares the shared stages {declared}; expected each once, "
        f"in the shared order {SHARED_NAMES}"
    )


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_a_domain_state_extends_the_compute_state(domain: Domain):
    node = class_named(tree(domain.state_module), domain.state_class)
    assert "ComputeDealState" in base_names(node), base_names(node)


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_every_prerequisite_is_produced_by_an_earlier_stage(domain: Domain):
    """A stage requiring a field no earlier stage writes skips forever."""
    produced: set[str] = set()
    for name, use in _scenario(domain):
        missing = use.required - produced
        assert missing == set(), (
            f"{domain.name}'s {name} requires {sorted(missing)}, which no "
            "earlier stage produces"
        )
        produced |= use.written


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_every_field_read_is_produced_first(domain: Domain):
    produced: set[str] = set()
    for name, use in _scenario(domain):
        missing = use.read - produced - use.written - DOMAIN_DEAL_FIELDS
        assert missing == set(), (
            f"{domain.name}'s {name} reads {sorted(missing)} before any stage "
            "writes it"
        )
        produced |= use.written


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_each_compute_state_field_has_one_producer(domain: Domain):
    """A handoff written by two stages lets a consumer read the first
    producer's value when the second fails, instead of skipping."""
    producers: dict[str, list[str]] = {}
    for name, use in _scenario(domain):
        for field_name in use.written & COMPUTE_FIELDS:
            producers.setdefault(field_name, []).append(name)
    repeated = {name: stages for name, stages in producers.items() if len(stages) > 1}
    assert repeated == {}, repeated


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_every_compute_state_field_is_consumed_after_it_is_produced(domain: Domain):
    """A field no later stage reads records nothing a later stage needs."""
    produced: set[str] = set()
    consumed: set[str] = set()
    for _name, use in _scenario(domain):
        consumed |= (use.read | use.required) & produced
        produced |= use.written
    unconsumed = COMPUTE_FIELDS - consumed
    assert unconsumed == set(), (
        f"{domain.name}: no stage after its producer reads {sorted(unconsumed)}"
    )


def test_the_shared_stages_use_only_declared_fields():
    declared = COMPUTE_FIELDS | DOMAIN_DEAL_FIELDS
    used = SHARED_USE.written | SHARED_USE.required
    assert used - declared == set(), used - declared


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_a_domain_stage_uses_only_its_states_fields(domain: Domain):
    declared = (
        fields(class_named(tree(domain.state_module), domain.state_class))
        | COMPUTE_FIELDS
        | DOMAIN_DEAL_FIELDS
    )
    use = state_use(_domain_own_stages(domain), state=STATE)
    used = use.written | use.required
    assert used - declared == set(), used - declared
