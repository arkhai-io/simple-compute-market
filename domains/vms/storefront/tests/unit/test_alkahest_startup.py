from __future__ import annotations


def test_vm_contributes_chain_values_to_shared_factory(monkeypatch):
    from types import SimpleNamespace

    import market_storefront.server as server
    import market_storefront.utils.config as config

    captured = []
    monkeypatch.setattr(
        config,
        "settlement_config_mapping",
        lambda: {"alkahest": {"enabled": True}},
    )
    monkeypatch.setattr(
        config,
        "CHAINS",
        {
            "anvil": SimpleNamespace(
                rpc_url="http://rpc",
                alkahest_address_config_path="addresses.json",
            )
        },
    )
    monkeypatch.setattr(server, "get_evm_wallet_address", lambda: "0x" + "11" * 20)
    monkeypatch.setattr(server, "get_evm_wallet_private_key", lambda: "secret")
    monkeypatch.setattr(
        server,
        "build_alkahest_clients",
        lambda policy, **_kwargs: captured.append(policy) or {"anvil": object()},
    )

    clients = server._build_alkahest_clients()

    assert tuple(clients) == ("anvil",)
    assert captured[0].chains[0].name == "anvil"
    assert captured[0].chains[0].rpc_url == "http://rpc"
