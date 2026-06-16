"""`market tokens settle --from` delivers issued credentials to the run-log.

Drives ``run_settle_from_log`` off a synthetic run-log with an agreed
negotiation and an already-created escrow (stage 3 skipped), with the
settle submit/poll HTTP patched at the tokens module seam. The
once-only secret must land durably in the run-log
(``credentials_delivered``) — that file is the buyer's only copy.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import domains.apitokens.buyer.settle_cli as settle_cli
from core_buyer.run_log import read_run


_PROPOSAL = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "cd" * 20,
    "fields": {"amount": 300, "token": "0x" + "ab" * 20},
    "literal_fields": {"token": "0x" + "ab" * 20},
    "rates": [],
    "demands": [],
    "expiration_unix": 1_800_000_000,
}

_CREDENTIALS = {
    "key_id": "ak_test_1",
    "secret": "sk_live_once_only",
    "base_url": "http://api.example:8080",
    "balance": 100,
}


@pytest.fixture
def agreed_run(tmp_path, monkeypatch):
    """A run-log holding an agreed token negotiation + created escrow."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    runs = tmp_path / "arkhai" / "buy-runs"
    runs.mkdir(parents=True)
    events = [
        {"event": "run_started", "run_id": "run-tok-1",
         "command": "market tokens negotiate",
         "seller_url": "http://seller:8002", "listing_id": "lst-1",
         "quantity": 100, "key_mode": "new", "chain_name": "anvil"},
        {"event": "run_ended", "run_id": "run-tok-1", "status": "agreed",
         "negotiation_id": "neg-1", "agreed_amount": 300,
         "accepted_escrow_proposal": _PROPOSAL},
        {"event": "escrow_created", "run_id": "run-tok-1",
         "escrow_uid": "0x" + "ee" * 32, "chain_name": "anvil"},
    ]
    path = runs / "run-tok-1.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return "run-tok-1"


@pytest.fixture
def fake_chain_config(monkeypatch):
    import domains.apitokens.buyer.common as common

    chain = SimpleNamespace(
        name="anvil",
        rpc_url="http://anvil:8545",
        chain_id=31337,
        alkahest_address_config_path=None,
    )
    monkeypatch.setattr(common, "chain_by_name", lambda name: chain)
    monkeypatch.setattr(
        common, "resolve_buyer_wallet",
        lambda **_kw: ("0x" + "cc" * 20, "0x" + "11" * 32),
    )
    return chain


def test_settle_writes_credentials_delivered_event(
    agreed_run, fake_chain_config, monkeypatch,
):
    submitted: dict = {}

    def fake_submit(**kw):
        submitted.update(kw)
        return {"status": "queued"}

    monkeypatch.setattr(settle_cli, "submit_settlement", fake_submit)
    monkeypatch.setattr(
        settle_cli, "wait_for_settlement",
        lambda **kw: {
            "status": "ready",
            "fulfillment_uid": "0x" + "ff" * 32,
            "tenant_credentials": dict(_CREDENTIALS),
        },
    )

    final = settle_cli.run_settle_from_log(
        run_id=agreed_run,
        escrow_uid=None,
        buyer_address=None,
        buyer_private_key=None,
        chain_name=None,
        poll_interval=0.01,
        settlement_timeout=5.0,
    )
    assert final["status"] == "ready"
    # Token deals carry no SSH key; the wire field defaults to "".
    assert "ssh_public_key" not in submitted

    events = read_run(agreed_run)
    delivered = [e for e in events if e.get("event") == "credentials_delivered"]
    assert len(delivered) == 1
    assert delivered[0]["credentials"] == _CREDENTIALS
    # Terminal status recorded too.
    assert any(
        e.get("event") == "run_ended" and e.get("status") == "ready"
        for e in events
    )


def test_settle_without_agreed_proposal_refuses(tmp_path, monkeypatch, fake_chain_config):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    runs = tmp_path / "arkhai" / "buy-runs"
    runs.mkdir(parents=True)
    events = [
        {"event": "run_started", "run_id": "run-tok-2",
         "seller_url": "http://seller:8002", "listing_id": "lst-1",
         "chain_name": "anvil"},
        {"event": "run_ended", "run_id": "run-tok-2", "status": "agreed",
         "negotiation_id": "neg-2", "agreed_amount": 300},
    ]
    (runs / "run-tok-2.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n"
    )

    import typer

    with pytest.raises(typer.Exit):
        settle_cli.run_settle_from_log(
            run_id="run-tok-2",
            escrow_uid=None,
            buyer_address=None,
            buyer_private_key=None,
            chain_name=None,
            poll_interval=0.01,
            settlement_timeout=5.0,
        )
