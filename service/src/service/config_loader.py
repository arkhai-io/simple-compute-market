"""User-level TOML config, XDG-aware.

Canonical location: `$XDG_CONFIG_HOME/arkhai/config.toml`, defaulting to
`~/.config/arkhai/config.toml` when XDG is unset.

The shape is small and deliberately flat-ish:

    [wallet]
    address = "0x..."
    private_key = "0x..."            # or leave out & set AGENT_PRIV_KEY env
    ssh_public_key = "ssh-ed25519 …" # used as the pubkey delivered at settle

    [chain]
    name = "ethereum_sepolia"        # ethereum_sepolia | base_sepolia | anvil
    rpc_url = "https://..."
    alkahest_address_config_path = "/etc/arkhai/alkahest.json"  # anvil only

    [registry]
    url = "http://localhost:8080"

    [seller]                         # optional; seller-specific overrides
    port = 8000
    agent_id = "alice"
    provisioning_service_url = "http://localhost:8085"

Lookup hierarchy used by `resolve_value()`:
    CLI flag  >  ENV var  >  TOML config  >  default

so existing workflows that use `--env` files or ambient environment
variables keep working unchanged. The TOML fills in the background so
you don't have to pass the same five flags on every invocation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import tomllib


T = TypeVar("T")


def user_config_dir() -> Path:
    """Return the XDG-aware arkhai config directory.

    Honors XDG_CONFIG_HOME when set, otherwise falls back to ~/.config.
    XDG_CONFIG_HOME is a platform/runtime knob (set by the OS or
    container orchestrator), not user config — it's the only env var
    this loader still consults.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / "arkhai"


def user_config_file() -> Path:
    """Return the path to the user's config.toml (may not exist)."""
    override = _config_path_override
    if override is not None:
        return override
    return user_config_dir() / "config.toml"


# Set by ``set_user_config_path`` from a CLI ``--config`` callback so
# every subsequent ``load_user_config()`` call resolves to the override.
_config_path_override: Optional[Path] = None


def set_user_config_path(path: Path | str | None) -> None:
    """Override the canonical TOML location for this process.

    Called from each CLI entry point's ``--config PATH`` callback before
    any subcommand body runs. ``None`` clears the override (back to the
    XDG default). Called once per process — there's no expectation of
    re-entrancy.
    """
    global _config_path_override
    _config_path_override = Path(path) if path is not None else None


def load_user_config(path: Optional[Path] = None) -> dict[str, Any]:
    """Read the user's TOML config as a plain dict.

    Lookup order: explicit ``path`` arg > ``set_user_config_path`` override >
    ``$XDG_CONFIG_HOME/arkhai/config.toml`` (or ``~/.config/arkhai/config.toml``).

    Missing file → empty dict. Unreadable / malformed → empty dict with
    a warning on stderr, so a typo never prevents the CLI from running.
    """
    p = path or user_config_file()
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        print(f"[config] could not read {p}: {exc}", file=sys.stderr)
        return {}


def get_dotted(doc: dict[str, Any], dotted: str) -> Any | None:
    """Walk a dotted path through a nested dict. None if any step is absent."""
    cur: Any = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def set_dotted(doc: dict[str, Any], dotted: str, value: Any) -> None:
    """Set a dotted key in-place, creating intermediate tables as needed."""
    parts = dotted.split(".")
    cur = doc
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def resolve_value(
    *,
    flag: Optional[T] = None,
    env_name: Optional[str] = None,
    toml_path: Optional[str] = None,
    default: Optional[T] = None,
    config: Optional[dict[str, Any]] = None,
    coerce: Callable[[str], T] | None = None,
) -> Optional[T]:
    """Single-stop resolver. Hierarchy: flag > env > toml > default.

    Pass `flag` as the already-parsed typer value (which may be None if
    the user didn't provide it). `env_name` is the ENV var name to try
    next (e.g. "CHAIN_RPC_URL"). `toml_path` is a dotted key into the
    loaded TOML config (e.g. "chain.rpc_url"). `default` is the final
    fallback.

    Strings come through unchanged; when `coerce` is provided, env and
    flag-string values pass through it (useful for ints, bools).
    """
    if flag is not None:
        return flag
    if env_name:
        raw = os.environ.get(env_name)
        if raw is not None and raw != "":
            return coerce(raw) if coerce else raw  # type: ignore[return-value]
    if toml_path:
        cfg = config if config is not None else load_user_config()
        val = get_dotted(cfg, toml_path)
        if val is not None and val != "":
            return val
    return default


# ---------------------------------------------------------------------------
# Typed shortcuts for the buyer-hot path. Each takes an optional `flag`
# override and returns either the resolved value or None (caller decides
# whether that's fatal).
# ---------------------------------------------------------------------------


def wallet_address(flag: Optional[str] = None,
                   config: Optional[dict[str, Any]] = None) -> Optional[str]:
    return resolve_value(
        flag=flag,
        env_name="AGENT_WALLET_ADDRESS",
        toml_path="wallet.address",
        config=config,
    )


def private_key(flag: Optional[str] = None,
                config: Optional[dict[str, Any]] = None) -> Optional[str]:
    return resolve_value(
        flag=flag,
        env_name="AGENT_PRIV_KEY",
        toml_path="wallet.private_key",
        config=config,
    )


def ssh_public_key(flag: Optional[str] = None,
                   config: Optional[dict[str, Any]] = None) -> Optional[str]:
    return resolve_value(
        flag=flag,
        env_name="SSH_PUBLIC_KEY",
        toml_path="wallet.ssh_public_key",
        config=config,
    )


def chain_name(flag: Optional[str] = None,
               config: Optional[dict[str, Any]] = None,
               default: str = "ethereum_sepolia") -> str:
    return resolve_value(
        flag=flag,
        env_name="CHAIN_NAME",
        toml_path="chain.name",
        default=default,
        config=config,
    )  # type: ignore[return-value]


def chain_rpc_url(flag: Optional[str] = None,
                  config: Optional[dict[str, Any]] = None) -> Optional[str]:
    return resolve_value(
        flag=flag,
        env_name="CHAIN_RPC_URL",
        toml_path="chain.rpc_url",
        config=config,
    )


def alkahest_address_config_path(flag: Optional[str] = None,
                                 config: Optional[dict[str, Any]] = None) -> Optional[str]:
    return resolve_value(
        flag=flag,
        env_name="ALKAHEST_ADDRESS_CONFIG_PATH",
        toml_path="chain.alkahest_address_config_path",
        config=config,
    )


def registry_urls(
    config: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Resolve the configured registry URL(s) as a list. Reads
    ``registry.urls`` from the TOML config; falls back to a localhost
    default. Mirrors the storefront's resolver — only the plural list
    form is recognised.
    """
    cfg = config if config is not None else load_user_config()
    raw = get_dotted(cfg, "registry.urls")
    if isinstance(raw, list) and raw:
        cleaned = [str(u).strip() for u in raw if str(u).strip()]
        if cleaned:
            return cleaned
    return ["http://localhost:8080"]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def write_user_config(doc: dict[str, Any], path: Optional[Path] = None) -> Path:
    """Serialize `doc` as TOML and write it to the user config path.

    No third-party writer needed — we emit a hand-rolled TOML subset that
    covers nested tables, strings, ints, floats, and bools. That's all
    our schema uses. Keys and values are quoted conservatively.
    """
    p = path or user_config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_serialize_toml(doc))
    return p


def _toml_escape(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Basic-string escape: quotes + backslashes; control chars → \uXXXX.
        esc = value.replace("\\", "\\\\").replace("\"", "\\\"")
        out = []
        for ch in esc:
            c = ord(ch)
            if c < 0x20:
                out.append(f"\\u{c:04x}")
            else:
                out.append(ch)
        return "\"" + "".join(out) + "\""
    raise ValueError(f"Unsupported TOML value type: {type(value).__name__}")


def _serialize_toml(doc: dict[str, Any]) -> str:
    """Hand-rolled minimal TOML emitter. Nested dicts become [table.subtable]."""
    lines: list[str] = []

    def _emit(table: dict[str, Any], prefix: list[str]) -> None:
        # Emit scalars first, then recurse into sub-tables.
        scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
        subtables = {k: v for k, v in table.items() if isinstance(v, dict)}
        if prefix and (scalars or not subtables):
            lines.append(f"[{'.'.join(prefix)}]")
        for k, v in scalars.items():
            lines.append(f"{k} = {_toml_escape(v)}")
        if scalars:
            lines.append("")
        for k, v in subtables.items():
            _emit(v, prefix + [k])

    _emit(doc, [])
    # Trim trailing blank lines.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"
