#!/usr/bin/env python3
"""Temporary test script to load and test the Market environment"""

import sys
import os
from pathlib import Path

def test_market_import():
    """Test importing the Market environment"""
    print("=" * 60)
    print("Testing Market Environment Import")
    print("=" * 60)
    
    # Import sys and add the app directory to avoid triggering app.__init__
    import sys
    from pathlib import Path
    
    # Add app directory to path for direct import
    app_dir = Path(__file__).parent / "app"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    
    # Also add environment directory
    env_dir = app_dir / "environment"
    if str(env_dir) not in sys.path:
        sys.path.insert(0, str(env_dir))
    
    try:
        # Import directly from the environment.seller module
        import importlib.util
        seller_dir = env_dir / "seller"
        spec = importlib.util.spec_from_file_location(
            "environment.seller.market",
            seller_dir / "market.py"
        )
        market_module = importlib.util.module_from_spec(spec)
        market_module.__package__ = "environment.seller"
        spec.loader.exec_module(market_module)
        Market = market_module.Market
        print("✓ Successfully imported Market from environment.seller.market")
        return Market
    except Exception as e:
        print(f"✗ Failed to import Market: {e}")
        print("\nPossible issues:")
        print("1. The C extension binding may need to be built")
        print("   - Run: cd app/environment/seller && uv run python build_binding.py")
        print("2. pufferlib may need to be installed/configured")
        print("3. The binding module may need to be compiled")
        import traceback
        traceback.print_exc()
        return None

def test_market_initialization(Market):
    """Test initializing the Market environment"""
    print("\n" + "=" * 60)
    print("Testing Market Environment Initialization")
    print("=" * 60)
    
    if Market is None:
        print("✗ Cannot test initialization - Market class not available")
        return None
    
    try:
        # Try creating a small environment instance
        print("Creating Market environment with num_envs=1...")
        env = Market(num_envs=1)
        print("✓ Successfully created Market environment")
        
        # Check environment properties
        print(f"  - Observation space: {env.single_observation_space}")
        print(f"  - Action space: {env.single_action_space}")
        print(f"  - Number of agents: {env.num_agents}")
        
        return env
    except Exception as e:
        print(f"✗ Failed to initialize Market environment: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_market_reset(env):
    """Test resetting the Market environment"""
    print("\n" + "=" * 60)
    print("Testing Market Environment Reset")
    print("=" * 60)
    
    if env is None:
        print("✗ Cannot test reset - environment not available")
        return None
    
    try:
        print("Calling env.reset()...")
        observations, info = env.reset(seed=42)
        print("✓ Successfully reset environment")
        print(f"  - Observations shape: {observations.shape}")
        print(f"  - Observations dtype: {observations.dtype}")
        print(f"  - Info: {info}")
        
        # Print first few observation values
        if len(observations.shape) == 1:
            print(f"  - First 5 observation values: {observations[:5]}")
        elif len(observations.shape) == 2:
            print(f"  - First observation (first 5 values): {observations[0, :5]}")
        
        return observations
    except Exception as e:
        print(f"✗ Failed to reset environment: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_market_step(env):
    """Test stepping the Market environment"""
    print("\n" + "=" * 60)
    print("Testing Market Environment Step")
    print("=" * 60)
    
    if env is None:
        print("✗ Cannot test step - environment not available")
        return
    
    try:
        import numpy as np
        
        # Generate a random action
        action_space = env.single_action_space
        print(f"Action space: {action_space}")
        
        if env.num_agents == 1:
            # Single agent: sample from action space
            if hasattr(action_space, 'sample'):
                actions = action_space.sample()
            else:
                # MultiDiscrete: sample each dimension
                actions = np.array([
                    np.random.randint(0, action_space.nvec[0]),
                    np.random.randint(0, action_space.nvec[1])
                ])
            print(f"Sampled action: {actions}")
        else:
            # Multiple agents: sample for each
            actions = np.array([
                [np.random.randint(0, action_space.nvec[0]),
                 np.random.randint(0, action_space.nvec[1])]
                for _ in range(env.num_agents)
            ])
            print(f"Sampled actions shape: {actions.shape}")
        
        print("Calling env.step()...")
        observations, rewards, terminals, truncations, info = env.step(actions)
        
        print("✓ Successfully stepped environment")
        print(f"  - Observations shape: {observations.shape}")
        print(f"  - Rewards shape: {rewards.shape}")
        print(f"  - Terminals shape: {terminals.shape}")
        print(f"  - Truncations shape: {truncations.shape}")
        print(f"  - Info: {info}")
        
        if len(rewards.shape) == 1:
            print(f"  - Rewards: {rewards}")
        else:
            print(f"  - First reward: {rewards[0]}")
        
        return True
    except Exception as e:
        print(f"✗ Failed to step environment: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_market_multiple_steps(env, num_steps=5):
    """Test multiple steps of the Market environment"""
    print("\n" + "=" * 60)
    print(f"Testing Market Environment - {num_steps} Steps")
    print("=" * 60)
    
    if env is None:
        print("✗ Cannot test multiple steps - environment not available")
        return
    
    try:
        import numpy as np
        
        # Reset first
        env.reset(seed=42)
        
        action_space = env.single_action_space
        total_reward = 0
        
        for step in range(num_steps):
            # Sample action
            if env.num_agents == 1:
                if hasattr(action_space, 'sample'):
                    actions = action_space.sample()
                else:
                    actions = np.array([
                        np.random.randint(0, action_space.nvec[0]),
                        np.random.randint(0, action_space.nvec[1])
                    ])
            else:
                actions = np.array([
                    [np.random.randint(0, action_space.nvec[0]),
                     np.random.randint(0, action_space.nvec[1])]
                    for _ in range(env.num_agents)
                ])
            
            observations, rewards, terminals, truncations, info = env.step(actions)
            
            if env.num_agents == 1:
                reward = rewards[0] if isinstance(rewards, np.ndarray) else rewards
            else:
                reward = rewards[0]
            
            total_reward += reward
            
            print(f"Step {step + 1}: reward={reward:.6f}, terminal={terminals[0] if env.num_agents == 1 else terminals[0]}")
            
            # Reset if terminal
            if terminals[0] if env.num_agents == 1 else terminals[0]:
                print(f"  Episode terminated, resetting...")
                env.reset(seed=42)
        
        print(f"\n✓ Completed {num_steps} steps")
        print(f"  Total reward: {total_reward:.6f}")
        print(f"  Average reward: {total_reward/num_steps:.6f}")
        
        return True
    except Exception as e:
        print(f"✗ Failed to run multiple steps: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function"""
    print("\n" + "=" * 60)
    print("Market Environment Test Suite")
    print("=" * 60)
    print(f"Python version: {sys.version}")
    print(f"Working directory: {os.getcwd()}")
    print(f"Script location: {Path(__file__).absolute()}")
    
    # Test import
    Market = test_market_import()
    
    # Test initialization
    env = test_market_initialization(Market)
    
    # Test reset
    observations = test_market_reset(env)
    
    # Test step
    if observations is not None:
        test_market_step(env)
    
    # Test multiple steps
    if env is not None:
        test_market_multiple_steps(env, num_steps=5)
    
    # Cleanup
    if env is not None:
        try:
            print("\n" + "=" * 60)
            print("Cleaning up environment...")
            env.close()
            print("✓ Environment closed successfully")
        except Exception as e:
            print(f"✗ Error closing environment: {e}")
    
    print("\n" + "=" * 60)
    print("Test Suite Complete")
    print("=" * 60)

if __name__ == "__main__":
    main()

