"""`market credits settle --from` delivers issued credentials to the run-log.

Drives ``run_settle_from_log`` off a synthetic run-log with an agreed
negotiation and an already-created escrow (stage 3 skipped), with the
settle submit/poll HTTP patched at the credits module seam. The
once-only secret must land durably in the run-log
(``credentials_delivered``) — that file is the buyer's only copy.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

import domains.apicredits.buyer.settle_cli as settle_cli
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.run_log import read_run
from market_identity import Eip191Signer, REQUEST_PROTOCOL, TrustedIdentitySet


_PROPOSAL = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "cd" * 20,
    "fields": {"amount": 300, "token": "0x" + "ab" * 20},
    "literal_fields": {"token": "0x" + "ab" * 20},
    "rates": [],
    "demands": [],
    "expiration_unix": 1_800_000_000,
}
_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
_SELLER_SIGNER = Eip191Signer(bytes.fromhex("22" * 32))
_PROFILE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
_IDENTITY = ResolvedBuyerIdentity(
    profile_id=_PROFILE_ID,
    principal=_SIGNER.identity,
    signer=_SIGNER,
    source="recovery",
)

_CREDENTIALS = {
    "key_id": "ak_test_1",
    "secret": "sk_live_once_only",
    "base_url": "http://api.example:8080",
    "balance": 100,
}


def _run_event(run_id: str, event: str, **fields) -> dict:
    return {
        "event": event,
        "run_id": run_id,
        "log_version": 3,
        "signature_protocol": REQUEST_PROTOCOL,
        "signature_version": 2,
        "buyer_profile_id": str(_PROFILE_ID),
        "buyer_principal": _SIGNER.identity.model_dump(mode="json"),
        **fields,
    }


@pytest.fixture
def agreed_run(tmp_path, monkeypatch):
    """A run-log holding an agreed token negotiation + created escrow."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    runs = tmp_path / "arkhai" / "buy-runs"
    runs.mkdir(parents=True)
    events = [
        _run_event(
            "run-tok-1",
            "run_started",
            command="market credits negotiate",
            seller_url="http://seller:8002",
            listing_id="lst-1",
            quantity=100,
            key_mode="new",
            chain_name="anvil",
            publisher_id="publisher-1",
            source_registry_url="http://registry:8080",
            source_registry_authority="registry-1",
        ),
        _run_event(
            "run-tok-1",
            "run_ended",
            status="agreed",
            publisher_principals=TrustedIdentitySet(
                identities=(_SELLER_SIGNER.identity,),
            ).model_dump(mode="json"),
            negotiation_id="neg-1",
            agreed_amount=300,
            accepted_escrow_proposal=_PROPOSAL,
        ),
        _run_event(
            "run-tok-1",
            "escrow_created",
            escrow_uid="0x" + "ee" * 32,
            chain_name="anvil",
        ),
    ]
    path = runs / "run-tok-1.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return "run-tok-1"


@pytest.fixture
def fake_chain_config(monkeypatch):
    import domains.apicredits.buyer.common as common

    chain = SimpleNamespace(
        name="anvil",
        rpc_url="http://anvil:8545",
        chain_id=31337,
        alkahest_address_config_path=None,
    )
    monkeypatch.setattr(common, "chain_by_name", lambda name: chain)
    monkeypatch.setattr(
        common,
        "resolve_buyer_wallet",
        lambda **_kw: ("0x" + "cc" * 20, "0x" + "11" * 32),
    )
    trust = TrustedIdentitySet(identities=(_SELLER_SIGNER.identity,))
    monkeypatch.setattr(
        common,
        "make_run_publisher_principals_refresh",
        lambda *_args, **_kwargs: lambda *_binding: trust,
    )
    monkeypatch.setattr(
        common,
        "resolve_indexer_urls",
        lambda: ["http://registry:8080"],
    )
    monkeypatch.setattr(
        common,
        "resolve_registry_authorities",
        lambda _urls: {"http://registry:8080": object()},
    )
    monkeypatch.setattr(common, "resolve_registry_api_keys", lambda: {})
    monkeypatch.setattr(common, "resolve_discovery_timeout", lambda: 5.0)
    import core_buyer.orchestration as buyer_orchestration

    monkeypatch.setattr(
        buyer_orchestration,
        "make_publisher_trust_resolver",
        lambda **_kwargs: lambda: trust,
    )
    return chain


def test_settle_writes_credentials_delivered_event(
    agreed_run,
    fake_chain_config,
    monkeypatch,
):
    submitted: dict = {}

    def fake_submit(**kw):
        submitted.update(kw)
        return {"status": "queued"}

    monkeypatch.setattr(settle_cli, "submit_settlement_request", fake_submit)
    monkeypatch.setattr(
        settle_cli,
        "wait_for_settlement",
        lambda **kw: {
            "status": "ready",
            "fulfillment_uid": "0x" + "ff" * 32,
            "tenant_credentials": dict(_CREDENTIALS),
        },
    )

    final = settle_cli.run_settle_from_log(
        run_id=agreed_run,
        escrow_uid=None,
        identity=_IDENTITY,
        evm_address=None,
        evm_private_key=None,
        chain_name=None,
        poll_interval=0.01,
        settlement_timeout=5.0,
    )
    assert final["status"] == "ready"
    # Credit deals carry no SSH key; the wire field defaults to "".
    assert "ssh_public_key" not in submitted

    events = read_run(agreed_run)
    delivered = [e for e in events if e.get("event") == "credentials_delivered"]
    assert len(delivered) == 1
    assert delivered[0]["credentials"] == _CREDENTIALS
    serialized_events = json.dumps(events)
    assert "11" * 32 not in serialized_events
    assert "signer" not in serialized_events
    assert "private_key" not in serialized_events
    # Terminal status recorded too.
    assert any(
        e.get("event") == "run_ended" and e.get("status") == "ready" for e in events
    )


def test_settle_without_agreed_proposal_refuses(
    tmp_path, monkeypatch, fake_chain_config
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    runs = tmp_path / "arkhai" / "buy-runs"
    runs.mkdir(parents=True)
    events = [
        _run_event(
            "run-tok-2",
            "run_started",
            seller_url="http://seller:8002",
            listing_id="lst-1",
            chain_name="anvil",
            publisher_id="publisher-1",
            source_registry_url="http://registry:8080",
            source_registry_authority="registry-1",
        ),
        _run_event(
            "run-tok-2",
            "run_ended",
            status="agreed",
            negotiation_id="neg-2",
            agreed_amount=300,
            publisher_principals=TrustedIdentitySet(
                identities=(_SELLER_SIGNER.identity,),
            ).model_dump(mode="json"),
        ),
    ]
    (runs / "run-tok-2.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n"
    )

    import typer

    with pytest.raises(typer.Exit):
        settle_cli.run_settle_from_log(
            run_id="run-tok-2",
            escrow_uid=None,
            identity=_IDENTITY,
            evm_address=None,
            evm_private_key=None,
            chain_name=None,
            poll_interval=0.01,
            settlement_timeout=5.0,
        )
