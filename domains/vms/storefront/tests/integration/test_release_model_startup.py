"""The VM storefront refuses to start with a contradictory Alkahest release model.

The real app and lifespan compose the storefront from configuration, its signer
from a development credential supplied as the Secret boundary supplies it, so
nothing but the refusal stops startup from opening the storefront's database.
A section stating both the oracle-gated and the interruptible model names two
arbiters for one escrow, so startup refuses it, enabled or not, before it opens
that database, builds its signer's services, or starts any loop.
"""

from __future__ import annotations

import base64

import pytest
from market_alkahest import ReleaseModelError
from market_identity import Ed25519Signer

import market_storefront.server as server
from market_storefront import lifecycle
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils import sqlite_client as sqlite_module
from tests.publication_app import _replaced_setting

# A deterministic development key; never used on any network.
SEED = b"\x75" * 32
SIGNER = Ed25519Signer(SEED)


@pytest.mark.parametrize("enabled", [True, False])
async def test_both_oracle_gated_and_interruptible_refuse_startup(
    tmp_path, monkeypatch, enabled
):
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(SEED).rstrip(b"=").decode()
    )
    # The process's database client is created by the first startup; this test
    # starts from none and leaves none behind.
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)
    db_path = tmp_path / "storefront.db"
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
    with (
        _replaced_setting("settlement", settlement),
        _replaced_setting("db_path", str(db_path)),
        _replaced_setting(
            "identity.principal", SIGNER.identity.model_dump(mode="json")
        ),
    ):
        with pytest.raises(ReleaseModelError, match="mutually exclusive"):
            async with app.router.lifespan_context(app):
                pass

    assert getattr(app.state, "storefront_container", None) is None
    assert sqlite_module._sqlite_client is None
    assert not db_path.exists()
    assert lifecycle.loop_states() == {}
