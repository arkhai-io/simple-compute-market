"""Read-only wrapper around the on-chain ERC-8004 IdentityRegistry contract.

Reads (``ownerOf``, ``tokenURI``, ``getMetadata``) are used by the JIT
indexing path in ``api/utils.py::ensure_agent_indexed``. Writes
(``register``, ``setMetadata``) are kept for ad-hoc admin scripts but are
not used by the indexer's request-path code.

Sync I/O — callers in async contexts should wrap in ``asyncio.to_thread``.
"""

from typing import List, Optional

from web3 import Web3
from web3.contract import Contract

from src.contracts.abis import IDENTITY_REGISTRY_ABI
from src.types import AgentMetadata, NetworkConfig


class IdentityRegistryClient:
    def __init__(self, network_config: NetworkConfig, private_key: Optional[str] = None):
        self.network_config = network_config
        self.w3 = Web3(Web3.HTTPProvider(network_config.rpc_url))
        self.contract_address = network_config.identity_registry
        self.contract: Contract = self.w3.eth.contract(
            address=self.contract_address,
            abi=IDENTITY_REGISTRY_ABI,
        )
        self.private_key = private_key
        self.account = None
        if private_key:
            self.account = self.w3.eth.account.from_key(private_key)

    def register(
        self,
        token_uri: str,
        metadata: List[AgentMetadata],
    ) -> str:
        """Register a new agent on-chain.

        Note: contract always mints to ``msg.sender`` (the account signing
        the transaction). To register for a different address, use that
        address's private key.
        """
        if not self.account:
            raise ValueError("Private key required for write operations")

        metadata_tuples = [
            (m.key, m.value.encode("utf-8") if isinstance(m.value, str) else m.value)
            for m in metadata
        ]

        tx = self.contract.functions.register(token_uri, metadata_tuples).build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
        })
        signed_tx = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        return tx_hash.hex()

    def set_metadata(self, agent_id: int, key: str, value: str) -> str:
        """Update a single metadata entry for an existing agent."""
        if not self.account:
            raise ValueError("Private key required for write operations")

        value_bytes = value.encode("utf-8") if isinstance(value, str) else value

        tx = self.contract.functions.setMetadata(agent_id, key, value_bytes).build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
        })
        signed_tx = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        return tx_hash.hex()

    def get_token_uri(self, agent_id: int) -> str:
        return self.contract.functions.tokenURI(agent_id).call()

    def get_owner(self, agent_id: int) -> str:
        return self.contract.functions.ownerOf(agent_id).call()

    def get_metadata(self, agent_id: int, key: str) -> bytes:
        """Returns bytes — decode with ``.decode('utf-8')`` for string values."""
        return self.contract.functions.getMetadata(agent_id, key).call()

    def get_total_supply(self) -> int:
        return self.contract.functions.totalSupply().call()
