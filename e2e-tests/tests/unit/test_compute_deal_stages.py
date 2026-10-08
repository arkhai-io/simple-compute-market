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

TESTS = Path(__file__).resolve().parents[1]
ROLES = TESTS / "e2e" / "roles"
SHARED = ROLES / "helpers" / "compute_deal_stages.py"
DOMAIN_DEAL = ROLES / "helpers" / "domain_deal.py"


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
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _classes(tree: ast.Module) -> list[ast.ClassDef]:
    return [node for node in tree.body if isinstance(node, ast.ClassDef)]


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    (found,) = [node for node in _classes(tree) if node.name == name]
    return found


def _fields(node: ast.ClassDef) -> set[str]:
    return {
        item.target.id
        for item in node.body
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
    }


def _base_names(node: ast.ClassDef) -> list[str]:
    return [base.id for base in node.bases if isinstance(base, ast.Name)]


def _is_stage(node: ast.ClassDef) -> bool:
    return any(
        isinstance(item, ast.FunctionDef) and item.name.startswith("test_")
        for item in node.body
    )


@dataclass
class _Use:
    written: set[str]
    read: set[str]
    required: set[str]


def _use(classes: list[ast.ClassDef]) -> _Use:
    """Which `deal_state` fields the stage classes write, read, and require."""
    use = _Use(set(), set(), set())
    for node in classes:
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == "deal_state"
            ):
                (use.written if isinstance(sub.ctx, ast.Store) else use.read).add(sub.attr)
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "require_state"
                and sub.args
                and isinstance(sub.args[0], ast.Name)
                and sub.args[0].id == "deal_state"
            ):
                for arg in sub.args[1:]:
                    assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                        f"require_state names a field with a non-literal at line {arg.lineno}"
                    )
                    use.required.add(arg.value)
    return use


SHARED_TREE = _tree(SHARED)
SHARED_STAGES = [node for node in _classes(SHARED_TREE) if _is_stage(node)]
SHARED_NAMES = [node.name for node in SHARED_STAGES]
COMPUTE_FIELDS = _fields(_class(SHARED_TREE, "ComputeDealState"))
DOMAIN_DEAL_FIELDS = _fields(_class(_tree(DOMAIN_DEAL), "DomainDealState"))
SHARED_USE = _use(SHARED_STAGES)


def _domain_stages(domain: Domain) -> list[ast.ClassDef]:
    return [
        node for node in _classes(_tree(domain.scenario)) if node.name.startswith("Test")
    ]


def _domain_own_stages(domain: Domain) -> list[ast.ClassDef]:
    return [
        node for node in _domain_stages(domain)
        if not set(_base_names(node)) & set(SHARED_NAMES)
    ]


def test_the_shared_stages_are_not_collected_where_they_are_defined():
    assert SHARED_STAGES, "the shared module defines no stage"
    collected = [node.name for node in _classes(SHARED_TREE) if node.name.startswith("Test")]
    assert collected == [], collected


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_a_domain_declares_every_shared_stage_once_in_order(domain: Domain):
    declared: list[str] = []
    for node in _domain_stages(domain):
        shared = [name for name in _base_names(node) if name in SHARED_NAMES]
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
    node = _class(_tree(domain.state_module), domain.state_class)
    assert "ComputeDealState" in _base_names(node), _base_names(node)


def test_every_compute_state_field_is_read():
    """A field nothing reads records nothing a later stage needs."""
    domain_reads = [
        (lambda use: use.read | use.required)(_use(_domain_own_stages(domain)))
        for domain in DOMAINS
    ]
    read_everywhere = set.intersection(*domain_reads) if domain_reads else set()
    unread = COMPUTE_FIELDS - SHARED_USE.read - SHARED_USE.required - read_everywhere
    assert unread == set(), unread


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_every_shared_prerequisite_has_a_producer(domain: Domain):
    """A required field no stage writes skips every stage that requires it."""
    produced = SHARED_USE.written | _use(_domain_own_stages(domain)).written
    missing = SHARED_USE.required - produced
    assert missing == set(), (
        f"the shared stages require {sorted(missing)}, which neither they nor "
        f"{domain.name}'s own stages produce"
    )


def test_the_shared_stages_use_only_declared_fields():
    declared = COMPUTE_FIELDS | DOMAIN_DEAL_FIELDS
    used = SHARED_USE.written | SHARED_USE.required
    assert used - declared == set(), used - declared


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.name)
def test_a_domain_stage_uses_only_its_states_fields(domain: Domain):
    declared = (
        _fields(_class(_tree(domain.state_module), domain.state_class))
        | COMPUTE_FIELDS
        | DOMAIN_DEAL_FIELDS
    )
    use = _use(_domain_own_stages(domain))
    used = use.written | use.required
    assert used - declared == set(), used - declared
