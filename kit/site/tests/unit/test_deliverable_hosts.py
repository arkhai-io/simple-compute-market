"""The usable-host rule, given whether the pool needs a host."""

from __future__ import annotations

import pytest

from market_site import declaration_has_usable_host

DELIVERABLE = frozenset({"enabled-host"})


def _usable(host_id, *, needs_host=True, backed=True, deliverable=DELIVERABLE):
    return declaration_has_usable_host(
        host_id, needs_host=needs_host, backed=backed, deliverable=deliverable
    )


def test_a_host_in_the_report_is_usable():
    assert _usable("enabled-host") is True


def test_a_host_absent_from_the_report_is_not_usable():
    # A disabled or never-registered host is one the report leaves out.
    assert _usable("disabled-host") is False


@pytest.mark.parametrize("host_id", [None, ""])
def test_a_declaration_naming_no_host_has_none_to_use(host_id):
    assert _usable(host_id) is False


def test_an_empty_report_leaves_no_host_usable():
    assert _usable("enabled-host", deliverable=frozenset()) is False


@pytest.mark.parametrize("host_id", [None, "disabled-host"])
def test_an_unbacked_pool_needs_no_usable_host(host_id):
    assert _usable(host_id, backed=False) is True


@pytest.mark.parametrize("host_id", [None, "disabled-host"])
def test_a_pool_needing_no_host_needs_no_usable_host(host_id):
    assert _usable(host_id, needs_host=False) is True


def test_without_a_report_any_named_host_is_usable():
    assert _usable("never-registered", deliverable=None) is True
    assert _usable(None, deliverable=None) is False
