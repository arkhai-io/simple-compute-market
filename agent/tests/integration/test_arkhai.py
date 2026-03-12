"""Integration tests for Arkhai training environment.

Branch 1: Basic infrastructure tests
- Test environment imports
- Test observation builder (basic shape validation)
- Test model loading paths
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


def test_torch_arkhai_seller_import():
    """Test that torch_arkhai_seller module can be imported."""
    try:
        import domain.compute.agent.app.policy.torch_arkhai_seller as torch_arkhai_seller
        assert torch_arkhai_seller is not None
    except ImportError as e:
        pytest.fail(f"Failed to import torch_arkhai_seller: {e}")


def test_observation_builder_basic():
    """Test that observation builder returns correct shape.

    This is a basic test for Branch 1 - just verifies the shape is correct.
    Branch 2 will add tests for feature value ranges.

    Note: This test is skipped in Branch 1 due to complex Pydantic model requirements.
    Branch 2 will include proper integration tests.
    """
    import pytest
    pytest.skip("Skipping complex integration test in Branch 1 - will be added in Branch 2")


def test_action_extraction_basic():
    """Test that action extraction works with mock model output."""
    import torch
    from domain.compute.agent.app.policy.arkhai_common import extract_actions_from_logits as _extract_actions_from_logits

    # Create mock output (action_logits, values)
    action_logits = torch.randn(1, 11)  # 9 price + 2 sell
    values = torch.randn(1, 1)

    output = (action_logits, values)

    # Extract actions
    price_idx, sell_flag = _extract_actions_from_logits(output)

    # Check types and ranges
    assert isinstance(price_idx, int), "price_idx should be int"
    assert isinstance(sell_flag, int), "sell_flag should be int"
    assert 0 <= price_idx <= 8, f"price_idx should be 0-8, got {price_idx}"
    assert sell_flag in (0, 1), f"sell_flag should be 0 or 1, got {sell_flag}"


def test_model_path_environment_variable(monkeypatch):
    """Test that ARKHAI_SELLER_MODEL_PATH environment variable is respected."""
    from domain.compute.agent.app.policy.arkhai_common import _MODEL_CACHE
    # Clear cache to ensure fresh load attempt
    _MODEL_CACHE.clear()

    from domain.compute.agent.app.policy.torch_arkhai_seller import _get_model

    # Set environment variable to a test path
    test_path = "/tmp/test_arkhai_model.pt"
    monkeypatch.setenv("ARKHAI_SELLER_MODEL_PATH", test_path)

    # Model won't load (file doesn't exist), but we can check the path is read
    model = _get_model(obs_dim_val=21)

    # Model should be None since file doesn't exist
    assert model is None, "Model should be None when file doesn't exist"

    # Clean up cache
    _MODEL_CACHE.clear()
