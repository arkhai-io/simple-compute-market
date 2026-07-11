"""Core storefront interface filled by concrete market domains."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DomainCodec = Callable[[Any], Any]


@dataclass(frozen=True)
class StorefrontDomainRuntime:
    """Domain-provided codecs for the core storefront role.

    Core storefront code should depend on this shape rather than importing a
    concrete market domain. A domain package fills these slots with its schema
    models and deterministic interpretation helpers; those helpers may in turn
    depend on kit or user-injected dependencies when the domain requires them.
    """

    schema_id: str
    normalize_listing: DomainCodec
    normalize_message: DomainCodec
    normalize_terms: DomainCodec
    normalize_materialization: DomainCodec
    normalize_receipt: DomainCodec
    normalize_result: DomainCodec

    def listing(self, value: Any) -> Any:
        return self.normalize_listing(value)

    def message(self, value: Any) -> Any:
        return self.normalize_message(value)

    def terms(self, value: Any) -> Any:
        return self.normalize_terms(value)

    def materialization(self, value: Any) -> Any:
        return self.normalize_materialization(value)

    def receipt(self, value: Any) -> Any:
        return self.normalize_receipt(value)

    def result(self, value: Any) -> Any:
        return self.normalize_result(value)

