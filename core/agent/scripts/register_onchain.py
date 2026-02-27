#!/usr/bin/env python3
"""
Standalone script to register an agent on-chain before starting the agent server.

Usage:
    python core/agent/scripts/register_onchain.py
    # Or via make:
    make register

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
from urllib.parse import urlparse

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.registry.onchain_registration import (
    register_onchain_from_env,
    build_agent_card_url,
    build_registration_file_url,
)
from app.utils.registry.blockchain_utils import build_erc8004_canonical_id
from app.utils.zerotier import (
    await_base_url_resolution,
    join_zerotier_network,
    get_zerotier_node_id,
    BaseUrlResolutionError,
)


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


def update_env_file_zerotier_ip(env_file: Path, zerotier_ip: str) -> bool:
    """
    Update .env file with ZEROTIER_IP.

    Returns:
        True if file was updated, False otherwise
    """
    if not zerotier_ip:
        return False

    if not env_file.exists():
        # Create a new file with just ZEROTIER_IP
        env_file.write_text(f"ZEROTIER_IP={zerotier_ip}\n")
        return True

    content = env_file.read_text()
    lines = content.split("\n")

    current_ip = None
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("ZEROTIER_IP="):
            current_ip = line.split("=", 1)[1].strip()
            if current_ip != zerotier_ip:
                lines[i] = f"ZEROTIER_IP={zerotier_ip}"
                updated = True
            break

    if current_ip is None:
        lines.append(f"ZEROTIER_IP={zerotier_ip}")
        updated = True

    if updated:
        env_file.write_text("\n".join(lines))

    return updated


def update_env_file_base_url_override(env_file: Path, base_url: str) -> bool:
    """
    Update .env file with BASE_URL_OVERRIDE.

    Returns:
        True if file was updated, False otherwise
    """
    if not base_url:
        return False

    if not env_file.exists():
        env_file.write_text(f"BASE_URL_OVERRIDE={base_url}\n")
        return True

    content = env_file.read_text()
    lines = content.split("\n")

    current_value = None
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("BASE_URL_OVERRIDE="):
            current_value = line.split("=", 1)[1].strip()
            if current_value != base_url:
                lines[i] = f"BASE_URL_OVERRIDE={base_url}"
                updated = True
            break

    if current_value is None:
        lines.append(f"BASE_URL_OVERRIDE={base_url}")
        updated = True

    if updated:
        env_file.write_text("\n".join(lines))

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

    # Path to the env file we will read/update
    env_file = Path(args.env_file)

    # Read config for display
    base_url_override_env = os.getenv("BASE_URL_OVERRIDE")
    zerotier_network = os.getenv("ZEROTIER_NETWORK")
    port = int(os.getenv("PORT", "8000"))  # Get port from env or default to 8000
    chain_id = int(os.getenv("CHAIN_ID", "1337"))
    identity_registry_address = os.getenv("IDENTITY_REGISTRY_ADDRESS")
    agent_wallet_address = os.getenv("AGENT_WALLET_ADDRESS")
    chain_rpc_url = os.getenv("CHAIN_RPC_URL")
    onchain_agent_id = os.getenv("ONCHAIN_AGENT_ID")

    # Determine final base URL, possibly using ZeroTier
    use_zerotier = bool(zerotier_network)
    resolved_base_url: str

    if use_zerotier:
        # Choose a template that always includes {ZEROTIER_IP}
        if base_url_override_env and "{ZEROTIER_IP}" in base_url_override_env:
            base_url_template = base_url_override_env
        else:
            # Extract port from BASE_URL_OVERRIDE if provided, otherwise use PORT env var or default
            template_port = port
            if base_url_override_env:
                # Try to extract port from existing BASE_URL_OVERRIDE
                parsed_existing = urlparse(base_url_override_env)
                if parsed_existing.port is not None:
                    template_port = parsed_existing.port
            # Default template with the determined port
            base_url_template = f"http://{{ZEROTIER_IP}}:{template_port}/"

        print("ZeroTier network detected. Ensuring network is joined before registration...")
        joined = join_zerotier_network(zerotier_network)
        if not joined:
            print(f"❌ Failed to join ZeroTier network {zerotier_network}.")
            return 1

        node_id = get_zerotier_node_id()
        if node_id:
            print(f"ZeroTier node ID: {node_id}")
            print("Share this node ID with the Market Controller for authorization.")
        else:
            print("⚠️  Unable to determine ZeroTier node ID (zerotier-cli info failed).")

        print("Waiting for ZeroTier IP assignment...")
        try:
            resolved_base_url = await await_base_url_resolution(
                base_url_template,
                zerotier_network,
                wait_timeout=120.0,
            )
        except BaseUrlResolutionError as exc:
            print(f"❌ Failed to resolve BASE_URL_OVERRIDE with ZeroTier IP: {exc}")
            return 1

        # Extract IP from resolved URL and store as ZEROTIER_IP in .env
        parsed = urlparse(resolved_base_url)
        zerotier_ip = parsed.hostname
        if zerotier_ip:
            ip_updated = update_env_file_zerotier_ip(env_file, zerotier_ip)
            if ip_updated:
                print(f"✅ Saved ZeroTier IP to {env_file}: ZEROTIER_IP={zerotier_ip}")
            else:
                print(f"✓ .env already has ZEROTIER_IP={zerotier_ip}")
        else:
            print("⚠️  Could not extract ZeroTier IP from resolved URL; skipping ZEROTIER_IP env update.")

        # Persist the resolved BASE_URL_OVERRIDE (no placeholder) back into .env
        base_url_updated = update_env_file_base_url_override(env_file, resolved_base_url)
        if base_url_updated:
            print(f"✅ Saved BASE_URL_OVERRIDE to {env_file}: {resolved_base_url}")
        else:
            print(f"✓ .env already has BASE_URL_OVERRIDE={resolved_base_url}")
    else:
        # No ZeroTier configured; fall back to existing env or localhost default with PORT
        if base_url_override_env:
            resolved_base_url = base_url_override_env
            if "{ZEROTIER_IP}" in base_url_override_env:
                print(
                    "⚠️  BASE_URL_OVERRIDE contains {ZEROTIER_IP} but ZEROTIER_NETWORK is not set. "
                    "Proceeding without ZeroTier resolution."
                )
        else:
            # Use PORT env var or default to 8000
            resolved_base_url = f"http://localhost:{port}"

    # Build URLs for display using resolved base URL
    agent_card_url = build_agent_card_url(resolved_base_url)
    registration_file_url = build_registration_file_url(resolved_base_url)
    
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
            base_url=resolved_base_url,
            chain_id=chain_id,
            explicit_agent_id=onchain_agent_id,
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
