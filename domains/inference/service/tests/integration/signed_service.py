"""The inference service composed with signed authentication; its modules resolve configuration at import."""

from __future__ import annotations

import importlib
import json
import sys
import time
import uuid
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Any

from arkhai_api_authority import create_db_engine, migrate_database
from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    RequestEnvelope,
    canonical_body_hash,
    sign_request,
)

# Deterministic development seeds for these tests only; never used on any network.
AUTHORITY_SEED = b"inference-authority-seed-32byte!"
AUTHORITY = Ed25519Signer(AUTHORITY_SEED)
STOREFRONT_SIGNER = Ed25519Signer(b"inference-storefront-seed-32-by!")
GATEWAY_SIGNER = Ed25519Signer(b"inference-gateway-seed-32-bytes!")
IMPOSTOR_SIGNER = Ed25519Signer(b"inference-impostor-seed-32-byte!")
OPERATOR_SIGNER = Ed25519Signer(b"inference-operator-seed-32-byte!")

SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"

_MODULES = (
    "inference_service.main",
    "inference_service.identity",
    "inference_service.config",
    "inference_service.container",
)


def load_signed_app(directory: Path, monkeypatch) -> Any:
    seed_file = directory / "site.ed25519"
    seed_file.write_bytes(urlsafe_b64encode(AUTHORITY_SEED).rstrip(b"=") + b"\n")
    (directory / "config.yml").write_text("")
    monkeypatch.setenv("CONFIG_DIRECTORY", str(directory))
    monkeypatch.setenv("INFERENCE_DATABASE_URL", f"sqlite:///{directory / 'inference.db'}")
    monkeypatch.setenv("INFERENCE_SITE_SIGNING_KEY_FILE", str(seed_file))
    monkeypatch.setenv(
        "INFERENCE_TRUSTED_PRINCIPALS",
        "@json "
        + json.dumps(
            {
                "seller": [STOREFRONT_SIGNER.identity.model_dump(mode="json")],
                "service": [GATEWAY_SIGNER.identity.model_dump(mode="json")],
                "admin": [OPERATOR_SIGNER.identity.model_dump(mode="json")],
            }
        ),
    )
    unload_service_modules()
    main = importlib.import_module("inference_service.main")
    migrate_service_database(directory / "inference.db")
    importlib.import_module("inference_service.container").init()
    return main.app


def migrate_service_database(path: Path) -> None:
    """Build the database as the service's migration command does; startup refuses any other."""
    chain = importlib.import_module("inference_service.migrate").CHAIN
    engine = create_db_engine(f"sqlite:///{path}", is_sqlite=True)
    try:
        migrate_database(engine, chain)
    finally:
        engine.dispose()


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
    timestamp: int | None = None,
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
            timestamp=int(time.time()) if timestamp is None else timestamp,
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
