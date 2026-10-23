"""The credits service composed with signed authentication; its modules resolve configuration at import."""

from __future__ import annotations

import importlib
import json
import sys
import time
import uuid
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Any

from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    RequestEnvelope,
    canonical_body_hash,
    sign_request,
)

# Deterministic development seeds for these tests only; never used on any network.
AUTHORITY_SEED = b"credits-authority-seed-32-byte!!"
AUTHORITY = Ed25519Signer(AUTHORITY_SEED)
STOREFRONT_SIGNER = Ed25519Signer(b"credits-storefront-seed-32-byte!")
GATED_SIGNER = Ed25519Signer(b"credits-gatedapp-seed-32-bytes!!")
IMPOSTOR_SIGNER = Ed25519Signer(b"credits-impostor-seed-32-bytes!!")

SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"

_MODULES = (
    "apicredits_service.main",
    "apicredits_service.identity",
    "apicredits_service.config",
    "apicredits_service.container",
)


def load_signed_app(directory: Path, monkeypatch) -> Any:
    seed_file = directory / "site.ed25519"
    seed_file.write_bytes(urlsafe_b64encode(AUTHORITY_SEED).rstrip(b"=") + b"\n")
    (directory / "config.yml").write_text("")
    monkeypatch.setenv("CONFIG_DIRECTORY", str(directory))
    monkeypatch.setenv("APICREDITS_DATABASE_URL", f"sqlite:///{directory / 'credits.db'}")
    monkeypatch.setenv("APICREDITS_SITE_SIGNING_KEY_FILE", str(seed_file))
    monkeypatch.setenv(
        "APICREDITS_TRUSTED_PRINCIPALS",
        "@json "
        + json.dumps(
            {
                "seller": [STOREFRONT_SIGNER.identity.model_dump(mode="json")],
                "service": [GATED_SIGNER.identity.model_dump(mode="json")],
            }
        ),
    )
    unload_service_modules()
    main = importlib.import_module("apicredits_service.main")
    importlib.import_module("apicredits_service.container").init()
    return main.app


def unload_service_modules() -> None:
    for name in _MODULES:
        sys.modules.pop(name, None)


def signed_headers(
    *,
    signer: Ed25519Signer,
    role: str,
    method: str,
    operation: str,
    resource: str,
    body: Any = EMPTY_BODY,
    request_id: str | None = None,
) -> dict[str, str]:
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method=method.upper(),
            operation=operation,
            resource=resource,
            request_id=request_id or str(uuid.uuid4()),
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        SIGNATURE_VERSION_HEADER: authenticated.protocol,
        IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        ROLE_HEADER: authenticated.role,
        REQUEST_ID_HEADER: authenticated.request_id,
        TIMESTAMP_HEADER: str(authenticated.timestamp),
        SIGNATURE_HEADER: authenticated.proof.value,
    }
