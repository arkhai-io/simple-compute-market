from __future__ import annotations

import pytest

from compute_provisioning import (
    JobExecution,
    JobExecutorTable,
    UnsupportedExecutorActionError,
)


def test_resolves_by_offering_mode_and_action() -> None:
    vm_runner, bm_runner = object(), object()
    table = JobExecutorTable()
    table.register("vm", "create", JobExecution(vm_runner, "vm.yaml"))
    table.register("bare_metal", "create", JobExecution(bm_runner, "bm.yaml"))
    table.freeze()

    assert table.resolve("vm", "create").runner is vm_runner
    assert table.resolve("bare_metal", "create").playbook_path == "bm.yaml"


def test_refuses_a_duplicate_key() -> None:
    table = JobExecutorTable()
    table.register("vm", "create", JobExecution(object()))

    with pytest.raises(ValueError, match="duplicate job executor"):
        table.register("vm", "create", JobExecution(object()))


def test_refuses_an_unknown_key() -> None:
    table = JobExecutorTable()
    table.register("vm", "create", JobExecution(object()))
    table.freeze()

    with pytest.raises(UnsupportedExecutorActionError):
        table.resolve("vm", "destroy")
    with pytest.raises(UnsupportedExecutorActionError):
        table.resolve("bare_metal", "create")


def test_nothing_resolves_before_composition_freezes_it() -> None:
    table = JobExecutorTable()
    table.register("vm", "create", JobExecution(object()))

    with pytest.raises(RuntimeError, match="not been composed"):
        table.resolve("vm", "create")


def test_a_frozen_table_takes_no_registration() -> None:
    table = JobExecutorTable()
    table.freeze()

    with pytest.raises(RuntimeError, match="frozen"):
        table.register("vm", "create", JobExecution(object()))


def test_runners_lists_each_runner_once() -> None:
    shared, other = object(), object()
    table = JobExecutorTable()
    table.register("vm", "create", JobExecution(shared))
    table.register("vm", "destroy", JobExecution(shared))
    table.register("bare_metal", "grant", JobExecution(other))

    assert table.runners() == (shared, other)
