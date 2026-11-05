import pytest

from market_resource_pools import declaration_has_usable_host, pool_needs_host

NEEDS_HOST = {"bare_metal.ansible": True, "api.quota": False}
DELIVERABLE = frozenset({"enabled-host"})


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


def _usable(host_id, *, provider="bare_metal.ansible", backed=True,
            requirement=NEEDS_HOST, deliverable=DELIVERABLE):
    return declaration_has_usable_host(
        host_id, provider, backed, requirement, deliverable
    )


def test_a_registered_enabled_host_is_usable():
    assert _usable("enabled-host") is True


def test_a_disabled_host_absent_from_the_report_is_not_usable():
    # A disabled host is registered but not reported as taking new delivery.
    assert _usable("disabled-host") is False


def test_an_unregistered_host_absent_from_the_report_is_not_usable():
    assert _usable("never-registered") is False


@pytest.mark.parametrize("host_id", [None, ""])
def test_a_declaration_naming_no_host_has_none_to_use(host_id):
    assert _usable(host_id) is False


@pytest.mark.parametrize("host_id", [None, "disabled-host"])
def test_an_unbacked_pool_needs_no_usable_host(host_id):
    assert _usable(host_id, backed=False) is True


@pytest.mark.parametrize("host_id", [None, "disabled-host"])
def test_a_provider_needing_no_host_needs_no_usable_host(host_id):
    assert _usable(host_id, provider="api.quota") is True


def test_a_provider_the_requirement_does_not_name_needs_a_usable_host():
    assert _usable(None, provider="unregistered") is False
    assert _usable("disabled-host", provider="unregistered") is False
    assert _usable("enabled-host", provider="unregistered") is True


@pytest.mark.parametrize("host_id", [None, "disabled-host"])
def test_no_supplied_requirement_applies_no_rule(host_id):
    assert _usable(host_id, requirement=None) is True


def test_without_a_report_any_named_host_is_usable():
    assert _usable("never-registered", deliverable=None) is True
    assert _usable(None, deliverable=None) is False


def test_an_empty_report_leaves_no_host_usable():
    assert _usable("enabled-host", deliverable=frozenset()) is False
