"""Integration tests for Arkhai buyer-side policy utilities."""

import pytest


def test_arkhai_common_import():
    """Test that arkhai_common shared module can be imported."""
    try:
        import domain.compute.agent.app.policy.arkhai_common as arkhai_common
        assert arkhai_common is not None
    except ImportError as e:
        pytest.fail(f"Failed to import arkhai_common: {e}")


def test_buyer_action_extraction():
    """Test that action extraction works with mock model output."""
    import torch
    from domain.compute.agent.app.policy.arkhai_common import extract_actions_from_logits

    action_logits = torch.randn(1, 11)  # 9 price + 2 sell
    values = torch.randn(1, 1)

    price_idx, sell_flag = extract_actions_from_logits((action_logits, values))

    assert isinstance(price_idx, int), "price_idx should be int"
    assert isinstance(sell_flag, int), "sell_flag should be int"
    assert 0 <= price_idx <= 8, f"price_idx should be 0-8, got {price_idx}"
    assert sell_flag in (0, 1), f"sell_flag should be 0 or 1, got {sell_flag}"


def test_buyer_model_path_environment_variable(monkeypatch):
    """Test that ARKHAI_NEGOTIATOR_BUYER_MODEL_PATH env var is respected."""
    from domain.compute.agent.app.policy.arkhai_common import _MODEL_CACHE
    _MODEL_CACHE.clear()

    from domain.compute.agent.app.policy.torch_arkhai_negotiator import _get_model

    monkeypatch.setenv("ARKHAI_NEGOTIATOR_BUYER_MODEL_PATH", "/tmp/nonexistent_buyer.pt")
    model = _get_model("minimize", obs_dim_val=21)
    assert model is None, "Model should be None when file doesn't exist"

    _MODEL_CACHE.clear()


def test_obs_dim_calculation():
    """Test observation dimension calculation for different node type counts."""
    from domain.compute.agent.app.policy.arkhai_common import obs_dim

    assert obs_dim(3) == 21  # 12 + 3*3
    assert obs_dim(1) == 15  # 12 + 3*1
    assert obs_dim(5) == 27  # 12 + 3*5


def test_build_action_parameters():
    """Test action parameter builder includes expected keys."""
    from domain.compute.agent.app.policy.arkhai_common import build_action_parameters

    params = build_action_parameters(
        order_id="test-order-123",
        price_idx=4,
        sell_flag=1,
    )

    assert params["order_id"] == "test-order-123"
    assert params["price_idx"] == 4
    assert params["price_multiplier"] == 1.0  # idx 4 = 1.0x multiplier
    assert params["sell_flag"] == 1
    assert params["energy_sell_action"] == "sell_50_percent"
