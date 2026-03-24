import asyncio
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from sqlalchemy.orm.attributes import flag_modified
from src.contracts.identity_registry import IdentityRegistryClient
from src.types import NetworkConfig, AgentMetadata
from src.db.models import Agent, AgentMetadataEntry
from src.db.database import SessionLocal
from src.config import settings

logger = logging.getLogger(__name__)


class EventSyncService:
    def __init__(self, network_config: NetworkConfig):
        self.identity_registry = IdentityRegistryClient(network_config)
        self.is_running = False
        self.sync_task: Optional[asyncio.Task] = None
        self.last_synced_block = 0

    async def start(self, sync_interval_ms: int = 60000):
        """Start the event sync service"""
        if self.is_running:
            logger.info("[EventSync] Service already running")
            return

        self.is_running = True
        logger.info("[EventSync] Starting event sync service...")

        # Initial sync to catch up on missed events
        await self.sync_from_start()

        # Set up periodic sync
        self.sync_task = asyncio.create_task(self._periodic_sync(sync_interval_ms))

    async def stop(self):
        """Stop the event sync service"""
        if not self.is_running:
            return

        self.is_running = False
        if self.sync_task:
            self.sync_task.cancel()
            try:
                await self.sync_task
            except asyncio.CancelledError:
                pass
        logger.info("[EventSync] Event sync service stopped")

    async def _periodic_sync(self, interval_ms: int):
        """Periodic sync loop"""
        while self.is_running:
            try:
                await asyncio.sleep(interval_ms / 1000)
                await self.sync_latest()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[EventSync] Error during periodic sync: {e}")

    async def sync_from_start(self):
        """Sync all events from contract deployment"""
        logger.info("[EventSync] Starting full sync from contract deployment...")
        
        try:
            current_block = self.identity_registry.w3.eth.block_number
            
            # Start from a reasonable block (e.g., 1000 blocks before current)
            start_block = max(0, current_block - 1000)
            
            await self.sync_block_range(start_block, current_block)
            self.last_synced_block = current_block
            
            logger.info(f"[EventSync] Full sync completed up to block {current_block}")
        except Exception as e:
            logger.error(f"[EventSync] Error during full sync: {e}")
            raise

    async def sync_latest(self):
        """Sync latest events since last sync"""
        try:
            current_block = self.identity_registry.w3.eth.block_number
            
            if self.last_synced_block == 0:
                await self.sync_from_start()
                return

            if current_block > self.last_synced_block:
                await self.sync_block_range(self.last_synced_block + 1, current_block)
                self.last_synced_block = current_block
                logger.info(f"[EventSync] Synced up to block {current_block}")
        except Exception as e:
            logger.error(f"[EventSync] Error during latest sync: {e}")
            raise

    async def sync_block_range(self, from_block: int, to_block: int):
        """Sync events in a block range"""
        db = SessionLocal()
        try:
            # Process in smaller chunks to avoid RPC limits and filter expiration
            # Many RPC providers have limits on block range queries
            chunk_size = 500  # Reduced from 1000 to avoid filter/query limits
            current_from = from_block

            while current_from <= to_block:
                current_to = min(current_from + chunk_size, to_block)

                try:
                    # Get Registered events (official ERC-8004 event name)
                    registered_events = self.identity_registry.get_past_agent_registered_events(
                        current_from, current_to
                    )

                    for event in registered_events:
                        try:
                            # Safely access event arguments
                            if not hasattr(event, 'args') or not event.args:
                                logger.warning(f"[EventSync] Event missing args: {event}")
                                continue
                            
                            # Extract agentId from event args (handles different web3.py versions)
                            agent_id_value = self._extract_event_arg(event.args, 'agentId', 'agent_id')
                            
                            # CRITICAL: Use 'is None' not truthy check because agentId 0 is valid!
                            if agent_id_value is None:
                                logger.warning(f"[EventSync] Could not extract agentId from event: {event}")
                                continue
                            
                            onchain_agent_id = int(agent_id_value)
                            chain_id = settings.chain_id
                            identity_registry = settings.identity_registry_address
                            
                            # Build ERC-8004 canonical ID: eip155:{chainId}:{identityRegistry}:{agentId}
                            # Normalize address to lowercase (Ethereum addresses are case-insensitive)
                            canonical_id = f"eip155:{chain_id}:{identity_registry.lower()}:{onchain_agent_id}"

                            # Fetch on-chain token URI and owner for this agent
                            token_uri = None
                            owner_address = None
                            try:
                                token_uri = self.identity_registry.get_token_uri(onchain_agent_id)
                            except Exception as e:
                                logger.warning(f"[EventSync] Could not fetch token URI for agent {onchain_agent_id}: {e}")
                            try:
                                owner_address = self.identity_registry.get_owner(onchain_agent_id)
                            except Exception as e:
                                logger.warning(f"[EventSync] Could not fetch owner for agent {onchain_agent_id}: {e}")

                            # Lookup existing agent by canonical ID or by (chain_id, identity_registry, onchain_agent_id) tuple
                            existing = db.query(Agent).filter(Agent.agent_id == canonical_id).first()
                            
                            # Fallback: lookup by tuple (for compatibility with agent-initiated registration)
                            # Normalize registry address to lowercase for comparison
                            normalized_registry = identity_registry.lower()
                            if not existing:
                                existing = db.query(Agent).filter(
                                    and_(
                                        Agent.chain_id == chain_id,
                                        Agent.identity_registry == normalized_registry,
                                        Agent.onchain_agent_id == onchain_agent_id
                                    )
                                ).first()

                            if existing:
                                # Update existing agent record with on-chain details
                                # Normalize identity_registry to lowercase (Ethereum addresses are case-insensitive)
                                normalized_registry = identity_registry.lower()
                                existing.agent_id = canonical_id  # Ensure canonical ID is set
                                existing.chain_id = chain_id
                                existing.identity_registry = normalized_registry
                                existing.onchain_agent_id = onchain_agent_id
                                existing.registry_address = normalized_registry  # Keep for backward compatibility
                                if token_uri:
                                    existing.token_uri = token_uri
                                if owner_address:
                                    existing.owner = owner_address
                                
                                # Update metadata with on-chain agent ID and ensure ERC-8004 format
                                metadata = dict(existing.metadata_json or {})
                                # Use camelCase for A2A/ERC-8004 JSON (migrate legacy key if present)
                                if "onchainAgentId" in metadata:
                                    # Migrate legacy key to camelCase
                                    metadata["onChainAgentId"] = metadata.pop("onchainAgentId")
                                else:
                                    metadata["onChainAgentId"] = onchain_agent_id  # Store as int

                                # Ensure metadata has ERC-8004 structure (category, type, etc.)
                                # If missing, try to infer from existing metadata or use defaults
                                if "category" not in metadata:
                                    metadata["category"] = metadata.get("label.category", "compute")
                                if "type" not in metadata:
                                    metadata["type"] = metadata.get("label.type", "trader")

                                existing.metadata_json = metadata
                                flag_modified(existing, "metadata_json")

                                db.commit()
                                block_number = getattr(event, 'blockNumber', getattr(event, 'block_number', None))
                                logger.info(
                                    f"[EventSync] Linked on-chain agent {onchain_agent_id} "
                                    f"to existing agent {canonical_id} from block {block_number}"
                                )
                            else:
                                # No matching off-chain registration; create a new agent row
                                # Normalize identity_registry to lowercase (Ethereum addresses are case-insensitive)
                                normalized_registry = identity_registry.lower()
                                agent = Agent(
                                    agent_id=canonical_id,  # Canonical ID is the primary identifier
                                    chain_id=chain_id,
                                    identity_registry=normalized_registry,
                                    onchain_agent_id=onchain_agent_id,
                                    registry_address=normalized_registry,  # Keep for backward compatibility
                                    owner=owner_address,
                                    token_uri=token_uri,
                                    metadata_json={
                                        "onChainAgentId": onchain_agent_id,  # camelCase for A2A/ERC-8004 JSON
                                        "category": "compute",  # Default
                                        "type": "trader",  # Default
                                    },
                                    health_status="healthy",
                                )
                                db.add(agent)
                                db.commit()
                                # Expire all objects to ensure subsequent queries see the newly committed agent
                                db.expire_all()
                                
                                block_number = getattr(event, 'blockNumber', getattr(event, 'block_number', None))
                                logger.info(f"[EventSync] Registered new on-chain-only agent {canonical_id} from block {block_number}")
                        except Exception as e:
                            logger.error(f"[EventSync] Error processing Registered event: {e}")
                            logger.debug(f"[EventSync] Event data: {event}")
                            continue

                    # Get MetadataSet events (official ERC-8004 event name)
                    metadata_events = self.identity_registry.get_past_metadata_set_events(
                        current_from, current_to
                    )

                    for event in metadata_events:
                        try:
                            # Safely access event arguments
                            if not hasattr(event, 'args') or not event.args:
                                logger.warning(f"[EventSync] MetadataUpdated event missing args: {event}")
                                continue
                            
                            # Extract event args (handles different web3.py versions)
                            agent_id_value = self._extract_event_arg(event.args, 'agentId', 'agent_id')
                            key_value = self._extract_event_arg(event.args, 'key')
                            
                            # CRITICAL: Use 'is None' not truthy check because agentId 0 is valid!
                            if agent_id_value is None or key_value is None:
                                logger.warning(f"[EventSync] Could not extract agentId/key from MetadataSet event: {event}")
                                continue
                            
                            onchain_agent_id = int(agent_id_value)
                            key = str(key_value)
                            
                            # Build canonical ID to lookup agent
                            chain_id = settings.chain_id
                            identity_registry = settings.identity_registry_address
                            # Normalize address to lowercase (Ethereum addresses are case-insensitive)
                            normalized_registry = identity_registry.lower()
                            canonical_id = f"eip155:{chain_id}:{normalized_registry}:{onchain_agent_id}"

                            # Get the metadata value from contract (returns bytes)
                            try:
                                value_bytes = self.identity_registry.get_metadata(onchain_agent_id, key)
                                
                                # Decode bytes to string if it's UTF-8 encoded
                                try:
                                    value = value_bytes.decode('utf-8')
                                except UnicodeDecodeError:
                                    # If not UTF-8, store as hex string
                                    value = value_bytes.hex()
                            except Exception as e:
                                logger.error(f"[EventSync] Error getting metadata for agent {canonical_id}, key {key}: {e}")
                                continue

                            # Find agent by canonical ID or by tuple
                            # Use db.refresh() or expire_all() to ensure we see newly committed agents
                            agent = db.query(Agent).filter(Agent.agent_id == canonical_id).first()
                            
                            if not agent:
                                # Fallback: lookup by tuple (normalize registry address)
                                agent = db.query(Agent).filter(
                                    and_(
                                        Agent.chain_id == chain_id,
                                        Agent.identity_registry == normalized_registry,
                                        Agent.onchain_agent_id == onchain_agent_id
                                    )
                                ).first()
                            
                            if not agent:
                                # Try one more time with a fresh query after expiring session cache
                                db.expire_all()
                                agent = db.query(Agent).filter(Agent.agent_id == canonical_id).first()
                                if not agent:
                                    agent = db.query(Agent).filter(
                                        and_(
                                            Agent.chain_id == chain_id,
                                            Agent.identity_registry == normalized_registry,
                                            Agent.onchain_agent_id == onchain_agent_id
                                        )
                                    ).first()
                            
                            if not agent:
                                # Debug: Check what agents exist with similar IDs
                                similar_agents = db.query(Agent).filter(
                                    Agent.onchain_agent_id == onchain_agent_id
                                ).all()
                                if similar_agents:
                                    logger.warning(
                                        f"[EventSync] Agent {canonical_id} not found for metadata update. "
                                        f"Found {len(similar_agents)} agents with same onchain_agent_id: "
                                        f"{[a.agent_id for a in similar_agents]}"
                                    )
                                else:
                                    logger.warning(
                                        f"[EventSync] Agent {canonical_id} not found for metadata update. "
                                        f"No agents found with onchain_agent_id={onchain_agent_id}"
                                    )
                                continue

                            # Update or insert metadata entry (using canonical ID for FK)
                            existing_metadata = db.query(AgentMetadataEntry).filter(
                                and_(
                                    AgentMetadataEntry.agent_id == canonical_id,
                                    AgentMetadataEntry.key == key
                                )
                            ).first()

                            if existing_metadata:
                                existing_metadata.value = value
                            else:
                                metadata_entry = AgentMetadataEntry(
                                    agent_id=canonical_id,  # Use canonical ID for FK
                                    key=key,
                                    value=value,
                                )
                                db.add(metadata_entry)

                            # Update agent's metadata JSON
                            current_metadata = dict(agent.metadata_json or {})
                            current_metadata[key] = value
                            agent.metadata_json = current_metadata
                            flag_modified(agent, "metadata_json")

                            db.commit()
                            logger.info(f"[EventSync] Updated metadata for agent {canonical_id}, key: {key}")
                        except Exception as e:
                            logger.error(f"[EventSync] Error processing MetadataSet event: {e}")
                            logger.debug(f"[EventSync] Event data: {event}")
                            db.rollback()
                            continue

                    # Get UriUpdated events (official ERC-8004 event name)
                    uri_updated_events = self.identity_registry.get_past_uri_updated_events(
                        current_from, current_to
                    )

                    for event in uri_updated_events:
                        try:
                            # Safely access event arguments
                            if not hasattr(event, 'args') or not event.args:
                                logger.warning(f"[EventSync] UriUpdated event missing args: {event}")
                                continue
                            
                            # Extract event args (handles different web3.py versions)
                            agent_id_value = self._extract_event_arg(event.args, 'agentId', 'agent_id')
                            new_uri_value = self._extract_event_arg(event.args, 'newUri', 'new_uri')
                            
                            if agent_id_value is None or new_uri_value is None:
                                logger.warning(f"[EventSync] Could not extract agentId/newUri from UriUpdated event: {event}")
                                continue
                            
                            onchain_agent_id = int(agent_id_value)
                            new_uri = str(new_uri_value)
                            
                            # Build canonical ID to lookup agent
                            chain_id = settings.chain_id
                            identity_registry = settings.identity_registry_address
                            # Normalize address to lowercase (Ethereum addresses are case-insensitive)
                            normalized_registry = identity_registry.lower()
                            canonical_id = f"eip155:{chain_id}:{normalized_registry}:{onchain_agent_id}"

                            # Find agent by canonical ID or by tuple
                            agent = db.query(Agent).filter(Agent.agent_id == canonical_id).first()
                            
                            if not agent:
                                # Fallback: lookup by tuple (normalize registry address)
                                agent = db.query(Agent).filter(
                                    and_(
                                        Agent.chain_id == chain_id,
                                        Agent.identity_registry == normalized_registry,
                                        Agent.onchain_agent_id == onchain_agent_id
                                    )
                                ).first()
                            
                            if not agent:
                                # Try one more time with a fresh query after expiring session cache
                                db.expire_all()
                                agent = db.query(Agent).filter(Agent.agent_id == canonical_id).first()
                                if not agent:
                                    agent = db.query(Agent).filter(
                                        and_(
                                            Agent.chain_id == chain_id,
                                            Agent.identity_registry == normalized_registry,
                                            Agent.onchain_agent_id == onchain_agent_id
                                        )
                                    ).first()
                            
                            if not agent:
                                logger.warning(f"[EventSync] Agent {canonical_id} not found for URI update")
                                continue

                            # Update agent's token URI
                            agent.token_uri = new_uri
                            db.commit()
                            
                            block_number = getattr(event, 'blockNumber', getattr(event, 'block_number', None))
                            logger.info(
                                f"[EventSync] Updated token URI for agent {canonical_id} to {new_uri} from block {block_number}"
                            )
                        except Exception as e:
                            logger.error(f"[EventSync] Error processing UriUpdated event: {e}")
                            logger.debug(f"[EventSync] Event data: {event}")
                            continue

                except Exception as e:
                    logger.error(f"[EventSync] Error syncing blocks {current_from}-{current_to}: {e}")
                    db.rollback()

                current_from = current_to + 1
        finally:
            db.close()

    def _extract_event_arg(self, args, *possible_keys):
        """Extract event argument by trying multiple key names (handles different web3.py versions)"""
        if not args:
            return None
        
        # Try attribute access first
        for key in possible_keys:
            if hasattr(args, key):
                return getattr(args, key)
        
        # Try dict access
        if isinstance(args, dict):
            for key in possible_keys:
                if key in args:
                    return args[key]
        
        # Try list/tuple access (first element)
        if isinstance(args, (list, tuple)) and len(args) > 0:
            return args[0]
        
        return None

    async def sync(self):
        """Manually trigger a sync"""
        await self.sync_latest()

