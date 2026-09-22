import pytest

from market_resource_pools import pool_needs_host


def test_no_supplied_requirement_requires_no_host():
    assert pool_needs_host("ansible", None) is False
    assert pool_needs_host(None, None) is False


@pytest.mark.parametrize(("declared", "expected"), [(True, True), (False, False)])
def test_a_declared_provider_needs_what_it_declares(declared, expected):
    assert pool_needs_host("ansible", {"ansible": declared}) is expected


def test_a_provider_the_requirement_does_not_name_needs_a_host():
    assert pool_needs_host("unregistered", {"ansible": False}) is True


def test_a_pool_with_no_provider_needs_a_host_once_a_requirement_is_supplied():
    assert pool_needs_host(None, {"ansible": False}) is True
    assert pool_needs_host(None, {}) is True


def test_a_requirement_value_that_is_not_a_bool_is_refused():
    with pytest.raises(TypeError):
        pool_needs_host("ansible", {"ansible": "yes"})
