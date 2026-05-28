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

    Identity is no longer carried per-chain: after the pluggable-identity
    refactor the storefront's identity is its EIP-191 wallet address,
    advertised once at the registry layer and reused across every chain
    it supports.
    """

    name: str
    rpc_url: str
    chain_id: int
    alkahest_address_config_path: Optional[str] = None


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
    omits it. Empty or malformed entries (missing ``rpc_url``) are
    dropped silently — operators get one warning surface (the empty
    dict) rather than a partial-load that pretends to succeed.

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

        alkahest_path = (
            str(sub.get("alkahest_address_config_path", "") or "").strip()
            or None
        )

        out[name] = ChainConfig(
            name=name,
            rpc_url=rpc_url,
            chain_id=chain_id,
            alkahest_address_config_path=alkahest_path,
        )
    return out


# ---------------------------------------------------------------------------
# Escrow templates — operator-defined shapes for accepted_escrows entries
# ---------------------------------------------------------------------------
# A template captures the part of an escrow that doesn't change between
# resources: the chain it lives on, the escrow contract address, every
# literal field on the obligation data (token addresses, tokenIds,
# array indices), and a named slot for each field whose value scales per
# unit of negotiated quantity (the canonical case is `amount per hour`).
#
# CSV rows reference templates by name and supply rate values via a
# `template:slot=value` DSL — the per-resource override surface is just
# numbers, never contract field paths.
#
# Wire-format mapping at publish time (cli_publish):
#   literal_fields      ← template.literal_fields
#   rates[i].field      ← template.rate_slots[name].field
#   rates[i].per        ← template.rate_slots[name].per
#   rates[i].value      ← per-resource CSV cell (multiplied by duration
#                          on the buyer side)


@dataclass(frozen=True)
class RateSlot:
    """One rate-bearing field on an escrow template.

    ``field`` is the dotted/indexed path into the obligation data
    (``"amount"``, ``"erc20Amounts[0]"``). ``per`` is the unit the
    rate scales by (``"hour"`` is the only one wired through today;
    ``"request"``, ``"kWh"``, etc. are reserved for later).
    """

    field: str
    per: str = "hour"


@dataclass(frozen=True)
class EscrowTemplate:
    """One ``[escrow_templates.<name>]`` table.

    ``name`` is the TOML table key — CSV cells reference templates by
    this identifier. ``chain`` must match a configured ``[chains.<name>]``
    entry. ``escrow_address`` is resolved at config-load time: a literal
    ``0x...`` string passes through; an ``auto:<obligation-kind>`` value
    routes through the chain's alkahest address config (override JSON
    when present, alkahest-py SDK default otherwise).

    ``literal_fields`` covers obligation-data keys whose values are
    fixed by the operator. ``rate_slots`` covers fields whose values
    scale per ``per`` unit; the dict is order-preserving so single-slot
    ergonomic sugar (drop the slot name in the CSV cell when only one
    slot exists) has a well-defined target.
    """

    name: str
    chain: str
    escrow_address: str
    literal_fields: dict[str, Any]
    rate_slots: dict[str, RateSlot]


# Maps the ``auto:<obligation-kind>`` suffix to ``(category_attr, field)``
# on the alkahest address config tree. Keep in sync with
# ``service.clients.alkahest._ADDRESS_CATEGORIES``. Tierable/nontierable
# split mirrors the contract names; attestation v2 lives in the same
# ``attestation_addresses`` category as v1.
_AUTO_ESCROW_LOOKUP: dict[str, tuple[str, str]] = {
    "erc20_nontierable":         ("erc20_addresses", "escrow_obligation_nontierable"),
    "erc20_tierable":            ("erc20_addresses", "escrow_obligation_tierable"),
    "erc721_nontierable":        ("erc721_addresses", "escrow_obligation_nontierable"),
    "erc721_tierable":           ("erc721_addresses", "escrow_obligation_tierable"),
    "erc1155_nontierable":       ("erc1155_addresses", "escrow_obligation_nontierable"),
    "erc1155_tierable":          ("erc1155_addresses", "escrow_obligation_tierable"),
    "native_token_nontierable":  ("native_token_addresses", "escrow_obligation_nontierable"),
    "native_token_tierable":     ("native_token_addresses", "escrow_obligation_tierable"),
    "token_bundle_nontierable":  ("token_bundle_addresses", "escrow_obligation_nontierable"),
    "token_bundle_tierable":     ("token_bundle_addresses", "escrow_obligation_tierable"),
    "attestation_nontierable":   ("attestation_addresses", "escrow_obligation"),
    "attestation2_nontierable":  ("attestation_addresses", "escrow_obligation2"),
}


def _resolve_auto_escrow(
    auto_key: str,
    chain: ChainConfig,
) -> str:
    """Resolve an ``auto:<obligation-kind>`` reference to a concrete address.

    Raises ``ValueError`` when the auto key is unrecognised, the chain
    lacks alkahest support, or the resolved address slot is the zero
    address (contract not deployed on this chain).
    """
    if auto_key not in _AUTO_ESCROW_LOOKUP:
        valid = ", ".join(sorted(_AUTO_ESCROW_LOOKUP))
        raise ValueError(
            f"unknown auto: escrow kind {auto_key!r}; expected one of: {valid}"
        )
    category, field = _AUTO_ESCROW_LOOKUP[auto_key]
    from service.clients.alkahest import (
        _load_override_config,
        _sdk_addresses_for_chain,
        get_alkahest_network,
        NETWORK_ANVIL,
    )

    override = _load_override_config(chain.alkahest_address_config_path)
    if override is not None:
        cat = override.get(category)
        if not isinstance(cat, dict) or field not in cat:
            raise ValueError(
                f"auto:{auto_key} not present in {chain.alkahest_address_config_path} "
                f"(missing {category}.{field})"
            )
        addr = str(cat[field])
    else:
        selected = get_alkahest_network(chain.name)
        if selected == NETWORK_ANVIL:
            raise ValueError(
                f"auto:{auto_key} on chain {chain.name!r}: anvil requires "
                f"alkahest_address_config_path"
            )
        cfg = _sdk_addresses_for_chain(selected)
        category_obj = getattr(cfg, category, None)
        if category_obj is None or not hasattr(category_obj, field):
            raise ValueError(
                f"auto:{auto_key}: alkahest SDK has no {category}.{field} for "
                f"chain {chain.name!r}"
            )
        addr = str(getattr(category_obj, field))
    if not addr.startswith("0x") or int(addr, 16) == 0:
        raise ValueError(
            f"auto:{auto_key} on chain {chain.name!r}: resolved to zero address "
            "(contract not deployed)"
        )
    return addr


def escrow_templates_from_config(
    config: Optional[dict[str, Any]] = None,
    *,
    chains: Optional[dict[str, ChainConfig]] = None,
) -> dict[str, EscrowTemplate]:
    """Return every ``[escrow_templates.<name>]`` table from the merged TOML.

    Each template's ``chain`` must match a key in ``chains``; templates
    referencing an unknown chain are dropped with a stderr warning so a
    typo never silently changes which escrow the publish path picks.
    ``escrow_address`` values starting with ``auto:`` resolve through the
    chain's alkahest address config; literal ``0x...`` values pass
    through unchanged.

    Invalid templates (missing chain, unresolvable auto: key, malformed
    rates) are dropped with a warning rather than raising, so a bad
    template never prevents the operator from starting the storefront.
    """
    cfg = config if config is not None else load_user_config()
    raw = cfg.get("escrow_templates")
    if not isinstance(raw, dict):
        return {}
    if chains is None:
        chains = chains_from_config(cfg)

    out: dict[str, EscrowTemplate] = {}
    for name, sub in raw.items():
        if not isinstance(name, str) or not isinstance(sub, dict):
            continue
        chain_name = str(sub.get("chain", "") or "").strip()
        if not chain_name:
            print(
                f"[config] escrow_templates.{name}: missing 'chain'; skipping",
                file=sys.stderr,
            )
            continue
        chain_cfg = chains.get(chain_name)
        if chain_cfg is None:
            print(
                f"[config] escrow_templates.{name}: unknown chain {chain_name!r}; "
                f"skipping",
                file=sys.stderr,
            )
            continue
        raw_addr = str(sub.get("escrow_address", "") or "").strip()
        if not raw_addr:
            print(
                f"[config] escrow_templates.{name}: missing 'escrow_address'; "
                f"skipping",
                file=sys.stderr,
            )
            continue
        if raw_addr.startswith("auto:"):
            try:
                escrow_address = _resolve_auto_escrow(raw_addr[len("auto:"):], chain_cfg)
            except ValueError as exc:
                print(
                    f"[config] escrow_templates.{name}: {exc}; skipping",
                    file=sys.stderr,
                )
                continue
        else:
            escrow_address = raw_addr
        literal_raw = sub.get("literal") or {}
        if not isinstance(literal_raw, dict):
            print(
                f"[config] escrow_templates.{name}: 'literal' must be a table; skipping",
                file=sys.stderr,
            )
            continue
        literal_fields = dict(literal_raw)

        rates_raw = sub.get("rates") or {}
        if not isinstance(rates_raw, dict):
            print(
                f"[config] escrow_templates.{name}: 'rates' must be a table; skipping",
                file=sys.stderr,
            )
            continue
        rate_slots: dict[str, RateSlot] = {}
        slot_ok = True
        for slot_name, slot_sub in rates_raw.items():
            if not isinstance(slot_name, str) or not isinstance(slot_sub, dict):
                continue
            field_name = str(slot_sub.get("field", "") or "").strip()
            if not field_name:
                print(
                    f"[config] escrow_templates.{name}.rates.{slot_name}: "
                    f"missing 'field'; skipping template",
                    file=sys.stderr,
                )
                slot_ok = False
                break
            per_unit = str(slot_sub.get("per", "hour") or "hour").strip() or "hour"
            rate_slots[slot_name] = RateSlot(field=field_name, per=per_unit)
        if not slot_ok:
            continue

        out[name] = EscrowTemplate(
            name=name,
            chain=chain_name,
            escrow_address=escrow_address,
            literal_fields=literal_fields,
            rate_slots=rate_slots,
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
