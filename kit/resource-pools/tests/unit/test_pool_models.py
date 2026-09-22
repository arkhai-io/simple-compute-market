"""Pool write models refuse invalid advertisement and backing declarations.

The models are the first place a typed client meets the rule, so a write
lacking or misdeclaring either tag cannot even be constructed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_resource_pools import PoolCreate, PoolReplace, PoolUpdate

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
        {**_VALID, "advertisable_modes": ["vm", "bare_metal"]},
        "advertisable_modes",
        id="backed-widened",
    ),
    pytest.param(
        {**_VALID, "capacity_backing": "unbacked"},
        "deliverable_modes",
        id="unbacked-delivers",
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


def test_create_omitting_policy_tags_is_not_defaulted_into_validity():
    with pytest.raises(ValidationError, match="capacity_backing"):
        PoolCreate(id="p", label="P", provider="x")


def test_replace_omitting_policy_tags_is_not_defaulted_into_validity():
    with pytest.raises(ValidationError, match="capacity_backing"):
        PoolReplace(label="P", provider="x", enabled=True)


def test_patch_leaving_policy_tags_alone_needs_no_declarations():
    assert PoolUpdate(label="renamed").policy_tags is None
