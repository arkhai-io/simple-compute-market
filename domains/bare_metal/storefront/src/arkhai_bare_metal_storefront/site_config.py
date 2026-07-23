"""Trusted provisioning-site bindings for the bare-metal storefront."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, cast
from urllib.parse import urlsplit, urlunsplit

_SITE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SiteConfigurationError(ValueError):
    """Configured site bindings are malformed or ambiguous."""


@dataclass(frozen=True)
class TrustedSiteBinding:
    """Operator-owned connection authority for one stable site identity."""

    site_id: str
    authority_url: str
    admin_key: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TrustedSiteBinding":
        unknown = set(raw) - {"site_id", "authority_url", "admin_key"}
        if unknown:
            raise SiteConfigurationError(
                "unknown site binding fields: " + ", ".join(sorted(unknown)),
            )
        site_id = str(raw.get("site_id") or "").strip()
        if not _SITE_ID.fullmatch(site_id):
            raise SiteConfigurationError(
                "site_id must be 1-128 characters using letters, digits, '.', '_', or '-'",
            )
        authority_url = _normalize_authority_url(raw.get("authority_url"))
        admin_key = str(raw.get("admin_key") or "").strip()
        if not admin_key:
            raise SiteConfigurationError(
                f"site {site_id!r} requires a non-empty admin_key",
            )
        return cls(
            site_id=site_id,
            authority_url=authority_url,
            admin_key=admin_key,
        )

    def diagnostic(self) -> dict[str, object]:
        """Return operational presence only, never routing or secret material."""
        return {
            "site_id": self.site_id,
            "authority_configured": True,
            "credential_configured": True,
        }


@dataclass(frozen=True)
class TrustedSiteBindings:
    """Immutable site-indexed configuration with uniqueness guarantees."""

    bindings: tuple[TrustedSiteBinding, ...] = ()

    def __post_init__(self) -> None:
        site_ids = [binding.site_id for binding in self.bindings]
        if len(site_ids) != len(set(site_ids)):
            raise SiteConfigurationError("site_id values must be unique")

    @property
    def by_site_id(self) -> Mapping[str, TrustedSiteBinding]:
        return MappingProxyType({binding.site_id: binding for binding in self.bindings})

    def diagnostic(self) -> tuple[dict[str, object], ...]:
        return tuple(binding.diagnostic() for binding in self.bindings)


def _normalize_authority_url(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SiteConfigurationError(
            "authority_url must be an absolute http or https URL",
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SiteConfigurationError(
            "authority_url must not contain credentials, a query, or a fragment",
        )
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def parse_trusted_site_bindings(raw: str | None) -> TrustedSiteBindings:
    """Parse a JSON array from trusted process configuration.

    An absent or blank value keeps pre-fulfillment mode available. If the
    variable is present, every entry is validated and any ambiguity fails
    process startup.
    """
    if raw is None or not raw.strip():
        return TrustedSiteBindings()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SiteConfigurationError(
            f"site bindings are not valid JSON: {exc.msg}",
        ) from exc
    if not isinstance(payload, list):
        raise SiteConfigurationError("site bindings must be a JSON array")
    bindings: list[TrustedSiteBinding] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise SiteConfigurationError(
                f"site binding at index {index} must be an object",
            )
        bindings.append(
            TrustedSiteBinding.from_mapping(
                cast(Mapping[str, Any], item),
            ),
        )
    return TrustedSiteBindings(tuple(bindings))
