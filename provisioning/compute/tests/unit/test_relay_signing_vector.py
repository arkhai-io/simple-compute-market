"""The family signer consumes the standalone plugin's published contract.

The vector's deterministic keys are public offline fixtures. They must never be
used on any network. Only signing and thumbprint cases belong to this consumer;
the standalone verifier owns its verification cases.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from compute_provisioning.relays.grants import sign_compact
from compute_provisioning.relays.keys import thumbprint


VECTOR_PATH = (
    Path(__file__).resolve().parents[4]
    / "tools/frp-grant-admission/vector/frp-grant-1.json"
)
VECTOR = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
KEYS = {key["name"]: key for key in VECTOR["keys"]}


@pytest.mark.parametrize("case", VECTOR["signing"], ids=lambda case: case["name"])
def test_family_signer_reproduces_published_token(case):
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(KEYS[case["key"]]["seed"]))
    assert sign_compact(case["header"], case["claims"], key) == case["token"]


def test_family_key_id_reproduces_published_thumbprint():
    case = VECTOR["thumbprint"]
    public_key = serialization.load_der_public_key(
        base64.b64decode(case["public_key_spki_base64"], validate=True)
    )
    assert thumbprint(public_key) == case["kid"]
