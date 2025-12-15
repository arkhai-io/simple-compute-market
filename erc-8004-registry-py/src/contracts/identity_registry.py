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
        token_uri: str,
        metadata: List[AgentMetadata]
    ) -> str:
        """
        Register a new agent on-chain.
        
        Note: Contract always mints to msg.sender (the account signing the transaction).
        To register for a different address, use that address's private key.
        
        Args:
            token_uri: URI pointing to agent card (IPFS, HTTPS, etc.)
            metadata: List of metadata entries (values will be converted to bytes)
        """
        if not self.account:
            raise ValueError("Private key required for write operations")
        
        # Convert metadata to tuple array with bytes values
        # Official contract expects MetadataEntry[] where value is bytes
        metadata_tuples = [
            (m.key, m.value.encode('utf-8') if isinstance(m.value, str) else m.value)
            for m in metadata
        ]
        
        # Build transaction - use register(string, MetadataEntry[]) overload
        tx = self.contract.functions.register(token_uri, metadata_tuples).build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
        })
        
        # Sign and send transaction
        signed_tx = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        return tx_hash.hex()

    def set_metadata(self, agent_id: int, key: str, value: str) -> str:
        """
        Update a single metadata entry for an existing agent.
        
        Args:
            agent_id: Agent ID
            key: Metadata key
            value: Metadata value (will be converted to bytes)
        """
        if not self.account:
            raise ValueError("Private key required for write operations")
        
        # Convert value to bytes
        value_bytes = value.encode('utf-8') if isinstance(value, str) else value
        
        tx = self.contract.functions.setMetadata(agent_id, key, value_bytes).build_transaction({
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

    def get_metadata(self, agent_id: int, key: str) -> bytes:
        """
        Get metadata value for a specific key.
        
        Returns bytes - decode with .decode('utf-8') if it's a string value.
        """
        return self.contract.functions.getMetadata(agent_id, key).call()

    def get_total_supply(self) -> int:
        """Get total number of registered agents"""
        return self.contract.functions.totalSupply().call()

    def get_past_agent_registered_events(self, from_block: int, to_block: Optional[int] = None):
        """Get past Registered events using get_logs (more reliable than filters)"""
        try:
            # Use get_logs directly instead of create_filter for better RPC compatibility
            return self.contract.events.Registered.get_logs(
                fromBlock=from_block,
                toBlock=to_block if to_block is not None else "latest"
            )
        except Exception as e:
            # Fallback: try with create_filter if get_logs fails
            # This handles cases where RPC doesn't support get_logs with block ranges
            try:
                event_filter = self.contract.events.Registered.create_filter(
                    from_block=from_block,
                    to_block=to_block or "latest"
                )
                return event_filter.get_all_entries()
            except Exception:
                # If both fail, re-raise the original error
                raise e

    def get_past_metadata_set_events(self, from_block: int, to_block: Optional[int] = None):
        """Get past MetadataSet events using get_logs (more reliable than filters)"""
        try:
            # Use get_logs directly instead of create_filter for better RPC compatibility
            return self.contract.events.MetadataSet.get_logs(
                fromBlock=from_block,
                toBlock=to_block if to_block is not None else "latest"
            )
        except Exception as e:
            # Fallback: try with create_filter if get_logs fails
            # This handles cases where RPC doesn't support get_logs with block ranges
            try:
                event_filter = self.contract.events.MetadataSet.create_filter(
                    from_block=from_block,
                    to_block=to_block or "latest"
                )
                return event_filter.get_all_entries()
            except Exception:
                # If both fail, re-raise the original error
                raise e

    def watch_agent_registered(self, callback, from_block: Optional[int] = None):
        """Watch for Registered events"""
        event_filter = self.contract.events.Registered.create_filter(
            from_block=from_block or "latest"
        )
        
        def handle_event(event):
            if event.args.agentId:
                callback(event.args.agentId, event.blockNumber)
        
        # In production, use web3.py's event listener or polling
        return event_filter

    def watch_metadata_set(self, callback, from_block: Optional[int] = None):
        """Watch for MetadataSet events"""
        event_filter = self.contract.events.MetadataSet.create_filter(
            from_block=from_block or "latest"
        )
        
        def handle_event(event):
            if event.args.agentId and event.args.key:
                callback(event.args.agentId, event.args.key, event.blockNumber)
        
        return event_filter

