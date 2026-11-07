"""Gate configuration.

A middleware is a seller-side component: it holds the operator's
``admin_api_key`` and talks to the credits service the same way the
storefront does. The ``purchase`` pointer is the only buyer-facing
data — it rides the 402/403 body so a client whose credits ran out
knows where to buy more (the re-purchase loop).
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PurchasePointer:
    """Where a client buys more credits, embedded in exhaustion bodies.

    All fields optional — a seller fills what it wants to expose. The
    registry + listing let a buyer's ``market credits buy`` re-discover
    the offering; ``service_name`` is human sugar.
    """

    service_name: str | None = None
    listing_id: str | None = None
    storefront_url: str | None = None
    registry_url: str | None = None

    def as_body(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in ("service_name", "listing_id", "storefront_url", "registry_url"):
            v = getattr(self, k)
            if v:
                out[k] = v
        return out


@dataclass(frozen=True)
class GateConfig:
    """Everything the gate needs, independent of the web framework.

    ``amount_per_request`` is charged per gated request (a flat
    one-token-per-call meter in v1; richer per-route metering is a
    later upgrade). Batching is opt-in: with ``flush_interval_seconds``
    at 0 (the default) every charge is a synchronous consume, which
    keeps behavior deterministic and the overdraft window zero. Set it
    positive to batch charges above ``low_balance_threshold`` and flush
    them on the interval; charges that would bring the estimated
    balance to within the threshold of zero stay synchronous so
    exhaustion still surfaces immediately.
    """

    service_url: str
    admin_key: str = ""
    identity_credential: str = ""
    identity_scheme: str = "ed25519"
    authority_principals: str = ""
    max_response_skew: int = 300
    amount_per_request: int = 1
    verify_ttl_seconds: float = 30.0
    low_balance_threshold: int = 0
    flush_interval_seconds: float = 0.0
    flush_max_batch: int = 256
    request_timeout_seconds: float = 10.0
    purchase: PurchasePointer = field(default_factory=PurchasePointer)

    @property
    def signing_enabled(self) -> bool:
        """Whether a signing credential was configured.

        Presence of the credential is the switch, mirroring the service's
        own `signed_authentication_enabled()`. The two must be flipped
        together: the service accepts signed requests or the shared secret,
        never both, so a middleware signing at a service that is not, or
        the reverse, is refused at every route.
        """
        return bool(self.identity_credential)

    def build_signing(self) -> Any:
        """Resolve the signing context, or ``None`` when not configured.

        Raises `SigningConfigurationError` when a credential is present but
        unusable, or when the authority principals are missing. Failing here
        is deliberate: a gated app configured to sign but unable to is
        misconfigured, and discovering that at startup is better than
        denying every request at runtime with a verification error.
        """
        if not self.signing_enabled:
            return None
        from .signing import (
            AuthoritySigning,
            build_signer,
            build_trusted_authorities,
        )

        return AuthoritySigning(
            signer=build_signer(self.identity_credential, self.identity_scheme),
            expected_authorities=build_trusted_authorities(
                self.authority_principals
            ),
            max_response_skew=self.max_response_skew,
        )

    @classmethod
    def from_env(cls, prefix: str = "APICREDITS_MIDDLEWARE_") -> "GateConfig":
        """Build from ``<PREFIX>*`` environment variables.

        Recognised: ``SERVICE_URL``, exactly one of ``ADMIN_KEY`` or
        ``ADMIN_KEY_FILE``, exactly one of ``IDENTITY_CREDENTIAL`` or
        ``IDENTITY_CREDENTIAL_FILE``, ``IDENTITY_SCHEME``,
        ``AUTHORITY_PRINCIPALS``, ``MAX_RESPONSE_SKEW``,
        ``AMOUNT_PER_REQUEST``, ``VERIFY_TTL_SECONDS``,
        ``LOW_BALANCE_THRESHOLD``, ``FLUSH_INTERVAL_SECONDS``,
        ``FLUSH_MAX_BATCH``, ``REQUEST_TIMEOUT_SECONDS``, and the purchase
        pointer ``PURCHASE_SERVICE_NAME`` / ``PURCHASE_LISTING_ID`` /
        ``PURCHASE_STOREFRONT_URL`` / ``PURCHASE_REGISTRY_URL``.
        """

        def _get(name: str, default: str = "") -> str:
            return os.environ.get(prefix + name, default)

        def _int(name: str, default: int) -> int:
            raw = _get(name)
            try:
                return int(raw) if raw else default
            except ValueError:
                return default

        def _float(name: str, default: float) -> float:
            raw = _get(name)
            try:
                return float(raw) if raw else default
            except ValueError:
                return default

        def _secret(name: str) -> str:
            """Read ``<NAME>`` inline or ``<NAME>_FILE`` from disk.

            The file form is the deployment convention: credentials arrive
            as read-only bind mounts, which is also why the file is read
            directly rather than through
            `market_identity.SecretFileCredentialProvider` -- that provider
            refuses group- or world-readable files, and a mounted
            credential is routinely 0644.

            Stripped, because a file written elsewhere may be newline
            terminated and `create_signer` requires canonical unpadded
            base64url.
            """
            inline = _get(name)
            file_name = _get(name + "_FILE")
            if inline and file_name:
                raise ValueError(
                    f"{name} and {name}_FILE are mutually exclusive"
                )
            if inline:
                return inline
            if not file_name:
                return ""
            path = Path(file_name)
            try:
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError(f"{name}_FILE must be a regular file")
                value = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ValueError(f"{name}_FILE cannot be read") from exc
            if not value:
                raise ValueError(f"{name}_FILE is empty")
            return value

        return cls(
            service_url=_get("SERVICE_URL", "http://localhost:8082").rstrip("/"),
            admin_key=_secret("ADMIN_KEY"),
            identity_credential=_secret("IDENTITY_CREDENTIAL"),
            identity_scheme=_get("IDENTITY_SCHEME", "ed25519"),
            authority_principals=_get("AUTHORITY_PRINCIPALS"),
            max_response_skew=_int("MAX_RESPONSE_SKEW", 300),
            amount_per_request=_int("AMOUNT_PER_REQUEST", 1),
            verify_ttl_seconds=_float("VERIFY_TTL_SECONDS", 30.0),
            low_balance_threshold=_int("LOW_BALANCE_THRESHOLD", 0),
            flush_interval_seconds=_float("FLUSH_INTERVAL_SECONDS", 0.0),
            flush_max_batch=_int("FLUSH_MAX_BATCH", 256),
            request_timeout_seconds=_float("REQUEST_TIMEOUT_SECONDS", 10.0),
            purchase=PurchasePointer(
                service_name=_get("PURCHASE_SERVICE_NAME") or None,
                listing_id=_get("PURCHASE_LISTING_ID") or None,
                storefront_url=_get("PURCHASE_STOREFRONT_URL") or None,
                registry_url=_get("PURCHASE_REGISTRY_URL") or None,
            ),
        )
