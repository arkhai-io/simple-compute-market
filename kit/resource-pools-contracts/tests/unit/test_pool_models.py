"""Pool write models refuse malformed declarations and domain-neutral hints.

The models are the first place a typed client meets the rule, so a write
lacking or misdeclaring either tag cannot even be constructed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_resource_pools_contracts import PoolCreate, PoolReplace, PoolUpdate

_VALID = {
    "deliverable_modes": ["vm"],
    "advertisable_modes": ["vm"],
    "capacity_backing": "backed",
}

_INVALID = [
    pytest.param({"deliverable_modes": ["vm"]}, "advertisable_modes", id="both-absent"),
    pytest.param(
        {k: v for k, v in _VALID.items() if k != "capacity_backing"},
        "capacity_backing",
        id="backing-absent",
    ),
    pytest.param({**_VALID, "capacity_backing": "yes"}, "capacity_backing", id="bad-backing"),
    pytest.param(
        {**_VALID, "deliverable_modes": []}, "advertisable_modes", id="backed-narrowed",
    ),
    pytest.param(
        {**_VALID, "advertisable_modes": ["vm", "bare_metal"]},
        "advertisable_modes",
        id="backed-widened",
    ),
    pytest.param(
        {**_VALID, "capacity_backing": "unbacked"},
        "deliverable_modes",
        id="unbacked-delivers",
    ),
    pytest.param(
        {**_VALID, "deliverable_modes": "vm"},
        "deliverable_modes",
        id="malformed-delivery",
    ),
]


def _create(tags):
    return PoolCreate(id="p", label="P", provider="x", policy_tags=tags)


def _replace(tags):
    return PoolReplace(label="P", provider="x", enabled=True, policy_tags=tags)


def _update(tags):
    return PoolUpdate(policy_tags=tags)


@pytest.mark.parametrize("build", [_create, _replace, _update])
def test_valid_declarations_construct(build):
    assert build(dict(_VALID)).policy_tags == _VALID


@pytest.mark.parametrize("build", [_create, _replace, _update])
@pytest.mark.parametrize(("tags", "named"), _INVALID)
def test_invalid_declarations_refuse_construction(build, tags, named):
    with pytest.raises(ValidationError, match=named):
        build(tags)


def test_create_and_replace_require_policy_tags_in_their_schema():
    # Required in the model, not defaulted and then refused, so the generated
    # schema tells a client the field cannot be omitted.
    assert "policy_tags" in PoolCreate.model_json_schema()["required"]
    assert "policy_tags" in PoolReplace.model_json_schema()["required"]
    with pytest.raises(ValidationError, match="policy_tags"):
        PoolCreate(id="p", label="P", provider="x")
    with pytest.raises(ValidationError, match="policy_tags"):
        PoolReplace(label="P", provider="x", enabled=True)


def test_patch_keeps_policy_tags_optional():
    assert "policy_tags" not in PoolUpdate.model_json_schema().get("required", [])


def test_patch_leaving_policy_tags_alone_needs_no_declarations():
    assert PoolUpdate(label="renamed").policy_tags is None


# Hints remain structural: the models know no provider registry or domain schema.
_HINT_INVALID = [
    *[pytest.param({"max_reservation_hold_seconds": value}, "max_reservation_hold_seconds", id=f"hold-{value!r}")
      for value in (-1, 1.5, "60", False, None)],
    *[pytest.param({"sla": value}, "sla", id=f"sla-{value!r}")
      for value in (-1, "99.9", False, None)],
    *[pytest.param({"listing_shapes": value}, "listing_shapes", id=f"shapes-{index}")
      for index, value in enumerate((
          None, [], {"": []}, {"vm": []}, {"vm": "shape"},
          {"vm": [{}]}, {"vm": [{"gpu": 1}]},
          {"vm": [{"gpu": {"count": {"offer": 1, "min": 4, "max": 2}}}]},
          {"vm": [{"gpu": {"count": {"offer": 1, "step": 2}}}]},
          {"vm": [
              {"gpu": {"count": {"offer": 1, "max": 4}}},
              {"gpu": {"count": {"offer": 1, "max": 8}}},
          ]},
      ))],
    *[pytest.param({"asking_rates": value}, "asking_rates", id=f"asking-{index}")
      for index, value in enumerate((None, [], {"vm": None}, {"vm": [{}]}))],
    *[pytest.param({"asking_rates": {"vm": [{
          "shape": {"future_family": {"quantity": 1}},
          "amount": "2", "asset": "usd", "period": "hour", **invalid,
      }]}}, "asking_rates", id=f"asking-entry-{index}")
      for index, invalid in enumerate((
          {"shape": {}}, {"shape": {"gpu": 1}}, {"amount": 2},
          {"amount": "0"}, {"amount": "1e3"}, {"asset": " usd"},
          {"period": "Hour"}, {"extra": True},
      ))],
    *[pytest.param({"pricing": {"future_family": {"rates": value}}}, "pricing", id=f"pricing-{index}")
      for index, value in enumerate((
          None, "rate", [{}], [None],
          [{"asset": "usd", "rate": 2, "per": "hour"}],
          [{"asset": "usd", "rate": "0", "per": "hour"}],
          [{"asset": " usd", "rate": "2", "per": "hour"}],
          [{"asset": "usd", "rate": "2", "per": "Hour"}],
          [{"asset": "usd", "rate": "2", "per": "hour"}] * 2,
      ))],
]

_HINT_VALID = [
    pytest.param({"max_reservation_hold_seconds": 0}, id="zero-hold"),
    pytest.param({"max_reservation_hold_seconds": 120}, id="integer-hold"),
    pytest.param({"sla": 0}, id="zero-sla"),
    pytest.param({"sla": 99.9}, id="fractional-sla"),
    pytest.param({"sla": 1234}, id="domain-owned-sla-ceiling"),
    pytest.param({"listing_shapes": {"future_mode": [
        {"future_family": {"unknown_field": {"offer": 1, "max": 4}}},
    ]}}, id="domain-owned-shape-vocabulary"),
    pytest.param({"listing_shapes": {"vm": [{"gpu": {"count": 1}}] * 2}}, id="identical-shapes"),
    pytest.param({"asking_rates": {"future_mode": []}}, id="withheld-asking-rates"),
    pytest.param({"asking_rates": {"future_mode": [{
        "shape": {"future_family": {"unknown_field": 1}},
        "amount": "2.10", "asset": "future-asset", "period": "month",
    }]}}, id="domain-owned-asking-vocabulary"),
    pytest.param({"pricing": {"future_family": {"rates": [
        {"asset": "future-asset", "rate": "0.05", "per": "month"},
    ]}}}, id="domain-owned-pricing-vocabulary"),
    pytest.param({"pricing": {"future_family": {"future_key": {"rates": []}}}}, id="empty-nested-rates"),
    pytest.param({"pricing": "domain-owned-value"}, id="pricing-outside-rate-lists"),
    pytest.param({"opaque_future_hint": {"nested": [None, False, "value"]}}, id="opaque-unknown-tag"),
]


@pytest.mark.parametrize("build", [_create, _replace, _update])
@pytest.mark.parametrize(("hint", "named"), _HINT_INVALID)
def test_malformed_hints_refuse_typed_construction(build, hint, named):
    with pytest.raises(ValidationError, match=named):
        build({**_VALID, **hint})


@pytest.mark.parametrize("build", [_create, _replace, _update])
@pytest.mark.parametrize("hint", _HINT_VALID)
def test_structural_hints_and_opaque_domain_values_construct_verbatim(build, hint):
    tags = {**_VALID, **hint}
    assert build(tags).policy_tags == tags


def test_all_hint_problems_are_reported_together():
    with pytest.raises(ValidationError) as refused:
        _create({**_VALID, "max_reservation_hold_seconds": -1, "sla": -1,
                 "listing_shapes": None, "asking_rates": None,
                 "pricing": {"memory": {"rates": "invalid"}}})
    for tag in ("max_reservation_hold_seconds", "sla", "listing_shapes", "asking_rates", "pricing"):
        assert tag in str(refused.value)
