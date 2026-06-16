"""Compatibility shim — refund parameter derivation moved to
``core_storefront.refund`` when the API-tokens domain became the
second storefront composition root."""

from core_storefront.refund import (  # noqa: F401
    ValidationResult,
    derive_refund_params,
)
