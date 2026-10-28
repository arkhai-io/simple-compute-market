"""The introduction scenario's stage set is declared, ordered, and wired.

Read from source rather than collected, so a scenario module is checked without
its lane's settings or services. Each compute domain's introduction scenario is
one row of ``DOMAINS``; a domain that runs the shared stages adds its row.

Only stages write the scenario's state: a driver returns what it did and the
stage records it, so who produces each field is read here. A stage's tests run
in order and hand state to each other, so the handoffs are read test by test.
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
    running_stages,
    state_use,
    tree,
)

TESTS = Path(__file__).resolve().parents[1]
ROLES = TESTS / "e2e" / "roles"
SHARED = ROLES / "helpers" / "introduction_stages.py"
STATE = "introduction_state"


@dataclass(frozen=True)
class Domain:
    name: str
    scenario: Path


DOMAINS = (
    Domain("vms", ROLES / "scenarios" / "vms" / "test_vm_introduction.py"),
    Domain(
        "bare_metal",
        ROLES / "scenarios" / "bare_metal" / "test_bare_metal_unbacked_introduction.py",
    ),
)

SHARED_TREE = tree(SHARED)
SHARED_STAGES = [node for node in classes(SHARED_TREE) if is_stage(node)]
SHARED_NAMES = [node.name for node in SHARED_STAGES]
SHARED_FIELDS = fields(class_named(SHARED_TREE, "IntroductionState"))
#: Set by each module's fixture when it builds the state, before any stage.
FIXTURE_FIELDS = {"run"}


def _steps(domain: Domain) -> list[tuple[str, StateUse]]:
    """Each test the domain's scenario runs, in order, with its use of the state."""
    return [
        (f"{name}.{item.name}", state_use([item], state=STATE))
        for name, body in running_stages(domain.scenario, SHARED_STAGES)
        for item in body.body
        if isinstance(item, ast.FunctionDef) and item.name.startswith("test_")
    ]


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
def test_every_field_a_test_uses_is_declared(domain: Domain):
    for name, use in _steps(domain):
        undeclared = (use.written | use.read | use.required) - SHARED_FIELDS
        assert undeclared == set(), f"{domain.name}'s {name} uses {sorted(undeclared)}"


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_every_field_is_produced_before_it_is_used(domain: Domain):
    """A test requiring a field no earlier test writes skips forever; one
    reading it reads the absent default."""
    produced = set(FIXTURE_FIELDS)
    for name, use in _steps(domain):
        missing = use.required - produced
        assert missing == set(), (
            f"{domain.name}'s {name} requires {sorted(missing)}, which no "
            "earlier test produces"
        )
        missing = use.read - produced - use.written
        assert missing == set(), (
            f"{domain.name}'s {name} reads {sorted(missing)} before any test writes it"
        )
        produced |= use.written


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_each_field_has_one_producer(domain: Domain):
    """A handoff written by two tests lets a consumer read the first
    producer's value when the second fails, instead of skipping."""
    producers: dict[str, list[str]] = {}
    for name, use in _steps(domain):
        for field_name in use.written:
            producers.setdefault(field_name, []).append(name)
    repeated = {name: tests for name, tests in producers.items() if len(tests) > 1}
    assert repeated == {}, repeated
    assert not FIXTURE_FIELDS & set(producers), producers
