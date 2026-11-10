"""
The application's configuration: the layered settings, with its secrets resolved.

The settings resolve as ``apicredits_service.settings_source`` describes; a
mounted storefront TOML is a further fallback for `storefront_admin_key`, below
every configured source (see below). Everything here resolves at import, so an
unreadable secret fails while an operator is watching.

storefront_admin_key resolution:
  ``storefront_admin_key_file`` selects one exact role-scoped secret file.
  Inline and file values are mutually exclusive. The historical mounted
  storefront-TOML fallback remains for non-Compose deployments that have not
  selected either explicit source.
"""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path
from typing import List

from dynaconf import Dynaconf

from apicredits_service.settings_source import load_settings_source

_dynaconf = load_settings_source()


def _resolve_storefront_admin_key_from_mount() -> str:
    """Read `admin_api_key` from a mounted storefront TOML, if present.

    Returns the value or "" if no candidate file exists or the key is
    missing. Errors (malformed TOML, permission denied) fall back
    silently so a misconfigured mount can't crash service startup.
    """
    candidates: List[Path] = []
    override = os.environ.get("STOREFRONT_TOML_PATH", "").strip()
    if override:
        candidates.append(Path(override))
    candidates.append(Path("/etc/arkhai/storefront.toml"))

    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            continue
        key = data.get("admin_api_key")
        if isinstance(key, str) and key:
            return key
    return ""


def _read_admin_key_file(file_name: str) -> str:
    path = Path(file_name)
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("storefront_admin_key_file must be a regular file")
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("storefront_admin_key_file cannot be read") from exc
    if not value:
        raise RuntimeError("storefront_admin_key_file is empty")
    return value


_inline_key = str(_dynaconf.get("storefront_admin_key", "") or "")
_key_file = str(_dynaconf.get("storefront_admin_key_file", "") or "")
if _inline_key and _key_file:
    raise RuntimeError(
        "storefront_admin_key and storefront_admin_key_file are mutually exclusive"
    )
if _key_file:
    _dynaconf.set("storefront_admin_key", _read_admin_key_file(_key_file))
elif not _inline_key:
    _fallback_key = _resolve_storefront_admin_key_from_mount()
    if _fallback_key:
        _dynaconf.set("storefront_admin_key", _fallback_key)


class Settings:
    """Thin wrapper around dynaconf that adds typed accessors."""

    def __init__(self, source: Dynaconf) -> None:
        self._source = source

    def __getattr__(self, name: str):  # type: ignore[override]
        return getattr(self._source, name)

    @property
    def is_sqlite(self) -> bool:
        return str(self._source.database_url).startswith("sqlite")


settings = Settings(_dynaconf)
