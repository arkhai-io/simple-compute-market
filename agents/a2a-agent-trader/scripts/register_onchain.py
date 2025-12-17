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

from app.utils.registry.onchain_registration import register_onchain_from_env, build_agent_card_url, build_registration_file_url
from app.utils.registry.blockchain_utils import build_erc8004_canonical_id


def update_env_file(env_file: Path, agent_id: int) -> bool:
    """
    Update .env file with ONCHAIN_AGENT_ID.
    
    Returns:
        True if file was updated, False otherwise
    """
    if not env_file.exists():
        return False
    
    content = env_file.read_text()
    lines = content.split('\n')
    
    # Check if ONCHAIN_AGENT_ID exists and if it needs updating
    current_agent_id = None
    updated = False
    for i, line in enumerate(lines):
        if line.startswith('ONCHAIN_AGENT_ID='):
            current_agent_id = line.split('=', 1)[1].strip()
            if current_agent_id != str(agent_id):
                lines[i] = f'ONCHAIN_AGENT_ID={agent_id}'
                updated = True
            break
    
    # Add if missing
    if current_agent_id is None:
        lines.append(f'ONCHAIN_AGENT_ID={agent_id}')
        updated = True
    
    # Write back if changed
    if updated:
        env_file.write_text('\n'.join(lines))
    
    return updated


async def main():
    """Register agent on-chain and output the agent ID."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', default='.env', help='Path to .env file')
    parser.add_argument('--no-update-env', action='store_true', help='Skip automatic .env file update (useful for CI/CD)')
    args, _ = parser.parse_known_args()
    
    # Load environment variables from .env file if available
    try:
        from dotenv import load_dotenv
        load_dotenv(args.env_file)
    except ImportError:
        # dotenv not available, rely on environment variables from Makefile or shell
        pass
    
    # Read config for display
    base_url_override = os.getenv("BASE_URL_OVERRIDE", "http://localhost:8000")
    chain_id = int(os.getenv("CHAIN_ID", "1337"))
    identity_registry_address = os.getenv("IDENTITY_REGISTRY_ADDRESS")
    agent_wallet_address = os.getenv("AGENT_WALLET_ADDRESS")
    chain_rpc_url = os.getenv("CHAIN_RPC_URL")
    onchain_agent_id = os.getenv("ONCHAIN_AGENT_ID")
    
    # Build URLs for display
    agent_card_url = build_agent_card_url(base_url_override)
    registration_file_url = build_registration_file_url(base_url_override)
    
    # Display registration info
    print("=" * 70)
    print("🔗 On-Chain Registration")
    print("=" * 70)
    print(f"Agent Card URL: {agent_card_url}")
    print(f"Registration File URL (tokenURI): {registration_file_url}")
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
        result = await register_onchain_from_env(
            base_url=base_url_override,
            chain_id=chain_id,
            explicit_agent_id=onchain_agent_id
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
            if not args.no_update_env:
                updated = update_env_file(env_file, numeric_agent_id)
                if updated:
                    print(f"✅ Auto-updated .env with ONCHAIN_AGENT_ID={numeric_agent_id}")
                elif env_file.exists():
                    print(f"✓ .env already has ONCHAIN_AGENT_ID={numeric_agent_id}")
                else:
                    print(f"💡 Tip: Add this to your .env file:")
                    print(f"   ONCHAIN_AGENT_ID={numeric_agent_id}")
            else:
                print("ℹ️  Skipped .env update (--no-update-env flag set)")
            
            return 0
        else:
            print("❌ Registration failed - no result returned")
            return 1
            
    except ValueError as e:
        # Missing env vars or validation errors
        print(f"❌ Error: {e}")
        print("\nPlease set the required environment variables in your .env file or environment.")
        return 1
    except Exception as e:
        print(f"❌ Registration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

