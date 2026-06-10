"""
tests/fixtures/abis.py
-----------------------
Shared contract ABI definitions used across test modules.

ABIs are kept minimal — only the function signatures needed by the tests.
Full ABIs should be loaded from build artefacts (e.g. Hardhat / Foundry
output JSON) in a real project; these stubs are sufficient for the current
test suite and serve as a reference for extension.
"""

from __future__ import annotations

# ERC-173 ownership standard — owner()
OWNABLE_ABI = [
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "previousOwner", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "newOwner", "type": "address"},
        ],
        "name": "OwnershipTransferred",
        "type": "event",
    },
]

# Minimal ERC-165 introspection — supportsInterface()
ERC165_ABI = [
    {
        "inputs": [{"internalType": "bytes4", "name": "interfaceId", "type": "bytes4"}],
        "name": "supportsInterface",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Placeholder stub for IdentityRegistry — extend with real ABI from build artefacts
IDENTITY_REGISTRY_ABI = OWNABLE_ABI + ERC165_ABI

# Placeholder stub for ReputationRegistry
REPUTATION_REGISTRY_ABI = OWNABLE_ABI + ERC165_ABI

# Placeholder stub for ValidationRegistry
VALIDATION_REGISTRY_ABI = OWNABLE_ABI + ERC165_ABI
