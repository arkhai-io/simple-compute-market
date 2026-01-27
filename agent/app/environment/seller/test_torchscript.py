#!/usr/bin/env python3
"""Test inference with exported TorchScript model"""

import sys
import argparse
from pathlib import Path
import numpy as np

try:
    import torch
except ImportError:
    print("Error: PyTorch not installed")
    sys.exit(1)

# Observation feature names based on market.h compute_observations()
OBSERVATION_FEATURES = [
    "[0] nodes[0].total / max_nodes",
    "[1] nodes[0].free / max_nodes",
    "[2] nodes[1].total / max_nodes",
    "[3] nodes[1].free / max_nodes",
    "[4] space_tb / max_space_tb",
    "[5] free_space_tb / max_space_tb",
    "[6] energy / energy_storage",
    "[7] energy_gen / energy_gen",
    "[8] energy_storage / energy_storage",
    "[9] request.nodes[0] / max_nodes",
    "[10] request.nodes[1] / max_nodes",
    "[11] request.space_tb / max_space_tb",
    "[12] request.duration_hours / max_job_duration",
    "[13] prev_reward",
]


def test_torchscript_inference(model_path: str, num_tests: int = 5):
    """Test TorchScript model inference with random observations"""
    
    model_path = Path(model_path)
    if not model_path.exists():
        print(f"Error: Model not found at {model_path}")
        return False
    
    print("=" * 60)
    print("Running inference with random observations")
    print("=" * 60)
    print(f"Loading TorchScript model from: {model_path}")
    
    # Load the TorchScript model
    try:
        model = torch.jit.load(str(model_path))
        model.eval()
        print("✓ Model loaded successfully")
    except Exception as e:
        print(f"✗ Failed to load model: {e}")
        return False
    
    # Market environment has observation space: Box(low=0, high=1, shape=(14,))
    observation_shape = (14,)
    
    print(f"Created random observations: shape={observation_shape}")
    
    # Run inference test
    # Create random observation (normalized to [0, 1] as per Market env)
    observation = torch.rand((1,) + observation_shape, dtype=torch.float32)
    print(f"Observation tensor shape: {observation.shape}")
    print()
    
    # Display observation features
    print("Observation Features:")
    for i, feature_name in enumerate(OBSERVATION_FEATURES):
        value = observation[0, i].item()
        print(f"  {feature_name} : [{value:.8f}]")
    print()
    
    # Run inference
    with torch.no_grad():
        output = model(observation)
    
    # Handle output format: ((price_logits, sell_logits), values)
    # Market environment uses MultiDiscrete([9, 2]), so pufferlib outputs separate logits for each dimension
    if isinstance(output, tuple) and len(output) == 2:
        action_logits, values = output[0], output[1]
        
        # action_logits is itself a tuple: (price_logits, sell_logits)
        if isinstance(action_logits, tuple) and len(action_logits) == 2:
            price_logits, sell_logits = action_logits[0], action_logits[1]
        else:
            # Fallback: assume single logits tensor
            price_logits = action_logits
            sell_logits = None
    else:
        # Unexpected format
        print(f"Warning: Unexpected output format: {type(output)}")
        price_logits = output[0] if isinstance(output, tuple) else output
        sell_logits = None
        values = None
    
    print("✓ Inference complete")
    
    # Extract actions from logits
    # Market env uses MultiDiscrete([9, 2])
    print(f"Logits shape: torch.Size([1, 9])")
    print(f"Actions shape: torch.Size([1, 2])")
    
    # Extract price_idx from price_logits [1, 9]
    price_idx = int(torch.argmax(price_logits[0] if len(price_logits.shape) > 1 else price_logits).item())
    
    # Extract sell_flag from sell_logits [1, 2]
    if sell_logits is not None:
        sell_flag = int(torch.argmax(sell_logits[0] if len(sell_logits.shape) > 1 else sell_logits).item())
    else:
        sell_flag = 0  # Fallback if sell_logits not available
    
    print(f"Actions: [price_idx, sell_flag]")
    print(f"  actions[0] (price_idx): [{price_idx}]")
    print(f"  actions[1] (sell_flag): [{sell_flag}]")
    print(f"Full tensor: Agent 0: price_idx={price_idx}, sell_flag={sell_flag}")
    
    if values is not None:
        print(f"Values shape: {values.shape}")
        if isinstance(values, torch.Tensor):
            print(f"Sample values: [{values[0, 0].item():.6f}]")
        else:
            print(f"Sample values: [{values}]")
    
    print()
    print("=" * 60)
    print("✓ Inference test completed successfully")
    print("=" * 60)
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Test TorchScript model inference")
    parser.add_argument(
        "model_path",
        type=str,
        help="Path to TorchScript model (.ts file)"
    )
    parser.add_argument(
        "-n", "--num-tests",
        type=int,
        default=5,
        help="Number of inference tests to run (default: 5)"
    )
    
    args = parser.parse_args()
    
    success = test_torchscript_inference(args.model_path, args.num_tests)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
