from __future__ import annotations

import pytest

from compute_provisioning import JobExecutorTable, UnsupportedExecutorActionError
from compute_provisioning.executor_mock import MockRuleSet


class _Executor:
    def __init__(self, *, rules=None) -> None:
        if rules is not None:
            self.rules = rules

    async def execute(self, run):
        raise NotImplementedError

    async def cancel(self, handle):
        return None


def test_resolves_by_offering_mode_and_action() -> None:
    vm, bare_metal = _Executor(), _Executor()
    table = JobExecutorTable()
    table.register("vm", "create", vm)
    table.register("bare_metal", "create", bare_metal)
    table.freeze()

    assert table.resolve("vm", "create") is vm
    assert table.resolve("bare_metal", "create") is bare_metal


def test_refuses_a_duplicate_key() -> None:
    table = JobExecutorTable()
    table.register("vm", "create", _Executor())

    with pytest.raises(ValueError, match="duplicate job executor"):
        table.register("vm", "create", _Executor())


def test_refuses_an_unknown_key() -> None:
    table = JobExecutorTable()
    table.register("vm", "create", _Executor())
    table.freeze()

    with pytest.raises(UnsupportedExecutorActionError):
        table.resolve("vm", "destroy")
    with pytest.raises(UnsupportedExecutorActionError):
        table.resolve("bare_metal", "create")


def test_nothing_resolves_before_composition_freezes_it() -> None:
    table = JobExecutorTable()
    table.register("vm", "create", _Executor())

    with pytest.raises(RuntimeError, match="not been composed"):
        table.resolve("vm", "create")


def test_a_frozen_table_takes_no_registration() -> None:
    table = JobExecutorTable()
    table.freeze()

    with pytest.raises(RuntimeError, match="frozen"):
        table.register("vm", "create", _Executor())


def test_executors_lists_each_executor_once() -> None:
    shared, other = _Executor(), _Executor()
    table = JobExecutorTable()
    table.register("vm", "create", shared)
    table.register("vm", "destroy", shared)
    table.register("bare_metal", "grant", other)

    assert table.executors() == (shared, other)


def test_a_mode_is_mock_only_when_every_executor_carries_mock_rules() -> None:
    table = JobExecutorTable()
    table.register("vm", "create", _Executor(rules=MockRuleSet()))
    table.register("vm", "destroy", _Executor())
    table.register("bare_metal", "grant", _Executor(rules=MockRuleSet()))

    assert table.executor_modes() == {"vm": "real", "bare_metal": "mock"}
