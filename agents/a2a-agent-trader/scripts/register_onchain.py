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

from app.utils.registry.onchain_registration import register_onchain
from app.utils.registry.blockchain_utils import build_erc8004_canonical_id
from app.agent_registration import build_agent_card_url


async def main():
    """Register agent on-chain and output the agent ID."""
    # Load environment variables from .env file if available
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', default='.env', help='Path to .env file')
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
            indexer_url=None  # Not needed for standalone registration
        )
        
        if result:
            tx_hash, numeric_agent_id = result
            
            # Build canonical ID
            canonical_id = build_erc8004_canonical_id(
                chain_id=chain_id,
                identity_registry=identity_registry_address,
                agent_id=numeric_agent_id
            )
            
            print()
            print("=" * 70)
            print("✅ Registration Successful!")
            print("=" * 70)
            print(f"Numeric Agent ID: {numeric_agent_id}")
            print(f"Canonical Agent ID: {canonical_id}")
            if tx_hash:
                print(f"Transaction Hash: {tx_hash}")
            else:
                print("(Using existing registration - no new transaction)")
            print("=" * 70)
            print()
            
            # Optionally update .env file
            env_file = Path(".env")
            if env_file.exists():
                print("💡 Tip: Add this to your .env file:")
                print(f"   ONCHAIN_AGENT_ID={numeric_agent_id}")
                print()
                print("Or update it automatically? (y/n): ", end="")
                try:
                    response = input().strip().lower()
                    if response == 'y':
                        # Read current .env
                        content = env_file.read_text()
                        
                        # Update or add ONCHAIN_AGENT_ID
                        lines = content.split('\n')
                        updated = False
                        for i, line in enumerate(lines):
                            if line.startswith('ONCHAIN_AGENT_ID='):
                                lines[i] = f'ONCHAIN_AGENT_ID={numeric_agent_id}'
                                updated = True
                                break
                        
                        if not updated:
                            lines.append(f'ONCHAIN_AGENT_ID={numeric_agent_id}')
                        
                        env_file.write_text('\n'.join(lines))
                        print(f"✅ Updated .env with ONCHAIN_AGENT_ID={numeric_agent_id}")
                except (KeyboardInterrupt, EOFError):
                    print("\n(Skipped .env update)")
            
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

