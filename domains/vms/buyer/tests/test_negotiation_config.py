from domains.vms.buyer.common import resolve_negotiation_config


def test_resolve_negotiation_config_preserves_policy_lists(monkeypatch):
    monkeypatch.setattr(
        "market_config.config_loader.load_user_config",
        lambda: {
            "negotiation": {
                "policies": ["buyer_escrow_shape_guard", "bisection"],
            },
        },
    )

    policies, policy_mode = resolve_negotiation_config()

    assert policies == ["buyer_escrow_shape_guard", "bisection"]
    assert policy_mode is None


def test_resolve_negotiation_config_preserves_policy_tables(monkeypatch):
    table = {
        "erc20": "erc20_bisection",
        "native_token": "native_token_bisection",
    }
    monkeypatch.setattr(
        "market_config.config_loader.load_user_config",
        lambda: {"negotiation": {"policies": table}},
    )

    policies, policy_mode = resolve_negotiation_config()

    assert policies == table
    assert policy_mode is None


def test_load_buyer_chain_builds_dispatch_for_policy_table(monkeypatch):
    from domains.vms.buyer.buyer_client import _load_buyer_chain

    monkeypatch.setattr("domains.vms.buyer.common.buyer_chains", lambda: {})

    chain = _load_buyer_chain(policies={
        "erc20": "erc20_bisection",
        "native_token": {"policy": "native_token_bisection"},
    })

    assert len(chain) == 2
    assert getattr(chain[0], "__name__", "") == "buyer_escrow_shape_guard"
    assert getattr(chain[1], "__name__", "") == "escrow_kind_dispatch_middleware"
