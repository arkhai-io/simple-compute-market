"""Unit tests for domains.vms.listings.pool_descriptors."""

from __future__ import annotations

from domains.vms.listings.pool_descriptors import resolve_region, resolve_sla


class TestResolveRegion:
    def test_hint_present_wins(self):
        assert resolve_region(
            {"region": "California, US"}, fallback="Texas, US",
        ) == "California, US"

    def test_absent_hint_falls_back(self):
        assert resolve_region({}, fallback="Texas, US") == "Texas, US"

    def test_fallback_can_be_none(self):
        assert resolve_region({}, fallback=None) is None

    def test_non_string_hint_falls_back(self):
        """A malformed hint value must not propagate as-is."""
        assert resolve_region({"region": 12345}, fallback="Texas, US") == "Texas, US"

    def test_empty_string_hint_falls_back(self):
        assert resolve_region({"region": ""}, fallback="Texas, US") == "Texas, US"


class TestResolveSla:
    def test_storefront_override_wins_over_everything(self):
        assert resolve_sla(
            {"sla": 90.0},
            accept_pool_declared_sla=True,
            storefront_override=99.99,
            config_default=50.0,
        ) == 99.99

    def test_storefront_override_zero_is_a_real_value_not_absent(self):
        assert resolve_sla(
            {"sla": 90.0},
            accept_pool_declared_sla=True,
            storefront_override=0.0,
            config_default=50.0,
        ) == 0.0

    def test_pool_hint_used_when_gate_open_and_no_override(self):
        assert resolve_sla(
            {"sla": 90.0},
            accept_pool_declared_sla=True,
            storefront_override=None,
            config_default=50.0,
        ) == 90.0

    def test_pool_hint_ignored_when_gate_closed(self):
        """The trust gate is storefront-wide: closed means the pool's
        claim is never read, even though it has one."""
        assert resolve_sla(
            {"sla": 90.0},
            accept_pool_declared_sla=False,
            storefront_override=None,
            config_default=50.0,
        ) == 50.0

    def test_config_default_used_when_no_override_and_no_hint(self):
        assert resolve_sla(
            {},
            accept_pool_declared_sla=True,
            storefront_override=None,
            config_default=50.0,
        ) == 50.0

    def test_config_default_used_when_gate_open_but_hint_invalid(self):
        assert resolve_sla(
            {"sla": "not-a-number"},
            accept_pool_declared_sla=True,
            storefront_override=None,
            config_default=50.0,
        ) == 50.0

    def test_config_default_used_when_gate_closed_and_no_override_even_with_hint(self):
        assert resolve_sla(
            {"sla": 90.0},
            accept_pool_declared_sla=False,
            storefront_override=None,
            config_default=0.0,
        ) == 0.0
