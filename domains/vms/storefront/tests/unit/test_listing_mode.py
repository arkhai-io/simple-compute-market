"""Unit tests for market_storefront.listings.listing_mode."""

from __future__ import annotations

from market_storefront.listings.listing_mode import resolve_vm_listing_mode


class TestResolveVmListingMode:
    def test_absent_tag_uses_the_callers_structural_default_fungible(self):
        mode, explanation = resolve_vm_listing_mode(
            {},
            structural_default="fungible",
        )
        assert mode == "fungible"
        assert explanation is None

    def test_absent_tag_uses_the_callers_structural_default_specific_resource(self):
        """The backward-compatibility case: a caller with exactly one
        enabled member passes "specific_resource" as its own structural
        default -- an untagged pool must not silently become fungible."""
        mode, explanation = resolve_vm_listing_mode(
            {},
            structural_default="specific_resource",
        )
        assert mode == "specific_resource"
        assert explanation is None

    def test_explicit_fungible_recognized_regardless_of_structural_default(self):
        mode, explanation = resolve_vm_listing_mode(
            {"listing_mode": "fungible"},
            structural_default="specific_resource",
        )
        assert mode == "fungible"
        assert explanation is None

    def test_explicit_specific_resource_recognized_regardless_of_structural_default(
        self,
    ):
        mode, explanation = resolve_vm_listing_mode(
            {"listing_mode": "specific_resource"},
            structural_default="fungible",
        )
        assert mode == "specific_resource"
        assert explanation is None

    def test_unrecognized_value_falls_back_to_the_structural_default_with_explanation(
        self,
    ):
        mode, explanation = resolve_vm_listing_mode(
            {"listing_mode": "bogus"},
            structural_default="fungible",
        )
        assert mode == "fungible"
        assert explanation is not None
        assert "bogus" in explanation

    def test_unrecognized_value_falls_back_to_specific_resource_default_too(self):
        mode, explanation = resolve_vm_listing_mode(
            {"listing_mode": "bogus"},
            structural_default="specific_resource",
        )
        assert mode == "specific_resource"
        assert explanation is not None
        assert "bogus" in explanation

    def test_other_policy_tags_are_ignored(self):
        mode, explanation = resolve_vm_listing_mode(
            {"max_reservation_hold_seconds": 60},
            structural_default="fungible",
        )
        assert mode == "fungible"
        assert explanation is None
