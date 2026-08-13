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
        "market_storefront.services.alkahest_service.build_clients",
        lambda: (_ for _ in ()).throw(AssertionError("chain client constructed")),
    )

    assert server._build_alkahest_clients() == {}
