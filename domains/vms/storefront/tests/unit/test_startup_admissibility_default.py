"""Parsing ``[admissibility.defaults.vm]``: no default, a declaration, or a refusal.

That a refusal stops the storefront before anything is constructed is proven at
the composition root, in ``test_admissibility_default_composition.py``.
"""

from __future__ import annotations

import pytest
from arkhai_vms import VM_CAPABILITY_SCHEMA
from market_capability_admissibility import Declaration, resolve

from market_storefront.services.publication_terms import (
    parse_configured_admissibility_default,
)
from tests._settings_overrides import settings_overrides


def test_no_table_is_no_default():
    assert parse_configured_admissibility_default() is None


def test_an_empty_table_is_no_default():
    with settings_overrides(**{"admissibility.defaults.vm": {}}):
        assert parse_configured_admissibility_default() is None


def test_a_readable_table_parses_under_the_configured_default_tier():
    with settings_overrides(
        **{
            "admissibility.defaults.vm": {
                "gpu": {"count": {"min": 1, "max": 4}},
                "memory": {"gib": {"max": 512}},
            }
        }
    ):
        declaration = parse_configured_admissibility_default()

    assert isinstance(declaration, Declaration)
    policy = resolve([declaration], VM_CAPABILITY_SCHEMA).policy
    assert policy is not None
    (problem,) = policy.admissibility_problems({"gpu": {"count": 8, "model": "H100"}})
    assert problem.paths == ("gpu.count",)
    assert problem.tier == "configured_default"


@pytest.mark.parametrize(
    ("table", "named"),
    [
        ({"gpu": {"count": {"min": 1, "step": 2}}}, "admissibility.defaults.vm.gpu.count"),
        ({"gpu": {"count": {"min": 8, "max": 4}}}, "admissibility.defaults.vm.gpu.count"),
        ({"gpu": {"count": {"offer": 2}}}, "admissibility.defaults.vm.gpu.count"),
        ({"gpu": {"count": 2}}, "admissibility.defaults.vm.gpu.count"),
        ({"gpu": {"model": {"max": 4}}}, "admissibility.defaults.vm.gpu.model"),
        ({"memory": {"foo": {"max": 4}}}, "admissibility.defaults.vm.memory.foo"),
    ],
)
def test_an_unreadable_table_is_refused_naming_the_problem(table, named):
    with settings_overrides(**{"admissibility.defaults.vm": table}):
        with pytest.raises(RuntimeError, match=named):
            parse_configured_admissibility_default()


def test_every_problem_is_named():
    with settings_overrides(
        **{
            "admissibility.defaults.vm": {
                "gpu": {"count": {"min": 8, "max": 4}},
                "memory": {"gib": {"mx": 4}},
            }
        }
    ):
        with pytest.raises(RuntimeError) as refused:
            parse_configured_admissibility_default()

    assert "gpu.count" in str(refused.value)
    assert "memory.gib" in str(refused.value)


@pytest.mark.parametrize(
    ("key", "value", "named"),
    [
        ("admissibility.defaults.vm", False, "admissibility.defaults.vm must be a table"),
        ("admissibility.defaults.vm", [], "admissibility.defaults.vm must be a table"),
        ("admissibility.defaults.vm", "", "admissibility.defaults.vm must be a table"),
        ("admissibility.defaults", [], "admissibility.defaults must be a table"),
        ("admissibility", "x", "admissibility must be a table"),
    ],
)
def test_a_value_that_is_not_a_table_is_refused(key, value, named):
    with settings_overrides(**{key: value}):
        with pytest.raises(RuntimeError, match=named):
            parse_configured_admissibility_default()
