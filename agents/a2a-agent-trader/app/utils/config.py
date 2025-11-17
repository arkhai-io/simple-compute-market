import os
from dataclasses import dataclass
from pathlib import Path


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


DEFAULT_TOKEN_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "token_registry.json"
)


def load_config() -> Config:
    # Get agent_id with fallback
    agent_id = os.getenv("AGENT_ID")
    if not agent_id:
        try:
            agent_id = os.uname().nodename
        except (AttributeError, OSError):
            # os.uname() not available on all platforms
            import socket
            agent_id = socket.gethostname()
    agent_id = agent_id or "root_agent"
    
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
