import os
from dataclasses import dataclass
from pathlib import Path

# Load .env file if it exists (before loading any config values)
try:
    from dotenv import load_dotenv
    # Load .env from the project root (parent of app directory)
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # python-dotenv not available, skip
    pass


def _get_bool_env(var_name: str, default: bool = False) -> bool:
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes")


def _get_int_env(var_name: str, default: int) -> int:
    value = os.getenv(var_name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    agent_id: str
    mcp_server_url: str
    base_url_override: str
    port: int
    remote_agent_port: int
    remote_agent_url_override: str
    chain_rpc_url: str
    agent_priv_key: str
    agent_wallet_address: str
    use_vertex_ai: bool
    policy_db_path: str
    event_validation_mode: str  # "warn" or "strict"
    enable_redis_ingest: bool
    redis_url: str
    redis_channels: str  # comma-separated
    enable_event_queue: bool
    market_provider: str  # "static" or "redis"
    log_file_path: str | None  # Path to log file, None for default
    log_level: str  # Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
    token_registry_path: str
    ssh_public_key: str
    # Auto-registration settings
    auto_register: bool  # AUTO_REGISTER - enable auto-registration on startup
    indexer_url: str  # INDEXER_URL - ERC-8004 Indexer API URL
    identity_registry_address: str | None  # IDENTITY_REGISTRY_ADDRESS - contract address (on-chain)
    onchain_agent_id: str | None  # ONCHAIN_AGENT_ID - Explicit on-chain agent ID (NFT token ID) to use for updates
    # Registry discovery settings
    enable_registry_discovery: bool  # ENABLE_REGISTRY_DISCOVERY - enable registry-based agent discovery
    registry_order_timeout: int  # REGISTRY_ORDER_TIMEOUT - timeout for registry API calls in seconds
    max_discovery_agents: int  # MAX_DISCOVERY_AGENTS - maximum number of agents to contact


DEFAULT_TOKEN_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "token_registry.json"
)


def load_config() -> Config:
    # Get agent_id from environment variable
    # Agent name must be a valid identifier: start with letter/underscore, 
    # and only contain letters, digits, and underscores
    agent_id = os.getenv("AGENT_ID")
    if not agent_id:
        # If AGENT_ID is not set, use a safe default instead of hostname
        # (hostnames often contain invalid characters like hyphens and dots)
        agent_id = "root_agent"
        import warnings
        warnings.warn(
            "AGENT_ID environment variable not set. Using default 'root_agent'. "
            "Please set AGENT_ID to a valid identifier (letters, digits, underscores only).",
            UserWarning
        )
    
    return Config(
        agent_id=agent_id,
        mcp_server_url=os.getenv("MCP_SERVER_URL", "http://localhost:8080/mcp"),
        base_url_override=os.getenv("BASE_URL_OVERRIDE", "http://localhost:8000"),
        port=_get_int_env("PORT", 8000),
        remote_agent_port=_get_int_env("REMOTE_AGENT_PORT", 8000),
        remote_agent_url_override=os.getenv(
            "REMOTE_AGENT_URL_OVERRIDE", "http://localhost:8001"
        ),
        chain_rpc_url=os.getenv("CHAIN_RPC_URL"),
        agent_priv_key=os.getenv("AGENT_PRIV_KEY"),
        agent_wallet_address=os.getenv("AGENT_WALLET_ADDRESS"),
        use_vertex_ai=_get_bool_env("GOOGLE_GENAI_USE_VERTEXAI", False),
        policy_db_path=os.getenv("POLICY_DB_PATH", "/tmp/policies.db"),
        event_validation_mode=os.getenv("EVENT_VALIDATION_MODE", "warn"),
        enable_redis_ingest=_get_bool_env("ENABLE_REDIS_INGEST", False),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        redis_channels=os.getenv("REDIS_CHANNELS", "events:*"),
        enable_event_queue=_get_bool_env("ENABLE_EVENT_QUEUE", True),
        market_provider=os.getenv("MARKET_PROVIDER", "static"),
        log_file_path=os.getenv("LOG_FILE_PATH"),  # None if not set
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        token_registry_path=os.getenv(
            "TOKEN_REGISTRY_PATH", str(DEFAULT_TOKEN_REGISTRY_PATH)
        ),
        ssh_public_key=os.getenv(
            "SSH_PUBLIC_KEY",
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDemoPublicKeyForComputeAccess demo@example",
        ),
        # Auto-registration settings
        auto_register=_get_bool_env("AUTO_REGISTER", False),
        indexer_url=os.getenv("INDEXER_URL", os.getenv("REGISTRY_URL", "http://localhost:8080")),  # Support both for backward compatibility
        identity_registry_address=os.getenv("IDENTITY_REGISTRY_ADDRESS"),
        onchain_agent_id=os.getenv("ONCHAIN_AGENT_ID"),  # Explicit on-chain agent ID (optional)
        # Registry discovery settings
        enable_registry_discovery=_get_bool_env("ENABLE_REGISTRY_DISCOVERY", True),
        registry_order_timeout=_get_int_env("REGISTRY_ORDER_TIMEOUT", 30),
        max_discovery_agents=_get_int_env("MAX_DISCOVERY_AGENTS", 10),
    )


def ensure_google_defaults_if_needed(cfg: Config) -> None:
    if not cfg.use_vertex_ai:
        return
    # Ensure GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION are set if using Vertex AI.
    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        try:
            import google.auth  # local import to avoid hard dep when not needed

            _, project_id = google.auth.default()
            if project_id:
                os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
        except Exception:
            # Best-effort; downstream code can still rely on explicit envs.
            pass
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.getenv("GOOGLE_CLOUD_LOCATION", "global"))


# Module-level singleton for convenience
CONFIG = load_config()
ensure_google_defaults_if_needed(CONFIG)
