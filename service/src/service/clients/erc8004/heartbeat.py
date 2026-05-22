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

from .signing import sign_eip191

# Try to use aiohttp for async HTTP, fallback to urllib
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

logger = logging.getLogger(__name__)

# Heartbeat interval (seconds) - should be less than Indexer's heartbeat_ttl_secs
HEARTBEAT_INTERVAL = 30  # Send heartbeat every 30 seconds
HEARTBEAT_DELAY = 5


async def send_heartbeat(
    agent_id: str,
    indexer_url: str,
    private_key: Optional[str] = None,
    bearer_token: Optional[str] = None,
) -> bool:
    """
    Send heartbeat to Indexer to indicate agent is alive.

    Signs the heartbeat with the agent's private key to authenticate the request.

    Args:
        agent_id: Agent ID (from Indexer registration)
        indexer_url: Indexer API URL
        private_key: Private key for signing heartbeat (optional if agent has no owner)
        bearer_token: Optional shared-secret token sent as Authorization: Bearer.
            Required by private registries that gate writes behind a token.

    Returns:
        True if successful, False otherwise
    """
    try:
        timestamp = int(time.time())

        # Prepare request body with signature if private key is available
        body = {}
        if private_key:
            message = f"heartbeat:{agent_id}:{timestamp}"
            signature = sign_eip191(private_key, message)
            if signature:
                body = {"signature": signature, "timestamp": timestamp}
            else:
                logger.warning("[HEARTBEAT] Signing unavailable, sending heartbeat without signature")

        # URL-encode the agent_id for use in path parameter (handles canonical IDs with colons)
        encoded_agent_id = urllib.parse.quote(agent_id, safe='')

        headers: dict[str, str] = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        if HAS_AIOHTTP:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{indexer_url.rstrip('/')}/agents/{encoded_agent_id}/heartbeat",
                        json=body,
                        headers=headers or None,
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
            urllib_headers = {'Content-Type': 'application/json'}
            if bearer_token:
                urllib_headers['Authorization'] = f"Bearer {bearer_token}"
            req = urllib.request.Request(
                f"{indexer_url.rstrip('/')}/agents/{encoded_agent_id}/heartbeat",
                data=json.dumps(body).encode('utf-8'),
                headers=urllib_headers,
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
    bearer_token: Optional[str] = None,
):
    """
    Background task to periodically send heartbeats to Indexer.

    Args:
        agent_id: Agent ID from registration (None if not registered)
        indexer_url: Indexer API URL
        private_key: Private key for signing heartbeats (optional)
        bearer_token: Optional shared-secret token for the Authorization header.
    """
    if agent_id is None:
        logger.debug("[HEARTBEAT] No agent ID, skipping heartbeat loop")
        return

    logger.info(f"[HEARTBEAT] Starting heartbeat loop for agent {agent_id}")
    if private_key:
        logger.debug("[HEARTBEAT] Heartbeats will be signed for authentication")
    else:
        logger.warning("[HEARTBEAT] No private key provided - heartbeats will be unsigned (may fail if Indexer requires auth)")

    # Send the first heartbeat immediately so the registry has the agent
    # in its DB before the seller's first publish/listing call. The
    # registry's chain event-sync runs every 60s; without an upfront
    # heartbeat, anything the seller does in the first minute after a
    # fresh restart hits a 404 from the registry's HTTP API.
    try:
        success = await send_heartbeat(agent_id, indexer_url, private_key, bearer_token)
        if success:
            logger.info(f"[HEARTBEAT] Initial heartbeat sent for agent {agent_id}")
    except Exception as e:
        logger.warning(f"[HEARTBEAT] Initial heartbeat failed: {e}")

    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            success = await send_heartbeat(agent_id, indexer_url, private_key, bearer_token)
            if success:
                logger.info(f"[HEARTBEAT] Heartbeat sent successfully for agent {agent_id}")
        except asyncio.CancelledError:
            logger.info("[HEARTBEAT] Heartbeat loop cancelled")
            break
        except Exception as e:
            logger.error(f"[HEARTBEAT] Error in heartbeat loop: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)  # Wait before retrying


async def start_agent_heartbeat(config: dict) -> Optional[str]:
    """
    Start agent heartbeat loops, one per configured indexer URL.

    Args:
        config: dict with keys: indexer_urls (list[str]) or legacy
                indexer_url (str), identity_registry_address,
                agent_wallet_address, onchain_agent_id, chain_rpc_url,
                agent_priv_key, indexer_auth (dict[str, str] mapping
                indexer URL -> bearer token for private registries).
                With multiple URLs, one independent heartbeat task is
                spawned per registry so a slow registry can't gate
                heartbeats to the others.
    """
    indexer_urls = config.get("indexer_urls")
    if not indexer_urls:
        legacy = config.get("indexer_url")
        indexer_urls = [legacy] if legacy else []
    elif isinstance(indexer_urls, str):
        # Defensive: caller passed a single string under the new key.
        indexer_urls = [indexer_urls]
    indexer_urls = [u for u in indexer_urls if u]

    identity_registry_address = config.get("identity_registry_address")
    agent_wallet_address = config.get("agent_wallet_address")
    onchain_agent_id = config.get("onchain_agent_id")
    chain_rpc_url = config.get("chain_rpc_url")
    agent_priv_key = config.get("agent_priv_key")
    indexer_auth = config.get("indexer_auth") or {}

    if not indexer_urls or not identity_registry_address:
        return None

    if not agent_wallet_address:
        logger.error("[HEARTBEAT] No wallet address configured")
        return None

    if not onchain_agent_id:
        logger.warning("[HEARTBEAT] ONCHAIN_AGENT_ID not set. Run 'make register' first.")
        return None

    try:
        agent_id = int(onchain_agent_id)
    except ValueError:
        logger.error(f"[HEARTBEAT] Invalid ONCHAIN_AGENT_ID: {onchain_agent_id}")
        return None

    await asyncio.sleep(HEARTBEAT_DELAY)

    chain_id = 1337  # Default
    try:
        from web3 import Web3
        from web3.providers import HTTPProvider
        from .blockchain import rpc_url_for_http_provider, build_erc8004_canonical_id
        if chain_rpc_url:
            http_url = rpc_url_for_http_provider(chain_rpc_url)
            w3 = Web3(HTTPProvider(http_url, request_kwargs={"timeout": 5}))
            chain_id = w3.eth.chain_id
    except Exception:
        from .blockchain import build_erc8004_canonical_id

    from .blockchain import build_erc8004_canonical_id
    canonical_id = build_erc8004_canonical_id(
        chain_id=chain_id,
        identity_registry=identity_registry_address,
        agent_id=agent_id,
    )

    for url in indexer_urls:
        token = indexer_auth.get(url) if isinstance(indexer_auth, dict) else None
        asyncio.create_task(heartbeat_loop(canonical_id, url, agent_priv_key, token))
    logger.info(
        "[HEARTBEAT] Started heartbeat for %s across %d registry/registries: %s",
        canonical_id, len(indexer_urls), indexer_urls,
    )
    return agent_wallet_address
