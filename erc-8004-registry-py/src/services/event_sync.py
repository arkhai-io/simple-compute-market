import asyncio
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
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
                            
                            # Try different ways to access agentId (handles different web3.py versions)
                            agent_id_value = None
                            if hasattr(event.args, 'agentId'):
                                agent_id_value = event.args.agentId
                            elif hasattr(event.args, 'agent_id'):
                                agent_id_value = event.args.agent_id
                            elif isinstance(event.args, (list, tuple)) and len(event.args) > 0:
                                agent_id_value = event.args[0]
                            
                            if not agent_id_value:
                                logger.warning(f"[EventSync] Could not extract agentId from event: {event}")
                                continue
                            
                            agent_id = str(agent_id_value)
                            chain_id = settings.chain_id
                            registry_address = settings.identity_registry_address

                            # Check if agent already exists
                            existing = db.query(Agent).filter(
                                Agent.agent_id == agent_id
                            ).first()

                            if not existing:
                                # Get token URI and metadata
                                token_uri = None
                                try:
                                    token_uri = self.identity_registry.get_token_uri(int(agent_id_value))
                                except Exception as e:
                                    logger.warning(f"[EventSync] Could not fetch token URI for agent {agent_id}: {e}")

                                # Insert new agent
                                agent = Agent(
                                    agent_id=agent_id,
                                    chain_id=chain_id,
                                    registry_address=registry_address,
                                    token_uri=token_uri,
                                    metadata_json={},
                                    health_status="healthy",
                                )
                                db.add(agent)
                                db.commit()

                                block_number = getattr(event, 'blockNumber', getattr(event, 'block_number', None))
                                logger.info(f"[EventSync] Registered agent {agent_id} from block {block_number}")
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
                            
                            # Try different ways to access event args (handles different web3.py versions)
                            agent_id_value = None
                            key_value = None
                            
                            if hasattr(event.args, 'agentId') and hasattr(event.args, 'key'):
                                agent_id_value = event.args.agentId
                                key_value = event.args.key
                            elif hasattr(event.args, 'agent_id') and hasattr(event.args, 'key'):
                                agent_id_value = event.args.agent_id
                                key_value = event.args.key
                            elif isinstance(event.args, (list, tuple)) and len(event.args) >= 2:
                                agent_id_value = event.args[0]
                                key_value = event.args[1]
                            
                            if not agent_id_value or not key_value:
                                logger.warning(f"[EventSync] Could not extract agentId/key from MetadataUpdated event: {event}")
                                continue
                            
                            agent_id = str(agent_id_value)
                            key = str(key_value)

                            try:
                                # Get the metadata value from contract (returns bytes)
                                value_bytes = self.identity_registry.get_metadata(int(agent_id_value), key)
                                
                                # Decode bytes to string if it's UTF-8 encoded
                                try:
                                    value = value_bytes.decode('utf-8')
                                except UnicodeDecodeError:
                                    # If not UTF-8, store as hex string
                                    value = value_bytes.hex()

                                # Update or insert metadata
                                existing_metadata = db.query(AgentMetadataEntry).filter(
                                    and_(
                                        AgentMetadataEntry.agent_id == agent_id,
                                        AgentMetadataEntry.key == key
                                    )
                                ).first()

                                if existing_metadata:
                                    existing_metadata.value = value
                                else:
                                    metadata_entry = AgentMetadataEntry(
                                        agent_id=agent_id,
                                        key=key,
                                        value=value,
                                    )
                                    db.add(metadata_entry)

                                # Update agent's metadata JSON
                                agent = db.query(Agent).filter(
                                    Agent.agent_id == agent_id
                                ).first()

                                if agent:
                                    current_metadata = agent.metadata_json or {}
                                    current_metadata[key] = value
                                    agent.metadata_json = current_metadata

                                db.commit()
                                logger.info(f"[EventSync] Updated metadata for agent {agent_id}, key: {key}")
                            except Exception as e:
                                logger.warning(f"[EventSync] Could not update metadata for agent {agent_id}, key {key}: {e}")
                                db.rollback()
                        except Exception as e:
                            logger.error(f"[EventSync] Error processing MetadataSet event: {e}")
                            logger.debug(f"[EventSync] Event data: {event}")
                            continue

                except Exception as e:
                    logger.error(f"[EventSync] Error syncing blocks {current_from}-{current_to}: {e}")
                    db.rollback()

                current_from = current_to + 1
        finally:
            db.close()

    async def sync(self):
        """Manually trigger a sync"""
        await self.sync_latest()

