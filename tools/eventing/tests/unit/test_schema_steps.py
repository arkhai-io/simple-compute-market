"""The schema steps' identities in a service's migration ledger."""

from __future__ import annotations

from eventing import SCHEMA_STEPS


def test_each_step_is_named_by_its_version() -> None:
    assert [step.name for step in SCHEMA_STEPS] == ["eventing_0001"]
