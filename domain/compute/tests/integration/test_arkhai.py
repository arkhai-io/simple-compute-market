"""Integration tests for Arkhai RL policy infrastructure.

Tests the active negotiation policy callable (torch_arkhai_negotiator)
and shared utilities in arkhai_common.
"""

import pytest


def test_pufferlib_import():
    """Test that PufferLib can be imported."""
    try:
        import pufferlib.ocean.arkhai.arkhai as arkhai_env
        assert arkhai_env is not None
    except ImportError as e:
        pytest.fail(f"Failed to import PufferLib Arkhai environment: {e}")


def test_torch_import():
    """Test that PyTorch can be imported."""
    try:
        import torch
        assert torch is not None
    except ImportError as e:
        pytest.fail(f"Failed to import PyTorch: {e}")


def test_torch_arkhai_negotiator_import():
    """Test that torch_arkhai_negotiator module can be imported."""
    try:
        import domain.compute.agent.app.policy.torch_arkhai_negotiator as negotiator
        assert negotiator is not None
    except ImportError as e:
        pytest.fail(f"Failed to import torch_arkhai_negotiator: {e}")


def test_action_extraction_basic():
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


def test_model_path_environment_variable(monkeypatch):
    """Test that ARKHAI_NEGOTIATOR_SELLER_MODEL_PATH env var is respected."""
    from domain.compute.agent.app.policy.arkhai_common import _MODEL_CACHE
    _MODEL_CACHE.clear()

    from domain.compute.agent.app.policy.torch_arkhai_negotiator import _get_model

    monkeypatch.setenv("ARKHAI_NEGOTIATOR_SELLER_MODEL_PATH", "/tmp/nonexistent.pt")
    model = _get_model("maximize", obs_dim_val=21)
    assert model is None, "Model should be None when file doesn't exist"

    _MODEL_CACHE.clear()
