"""Per-user install role marker.

A marker file at `~/.market/role` contains one of:
    "buyer"   — pure client: no agent, no server, no on-chain registration
    "seller"  — full stack: agent + registry + on-chain identity + provisioning
    (absent) — treated as "unset" in code; the CLI shows all commands so
               developers working from a checkout aren't surprised.

Written by `market install` / `market install --seller`. Read at CLI
startup to decide which subcommands to register.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

Role = Literal["buyer", "seller", "unset"]

ROLE_FILE = Path.home() / ".market" / "role"

_VALID_ROLES = {"buyer", "seller"}


def get_role() -> Role:
    """Return the current install role, or 'unset' if no marker is present.

    Unknown contents (anything other than 'buyer' / 'seller') also return
    'unset' so a corrupted marker never hides commands.
    """
    try:
        raw = ROLE_FILE.read_text().strip()
    except FileNotFoundError:
        return "unset"
    except OSError:
        return "unset"
    if raw in _VALID_ROLES:
        return raw  # type: ignore[return-value]
    return "unset"


def set_role(role: Role) -> Path:
    """Persist the install role. Returns the path it was written to."""
    if role not in _VALID_ROLES:
        raise ValueError(f"Invalid role {role!r}; expected one of {_VALID_ROLES}")
    ROLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROLE_FILE.write_text(role + "\n")
    return ROLE_FILE


def clear_role() -> Optional[Path]:
    """Delete the marker file (if present). Returns the path or None."""
    try:
        ROLE_FILE.unlink()
        return ROLE_FILE
    except FileNotFoundError:
        return None
