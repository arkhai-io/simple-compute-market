from __future__ import annotations


def test_fiat_only_startup_does_not_construct_alkahest_clients(monkeypatch):
    import market_storefront.server as server
    import market_storefront.utils.config as config

    monkeypatch.setattr(
        config,
        "settlement_config_mapping",
        lambda: {
            "priority": ["fiat.stripe.v1"],
            "stripe": {"enabled": True},
        },
    )
    monkeypatch.setattr(config, "CHAINS", {})
    monkeypatch.setattr(
        server,
        "build_alkahest_clients",
        lambda _policy, **_kwargs: (_ for _ in ()).throw(
            AssertionError("chain client constructed")
        ),
    )

    assert server._build_alkahest_clients() == {}


def test_stripe_startup_survives_unready_configured_alkahest(monkeypatch):
    import market_storefront.server as server
    import market_storefront.utils.config as config

    chain = object()
    monkeypatch.setattr(
        config,
        "settlement_config_mapping",
        lambda: {
            "priority": ["fiat.stripe.v1", "alkahest.v1"],
            "stripe": {"enabled": True},
            "alkahest": {"enabled": True},
        },
    )
    monkeypatch.setattr(config, "CHAINS", {"anvil": chain})
    monkeypatch.setattr(server, "get_evm_wallet_address", lambda: "")
    monkeypatch.setattr(server, "get_evm_wallet_private_key", lambda: "")

    assert server._build_alkahest_clients() == {}


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
