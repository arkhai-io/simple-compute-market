"""Helpers for matching registry URLs across config keys and runtime values.

[registry.auth] in the TOML is a free-form table where keys are URLs and
values are bearer tokens. Operators frequently mis-key it — wrong case,
extra trailing slash, mixed scheme — and the resulting silent
unauthenticated requests then 401 against a "public" config.

Normalize both sides (the auth dict keys at load time, and the URL the
caller is looking up at request time) so the dict lookup is robust to
those surface differences. Path / query / fragment are preserved; only
the parts users actually trip over (scheme case, host case, trailing
slash on the authority) get normalized away.
"""
from __future__ import annotations

from typing import Mapping, Optional
from urllib.parse import urlsplit, urlunsplit


def normalize_registry_url(url: str) -> str:
    """Return a canonical form for a registry URL.

    Rules:
      - scheme lowercased
      - host lowercased
      - port left as-is (it's authoritative, not display)
      - trailing slash stripped from the path when the path is empty or "/"
      - everything else (path beyond /, query, fragment) preserved verbatim

    No URL is rejected — this is best-effort canonicalization, not
    validation. A malformed input round-trips to whatever urlsplit/
    urlunsplit make of it. Empty strings round-trip to empty.
    """
    if not url:
        return url
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    # urlsplit puts userinfo into netloc; we lowercase the whole netloc
    # so host case is normalized without untangling userinfo (which is
    # rare for registry URLs and case-sensitive anyway).
    netloc = parts.netloc.lower()
    path = parts.path
    if path in ("", "/"):
        path = ""
    return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))


def normalize_auth_map(auth: Optional[Mapping[str, str]]) -> dict[str, str]:
    """Return a new dict with every key passed through normalize_registry_url.

    Later entries win if normalization collapses two keys to the same
    canonical form — but that's an operator config bug, so we don't try
    to be clever about it.
    """
    out: dict[str, str] = {}
    if not auth:
        return out
    for raw_key, value in auth.items():
        if not isinstance(raw_key, str):
            continue
        out[normalize_registry_url(raw_key)] = str(value)
    return out


def lookup_registry_auth(
    auth: Optional[Mapping[str, str]],
    url: str,
) -> Optional[str]:
    """Look up a bearer token for ``url`` in a [registry.auth] map.

    Both the map keys and the lookup URL get normalized first, so
    differences in case or trailing slash don't cause a miss.
    Returns None when no entry matches or the matched value is empty.
    """
    if not auth:
        return None
    normalized = normalize_auth_map(auth)
    token = normalized.get(normalize_registry_url(url))
    return token or None
