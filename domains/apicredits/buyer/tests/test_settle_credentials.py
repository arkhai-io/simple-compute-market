"""`market credits settle --from` keeps an issued key private, and `credentials show` reads it.

Drives settlement through the plugin's composition off a synthetic run-log
with an agreed negotiation and an already-created escrow, with the settle
submit/poll HTTP patched at the Alkahest stage's seam. The secret is kept in
the buyer's private credential store; the run-log records only the key's
non-secret fields and the store's reference.
"""

from __future__ import annotations

import base64
import json
import logging
import stat
import uuid
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

import arkhai_api_buying.buy as buy
import arkhai_api_buying.commands as commands
import arkhai_api_buying.settlement_composition as settlement_composition
import arkhai_api_buying.stages as stages
import arkhai_api_buying_alkahest.stage as alkahest_stage
from arkhai_api_buying.settle import run_settle_from_log
from arkhai_apicredits_buyer.cli import SETTLEMENT, app
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.negotiation_client import AuthenticatedHTTPError
from core_buyer.run_log import RunLog, read_run
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import REQUEST_PROTOCOL, Eip191Signer, TrustedIdentitySet


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

# A canary secret for these tests only; it is not a real key.
_SECRET = "sk_canary_never_logged"
_CREDENTIALS = {
    "key_id": "ak_test_1",
    "secret": _SECRET,
    "base_url": "http://api.example:8080",
    "balance": 100,
}


def _run_event(run_id: str, event: str, **fields) -> dict:
    if fields.get("status") == "agreed":
        params = {"accepted_escrow": dict(_PROPOSAL)}
        option = SettlementOption(
            option_id=derive_settlement_option_id(mechanism="alkahest.v1", asset="token", rates=[], params=params),
            mechanism="alkahest.v1", asset="token", rates=[], params=params,
        )
        agreement = Agreement(
            negotiation_id=fields["negotiation_id"], listing_id="lst-1", listing_hash="0"*64,
            buyer=_SIGNER.identity.model_dump(mode="json"), seller=_SELLER_SIGNER.identity.model_dump(mode="json"),
            settlement=option, amount=300, asset="token", duration_seconds=0,
            start_utc="2025-01-01T00:00:00Z", accepted_at="2025-01-01T00:00:00Z",
        )
        fields["agreement"] = agreement.model_dump(mode="json")
        fields["agreement_bytes"] = base64.b64encode(agreement.model_dump_json().encode()).decode()
        fields["settlement_selection"] = {"mechanism": option.mechanism, "option_id": option.option_id,
                                          "expiration_unix": 1_800_000_000}
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
            settlement_selection={
                "mechanism": "alkahest.v1",
                "option_id": "legacy-alkahest",
                "expiration_unix": 1_800_000_000,
            },
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
    import arkhai_api_buying.common as common

    chain = SimpleNamespace(
        name="anvil",
        rpc_url="http://anvil:8545",
        chain_id=31337,
        alkahest_address_config_path=None,
    )
    monkeypatch.setattr(alkahest_stage, "chain_by_name", lambda name: chain)
    monkeypatch.setattr(
        alkahest_stage,
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
    monkeypatch.setattr(
        stages,
        "make_publisher_trust_resolver",
        lambda **_kwargs: lambda: trust,
    )
    return chain


def test_settle_keeps_the_secret_in_the_private_store(
    agreed_run,
    fake_chain_config,
    tmp_path,
    monkeypatch,
):
    submitted: dict = {}

    def fake_submit(**kw):
        submitted.update(kw)
        return {"status": "queued"}

    monkeypatch.setattr(alkahest_stage, "submit_settlement_request", fake_submit)
    monkeypatch.setattr(
        alkahest_stage,
        "wait_for_settlement",
        lambda **kw: {
            "status": "ready",
            "fulfillment_uid": "0x" + "ff" * 32,
            "tenant_credentials": dict(_CREDENTIALS),
        },
    )

    final = run_settle_from_log(
        SETTLEMENT,
        run_id=agreed_run,
        identity=_IDENTITY,
        options={},
        poll_interval=0.01,
        settlement_timeout=5.0,
    )
    assert final["status"] == "ready"
    # Credit deals carry no SSH key; the wire field defaults to "".
    assert "ssh_public_key" not in submitted

    events = read_run(agreed_run)
    (delivered,) = [e for e in events if e.get("event") == "credentials_delivered"]
    assert delivered["key_id"] == "ak_test_1"
    assert delivered["base_url"] == _CREDENTIALS["base_url"]
    assert delivered["delivery_ref"] == f"file:{agreed_run}"
    serialized_events = json.dumps(events)
    assert _SECRET not in serialized_events
    assert "11" * 32 not in serialized_events
    assert "signer" not in serialized_events
    assert "private_key" not in serialized_events
    assert any(
        e.get("event") == "run_ended" and e.get("status") == "ready" for e in events
    )
    stored = tmp_path / "arkhai" / "buy-credentials" / f"{agreed_run}.json"
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert json.loads(stored.read_text())["credentials"] == _CREDENTIALS


@pytest.fixture
def secret_everywhere(agreed_run, fake_chain_config, monkeypatch):
    """A seller whose submit response, polls, and terminal status all carry the canary secret."""
    ready = {
        "status": "ready",
        "fulfillment_uid": "0x" + "ff" * 32,
        "tenant_credentials": dict(_CREDENTIALS),
    }
    monkeypatch.setattr(
        alkahest_stage, "submit_settlement_request", lambda **_kw: dict(ready),
    )

    def fake_wait(*, on_poll, **_kw):
        on_poll(1, {"status": "provisioning"})
        on_poll(2, dict(ready))
        return dict(ready)

    monkeypatch.setattr(alkahest_stage, "wait_for_settlement", fake_wait)
    monkeypatch.setattr(commands.common, "resolve_recovery_buyer_identity", lambda _run: _IDENTITY)
    return agreed_run


def _settle(run_id: str):
    return CliRunner().invoke(app, ["credits", "settle", "--from", run_id])


def test_the_secret_reaches_only_the_store_and_the_panel(secret_everywhere, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)

    result = _settle(secret_everywhere)

    assert result.exit_code == 0, (result.output, result.exception)
    run_log = (tmp_path / "arkhai" / "buy-runs" / f"{secret_everywhere}.jsonl").read_text()
    assert "settle_status" in run_log and "settle_terminal" in run_log
    assert _SECRET not in run_log
    assert _SECRET not in caplog.text
    before, _, rest = result.output.partition("API key issued")
    panel, hint, after = rest.partition("Read it again")
    assert hint
    assert _SECRET not in before
    assert panel.count(_SECRET) == 1
    assert _SECRET not in after
    assert (tmp_path / "arkhai" / "buy-credentials" / f"{secret_everywhere}.json").exists()


def test_a_failed_private_write_shows_the_key_once_and_exits_8(secret_everywhere, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "arkhai" / "buy-credentials").symlink_to(elsewhere)

    result = _settle(secret_everywhere)

    assert result.exit_code == 8, (result.output, result.exception)
    assert result.output.count(_SECRET) == 1
    assert "NOT SAVED" in result.output
    events = read_run(secret_everywhere)
    (unsaved,) = [e for e in events if e.get("event") == "credentials_unsaved"]
    assert unsaved["error"] == "CredentialStoreError"
    assert not [e for e in events if e.get("event") == "credentials_delivered"]
    assert _SECRET not in json.dumps(events)
    assert list(elsewhere.iterdir()) == []


def test_a_seller_error_carrying_the_secret_reaches_neither_log_nor_output(
    agreed_run, fake_chain_config, tmp_path, monkeypatch, caplog,
):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(commands.common, "resolve_recovery_buyer_identity", lambda _run: _IDENTITY)
    body = {"status": "ready", "tenant_credentials": dict(_CREDENTIALS)}

    def refused(**_kw):
        raise AuthenticatedHTTPError(
            f"POST http://seller:8002/api/v1/settle -> authenticated HTTP 409: {json.dumps(body)}",
            status_code=409, body=body,
        )

    monkeypatch.setattr(alkahest_stage, "submit_settlement_request", refused)

    result = _settle(agreed_run)

    assert result.exit_code == 5, (result.output, result.exception)
    run_log = (tmp_path / "arkhai" / "buy-runs" / f"{agreed_run}.jsonl").read_text()
    assert "settle_submit_failed" in run_log
    assert _SECRET not in run_log
    assert _SECRET not in result.output
    assert _SECRET not in caplog.text
    assert "authenticated HTTP 409" in result.output

def test_a_status_poll_error_carrying_the_secret_reaches_neither_log_nor_output(
    agreed_run, fake_chain_config, tmp_path, monkeypatch, caplog,
):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(commands.common, "resolve_recovery_buyer_identity", lambda _run: _IDENTITY)
    body = {"status": "ready", "tenant_credentials": dict(_CREDENTIALS)}

    def refused(**_kw):
        raise AuthenticatedHTTPError(
            f"GET http://seller:8002/api/v1/settle/x/status -> authenticated HTTP 409: {json.dumps(body)}",
            status_code=409, body=body,
        )

    monkeypatch.setattr(alkahest_stage, "submit_settlement_request", lambda **_kw: {"status": "queued"})
    monkeypatch.setattr(alkahest_stage, "wait_for_settlement", refused)

    result = _settle(agreed_run)

    assert result.exit_code == 5, (result.output, result.exception)
    run_log = (tmp_path / "arkhai" / "buy-runs" / f"{agreed_run}.jsonl").read_text()
    assert "settle_status_failed" in run_log and '"status":"error"' in run_log
    assert _SECRET not in run_log + result.output + caplog.text


def test_a_run_log_refusing_the_polled_body_still_saves_and_shows_the_key(
    secret_everywhere, tmp_path, monkeypatch,
):
    real = RunLog.event

    def refuse_bodies(self, event, **fields):
        if "tenant_credentials" in json.dumps(fields):
            raise OSError("disk full")
        real(self, event, **fields)

    monkeypatch.setattr(RunLog, "event", refuse_bodies)

    result = _settle(secret_everywhere)

    assert result.exit_code == 0, (result.output, result.exception)
    assert result.output.count(_SECRET) == 1
    assert (tmp_path / "arkhai" / "buy-credentials" / f"{secret_everywhere}.json").exists()


def test_credentials_show_prefers_the_stored_key_to_a_legacy_copy(secret_everywhere, tmp_path):
    path = tmp_path / "arkhai" / "buy-runs" / f"{secret_everywhere}.jsonl"
    with path.open("a") as stream:
        stream.write(json.dumps(_run_event(
            secret_everywhere, "credentials_delivered",
            credentials={**_CREDENTIALS, "secret": "sk_legacy_copy"},
        )) + "\n")
    SETTLEMENT.credential_store.save(secret_everywhere, _CREDENTIALS)

    as_json = _show(secret_everywhere, "--json")

    assert json.loads(as_json.output)["secret"] == _SECRET
    assert json.loads(as_json.output)["source"] == "store"


def _show(run_id: str, *extra: str):
    return CliRunner().invoke(app, ["credits", "credentials", "show", "--from", run_id, *extra])


def test_credentials_show_reads_the_stored_key(secret_everywhere):
    assert _settle(secret_everywhere).exit_code == 0

    shown = _show(secret_everywhere)
    as_json = _show(secret_everywhere, "--json")

    assert shown.exit_code == 0, (shown.output, shown.exception)
    assert _SECRET in shown.output and "ak_test_1" in shown.output
    assert as_json.exit_code == 0, (as_json.output, as_json.exception)
    assert json.loads(as_json.output) == {
        "run_id": secret_everywhere,
        "key_id": "ak_test_1",
        "secret": _SECRET,
        "base_url": _CREDENTIALS["base_url"],
        "balance": 100,
        "source": "store",
    }


def test_credentials_show_reads_a_run_recorded_before_private_storage(
    secret_everywhere, tmp_path,
):
    path = tmp_path / "arkhai" / "buy-runs" / f"{secret_everywhere}.jsonl"
    with path.open("a") as stream:
        stream.write(json.dumps(_run_event(
            secret_everywhere, "credentials_delivered", credentials=dict(_CREDENTIALS),
        )) + "\n")
    before = path.read_text()

    shown = _show(secret_everywhere)
    as_json = _show(secret_everywhere, "--json")

    assert shown.exit_code == 0, (shown.output, shown.exception)
    assert "held in the run log" in " ".join(shown.output.split())
    assert json.loads(as_json.output)["source"] == "run_log"
    assert json.loads(as_json.output)["secret"] == _SECRET
    assert path.read_text() == before


def test_credentials_show_finds_a_saved_key_its_run_log_never_recorded(secret_everywhere):
    SETTLEMENT.credential_store.save(secret_everywhere, _CREDENTIALS)

    as_json = _show(secret_everywhere, "--json")

    assert as_json.exit_code == 0, (as_json.output, as_json.exception)
    assert json.loads(as_json.output)["secret"] == _SECRET
    assert json.loads(as_json.output)["source"] == "store"

def test_credentials_show_refuses_a_run_with_no_delivery(secret_everywhere):
    shown = _show(secret_everywhere)

    assert shown.exit_code == 1
    assert "records no delivered credential" in shown.output


def test_credentials_show_refuses_an_unknown_run(secret_everywhere, monkeypatch):
    def unknown(_run):
        raise commands.RunLogError("run log is empty")

    monkeypatch.setattr(commands.common, "resolve_recovery_buyer_identity", unknown)

    shown = _show("no-such-run")

    assert shown.exit_code == 1
    assert "cannot be read" in shown.output


@pytest.mark.parametrize(
    ("reference", "message"),
    [("keyring:run-tok-1", "is not held by the file store"), ("file:run-tok-1", "holds no key")],
    ids=["another scheme", "a removed record"],
)
def test_credentials_show_refuses_a_reference_the_store_cannot_answer(
    secret_everywhere, tmp_path, reference, message,
):
    path = tmp_path / "arkhai" / "buy-runs" / f"{secret_everywhere}.jsonl"
    with path.open("a") as stream:
        stream.write(json.dumps(_run_event(
            secret_everywhere, "credentials_delivered", key_id="ak_test_1", delivery_ref=reference,
        )) + "\n")

    shown = _show(secret_everywhere)

    assert shown.exit_code == 1
    assert message in " ".join(shown.output.split())


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
            settlement_selection={
                "mechanism": "alkahest.v1",
                "option_id": "legacy-alkahest",
                "expiration_unix": 1_800_000_000,
            },
        ),
    ]
    (runs / "run-tok-2.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n"
    )

    with pytest.raises(typer.Exit):
        run_settle_from_log(
            SETTLEMENT,
            run_id="run-tok-2",
            identity=_IDENTITY,
            options={},
            poll_interval=0.01,
            settlement_timeout=5.0,
        )


_CONDITION = {
    "chain_name": "anvil",
    "arbiter": "0x" + "55" * 20,
    "demand_data": {"recipient": "0x" + "44" * 20},
}


@pytest.mark.parametrize(
    ("proposal", "reason"),
    [
        (_PROPOSAL, "release_condition_unselected"),
        ({**_PROPOSAL, "demands": None, "demand": _CONDITION}, "not the listing that authorizes"),
    ],
    ids=["naming no condition", "selecting a condition"],
)
def test_settle_creates_no_escrow_from_an_accepted_proposal_alone(
    tmp_path, monkeypatch, fake_chain_config, proposal, reason
):
    """A run-log records the accepted proposal but not the listing that
    authorizes its release condition, so with no accepted escrow terms the
    resumed settlement refuses by name and nothing reaches the chain."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    runs = tmp_path / "arkhai" / "buy-runs"
    runs.mkdir(parents=True)
    events = [
        _run_event(
            "run-tok-3",
            "run_started",
            seller_url="http://seller:8002",
            listing_id="lst-1",
            chain_name="anvil",
            publisher_id="publisher-1",
            source_registry_url="http://registry:8080",
            source_registry_authority="registry-1",
        ),
        _run_event(
            "run-tok-3",
            "run_ended",
            status="agreed",
            negotiation_id="neg-3",
            agreed_amount=300,
            publisher_principals=TrustedIdentitySet(
                identities=(_SELLER_SIGNER.identity,),
            ).model_dump(mode="json"),
            accepted_escrow_proposal=proposal,
            settlement_selection={
                "mechanism": "alkahest.v1",
                "option_id": "legacy-alkahest",
                "expiration_unix": 1_800_000_000,
            },
        ),
    ]
    (runs / "run-tok-3.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n"
    )

    def _no_escrow(**_kwargs):
        def refuse(_terms):
            raise AssertionError("an escrow was created without its release condition")

        return refuse

    monkeypatch.setattr(alkahest_stage, "make_create_escrow_fn", _no_escrow)

    with pytest.raises(typer.Exit) as refused:
        run_settle_from_log(
            SETTLEMENT,
            run_id="run-tok-3",
            identity=_IDENTITY,
            options={},
            poll_interval=0.01,
            settlement_timeout=5.0,
        )

    assert refused.value.exit_code == 3
    (missing,) = [
        e for e in read_run("run-tok-3") if e.get("event") == "escrow_release_condition_missing"
    ]
    assert reason in missing["error"]


def test_buy_from_resumes_an_accepted_run_with_no_mechanism_enabled(
    agreed_run,
    fake_chain_config,
    monkeypatch,
):
    """Enablement gates only a fresh deal; a run accepted under Alkahest completes after it is disabled."""
    monkeypatch.setattr(buy, "resolve_recovery_buyer_identity", lambda _run: _IDENTITY)
    monkeypatch.setattr(
        settlement_composition,
        "load_user_config",
        lambda: {"Settlement": {"schema_version": 1, "priority": [], "alkahest": {"enabled": False}}},
    )
    monkeypatch.setattr(alkahest_stage, "submit_settlement_request", lambda **_kw: {"status": "queued"})
    monkeypatch.setattr(
        alkahest_stage,
        "wait_for_settlement",
        lambda **_kw: {"status": "ready", "fulfillment_uid": "0x" + "ff" * 32},
    )

    result = CliRunner().invoke(app, ["credits", "buy", "--from", agreed_run, "--yes"])

    assert result.exit_code == 0, (result.output, result.exception)
    assert any(
        e.get("event") == "run_ended" and e.get("status") == "ready" for e in read_run(agreed_run)
    )
