"""Unit tests for domains.vms.listings.listing_cardinality_mode."""

from __future__ import annotations

from domains.vms.listings.listing_cardinality_mode import (
    resolve_vm_listing_cardinality_mode,
)

SETTLED = "listing_cardinality_mode"
DEPRECATED = "listing_mode"


class TestResolveVmListingCardinalityMode:
    def test_absent_tag_uses_the_callers_structural_default_fungible(self):
        resolved = resolve_vm_listing_cardinality_mode(
            {}, structural_default="fungible",
        )
        assert resolved.mode == "fungible"
        assert resolved.fallback_explanation is None
        assert resolved.deprecated_key_notice is None

    def test_absent_tag_uses_the_callers_structural_default_specific_resource(self):
        """The backward-compatibility case: a caller with exactly one
        enabled member passes "specific_resource" as its own structural
        default -- an untagged pool must not silently become fungible."""
        resolved = resolve_vm_listing_cardinality_mode(
            {}, structural_default="specific_resource",
        )
        assert resolved.mode == "specific_resource"
        assert resolved.fallback_explanation is None

    def test_absence_is_silent(self):
        """Absence encodes "no cardinality question applies", so no
        operator notice is owed for it -- only for a supplied value."""
        resolved = resolve_vm_listing_cardinality_mode(
            {}, structural_default="fungible",
        )
        assert resolved.fallback_explanation is None
        assert resolved.deprecated_key_notice is None

    def test_explicit_fungible_recognized_regardless_of_structural_default(self):
        resolved = resolve_vm_listing_cardinality_mode(
            {SETTLED: "fungible"}, structural_default="specific_resource",
        )
        assert resolved.mode == "fungible"
        assert resolved.fallback_explanation is None

    def test_explicit_specific_resource_recognized_regardless_of_default(self):
        resolved = resolve_vm_listing_cardinality_mode(
            {SETTLED: "specific_resource"}, structural_default="fungible",
        )
        assert resolved.mode == "specific_resource"
        assert resolved.fallback_explanation is None

    def test_unrecognized_value_falls_back_with_explanation(self):
        resolved = resolve_vm_listing_cardinality_mode(
            {SETTLED: "bogus"}, structural_default="fungible",
        )
        assert resolved.mode == "fungible"
        assert resolved.fallback_explanation is not None
        assert "bogus" in resolved.fallback_explanation

    def test_unrecognized_value_falls_back_to_specific_resource_default_too(self):
        resolved = resolve_vm_listing_cardinality_mode(
            {SETTLED: "bogus"}, structural_default="specific_resource",
        )
        assert resolved.mode == "specific_resource"
        assert "bogus" in resolved.fallback_explanation

    def test_other_policy_tags_are_ignored(self):
        resolved = resolve_vm_listing_cardinality_mode(
            {"max_reservation_hold_seconds": 60}, structural_default="fungible",
        )
        assert resolved.mode == "fungible"
        assert resolved.fallback_explanation is None


class TestDeprecatedIngestionAlias:
    """The skew case the alias exists to prevent.

    A projection from an unupgraded site carries only the deprecated key.
    It must resolve to the cardinality that key names -- not to the
    structural default, which is what an ignored key would produce, and
    which would reclassify the pool without erroring because the key is
    optional.
    """

    def test_deprecated_key_resolves_and_does_not_fall_back(self):
        resolved = resolve_vm_listing_cardinality_mode(
            {DEPRECATED: "specific_resource"}, structural_default="fungible",
        )
        assert resolved.mode == "specific_resource"
        assert resolved.fallback_explanation is None

    def test_deprecated_key_emits_an_operator_notice(self):
        resolved = resolve_vm_listing_cardinality_mode(
            {DEPRECATED: "fungible"}, structural_default="specific_resource",
        )
        assert resolved.deprecated_key_notice is not None
        assert DEPRECATED in resolved.deprecated_key_notice
        assert SETTLED in resolved.deprecated_key_notice

    def test_settled_key_emits_no_deprecation_notice(self):
        resolved = resolve_vm_listing_cardinality_mode(
            {SETTLED: "fungible"}, structural_default="fungible",
        )
        assert resolved.deprecated_key_notice is None

    def test_settled_key_wins_when_both_present(self):
        resolved = resolve_vm_listing_cardinality_mode(
            {SETTLED: "fungible", DEPRECATED: "specific_resource"},
            structural_default="specific_resource",
        )
        assert resolved.mode == "fungible"
        assert resolved.deprecated_key_notice is None

    def test_unrecognized_value_under_deprecated_key_reports_both_notices(self):
        """The two notices mean opposite things -- one says the value was
        rejected, the other says the key was honored but is going away --
        so a pool in both conditions must report both rather than having
        one mask the other."""
        resolved = resolve_vm_listing_cardinality_mode(
            {DEPRECATED: "bogus"}, structural_default="fungible",
        )
        assert resolved.mode == "fungible"
        assert resolved.fallback_explanation is not None
        assert "bogus" in resolved.fallback_explanation
        assert resolved.deprecated_key_notice is not None
