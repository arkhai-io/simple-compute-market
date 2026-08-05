"""Unit tests for domains.vms.listings.listing_mode."""

from __future__ import annotations

from domains.vms.listings.listing_mode import resolve_vm_listing_mode


class TestResolveVmListingMode:
    def test_absent_tag_defaults_to_fungible(self):
        mode, explanation = resolve_vm_listing_mode({})
        assert mode == "fungible"
        assert explanation is None

    def test_explicit_fungible_recognized(self):
        mode, explanation = resolve_vm_listing_mode({"listing_mode": "fungible"})
        assert mode == "fungible"
        assert explanation is None

    def test_explicit_specific_resource_recognized(self):
        mode, explanation = resolve_vm_listing_mode(
            {"listing_mode": "specific_resource"},
        )
        assert mode == "specific_resource"
        assert explanation is None

    def test_unrecognized_value_falls_back_to_default_with_explanation(self):
        mode, explanation = resolve_vm_listing_mode({"listing_mode": "bogus"})
        assert mode == "fungible"
        assert explanation is not None
        assert "bogus" in explanation

    def test_other_policy_tags_are_ignored(self):
        mode, explanation = resolve_vm_listing_mode(
            {"max_reservation_hold_seconds": 60},
        )
        assert mode == "fungible"
        assert explanation is None
