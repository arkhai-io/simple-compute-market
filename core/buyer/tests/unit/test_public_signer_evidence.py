"""Public protocol identities are evidence; private signer carriers are refused."""

import base64
import uuid

import pytest
from market_identity import Ed25519Signer

from core_buyer.run_log import RunLog, RunLogError, read_run, runs_dir


def test_nested_public_signer_evidence_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # Deterministic development identities; never use on a public network.
    buyer = Ed25519Signer(b"\x11" * 32)
    producer = Ed25519Signer(b"\x12" * 32)
    log = RunLog.start(profile_id=uuid.uuid4(), principal=buyer.identity)
    evidence = {
        "payload": "public evidence",
        "signer": producer.identity.model_dump(mode="json"),
        "proof": {
            "scheme": "ed25519",
            "value": base64.urlsafe_b64encode(producer.sign(b"public evidence")).rstrip(b"=").decode(),
        },
    }
    log.event("delivery_end", acknowledgement={"signed_claim": evidence})
    events = read_run(log.run_id, signer=buyer)
    assert events[-1]["acknowledgement"]["signed_claim"] == evidence


@pytest.mark.parametrize("signer_value", [
    "PRIVATE-SIGNER-CANARY",
    Ed25519Signer(b"\x12" * 32),
    {"scheme": "ed25519", "identifier": "invalid"},
    {"scheme": "unsupported", "identifier": "public"},
    {
        "scheme": "ed25519",
        "identifier": Ed25519Signer(b"\x12" * 32).identity.identifier,
        "private_key": "PRIVATE-SIGNER-CANARY",
    },
    {"scheme": "eip191", "identifier": "0x" + "AB" * 20},
    {"scheme": "ed25519", "identifier": {"credential": "PRIVATE-SIGNER-CANARY"}},
])
def test_nonpublic_signer_carriers_are_rejected_before_writing(monkeypatch, tmp_path, signer_value):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # Deterministic development identity; never use on a public network.
    buyer = Ed25519Signer(b"\x11" * 32)
    with pytest.raises(RunLogError, match="credential or signer field"):
        RunLog.start(
            profile_id=uuid.uuid4(), principal=buyer.identity,
            evidence={"nested": {"signer": signer_value}},
        )
    assert not list(runs_dir().glob("*.jsonl"))


def test_public_signer_does_not_hide_a_nested_private_sibling(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # Deterministic development identity; never use on a public network.
    buyer = Ed25519Signer(b"\x11" * 32)
    log = RunLog.start(profile_id=uuid.uuid4(), principal=buyer.identity)
    with pytest.raises(RunLogError, match="credential or signer field"):
        log.event("delivery_end", acknowledgement={
            "signer": buyer.identity.model_dump(mode="json"),
            "nested": {"api_key": "PRIVATE-SIGNER-CANARY"},
        })
    assert len(read_run(log.run_id, signer=buyer)) == 1
    assert "PRIVATE-SIGNER-CANARY" not in log.path.read_text()
