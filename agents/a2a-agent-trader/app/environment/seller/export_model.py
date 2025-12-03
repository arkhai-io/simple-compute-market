#!/usr/bin/env python3
"""Export trained model checkpoints to TorchScript format"""

import sys
import os
import argparse
from pathlib import Path
import traceback

# Pufferlib imports
try:
    import pufferlib.pufferl as pufferl
    import pufferlib.vector as vec
    import torch
    import torch.nn as nn
except ImportError as e:
    print(f"Error: Required dependencies not installed: {e}")
    print("Install with: uv sync")
    sys.exit(1)

# Add the app directory to the path
app_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(app_dir))

# Don't import Market directly - we'll load it manually to avoid triggering app.__init__

# Module-level Market class and env_creator (needed for pickling in multiprocessing)
_Market = None

def _load_market_class():
    """Load Market class - needed for env_creator"""
    global _Market
    if _Market is not None:
        return _Market
    
    env_dir = Path(__file__).parent
    
    # Import binding module directly from .so file
    binding_so = list(env_dir.glob("binding*.so"))
    if not binding_so:
        raise ImportError("Binding .so file not found. Run: make build-market-env")
    
    # Load binding module
    import importlib.util
    binding_spec = importlib.util.spec_from_file_location("binding", binding_so[0])
    binding_module = importlib.util.module_from_spec(binding_spec)
    binding_spec.loader.exec_module(binding_module)
    
    # Create a mock module for 'environment.seller' package to satisfy relative imports
    import types as types_module
    environment_module = types_module.ModuleType('environment')
    seller_module = types_module.ModuleType('environment.seller')
    seller_module.binding = binding_module
    sys.modules['environment'] = environment_module
    sys.modules['environment.seller'] = seller_module
    sys.modules['environment.seller.binding'] = binding_module
    
    # Now import market.py
    market_path = env_dir / "market.py"
    spec = importlib.util.spec_from_file_location("environment.seller.market", market_path)
    market_module = importlib.util.module_from_spec(spec)
    market_module.__package__ = "environment.seller"
    spec.loader.exec_module(market_module)
    
    _Market = market_module.Market
    return _Market

def env_creator(**kwargs):
    """Create Market environment instance - module level for pickling"""
    Market = _load_market_class()
    return Market(**kwargs)


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


def extract_model_from_policy(policy):
    """Extract the actual neural network model from pufferlib policy wrapper"""
    # Pufferlib policies typically wrap the model in various attributes
    # Try common attribute names in order of likelihood
    candidates = ['policy', 'network', 'model', 'actor', 'critic', 'net']
    
    for attr_name in candidates:
        if hasattr(policy, attr_name):
            attr = getattr(policy, attr_name)
            if isinstance(attr, nn.Module):
                return attr
    
    # If policy itself is a model
    if isinstance(policy, nn.Module):
        return policy
    
    # Try to find any nn.Module attribute (excluding common non-model attributes)
    exclude_attrs = {'__class__', '__dict__', '__module__', '__weakref__', 'device', 'dtype'}
    for attr_name in dir(policy):
        if attr_name.startswith('_') or attr_name in exclude_attrs:
            continue
        try:
            attr = getattr(policy, attr_name)
            if isinstance(attr, nn.Module):
                return attr
        except (AttributeError, TypeError):
            continue
    
    # Last resort: check if policy has a forward method and is callable
    if hasattr(policy, 'forward') and callable(policy.forward):
        return policy
    
    raise ValueError(
        f"Could not find neural network model in policy object of type {type(policy)}. "
        f"Available attributes: {[a for a in dir(policy) if not a.startswith('__')]}"
    )


def export_torchscript(
    checkpoint_path: str,
    out_path: str = None,
    observation_shape: tuple = (14,),
    device: str = "cpu",
    use_script: bool = False,
):
    """
    Export a trained model checkpoint to TorchScript format.
    
    Args:
        checkpoint_path: Path to the model checkpoint (.pt file)
        out_path: Output path for TorchScript file (default: checkpoint_path with .ts extension)
        observation_shape: Shape of observation input (default: (14,) for Market environment)
        device: Device to use for export ('cpu' or 'cuda')
        use_script: If True, use torch.jit.script instead of torch.jit.trace
    """
    checkpoint_path = Path(checkpoint_path)
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")
    
    if out_path is None:
        out_path = checkpoint_path.with_suffix('.ts')
    else:
        out_path = Path(out_path)
    
    print("=" * 60)
    print("Exporting Model to TorchScript")
    print("=" * 60)
    print(f"Checkpoint: {checkpoint_path}")
    print(f"Output: {out_path}")
    print(f"Device: {device}")
    print(f"Method: {'script' if use_script else 'trace'}")
    print()
    
    # Load Market class (module-level, cached) - same as train.py
    print("Loading Market environment class...")
    try:
        _load_market_class()
        print("✓ Market class loaded successfully")
    except Exception as e:
        print(f"✗ Failed to load Market class: {e}")
        traceback.print_exc()
        return False
    
    print("Environment creator ready...")
    
    # Create args for loading policy - match the structure from default.ini
    args = {
        'package': None,
        'env_name': None,
        'policy_name': 'Policy',
        'rnn_name': 'Recurrent',  # Change to None if not using RNN
        'load_model_path': str(checkpoint_path),
        'base': {
            'package': None,
            'env_name': None,
            'policy_name': 'Policy',
            'rnn_name': 'Recurrent',
        },
    }
    
    # Register seller environment module so pufferlib can import it
    # pufferlib tries to import 'pufferlib.environments.{package}' when package is set
    # We'll register it as 'pufferlib.environments.seller' to match our directory structure
    print("Registering seller environment module for pufferlib...")
    import types
    
    # Get Market class
    MarketClass = _load_market_class()
    
    # Get Policy and Recurrent classes from pufferlib.ocean (these are the standard implementations)
    try:
        import pufferlib.ocean as ocean
        PolicyClass = ocean.Policy
        RecurrentClass = ocean.Recurrent
    except (ImportError, AttributeError) as e:
        print(f"✗ Failed to import Policy/Recurrent from pufferlib.ocean: {e}")
        traceback.print_exc()
        return False
    
    # Create seller environment module structure that pufferlib expects
    # Register as 'pufferlib.environments.seller' to match our directory structure
    env_module = types.ModuleType('pufferlib.environments.seller')
    env_module.torch = types.ModuleType('torch')
    env_module.torch.Policy = PolicyClass
    env_module.torch.Recurrent = RecurrentClass
    env_module.Market = MarketClass  # Include Market class for completeness
    
    # Register the module
    sys.modules['pufferlib.environments.seller'] = env_module
    
    # Also register the None module as fallback (in case package=None is used)
    # But prefer using 'seller' as package name
    none_module = types.ModuleType('pufferlib.environments.None')
    none_module.torch = types.ModuleType('torch')
    none_module.torch.Policy = PolicyClass
    none_module.torch.Recurrent = RecurrentClass
    sys.modules['pufferlib.environments.None'] = none_module
    
    try:
        # Use the exact same approach as train.py
        # train.py creates a NEW policy first, then loads checkpoint via trainer
        print("Creating policy architecture (same as train.py)...")
        
        # Create args matching train.py exactly - but WITHOUT load_model_path
        # We'll load checkpoint via trainer instead
        base_params = {
            'package': None,
            'env_name': None,
            'policy_name': 'Policy',
            'rnn_name': 'Recurrent',
        }
        
        # Load config files like train.py does
        import configparser
        env_dir = Path(__file__).parent
        default_config_path = env_dir / "default.ini"
        market_config_path = env_dir / "market.ini"
        
        # Parse both config files - default.ini first, then market.ini overrides
        config = configparser.ConfigParser()
        config.read([str(default_config_path), str(market_config_path)])
        
        # Parse config sections like train.py
        base_params = {}
        if 'base' in config:
            base_params = dict(config['base'])
        
        # Parse train params and convert types
        train_params = {}
        if 'train' in config:
            for key, value in config['train'].items():
                # Handle boolean strings
                if key in ['torch_deterministic', 'cpu_offload', 'compile', 'compile_fullgraph', 'anneal_lr', 'use_rnn']:
                    train_params[key] = value.lower() in ('true', '1', 'yes', 'on')
                # Handle numbers
                elif isinstance(value, str):
                    value_clean = value.replace('_', '').strip()
                    if value_clean.replace('.', '').replace('-', '').replace('e', '').replace('E', '').replace('+', '').isdigit():
                        try:
                            if '.' in value_clean or 'e' in value_clean.lower():
                                train_params[key] = float(value_clean)
                            else:
                                train_params[key] = int(value_clean)
                        except ValueError:
                            train_params[key] = value
                    else:
                        train_params[key] = value
                else:
                    train_params[key] = value
        
        # Override device from function parameter
        train_params['device'] = device
        
        # Parse other sections
        env_kwargs = {}
        if 'env' in config:
            for key, value in config['env'].items():
                try:
                    if '.' in value or 'e' in value.lower():
                        env_kwargs[key] = float(value)
                    else:
                        env_kwargs[key] = int(value)
                except ValueError:
                    env_kwargs[key] = value
        
        vec_config = {}
        if 'vec' in config:
            for key, value in config['vec'].items():
                if key == 'backend':
                    vec_config[key] = value
                elif key == 'zero_copy':
                    vec_config[key] = value.lower() in ('true', '1', 'yes', 'on')
                elif value == 'auto':
                    vec_config[key] = 'auto'
                else:
                    try:
                        vec_config[key] = int(value)
                    except ValueError:
                        vec_config[key] = value
        
        # Set defaults if not in config
        vec_config.setdefault('num_envs', 1)
        train_params.setdefault('torch_deterministic', True)
        train_params.setdefault('seed', 42)
        train_params.setdefault('batch_size', 'auto')
        train_params.setdefault('total_timesteps', 1)
        
        policy_params = {}
        if 'policy' in config:
            policy_params = dict(config['policy'])
        
        rnn_params = {}
        if 'rnn' in config:
            rnn_params = dict(config['rnn'])
        
        # Update base_params with actual values from config
        # Use 'seller' as package to match our registered module
        base_params = {
            'package': 'seller',  # Use 'seller' to match registered module
            'env_name': base_params.get('env_name', None),
            'policy_name': base_params.get('policy_name', 'Policy'),
            'rnn_name': base_params.get('rnn_name', 'Recurrent'),
        }
        
        # Create vectorized environment like train.py does
        print("Creating vectorized environment...")
        vec_num_envs = vec_config.get('num_envs', 1)
        vec_backend = vec_config.get('backend', 'Serial')
        seed = train_params.get('seed', 42)
        
        # Use appropriate backend from config
        if vec_backend == 'Serial':
            backend_class = vec.Serial
        elif vec_backend == 'Multiprocessing':
            backend_class = vec.Multiprocessing
        else:
            # Default to Serial for local environments
            backend_class = vec.Serial
        
        vecenv = vec.make(
            env_creator,
            env_kwargs=env_kwargs,
            num_envs=vec_num_envs,
            seed=seed,
            backend=backend_class,
        )
        print("✓ Vectorized environment created")
        
        # Use 'seller' as package name to match our registered module
        args = {
            'package': 'seller',  # Use 'seller' instead of None to match registered module
            'env_name': None,
            'policy_name': base_params['policy_name'],
            'rnn_name': base_params['rnn_name'],
            'load_id': None,
            'load_model_path': str(checkpoint_path),  # Load checkpoint directly via load_policy
            'base': base_params,
            'env': env_kwargs,
            'vec': vec_config,
            'policy': policy_params,
            'rnn': rnn_params,
            'train': train_params,
        }
        
        # Load policy with checkpoint - pufferlib's load_policy handles load_model_path
        policy = pufferl.load_policy(args, vecenv)
        print("✓ Policy loaded with checkpoint weights")
        
    except Exception as e:
        print(f"✗ Failed to load policy: {e}")
        traceback.print_exc()
        return False
    finally:
        # Clean up - remove registered modules (optional, but good practice)
        # Note: We keep them registered in case they're needed elsewhere in the session
        pass
    
    # Extract the actual model
    print("Extracting neural network model...")
    try:
        model = extract_model_from_policy(policy)
        print(f"✓ Model extracted: {type(model).__name__}")
    except Exception as e:
        print(f"✗ Failed to extract model: {e}")
        traceback.print_exc()
        return False
    
    # Set model to eval mode
    model.eval()
    
    # Create example input based on observation space
    # Market environment has shape (14,) observation space
    print(f"Creating example input with shape {observation_shape}...")
    example_input = torch.zeros((1,) + observation_shape, dtype=torch.float32)
    
    # Move to device if needed
    if device == "cuda" and torch.cuda.is_available():
        model = model.to(device)
        example_input = example_input.to(device)
        print(f"✓ Moved model and input to {device}")
    elif device == "cuda":
        print("⚠ CUDA requested but not available, using CPU")
        device = "cpu"
    
    # Export to TorchScript
    print(f"Exporting to TorchScript ({'script' if use_script else 'trace'})...")
    try:
        with torch.no_grad():
            if use_script:
                # Use torch.jit.script for more flexible models (handles control flow)
                scripted = torch.jit.script(model)
            else:
                # Use torch.jit.trace for simpler models (faster, but requires example input)
                scripted = torch.jit.trace(model, example_input)
        
        # Save the scripted model
        scripted.save(str(out_path))
        print(f"✓ TorchScript model saved to: {out_path}")
        
        # Verify the exported model can be loaded
        print("Verifying exported model...")
        loaded_model = torch.jit.load(str(out_path))
        test_output = loaded_model(example_input)
        print(f"✓ Verification successful - output shape: {test_output.shape if hasattr(test_output, 'shape') else 'N/A'}")
        
        return True
        
    except Exception as e:
        print(f"✗ Export failed: {e}")
        traceback.print_exc()
        return False
    finally:
        vecenv.close()


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Export trained model checkpoints to TorchScript format"
    )
    parser.add_argument(
        "checkpoint",
        type=str,
        nargs="?",
        default=None,
        help="Path to model checkpoint (.pt file). If not provided, uses latest checkpoint from experiments/"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output path for TorchScript file (default: checkpoint path with .ts extension)"
    )
    parser.add_argument(
        "--obs-shape",
        type=int,
        nargs="+",
        default=[14],
        help="Observation shape (default: [14] for Market environment)"
    )
    parser.add_argument(
        "--device",
        type=str,
        choices=["cpu", "cuda"],
        default="cpu",
        help="Device to use for export (default: cpu)"
    )
    parser.add_argument(
        "--script",
        action="store_true",
        help="Use torch.jit.script instead of torch.jit.trace (better for models with control flow)"
    )
    
    args = parser.parse_args()
    
    # Find checkpoint if not provided
    checkpoint_path = args.checkpoint
    if checkpoint_path is None:
        print("No checkpoint provided, looking for latest checkpoint...")
        checkpoint_path = find_latest_checkpoint()
        if checkpoint_path is None:
            print("✗ No checkpoint found in experiments/ directory")
            print("Please provide a checkpoint path or ensure experiments/ contains .pt files")
            sys.exit(1)
        print(f"Found latest checkpoint: {checkpoint_path}")
    
    # Convert obs_shape to tuple
    obs_shape = tuple(args.obs_shape)
    
    # Export the model
    success = export_torchscript(
        checkpoint_path=checkpoint_path,
        out_path=args.output,
        observation_shape=obs_shape,
        device=args.device,
        use_script=args.script,
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

