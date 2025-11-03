import os
from dataclasses import dataclass


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
    mcp_server_url: str
    base_url_override: str
    port: int
    remote_agent_url_override: str
    use_vertex_ai: bool
    policy_db_path: str


def load_config() -> Config:
    return Config(
        mcp_server_url=os.getenv("MCP_SERVER_URL", "http://localhost:8080/mcp"),
        base_url_override=os.getenv("BASE_URL_OVERRIDE", "http://localhost:8000"),
        port=_get_int_env("PORT", 8000),
        remote_agent_url_override=os.getenv(
            "REMOTE_AGENT_URL_OVERRIDE", "http://localhost:8001"
        ),
        use_vertex_ai=_get_bool_env("GOOGLE_GENAI_USE_VERTEXAI", False),
        policy_db_path=os.getenv("POLICY_DB_PATH", "/tmp/policies.db"),
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


