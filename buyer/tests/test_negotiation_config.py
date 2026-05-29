from market_buyer.common import resolve_negotiation_config


def test_resolve_negotiation_config_preserves_policy_lists(monkeypatch):
    monkeypatch.setattr(
        "service.config_loader.load_user_config",
        lambda: {
            "negotiation": {
                "policies": ["buyer_escrow_shape_guard", "bisection"],
            },
        },
    )

    policies, policy_mode = resolve_negotiation_config()

    assert policies == ["buyer_escrow_shape_guard", "bisection"]
    assert policy_mode is None
