# ERC-8004 Contract ABIs
# Based on https://github.com/erc-8004/erc-8004-contracts
# Official contract interface - matches IdentityRegistry.sol

IDENTITY_REGISTRY_ABI = [
    {
        "inputs": [],
        "name": "register",
        "outputs": [{"name": "agentId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "tokenUri", "type": "string"}],
        "name": "register",
        "outputs": [{"name": "agentId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "tokenUri", "type": "string"},
            {
                "name": "metadata",
                "type": "tuple[]",
                "components": [
                    {"name": "key", "type": "string"},
                    {"name": "value", "type": "bytes"}
                ]
            }
        ],
        "name": "register",
        "outputs": [{"name": "agentId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "key", "type": "string"},
            {"name": "value", "type": "bytes"}
        ],
        "name": "setMetadata",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "name": "tokenURI",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "key", "type": "string"}
        ],
        "name": "getMetadata",
        "outputs": [{"name": "", "type": "bytes"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": False, "name": "tokenURI", "type": "string"},
            {"indexed": True, "name": "owner", "type": "address"}
        ],
        "name": "Registered",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": True, "name": "indexedKey", "type": "string"},
            {"indexed": False, "name": "key", "type": "string"},
            {"indexed": False, "name": "value", "type": "bytes"}
        ],
        "name": "MetadataSet",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": False, "name": "newUri", "type": "string"},
            {"indexed": True, "name": "updatedBy", "type": "address"}
        ],
        "name": "UriUpdated",
        "type": "event",
    },
]

REPUTATION_REGISTRY_ABI = [
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "score", "type": "uint8"},
            {"name": "tags", "type": "string[]"},
            {"name": "fileRef", "type": "string"}
        ],
        "name": "giveFeedback",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "client", "type": "address"}
        ],
        "name": "getFeedbackSummary",
        "outputs": [
            {"name": "count", "type": "uint256"},
            {"name": "averageScore", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

VALIDATION_REGISTRY_ABI = [
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "validator", "type": "address"}
        ],
        "name": "requestValidation",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "score", "type": "uint8"},
            {"name": "tags", "type": "string[]"}
        ],
        "name": "respondValidation",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

