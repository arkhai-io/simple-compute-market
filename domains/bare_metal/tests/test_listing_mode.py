"""Unit tests for arkhai_bare_metal.listing_mode."""

from __future__ import annotations

from arkhai_bare_metal.listing_mode import resolve_bare_metal_listing_mode


class TestResolveBareMetalListingMode:
    def test_absent_tag_defaults_to_specific_resource(self):
        mode, explanation = resolve_bare_metal_listing_mode({})
        assert mode == "specific_resource"
        assert explanation is None

    def test_explicit_specific_resource_recognized(self):
        mode, explanation = resolve_bare_metal_listing_mode(
            {"listing_mode": "specific_resource"},
        )
        assert mode == "specific_resource"
        assert explanation is None

    def test_unrecognized_value_falls_back_with_explanation(self):
        """Bare metal has no pooled concept -- even "fungible" (a value
        another domain accepts) is unrecognized here and gets the same
        non-fatal, operator-visible handling as any other bad value."""
        mode, explanation = resolve_bare_metal_listing_mode(
            {"listing_mode": "fungible"},
        )
        assert mode == "specific_resource"
        assert explanation is not None
        assert "fungible" in explanation
