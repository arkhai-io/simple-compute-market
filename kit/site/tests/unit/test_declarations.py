"""The capacity declaration model: its fields' rules, in one place."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from market_site import CapacityDeclaration


def _declaration(**overrides) -> CapacityDeclaration:
    fields = {
        "resource_id": "r1",
        "pool_id": "default",
        "resource_type": "compute.gpu",
        "capacity": {"gpu_count": 8},
    }
    fields.update(overrides)
    return CapacityDeclaration(**fields)


def test_capacity_is_stored_as_exact_decimals_and_compares_by_value():
    declaration = _declaration(capacity={"gpu_count": 8, "ram_gb": 0.5})

    assert declaration.capacity == {"gpu_count": Decimal("8"), "ram_gb": Decimal("0.5")}
    assert _declaration(capacity={"gpu_count": 8.0}) == _declaration()


@pytest.mark.parametrize("amount", [-1, True, "8", float("inf"), float("nan"), None])
def test_a_dimension_must_be_a_finite_non_negative_number(amount):
    with pytest.raises(ValidationError, match="non-negative number"):
        _declaration(capacity={"gpu_count": amount})


def test_a_declaration_names_at_least_one_dimension():
    with pytest.raises(ValidationError):
        _declaration(capacity={})


@pytest.mark.parametrize("key", sorted(CapacityDeclaration.IDENTITY_FIELDS))
def test_an_attribute_may_not_restate_an_identity_field(key):
    with pytest.raises(ValidationError, match=key):
        _declaration(attributes={key: "x", "gpu_model": "H200"})


def test_the_identity_fields_are_declaration_fields():
    """The reserved attribute names are exactly fields the model declares."""
    assert CapacityDeclaration.IDENTITY_FIELDS <= set(CapacityDeclaration.model_fields)


def test_unknown_fields_are_refused():
    with pytest.raises(ValidationError, match="total_units"):
        _declaration(total_units=8)


def test_a_declaration_is_immutable():
    with pytest.raises(ValidationError):
        _declaration().pool_id = "elsewhere"
