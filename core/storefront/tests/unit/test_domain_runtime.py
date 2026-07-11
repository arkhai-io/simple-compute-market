from __future__ import annotations

import pytest

from core_storefront.domain_runtime import StorefrontDomainRuntime


def _kinded(expected: str):
    def normalize(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise TypeError("expected dict")
        if value.get("kind") != expected:
            raise ValueError(f"expected kind {expected}")
        return dict(value)

    return normalize


def test_storefront_domain_runtime_delegates_to_domain_codecs() -> None:
    runtime = StorefrontDomainRuntime(
        schema_id="demo.v1",
        normalize_listing=_kinded("listing"),
        normalize_message=_kinded("message"),
        normalize_terms=_kinded("terms"),
        normalize_materialization=_kinded("materialization"),
        normalize_receipt=_kinded("receipt"),
        normalize_result=_kinded("result"),
    )

    assert runtime.schema_id == "demo.v1"
    assert runtime.listing({"kind": "listing", "id": "l1"}) == {
        "kind": "listing",
        "id": "l1",
    }
    assert runtime.message({"kind": "message"}) == {"kind": "message"}
    assert runtime.terms({"kind": "terms"}) == {"kind": "terms"}
    assert runtime.materialization({"kind": "materialization"}) == {
        "kind": "materialization",
    }
    assert runtime.receipt({"kind": "receipt"}) == {"kind": "receipt"}
    assert runtime.result({"kind": "result"}) == {"kind": "result"}


def test_storefront_domain_runtime_surfaces_domain_validation_errors() -> None:
    runtime = StorefrontDomainRuntime(
        schema_id="demo.v1",
        normalize_listing=_kinded("listing"),
        normalize_message=_kinded("message"),
        normalize_terms=_kinded("terms"),
        normalize_materialization=_kinded("materialization"),
        normalize_receipt=_kinded("receipt"),
        normalize_result=_kinded("result"),
    )

    with pytest.raises(ValueError, match="expected kind listing"):
        runtime.listing({"kind": "message"})

