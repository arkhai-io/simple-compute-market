# ERC-8004 Contract ABIs
# Based on https://github.com/erc-8004/erc-8004-contracts

IDENTITY_REGISTRY_ABI = [
    {
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "tokenURI", "type": "string"},
            {
                "name": "metadata",
                "type": "tuple[]",
                "components": [
                    {"name": "key", "type": "string"},
                    {"name": "value", "type": "string"}
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
            {
                "name": "metadata",
                "type": "tuple[]",
                "components": [
                    {"name": "key", "type": "string"},
                    {"name": "value", "type": "string"}
                ]
            }
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
        "outputs": [{"name": "", "type": "string"}],
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
        "inputs": [{"indexed": True, "name": "agentId", "type": "uint256"}],
        "name": "AgentRegistered",
        "type": "event",
    },
    {
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": True, "name": "key", "type": "string"}
        ],
        "name": "MetadataUpdated",
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

