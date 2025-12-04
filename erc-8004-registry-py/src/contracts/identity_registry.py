from web3 import Web3
from web3.contract import Contract
from typing import List, Optional
from src.contracts.abis import IDENTITY_REGISTRY_ABI
from src.types import AgentMetadata, NetworkConfig


class IdentityRegistryClient:
    def __init__(self, network_config: NetworkConfig, private_key: Optional[str] = None):
        self.network_config = network_config
        self.w3 = Web3(Web3.HTTPProvider(network_config.rpc_url))
        self.contract_address = network_config.identity_registry
        self.contract: Contract = self.w3.eth.contract(
            address=self.contract_address,
            abi=IDENTITY_REGISTRY_ABI
        )
        self.private_key = private_key
        self.account = None
        if private_key:
            self.account = self.w3.eth.account.from_key(private_key)

    def register(
        self,
        to: str,
        token_uri: str,
        metadata: List[AgentMetadata]
    ) -> str:
        """Register a new agent on-chain"""
        if not self.account:
            raise ValueError("Private key required for write operations")
        
        # Prepare metadata tuple
        metadata_tuples = [(m.key, m.value) for m in metadata]
        
        # Build transaction
        tx = self.contract.functions.register(to, token_uri, metadata_tuples).build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
        })
        
        # Sign and send transaction
        signed_tx = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        return tx_hash.hex()

    def set_metadata(self, agent_id: int, metadata: List[AgentMetadata]) -> str:
        """Update metadata for an existing agent"""
        if not self.account:
            raise ValueError("Private key required for write operations")
        
        metadata_tuples = [(m.key, m.value) for m in metadata]
        
        tx = self.contract.functions.setMetadata(agent_id, metadata_tuples).build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
        })
        
        signed_tx = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        return tx_hash.hex()

    def get_token_uri(self, agent_id: int) -> str:
        """Get the token URI for an agent"""
        return self.contract.functions.tokenURI(agent_id).call()

    def get_owner(self, agent_id: int) -> str:
        """Get the owner of an agent NFT"""
        return self.contract.functions.ownerOf(agent_id).call()

    def get_metadata(self, agent_id: int, key: str) -> str:
        """Get metadata value for a specific key"""
        return self.contract.functions.getMetadata(agent_id, key).call()

    def get_total_supply(self) -> int:
        """Get total number of registered agents"""
        return self.contract.functions.totalSupply().call()

    def get_past_agent_registered_events(self, from_block: int, to_block: Optional[int] = None):
        """Get past AgentRegistered events"""
        event_filter = self.contract.events.AgentRegistered.create_filter(
            from_block=from_block,
            to_block=to_block or "latest"
        )
        return event_filter.get_all_entries()

    def get_past_metadata_updated_events(self, from_block: int, to_block: Optional[int] = None):
        """Get past MetadataUpdated events"""
        event_filter = self.contract.events.MetadataUpdated.create_filter(
            from_block=from_block,
            to_block=to_block or "latest"
        )
        return event_filter.get_all_entries()

    def watch_agent_registered(self, callback, from_block: Optional[int] = None):
        """Watch for AgentRegistered events"""
        event_filter = self.contract.events.AgentRegistered.create_filter(
            from_block=from_block or "latest"
        )
        
        def handle_event(event):
            if event.args.agentId:
                callback(event.args.agentId, event.blockNumber)
        
        # In production, use web3.py's event listener or polling
        return event_filter

    def watch_metadata_updated(self, callback, from_block: Optional[int] = None):
        """Watch for MetadataUpdated events"""
        event_filter = self.contract.events.MetadataUpdated.create_filter(
            from_block=from_block or "latest"
        )
        
        def handle_event(event):
            if event.args.agentId and event.args.key:
                callback(event.args.agentId, event.args.key, event.blockNumber)
        
        return event_filter

