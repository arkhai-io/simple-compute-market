"""The bare-metal storefront's settlement composition imports from its owners.

`make check-architecture` holds this composition's layer and scope rules: no core
or kit package imports it, and it imports no VM implementation.
"""

from __future__ import annotations

import importlib


def test_settlement_composition_imports_publication_payload_from_runtime_owner() -> (
    None
):
    module = importlib.import_module(
        "arkhai_bare_metal_storefront.settlement_composition"
    )

    assert module.BareMetalStorefrontSettlementComposition is not None
