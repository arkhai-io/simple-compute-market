from __future__ import annotations

import pytest

from market_identity import (
    Ed25519Signer,
    Eip191Signer,
    RequestEnvelope,
    Signer,
    canonical_body_hash,
)

ED25519_SEED = bytes(range(32))
EIP191_KEY = bytes.fromhex(
    "5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
)
NOW = 1_900_000_000
BODY = {"amount": 17, "items": ["cpu", "memory"], "metadata": {"a": 1, "z": 2}}


@pytest.fixture
def ed25519_signer() -> Ed25519Signer:
    return Ed25519Signer(ED25519_SEED)


@pytest.fixture
def eip191_signer() -> Eip191Signer:
    return Eip191Signer(EIP191_KEY)


@pytest.fixture(params=("ed25519", "eip191"))
def signer(request: pytest.FixtureRequest) -> Signer:
    if request.param == "ed25519":
        return Ed25519Signer(ED25519_SEED)
    return Eip191Signer(EIP191_KEY)


@pytest.fixture
def request_envelope(signer: Signer) -> RequestEnvelope:
    return RequestEnvelope(
        role="buyer",
        principal=signer.identity,
        method="post",
        operation="negotiation.advance",
        resource="negotiation/thread-17",
        request_id="7f0ed41b-6ad8-4a1f-94dc-80691c28b841",
        timestamp=NOW,
        body_hash=canonical_body_hash(BODY),
    )
