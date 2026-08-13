from __future__ import annotations

from dataclasses import fields

import pytest

from tests.e2e.roles.scenarios.vms.hosted.driver import STAGE_CONTRACTS
from tests.e2e.roles.scenarios.vms.hosted.state import (
    DealState,
    HostedStagePrerequisiteError,
    require_state,
    state_fields,
)


def test_every_hosted_state_field_has_exactly_one_producer_and_a_consumer() -> None:
    declared = set(state_fields())
    producers: dict[str, list[str]] = {name: [] for name in declared}
    consumers: dict[str, list[str]] = {name: [] for name in declared}
    for stage in STAGE_CONTRACTS:
        for name in stage.produces:
            assert name in declared, f"{stage.name} produces unknown field {name}"
            producers[name].append(stage.name)
        for name in stage.requires:
            assert name in declared, f"{stage.name} consumes unknown field {name}"
            consumers[name].append(stage.name)
    assert {name: value for name, value in producers.items() if len(value) != 1} == {}
    assert {name: value for name, value in consumers.items() if not value} == {}


def test_stage_contract_is_forward_only_and_has_no_implicit_dependency() -> None:
    available: set[str] = set()
    for stage in STAGE_CONTRACTS:
        missing = set(stage.requires).difference(available)
        assert not missing, f"{stage.name} requires unproduced fields: {sorted(missing)}"
        available.update(stage.produces)
    assert available == {item.name for item in fields(DealState)}


@pytest.mark.parametrize("name", state_fields())
def test_require_state_fails_selected_stage_instead_of_skipping(name: str) -> None:
    state = DealState()
    with pytest.raises(HostedStagePrerequisiteError, match=rf"DealState\.{name}="):
        require_state(state, name)


def test_require_state_rejects_misspelled_field() -> None:
    with pytest.raises(AttributeError, match="unknown hosted DealState"):
        require_state(DealState(), "authority_readdy")
