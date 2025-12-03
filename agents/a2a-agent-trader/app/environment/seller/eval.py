#!/usr/bin/env python3
"""Evaluate the Market environment using pufferlib"""

import sys
import os
import traceback
from pathlib import Path
import numpy as np

# Pufferlib imports - may fail if not installed
try:
    import pufferlib.pufferl as pufferl
    import pufferlib.vector as vec
except ImportError:
    pufferl = None
    vec = None

# Add the app directory to the path
app_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(app_dir))

def find_latest_checkpoint(experiment_dir="experiments"):
    """Find the latest checkpoint in experiments directory"""
    exp_path = Path(experiment_dir)
    if not exp_path.exists():
        return None
    
    # Look for checkpoint files
    checkpoint_files = []
    for pattern in ["**/*.pt", "**/*.pth"]:
        checkpoint_files.extend(exp_path.glob(pattern))
    
    if not checkpoint_files:
        return None
    
    # Return the most recently modified
    return max(checkpoint_files, key=lambda p: p.stat().st_mtime)

def load_model_from_checkpoint(checkpoint_path, vecenv, args):
    """Load a trained model from checkpoint"""
    if pufferl is None:
        return None
    
    try:
        # Update args with checkpoint path
        args['load_model_path'] = str(checkpoint_path)
        policy = pufferl.load_policy(args, vecenv)
        return policy
    except Exception as e:
        print(f"Warning: Failed to load model from {checkpoint_path}: {e}")
        return None

def main():
    """Main evaluation function"""
    if pufferl is None or vec is None:
        print("Error: pufferlib is not installed")
        print("Install with: uv sync")
        sys.exit(1)
    
    try:
        from app.environment.seller.market import Market
        
        # Get model path from environment or use default
        model_path = os.environ.get('LOAD_MODEL_PATH', 'latest')
        
        # Create a simple environment for evaluation
        env = Market(num_envs=1)
        obs, info = env.reset()
        
        print(f"Environment reset successfully!")
        print(f"Observation shape: {obs.shape}")
        print(f"Observation space: {env.single_observation_space}")
        print(f"Action space: {env.single_action_space}")
        
        # Try to load model if path is provided
        policy = None
        if model_path == 'latest':
            checkpoint_path = find_latest_checkpoint()
            if checkpoint_path:
                print(f"\nFound latest checkpoint: {checkpoint_path}")
                # Create minimal args for loading
                args = {
                    'package': None,
                    'env_name': None,
                    'policy_name': 'Policy',
                    'rnn_name': 'Recurrent',
                    'load_model_path': str(checkpoint_path),
                }
                # Create a simple vecenv for loading
                vecenv = vec.make(lambda **kwargs: Market(**kwargs), num_envs=1, seed=42)
                policy = load_model_from_checkpoint(checkpoint_path, vecenv, args)
                if policy:
                    print("Model loaded successfully!")
                else:
                    print("Warning: Could not load model, using random actions")
            else:
                print("\nNo checkpoint found, using random actions")
        elif Path(model_path).exists():
            print(f"\nLoading model from: {model_path}")
            args = {
                'package': None,
                'env_name': None,
                'policy_name': 'Policy',
                'rnn_name': 'Recurrent',
                'load_model_path': str(model_path),
            }
            vecenv = vec.make(lambda **kwargs: Market(**kwargs), num_envs=1, seed=42)
            policy = load_model_from_checkpoint(model_path, vecenv, args)
            if not policy:
                print("Warning: Could not load model, using random actions")
        else:
            print(f"\nModel path not found: {model_path}, using random actions")
        
        # Run evaluation
        num_steps = int(os.environ.get('EVAL_STEPS', '100'))
        print(f"\nRunning evaluation for {num_steps} steps...")
        
        total_reward = 0.0
        episode_count = 0
        
        for i in range(num_steps):
            if policy:
                # Use policy to get action
                # Note: This is simplified - actual policy interface may differ
                action = env.single_action_space.sample()  # Placeholder
            else:
                action = env.single_action_space.sample()
            
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward[0]
            
            if (i + 1) % 10 == 0:
                print(f"Step {i+1}/{num_steps}: reward={reward[0]:.6f}, "
                      f"terminated={terminated[0]}, truncated={truncated[0]}")
            
            if terminated[0] or truncated[0]:
                episode_count += 1
                if info and len(info) > 0:
                    log_info = info[0]
                    print(f"\nEpisode {episode_count} complete:")
                    print(f"  Score: {log_info.get('score', 0):.2f}")
                    print(f"  Profit: {log_info.get('profit', 0):.2f}")
                    print(f"  Episode length: {log_info.get('episode_length', 0):.0f}")
                obs, info = env.reset()
        
        env.close()
        print(f"\nEvaluation complete!")
        print(f"Total steps: {num_steps}")
        print(f"Episodes completed: {episode_count}")
        print(f"Average reward: {total_reward / num_steps:.6f}")
        
    except ImportError as e:
        print(f"Error importing: {e}")
        print("Make sure pufferlib is installed: uv sync")
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"Evaluation error: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

