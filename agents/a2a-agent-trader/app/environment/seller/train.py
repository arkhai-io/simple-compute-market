#!/usr/bin/env python3
"""Train the Market environment using pufferlib"""

import sys
import os
import configparser
import importlib.util
import traceback
from pathlib import Path

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

# Module-level Market class (needed for pickling in multiprocessing)
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
    binding_spec = importlib.util.spec_from_file_location("binding", binding_so[0])
    binding_module = importlib.util.module_from_spec(binding_spec)
    binding_spec.loader.exec_module(binding_module)
    
    # Create a mock module for 'environment.seller' package to satisfy relative imports
    environment_module = type(sys)('environment')
    seller_module = type(sys)('environment.seller')
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

def validate_config(config, required_sections=None, required_keys=None):
    """Validate that required config sections and keys exist"""
    if required_sections:
        missing_sections = [s for s in required_sections if s not in config]
        if missing_sections:
            raise ValueError(f"Missing required config sections: {missing_sections}")
    
    if required_keys:
        for section, keys in required_keys.items():
            if section in config:
                missing_keys = [k for k in keys if k not in config[section]]
                if missing_keys:
                    raise ValueError(f"Missing required keys in [{section}]: {missing_keys}")

def main():
    """Main training function"""
    if pufferl is None:
        print("Error: pufferlib is not installed")
        print("Install with: uv sync")
        sys.exit(1)
    
    try:
        # Load Market class (module-level, cached)
        _load_market_class()
        
        # Get device from environment variable
        device = os.environ.get('PUFFERLIB_DEVICE', 'cpu')
        
        # Get config paths - use both default.ini and market.ini
        env_dir = Path(__file__).parent
        default_config_path = env_dir / "default.ini"
        market_config_path = env_dir / "market.ini"
        
        print(f"Using default config: {default_config_path}")
        print(f"Using market config: {market_config_path}")
        print(f"Using device: {device}")
        print("\nNote: Using pufferlib Python API for local environment")
        print("For full CLI support, register the environment with pufferlib's ocean package\n")
        
        # Parse both config files - default.ini first, then market.ini overrides
        config = configparser.ConfigParser()
        config.read([str(default_config_path), str(market_config_path)])
        
        # Validate required config sections exist
        validate_config(config, required_sections=['train'])
        validate_config(config, required_keys={
            'train': ['total_timesteps', 'batch_size']
        })
        
        # Parse ALL config sections from INI files first
        # Parse base config
        base_params = {}
        if 'base' in config:
            base_params = dict(config['base'])
        
        # Parse vec config from INI files (convert values to proper types)
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
        
        # Parse policy config
        policy_params = {}
        if 'policy' in config:
            policy_params = dict(config['policy'])
        
        # Parse rnn config
        rnn_params = {}
        if 'rnn' in config:
            rnn_params = dict(config['rnn'])
        
        # Parse training parameters from INI files - get ALL values
        train_params = {}
        if 'train' in config:
            for key, value in config['train'].items():
                # Store as string first, we'll convert types later
                train_params[key] = value
        
        # Convert training params to proper types
        for key, value in list(train_params.items()):
            # Handle boolean strings first
            if key in ['torch_deterministic', 'cpu_offload', 'compile', 'compile_fullgraph', 'anneal_lr', 'use_rnn']:
                train_params[key] = str(value).lower() in ('true', '1', 'yes', 'on')
            # Handle numbers with underscores (e.g., 100_000_000)
            elif isinstance(value, str):
                value_clean = value.replace('_', '').strip()
                # Check if it's a number (including scientific notation)
                if value_clean.replace('.', '').replace('-', '').replace('e', '').replace('E', '').replace('+', '').isdigit():
                    try:
                        if '.' in value_clean or 'e' in value_clean.lower():
                            train_params[key] = float(value_clean)
                        else:
                            train_params[key] = int(value_clean)
                    except ValueError:
                        pass  # Keep as string if conversion fails
        
        # Override device from environment variable (takes precedence)
        train_params['device'] = device
        
        # Set use_rnn based on rnn_name if not explicitly set in train section
        if 'use_rnn' not in train_params:
            rnn_name = base_params.get('rnn_name')
            train_params['use_rnn'] = rnn_name and str(rnn_name).lower() != 'none'
        
        # Extract environment parameters from config
        env_kwargs = {}
        if 'env' in config:
            for key, value in config['env'].items():
                try:
                    # Try to convert to appropriate type
                    if '.' in value or 'e' in value.lower():
                        env_kwargs[key] = float(value)
                    else:
                        env_kwargs[key] = int(value)
                except ValueError:
                    env_kwargs[key] = value
        
        # Get values from parsed configs for vecenv creation
        vec_num_envs = vec_config.get('num_envs', 2)  # From default.ini or market.ini
        vec_backend = vec_config.get('backend', 'Multiprocessing')  # From default.ini or market.ini
        seed = train_params.get('seed', 42)  # From train section
        
        # Create vectorized environment
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
        
        # Create args dict for load_policy - use values from INI files only
        # WandbLogger expects wandb_project, wandb_group, and tag at top level
        args = {
            'package': base_params.get('package'),
            'env_name': base_params.get('env_name'),
            'policy_name': base_params.get('policy_name'),
            'rnn_name': base_params.get('rnn_name'),
            'load_id': None,
            'load_model_path': None,
            'wandb_project': train_params.get('project', 'puffer_market'),  # For WandbLogger
            'wandb_group': train_params.get('name', 'market_training'),  # For WandbLogger (uses name as group)
            'tag': wandb_tag if (wandb_tag := os.environ.get('WANDB_TAG')) and wandb_tag.strip() else None,  # Optional tag from environment (None if empty)
            'base': base_params,
            'env': env_kwargs,  # From [env] section in INI files
            'vec': vec_config,  # From [vec] section in INI files
            'policy': policy_params,  # From [policy] section in INI files
            'rnn': rnn_params,  # From [rnn] section in INI files
            'train': train_params,  # From [train] section in INI files
        }
        
        # Load policy
        policy = pufferl.load_policy(args, vecenv)
        
        # Create logger - support wandb if configured
        logger = None
        use_wandb = os.environ.get('USE_WANDB', 'false').lower() in ('true', '1', 'yes', 'on')
        
        if use_wandb:
            try:
                # Use pufferlib's WandbLogger - it expects args dict as first parameter
                # The args dict should contain project and name from train_params
                logger = pufferl.WandbLogger(args, load_id=None)
                print(f"✓ Wandb logger initialized: project={train_params.get('project', 'puffer_market')}, name={train_params.get('name', 'market_training')}")
            except Exception as e:
                print(f"Warning: Failed to initialize wandb logger: {e}")
                print("Continuing without wandb logging...")
                traceback.print_exc()
                logger = None
        
        # Create trainer - PuffeRL expects config dict with train params at top level
        # PuffeRL accesses config['torch_deterministic'] directly, not config['train']['torch_deterministic']
        # So we need to merge train_params into the top level
        full_config = train_params.copy()  # Start with all train params at top level
        
        # Calculate expected batch_size if it's set to 'auto'
        # Pufferlib calculates batch_size as: total_agents * bptt_horizon
        # where total_agents = env.num_envs * vec.num_envs
        batch_size = full_config.get('batch_size', 'auto')
        if batch_size == 'auto':
            # Get values needed for batch_size calculation
            env_num_envs = env_kwargs.get('num_envs', 1)  # From [env] section
            vec_num_envs = vec_config.get('num_envs', 1)  # From [vec] section
            bptt_horizon = full_config.get('bptt_horizon', 64)  # From [train] section
            
            # Calculate expected batch_size
            total_agents = env_num_envs * vec_num_envs
            expected_batch_size = total_agents * bptt_horizon
            
            # Get total_timesteps for validation
            total_timesteps = full_config.get('total_timesteps', 0)
            
            # Validate: total_epochs = total_timesteps // batch_size
            # If batch_size > total_timesteps, total_epochs will be 0, causing division by zero
            if total_timesteps > 0 and expected_batch_size > total_timesteps:
                # Set batch_size to a reasonable value that ensures total_epochs > 0
                # Use at least 2 epochs, so batch_size <= total_timesteps // 2
                safe_batch_size = max(1, total_timesteps // 2)
                full_config['batch_size'] = safe_batch_size
                print(f"Warning: Calculated batch_size ({expected_batch_size}) > total_timesteps ({total_timesteps})")
                print(f"Setting batch_size to {safe_batch_size} to ensure total_epochs > 0")
                print(f"  (env.num_envs={env_num_envs}, vec.num_envs={vec_num_envs}, bptt_horizon={bptt_horizon})")
            else:
                # batch_size is reasonable, let pufferlib calculate it
                full_config['batch_size'] = 'auto'
        elif isinstance(batch_size, str) and batch_size != 'auto':
            # Convert string batch_size to int if it's a number
            try:
                full_config['batch_size'] = int(batch_size.replace('_', ''))
            except ValueError:
                # Keep as string if conversion fails
                pass
        
        full_config['env'] = env_kwargs  # From [env] section
        full_config['vec'] = vec_config  # From [vec] section
        # Add optional sections from INI files if they exist
        if policy_params:
            full_config['policy'] = policy_params  # From [policy] section
        if rnn_params:
            full_config['rnn'] = rnn_params  # From [rnn] section
        
        trainer = pufferl.PuffeRL(full_config, vecenv, policy, logger)
        
        # Train
        print("Starting training...")
        trainer.print_dashboard()

        # Get checkpoint interval from config (for saving model checkpoints)
        checkpoint_interval = train_params.get('checkpoint_interval', 200)
        # Logging interval for wandb (more frequent than checkpoints)
        log_interval = train_params.get('log_interval', 10)  # Log to wandb every N iterations
        total_timesteps = train_params.get('total_timesteps', 0)
        
        print(f"Checkpoint interval: {checkpoint_interval} iterations")
        print(f"Wandb log interval: {log_interval} iterations")
        print(f"Total timesteps target: {total_timesteps:,}")
        print("Training will save checkpoints periodically...\n")
        
        iteration = 0
        # Calculate steps per iteration (batch_size from config)
        batch_size = full_config.get('batch_size', 1)
        if isinstance(batch_size, str) and batch_size == 'auto':
            # If auto, calculate it
            env_num_envs = env_kwargs.get('num_envs', 1)
            vec_num_envs = vec_config.get('num_envs', 1)
            bptt_horizon = full_config.get('bptt_horizon', 64)
            batch_size = env_num_envs * vec_num_envs * bptt_horizon
        
        steps_per_iteration = batch_size
        current_steps = 0
        
        try:
            while True:
                trainer.evaluate()
                trainer.train()
                trainer.mean_and_log()
                
                iteration += 1
                current_steps += steps_per_iteration
                
                # Log to wandb more frequently (every log_interval iterations)
                if logger and iteration % log_interval == 0:
                    trainer.print_dashboard()
                
                # Save checkpoint periodically (every checkpoint_interval iterations)
                if iteration % checkpoint_interval == 0:
                    print(f"\n[Iteration {iteration}] Steps: {current_steps:,}/{total_timesteps:,} Saving checkpoint...")
                    trainer.save_checkpoint()
                    if logger:
                        print(f"Checkpoint saved and logged to wandb")
                    print()
                
                # Check if we've reached total_timesteps
                if total_timesteps > 0 and current_steps >= total_timesteps:
                    print(f"\n[Training Complete] Reached {current_steps:,} steps (target: {total_timesteps:,})")
                    break
        except KeyboardInterrupt:
            print("\nTraining interrupted by user")
        finally:
            # Final save and close
            print(f"\n[Final] Saving checkpoint at iteration {iteration}...")
            trainer.save_checkpoint()
            trainer.close()
            if logger:
                logger.close()
            print("\nTraining complete!")
        
    except ImportError as e:
        print(f"Error importing pufferlib: {e}")
        print("Make sure pufferlib is installed: uv sync")
        sys.exit(1)
    except Exception as e:
        print(f"Training error: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

