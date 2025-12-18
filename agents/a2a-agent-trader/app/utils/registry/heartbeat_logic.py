"""
Heartbeat functionality for agent registration.
"""
import asyncio
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    HAS_ETH_ACCOUNT = True
except ImportError:
    HAS_ETH_ACCOUNT = False

# Try to use aiohttp for async HTTP, fallback to urllib
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

logger = logging.getLogger(__name__)

# Heartbeat interval (seconds) - should be less than Indexer's heartbeat_ttl_secs
HEARTBEAT_INTERVAL = 30  # Send heartbeat every 30 seconds


async def send_heartbeat(
    agent_id: str, 
    indexer_url: str, 
    private_key: Optional[str] = None,
    owner_address: Optional[str] = None
) -> bool:
    """
    Send heartbeat to Indexer to indicate agent is alive.
    
    Signs the heartbeat with the agent's private key to authenticate the request.
    
    Args:
        agent_id: Agent ID (from Indexer registration)
        indexer_url: Indexer API URL
        private_key: Private key for signing heartbeat (optional if agent has no owner)
        owner_address: Owner wallet address (optional, used for logging)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        timestamp = int(time.time())
        
        # Prepare request body with signature if private key is available
        body = {}
        if private_key:
            if not HAS_ETH_ACCOUNT:
                logger.warning("[HEARTBEAT] eth_account not available, sending heartbeat without signature")
            else:
                try:
                    # Construct message to sign
                    message = f"heartbeat:{agent_id}:{timestamp}"
                    
                    # Sign message using EIP-191 personal sign format
                    message_hash = encode_defunct(text=message)
                    signed_message = Account.sign_message(message_hash, private_key)
                    signature = signed_message.signature.hex()
                    
                    body = {
                        "signature": signature,
                        "timestamp": timestamp
                    }
                except Exception as e:
                    logger.warning(f"[HEARTBEAT] Failed to sign heartbeat: {e}")
        
        # URL-encode the agent_id for use in path parameter (handles canonical IDs with colons)
        encoded_agent_id = urllib.parse.quote(agent_id, safe='')
        
        if HAS_AIOHTTP:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{indexer_url.rstrip('/')}/agents/{encoded_agent_id}/heartbeat",
                        json=body,
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        if response.status == 200:
                            return True
                        elif response.status == 401:
                            logger.warning(f"[HEARTBEAT] Authentication failed (401) - signature may be invalid for agent {agent_id}")
                            return False
                        elif response.status == 404:
                            logger.warning(f"[HEARTBEAT] Agent not found (404) - agent {agent_id} may not be indexed yet")
                            return False
                        else:
                            # Try to read error response body for more context
                            try:
                                error_body = await response.text()
                                logger.warning(f"[HEARTBEAT] HTTP {response.status} error for agent {agent_id}: {error_body[:200]}")
                            except:
                                logger.warning(f"[HEARTBEAT] HTTP {response.status} error for agent {agent_id}")
                            return False
            except aiohttp.ClientError as e:
                logger.warning(f"[HEARTBEAT] Network error sending heartbeat for agent {agent_id}: {e}")
                return False
            except asyncio.TimeoutError:
                logger.warning(f"[HEARTBEAT] Timeout sending heartbeat to {indexer_url} for agent {agent_id}")
                return False
        else:
            req = urllib.request.Request(
                f"{indexer_url.rstrip('/')}/agents/{encoded_agent_id}/heartbeat",
                data=json.dumps(body).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        return True
                    else:
                        logger.warning(f"[HEARTBEAT] HTTP {response.status} error for agent {agent_id}")
                        return False
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    logger.warning(f"[HEARTBEAT] Authentication failed (401) - signature may be invalid for agent {agent_id}")
                elif e.code == 404:
                    logger.warning(f"[HEARTBEAT] Agent not found (404) - agent {agent_id} may not be indexed yet")
                else:
                    logger.warning(f"[HEARTBEAT] HTTP {e.code} error for agent {agent_id}: {e.reason}")
                return False
            except urllib.error.URLError as e:
                logger.warning(f"[HEARTBEAT] Network error sending heartbeat for agent {agent_id}: {e.reason}")
                return False
            except Exception as e:
                logger.warning(f"[HEARTBEAT] Failed to send heartbeat for agent {agent_id} (urllib): {type(e).__name__}: {e}")
                return False
    except Exception as e:
        logger.warning(f"[HEARTBEAT] Unexpected error sending heartbeat for agent {agent_id}: {type(e).__name__}: {e}")
    return False


async def heartbeat_loop(
    agent_id: Optional[str], 
    indexer_url: str,
    private_key: Optional[str] = None,
    owner_address: Optional[str] = None
):
    """
    Background task to periodically send heartbeats to Indexer.
    
    Args:
        agent_id: Agent ID from registration (None if not registered)
        indexer_url: Indexer API URL
        private_key: Private key for signing heartbeats (optional)
        owner_address: Owner wallet address (optional, for logging)
    """
    if agent_id is None:
        logger.debug("[HEARTBEAT] No agent ID, skipping heartbeat loop")
        return
    
    logger.info(f"[HEARTBEAT] Starting heartbeat loop for agent {agent_id}")
    if private_key:
        logger.debug("[HEARTBEAT] Heartbeats will be signed for authentication")
    else:
        logger.warning("[HEARTBEAT] No private key provided - heartbeats will be unsigned (may fail if Indexer requires auth)")
    
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            success = await send_heartbeat(agent_id, indexer_url, private_key, owner_address)
            if success:
                logger.debug(f"[HEARTBEAT] Heartbeat sent successfully")
        except asyncio.CancelledError:
            logger.info("[HEARTBEAT] Heartbeat loop cancelled")
            break
        except Exception as e:
            logger.error(f"[HEARTBEAT] Error in heartbeat loop: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)  # Wait before retrying

