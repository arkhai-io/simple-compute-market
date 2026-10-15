"""The VM storefront refuses to start with a contradictory Alkahest release model.

The real app and lifespan compose the storefront from configuration. A section
stating both the oracle-gated and the interruptible model names two arbiters
for one escrow, so startup refuses it, enabled or not, before it builds the
storefront's database, signer, or any loop.
"""

from __future__ import annotations

import pytest
from market_alkahest import ReleaseModelError

import market_storefront.container as container
import market_storefront.server as server
from market_storefront import lifecycle
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from tests.publication_app import _replaced_setting


@pytest.mark.parametrize("enabled", [True, False])
async def test_both_oracle_gated_and_interruptible_refuse_startup(enabled):
    app = server.build_vm_storefront_app(
        registry=build_vm_storefront_registry(build_vm_storefront_domain())
    )
    settlement = {
        "schema_version": 1,
        "priority": ["alkahest.v1"] if enabled else [],
        "alkahest": {
            "enabled": enabled,
            "oracle_gated": True,
            # A development address; never used on a public network.
            "trusted_oracle_addresses": ["0x" + "cd" * 20],
            "interruptible": True,
        },
    }
    with _replaced_setting("settlement", settlement):
        with pytest.raises(ReleaseModelError, match="mutually exclusive"):
            async with app.router.lifespan_context(app):
                pass

    assert getattr(app.state, "storefront_container", None) is None
    assert container.resolved_sqlite_client is None
    assert lifecycle.loop_states() == {}
