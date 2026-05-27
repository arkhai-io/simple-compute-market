"""Buyer- and storefront-side TOML config, XDG-aware.

Canonical locations:

* buyer:      ``$XDG_CONFIG_HOME/arkhai/buyer.toml``
* storefront: ``$XDG_CONFIG_HOME/arkhai/storefront.toml``

Both default to ``~/.config/arkhai/`` when XDG is unset.

Schema (storefront and buyer share wallet/chains/registry tables):

    [wallet]
    address = "0x..."
    private_key = "0x..."            # one key signs for every configured chain
    ssh_public_key = "ssh-ed25519 ..." # used as the pubkey delivered at settle

    # One [chains.<name>] table per chain the operator wants to transact
    # on. Listings advertise their accepted chains via the
    # accepted_escrows[].chain_name tuples; the runtime picks the matching
    # entry here when settling.
    [chains.ethereum_sepolia]
    rpc_url = "https://..."
    chain_id = 11155111
    # alkahest_address_config_path = "/etc/arkhai/alkahest.json"  # anvil only
    # identity_registry_address = "0x..."     # defaults from KNOWN_IDENTITY_REGISTRY

    [chains.base_sepolia]
    rpc_url = "https://..."
    chain_id = 84532

    [registry]
    urls = ["http://localhost:8080"]

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import tomllib


T = TypeVar("T")


@dataclass(frozen=True)
class ChainConfig:
    """One entry from the operator's ``[chains.<name>]`` config table.

    ``name`` is the table key — the dict returned by
    :func:`chains_from_config` is keyed by this exact value, and listings
    advertise it in their ``accepted_escrows[].chain_name`` tuples.

    ``onchain_agent_id`` is the storefront's ERC-8004 agent ID **for this
    chain** — every chain has its own identity registry, so an agent has
    one ID per chain. Auto-populated by the startup identity task on
    fresh boots (and written back to TOML); operators can also pin it
    manually to bring an identity from elsewhere.
    """

    name: str
    rpc_url: str
    chain_id: int
    alkahest_address_config_path: Optional[str] = None
    identity_registry_address: Optional[str] = None
    onchain_agent_id: Optional[int] = None


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
    """Return the path to the buyer's primary ``buyer.toml`` (may not exist).

    Other files in the layered set (e.g. ``buyer.secrets.toml``) are
    discovered by :func:`user_config_files`; this function still returns
    the base file path for callers that need a single canonical location
    (e.g. ``write_user_config`` defaults).
    """
    override = _config_path_override
    if override is not None:
        return override
    return user_config_dir() / "buyer.toml"


def user_config_files() -> list[Path]:
    """Return the ordered list of TOML files the loader merges.

    Base first, overlays later — files listed later win on key conflicts.
    Today: ``buyer.toml`` (ConfigMap-rendered base) then
    ``buyer.secrets.toml`` (Secret-rendered sensitive overlay). Missing
    files are skipped silently at load time, so local-dev with a single
    ``buyer.toml`` keeps working.

    The ``--config PATH`` override (via :func:`set_user_config_path`)
    short-circuits this to a single-file load — useful for tests and ad-
    hoc invocations that want full control over what's read.

    Under pytest, when neither ``set_user_config_path()`` nor
    ``XDG_CONFIG_HOME`` has been set, the loader returns an empty list
    instead of reading the developer's ambient
    ``~/.config/arkhai/buyer.toml``. That file otherwise leaks into
    test process state — e.g. the storefront's seller_auth dependency
    flips from dev-bypass to enforcing mode because a populated
    ``wallet.address`` was loaded into ``CONFIG.agent_wallet_address``
    at module-import time. Tests that legitimately exercise the layered
    loader monkeypatch ``XDG_CONFIG_HOME`` to a tmp dir, which preserves
    their behaviour.
    """
    if _config_path_override is not None:
        return [_config_path_override]
    base = user_config_dir()
    if "pytest" in sys.modules:
        # Trust XDG only when it's been pointed somewhere other than the
        # user's home — i.e. a test fixture explicitly set it. Bare
        # ambient XDG ($HOME/.config) is suppressed: a populated
        # ~/.config/arkhai/buyer.toml would otherwise leak into every
        # storefront-importing test, flipping seller_auth into enforcing
        # mode and causing surprising 403s. Tests that exercise the
        # loader's layered behaviour monkeypatch XDG_CONFIG_HOME to
        # tmp_path, which is not under home and so passes through.
        try:
            home_default = (Path.home() / ".config").resolve()
            if base.resolve().parent == home_default:
                return []
        except (OSError, RuntimeError):
            return []
    return [base / "buyer.toml", base / "buyer.secrets.toml"]


def storefront_config_file() -> Path:
    """Return the path to the storefront's primary ``storefront.toml``.

    Mirrors :func:`user_config_file` for the storefront's own file pair
    (``storefront.toml`` + ``storefront.secrets.toml``). The storefront has
    a separate identity and role-scoped knobs, so it gets its own file
    rather than reusing the buyer's ``config.toml``. On a host that runs
    both buyer and seller, this prevents one role's CLI scaffold from
    clobbering the other's.

    Honours :func:`set_user_config_path` so ``--config PATH`` on the
    storefront CLI applies here too.
    """
    override = _config_path_override
    if override is not None:
        return override
    return user_config_dir() / "storefront.toml"


def storefront_config_files() -> list[Path]:
    """Return the ordered list of TOML files the storefront loader merges.

    Mirrors :func:`user_config_files` but for the storefront's own files
    (``storefront.toml`` + ``storefront.secrets.toml``) instead of the buyer's
    shared ``config.toml``. The storefront has a separate identity and
    role-scoped knobs, so it gets its own file pair rather than reusing the
    buyer's. See ARCHITECTURE.md "Storefront chart layout".

    Pytest guard mirrors :func:`user_config_files` — when XDG hasn't been
    pointed at a tmp dir, returns ``[]`` so the developer's ambient
    ``~/.config/arkhai/storefront.toml`` doesn't leak into test process state.
    """
    base = user_config_dir()
    if "pytest" in sys.modules:
        try:
            home_default = (Path.home() / ".config").resolve()
            if base.resolve().parent == home_default:
                return []
        except (OSError, RuntimeError):
            return []
    return [base / "storefront.toml", base / "storefront.secrets.toml"]


def load_storefront_config() -> dict[str, Any]:
    """Read the storefront's layered TOML config as a single merged dict.

    Mirrors :func:`load_user_config` (no-path form) but walks
    :func:`storefront_config_files` instead of :func:`user_config_files`.
    Use this from the storefront's ``config show`` / ``config get`` CLI
    commands so they reflect what the storefront server actually reads,
    not the buyer's layered files.
    """
    merged: dict[str, Any] = {}
    for p in storefront_config_files():
        _deep_merge(merged, _read_one(p))
    return merged


# Set by ``set_user_config_path`` from a CLI ``--config`` callback so
# every subsequent ``load_user_config()`` call resolves to the override.
_config_path_override: Optional[Path] = None


def set_user_config_path(path: Path | str | None) -> None:
    """Override the canonical TOML location for this process.

    Called from each CLI entry point's ``--config PATH`` callback before
    any subcommand body runs. ``None`` clears the override (back to the
    XDG default). Called once per process — there's no expectation of
    re-entrancy.

    When set, the override replaces the entire layered file stack — only
    the single specified file is read. Tests rely on this to stay
    isolated from any ambient ``config.secrets.toml`` in the user's
    XDG dir.
    """
    global _config_path_override
    _config_path_override = Path(path) if path is not None else None


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into ``base``, returning ``base``.

    Nested tables compose (so the ConfigMap's ``[wallet] ssh_public_key``
    and the Secret's ``[wallet] private_key`` end up as siblings in the
    merged ``wallet`` table). Scalar conflicts resolve overlay-wins.
    """
    for key, val in overlay.items():
        existing = base.get(key)
        if isinstance(existing, dict) and isinstance(val, dict):
            _deep_merge(existing, val)
        else:
            base[key] = val
    return base


def _read_one(path: Path) -> dict[str, Any]:
    """Read a single TOML file. Missing/malformed → empty dict + warn."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        print(f"[config] could not read {path}: {exc}", file=sys.stderr)
        return {}


def load_user_config(path: Optional[Path] = None) -> dict[str, Any]:
    """Read the user's layered TOML config as a single merged dict.

    Explicit ``path`` arg → load that one file only (used in tests).
    Otherwise walk :func:`user_config_files` and deep-merge each layer
    in order. Missing files in the stack are silently skipped.

    Missing/malformed files don't raise — empty dict, warning on stderr,
    so a typo never prevents the CLI from running.
    """
    if path is not None:
        return _read_one(path)
    merged: dict[str, Any] = {}
    for p in user_config_files():
        _deep_merge(merged, _read_one(p))
    return merged


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


# Canonical ERC-8004 v0.1 IdentityRegistry CREATE2 vanity address. The
# alkahest deployer uses the same salt across every chain it deploys to,
# so for the canonical deployment this address is the same on every chain.
# Custom deployments override via ``[registry] identity_registry_address``
# in the TOML.
_CANONICAL_IDENTITY_REGISTRY = "0x8004A818BFB912233c491871b3d84c89A494BD9e"
KNOWN_IDENTITY_REGISTRY: dict[str, str] = {
    "base_sepolia":     _CANONICAL_IDENTITY_REGISTRY,
    "ethereum_sepolia": _CANONICAL_IDENTITY_REGISTRY,
    "anvil":            _CANONICAL_IDENTITY_REGISTRY,
}


def derive_wallet_address(private_key: Optional[str]) -> Optional[str]:
    """Compute the checksummed EVM address from an ECDSA private key.

    Pure local — no RPC. Returns ``None`` when the key is missing or
    eth_account refuses it (malformed hex, wrong length, etc.). Callers
    decide whether the absence is fatal.
    """
    if not private_key:
        return None
    try:
        from eth_account import Account
        return Account.from_key(private_key).address
    except Exception:
        return None


# Canonical chain_id ↔ chain_name table. Used to derive ``chain.name``
# from a configured ``chain.rpc_url`` via a one-shot ``eth_chainId``
# call, so operators who set the RPC don't also have to set the name.
# The set mirrors ``service.clients.alkahest.SUPPORTED_NETWORKS``;
# ``genlayer_bradbury`` is omitted because its mainnet chain ID isn't
# pinned in the codebase yet — users on that chain must set chain.name
# explicitly.
KNOWN_CHAIN_IDS: dict[str, int] = {
    "anvil":                31337,
    "base_sepolia":         84532,
    "ethereum_sepolia":     11155111,
    "ethereum_mainnet":     1,
    "filecoin_calibration": 314159,
}
CHAIN_NAME_BY_ID: dict[int, str] = {v: k for k, v in KNOWN_CHAIN_IDS.items()}
# Anvil ships with two common default chain IDs; both map to the same name.
CHAIN_NAME_BY_ID[1337] = "anvil"


def query_chain_id_via_rpc(
    rpc_url: Optional[str],
    *,
    timeout: float = 5.0,
) -> Optional[int]:
    """Issue a one-shot ``eth_chainId`` against ``rpc_url``.

    Returns the decoded integer chain ID, or ``None`` on any failure
    (no url, transport error, malformed reply). Translates ``ws://``
    and ``wss://`` to ``http(s)://`` for the urllib client — the
    ``eth_chainId`` method works identically over either transport.
    """
    if not rpc_url or not rpc_url.strip():
        return None
    url = rpc_url.strip()
    if url.startswith("ws://"):
        url = "http://" + url[len("ws://"):]
    elif url.startswith("wss://"):
        url = "https://" + url[len("wss://"):]
    import json as _json
    import urllib.error as _urlerr
    import urllib.request as _urlreq
    try:
        req = _urlreq.Request(
            url,
            data=_json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "method": "eth_chainId", "params": [],
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            body = _json.loads(resp.read())
        raw = body.get("result", "0x0")
        cid = int(raw, 16)
        return cid or None
    except (_urlerr.URLError, OSError, ValueError, TypeError):
        return None


def chain_name_for_rpc(
    rpc_url: Optional[str],
    *,
    timeout: float = 5.0,
) -> Optional[str]:
    """Look up the canonical chain name the given RPC serves.

    Returns ``None`` if the RPC is unreachable, returns garbage, or
    reports a chain ID we don't have a canonical name for.
    """
    cid = query_chain_id_via_rpc(rpc_url, timeout=timeout)
    if cid is None:
        return None
    return CHAIN_NAME_BY_ID.get(cid)


def chains_from_config(
    config: Optional[dict[str, Any]] = None,
) -> dict[str, ChainConfig]:
    """Return every ``[chains.<name>]`` table from the merged TOML config.

    Resolves each entry to a :class:`ChainConfig`. ``chain_id`` falls
    back to :data:`KNOWN_CHAIN_IDS` lookup by name when the table
    omits it; ``identity_registry_address`` falls back to
    :data:`KNOWN_IDENTITY_REGISTRY`. Empty or malformed entries
    (missing ``rpc_url``) are dropped silently — operators get one
    warning surface (the empty dict) rather than a partial-load that
    pretends to succeed.

    The dict's iteration order matches TOML order (Python 3.7+).
    Callers that want a deterministic default chain pick
    ``next(iter(chains.values()))``.
    """
    cfg = config if config is not None else load_user_config()
    raw = cfg.get("chains")
    if not isinstance(raw, dict):
        return {}

    out: dict[str, ChainConfig] = {}
    for name, sub in raw.items():
        if not isinstance(name, str) or not isinstance(sub, dict):
            continue
        rpc_url = str(sub.get("rpc_url", "") or "").strip()
        if not rpc_url:
            continue

        chain_id = int(sub.get("chain_id", 0) or 0)
        if not chain_id:
            chain_id = KNOWN_CHAIN_IDS.get(name, 0)

        identity_reg = (
            str(sub.get("identity_registry_address", "") or "").strip()
            or KNOWN_IDENTITY_REGISTRY.get(name)
        )

        alkahest_path = (
            str(sub.get("alkahest_address_config_path", "") or "").strip()
            or None
        )

        raw_agent_id = sub.get("onchain_agent_id")
        agent_id: Optional[int] = None
        if raw_agent_id not in (None, "", 0):
            try:
                agent_id = int(raw_agent_id)
            except (TypeError, ValueError):
                agent_id = None

        out[name] = ChainConfig(
            name=name,
            rpc_url=rpc_url,
            chain_id=chain_id,
            alkahest_address_config_path=alkahest_path,
            identity_registry_address=identity_reg,
            onchain_agent_id=agent_id,
        )
    return out


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
