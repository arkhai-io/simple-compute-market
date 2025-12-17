#!/usr/bin/env python3
"""
Standalone script to register an agent on-chain before starting the agent server.

Usage:
    python scripts/register_onchain.py
    # Or via make:
    make register-onchain

The script will:
1. Read configuration from .env file
2. Register the agent on-chain via ERC-8004 IdentityRegistry
3. Output the numeric agent ID and canonical ID
4. Optionally update .env with ONCHAIN_AGENT_ID
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.registry.onchain_registration import register_onchain, build_agent_card_url
from app.utils.registry.blockchain_utils import build_erc8004_canonical_id


async def main():
    """Register agent on-chain and output the agent ID."""
    # Load environment variables from .env file if available
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', default='.env', help='Path to .env file')
    parser.add_argument('--no-update-env', action='store_true', help='Skip automatic .env file update (useful for CI/CD)')
    args, _ = parser.parse_known_args()
    
    try:
        from dotenv import load_dotenv
        load_dotenv(args.env_file)
    except ImportError:
        # dotenv not available, rely on environment variables from Makefile or shell
        pass
    
    # Required environment variables
    agent_priv_key = os.getenv("AGENT_PRIV_KEY")
    chain_rpc_url = os.getenv("CHAIN_RPC_URL")
    identity_registry_address = os.getenv("IDENTITY_REGISTRY_ADDRESS")
    agent_wallet_address = os.getenv("AGENT_WALLET_ADDRESS")
    base_url_override = os.getenv("BASE_URL_OVERRIDE", "http://localhost:8000")
    chain_id = int(os.getenv("CHAIN_ID", "1337"))
    onchain_agent_id = os.getenv("ONCHAIN_AGENT_ID")  # Optional - for existing agents
    
    # Get agent name with validation (for on-chain metadata)
    try:
        from app.utils.config import get_agent_id
        agent_name = get_agent_id()  # Validates and returns default if not set
    except (ImportError, ValueError) as e:
        # Fallback if config not available or validation fails
        agent_name = os.getenv("AGENT_ID")
        if agent_name:
            print(f"⚠️  Warning: AGENT_ID validation failed: {e}")
            print(f"   Using AGENT_ID as-is: {agent_name}")
    
    # Validate required variables
    missing = []
    if not agent_priv_key:
        missing.append("AGENT_PRIV_KEY")
    if not chain_rpc_url:
        missing.append("CHAIN_RPC_URL")
    if not identity_registry_address:
        missing.append("IDENTITY_REGISTRY_ADDRESS")
    if not agent_wallet_address:
        missing.append("AGENT_WALLET_ADDRESS")
    
    if missing:
        print("❌ Error: Missing required environment variables:")
        for var in missing:
            print(f"   - {var}")
        print("\nPlease set these in your .env file or environment.")
        sys.exit(1)
    
    # Build agent card URL
    agent_card_url = build_agent_card_url(base_url_override)
    
    print("=" * 70)
    print("🔗 On-Chain Registration")
    print("=" * 70)
    print(f"Agent Card URL: {agent_card_url}")
    print(f"Identity Registry: {identity_registry_address}")
    print(f"Chain RPC: {chain_rpc_url}")
    print(f"Chain ID: {chain_id}")
    print(f"Wallet Address: {agent_wallet_address}")
    if onchain_agent_id:
        print(f"Existing Agent ID: {onchain_agent_id}")
    print("=" * 70)
    print()
    
    # Register on-chain
    print("Registering agent on-chain...")
    try:
        result = await register_onchain(
            agent_card_url=agent_card_url,
            private_key=agent_priv_key,
            rpc_url=chain_rpc_url,
            contract_address=identity_registry_address,
            owner_address=agent_wallet_address,
            explicit_agent_id=onchain_agent_id,
            indexer_url=None,  # Not needed for standalone registration
            agent_name=agent_name  # Pass AGENT_ID env var for agentName metadata
        )
        
        if result:
            tx_hash, numeric_agent_id, updates_dict = result
            
            # Build canonical ID
            canonical_id = build_erc8004_canonical_id(
                chain_id=chain_id,
                identity_registry=identity_registry_address,
                agent_id=numeric_agent_id
            )
            
            print()
            print("=" * 70)
            
            # Determine status and show appropriate message
            if updates_dict is None:
                # New registration
                print("✅ New Registration Successful!")
                status_msg = "New agent registered on-chain"
            elif updates_dict.get('no_changes', False):
                # No changes detected
                print("✓ No Changes Detected")
                status_msg = "Agent already up to date"
            else:
                # Updates were made
                print("✅ Registration Updated!")
                status_msg = "Existing agent updated"
                changes = []
                if updates_dict.get('token_uri_updated'):
                    changes.append("Token URI")
                if updates_dict.get('metadata_updated'):
                    changes.extend(updates_dict['metadata_updated'])
                if changes:
                    print(f"  Changes: {', '.join(changes)}")
            
            print("=" * 70)
            print(f"Status: {status_msg}")
            print(f"Numeric Agent ID: {numeric_agent_id}")
            print(f"Canonical Agent ID: {canonical_id}")
            if tx_hash:
                print(f"Transaction Hash: {tx_hash}")
            else:
                print("Transaction: None (no changes made)")
            print("=" * 70)
            print()
            
            # Auto-update .env file (unless --no-update-env flag is set)
            env_file = Path(args.env_file)
            should_update_env = not args.no_update_env
            
            if should_update_env and env_file.exists():
                # Read current .env
                content = env_file.read_text()
                lines = content.split('\n')
                
                # Check if ONCHAIN_AGENT_ID exists and if it needs updating
                current_agent_id = None
                updated = False
                for i, line in enumerate(lines):
                    if line.startswith('ONCHAIN_AGENT_ID='):
                        current_agent_id = line.split('=', 1)[1].strip()
                        if current_agent_id != str(numeric_agent_id):
                            lines[i] = f'ONCHAIN_AGENT_ID={numeric_agent_id}'
                            updated = True
                        break
                
                # Add if missing
                if current_agent_id is None:
                    lines.append(f'ONCHAIN_AGENT_ID={numeric_agent_id}')
                    updated = True
                
                # Write back if changed
                if updated:
                    env_file.write_text('\n'.join(lines))
                    print(f"✅ Auto-updated .env with ONCHAIN_AGENT_ID={numeric_agent_id}")
                else:
                    print(f"✓ .env already has ONCHAIN_AGENT_ID={numeric_agent_id}")
            elif args.no_update_env:
                print("ℹ️  Skipped .env update (--no-update-env flag set)")
            elif not env_file.exists():
                print(f"💡 Tip: Add this to your .env file:")
                print(f"   ONCHAIN_AGENT_ID={numeric_agent_id}")
            
            return 0
        else:
            print("❌ Registration failed - no result returned")
            return 1
            
    except Exception as e:
        print(f"❌ Registration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

