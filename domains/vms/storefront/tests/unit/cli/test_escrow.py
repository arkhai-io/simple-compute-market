from __future__ import annotations

from types import SimpleNamespace

import typer
from market_identity import Ed25519Signer

from storefront_client.fixtures.escrow import build_claim_response, build_refund_response
from tests._settings_overrides import settings_overrides

from .conftest import fake_chain

_BUYER_PRINCIPAL = Ed25519Signer(b"\x41" * 32).identity


def test_escrow_claim_storefront_error(monkeypatch, runner, app):
    import market_storefront.groups.escrow as escrow_group

    monkeypatch.setattr(
        escrow_group,
        "_submit_claim",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(typer.Exit(1)),
    )

    result = runner.invoke(
        app,
        [
            "escrow",
            "claim",
            "listing-001",
            "--escrow-uid",
            "0xESCROW",
            "--fulfillment-uid",
            "0xFULF",
        ],
    )

    assert result.exit_code == 1


def test_escrow_claim_bad_status(monkeypatch, runner, app):
    import market_storefront.groups.escrow as escrow_group

    monkeypatch.setattr(escrow_group, "_submit_claim", lambda *_args, **_kwargs: {"status": "error"})

    result = runner.invoke(
        app,
        [
            "escrow",
            "claim",
            "listing-001",
            "--escrow-uid",
            "0xESCROW",
            "--fulfillment-uid",
            "0xFULF",
        ],
    )

    assert result.exit_code == 7


def test_escrow_claim_happy_path_propagates_arguments(monkeypatch, runner, app):
    import market_storefront.groups.escrow as escrow_group

    calls: list[tuple] = []
    monkeypatch.setattr(
        escrow_group,
        "_submit_claim",
        lambda *args: calls.append(args) or build_claim_response(),
    )

    result = runner.invoke(
        app,
        [
            "escrow",
            "claim",
            "listing-001",
            "--escrow-uid",
            "0xESCROW",
            "--fulfillment-uid",
            "0xFULF",
            "--storefront-url",
            "http://seller.test",
        ],
    )

    assert result.exit_code == 0
    assert "claimed" in result.output.lower()
    assert calls == [
        ("http://seller.test", "listing-001", "0xESCROW", "0xFULF")
    ]


def test_escrow_refund_storefront_error(monkeypatch, runner, app):
    import market_storefront.groups.escrow as escrow_group

    monkeypatch.setattr(
        escrow_group,
        "_submit_refund",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(typer.Exit(1)),
    )

    result = runner.invoke(
        app,
        [
            "escrow",
            "refund",
            "listing-001",
            "--buyer",
            "0xBUYER",
            "--buyer-scheme",
            _BUYER_PRINCIPAL.scheme.value,
            "--buyer-identifier",
            _BUYER_PRINCIPAL.identifier,
        ],
    )

    assert result.exit_code == 1


def test_escrow_refund_bad_status(monkeypatch, runner, app):
    import market_storefront.groups.escrow as escrow_group

    monkeypatch.setattr(escrow_group, "_submit_refund", lambda *_args, **_kwargs: {"status": "error"})

    result = runner.invoke(
        app,
        [
            "escrow",
            "refund",
            "listing-001",
            "--buyer",
            "0xBUYER",
            "--buyer-scheme",
            _BUYER_PRINCIPAL.scheme.value,
            "--buyer-identifier",
            _BUYER_PRINCIPAL.identifier,
        ],
    )

    assert result.exit_code == 6


def test_escrow_refund_happy_path_propagates_arguments(monkeypatch, runner, app):
    import market_storefront.groups.escrow as escrow_group

    calls: list[tuple] = []
    monkeypatch.setattr(
        escrow_group,
        "_submit_refund",
        lambda *args: calls.append(args) or build_refund_response(),
    )
    monkeypatch.setattr("market_alkahest.token.render_token", lambda _token, **_kwargs: "MOCK")

    result = runner.invoke(
        app,
        [
            "escrow",
            "refund",
            "listing-001",
            "--buyer",
            "0xBUYER",
            "--buyer-scheme",
            _BUYER_PRINCIPAL.scheme.value,
            "--buyer-identifier",
            _BUYER_PRINCIPAL.identifier,
            "--amount",
            "1000",
            "--token",
            "0xTOKEN",
            "--storefront-url",
            "http://seller.test",
        ],
    )

    assert result.exit_code == 0
    assert "refunded" in result.output.lower()
    assert calls == [
        (
            "http://seller.test",
            "listing-001",
            _BUYER_PRINCIPAL,
            "0xBUYER",
            "1000",
            "0xTOKEN",
        )
    ]


def test_escrow_show_no_chains(monkeypatch, runner, app):
    monkeypatch.setattr("market_storefront.utils.config.CHAINS", {})

    result = runner.invoke(app, ["escrow", "show", "--escrow-uid", "0xUID"])

    assert result.exit_code == 2
    assert "chain" in result.output.lower()


def test_escrow_show_multi_chain_no_flag(monkeypatch, runner, app):
    monkeypatch.setattr(
        "market_storefront.utils.config.CHAINS",
        {"anvil": fake_chain("anvil"), "base_sepolia": fake_chain("base_sepolia")},
    )

    result = runner.invoke(app, ["escrow", "show", "--escrow-uid", "0xUID"])

    assert result.exit_code == 2
    assert "chain" in result.output.lower()


def test_escrow_show_unknown_chain(monkeypatch, runner, app):
    monkeypatch.setattr("market_storefront.utils.config.CHAINS", {"anvil": fake_chain("anvil")})

    result = runner.invoke(app, ["escrow", "show", "--escrow-uid", "0xUID", "--chain", "bogus"])

    assert result.exit_code == 2
    assert "bogus" in result.output or "not configured" in result.output.lower()


def test_escrow_show_no_private_key(monkeypatch, runner, app):
    monkeypatch.setattr("market_storefront.utils.config.CHAINS", {"anvil": fake_chain("anvil")})

    with settings_overrides(**{"wallet.private_key": ""}):
        result = runner.invoke(app, ["escrow", "show", "--escrow-uid", "0xUID"])

    assert result.exit_code == 2
    assert "private_key" in result.output or "wallet" in result.output.lower()


def test_escrow_show_prewarm_fails(monkeypatch, runner, app, private_key):
    monkeypatch.setattr("market_storefront.utils.config.CHAINS", {"anvil": fake_chain("anvil")})
    monkeypatch.setattr(
        "market_alkahest.alkahest.prewarm_alkahest_address_config_cache",
        lambda _path: (_ for _ in ()).throw(RuntimeError("address config not found")),
    )

    with settings_overrides(**{"wallet.private_key": private_key}):
        result = runner.invoke(app, ["escrow", "show", "--escrow-uid", "0xUID"])

    assert result.exit_code == 2
    assert "address config not found" in result.output


def test_escrow_show_get_obligation_fails(patch_escrow_show_prereqs, runner, app, private_key):
    patch_escrow_show_prereqs(error=RuntimeError("escrow not found"))

    with settings_overrides(**{"wallet.private_key": private_key}):
        result = runner.invoke(app, ["escrow", "show", "--escrow-uid", "0xUID"])

    assert result.exit_code == 4
    assert "escrow not found" in result.output


def test_escrow_show_happy_path(patch_escrow_show_prereqs, runner, app, private_key):
    fake_attestation = SimpleNamespace(
        uid="0xUID",
        schema="0xSCHEMA",
        attester="0xATTESTER",
        recipient="0xRECIPIENT",
        time=1700000000,
        expiration_time=0,
        revocation_time=0,
        ref_uid="0x0",
        revocable=True,
    )
    fake_obligation = {"token": "0xTOKEN", "amount": 1000}
    fake_codec = SimpleNamespace(kind="ERC20EscrowObligation")
    patch_escrow_show_prereqs(decoded=(fake_codec, {"attestation": fake_attestation, "data": fake_obligation}))

    with settings_overrides(**{"wallet.private_key": private_key}):
        result = runner.invoke(app, ["escrow", "show", "--escrow-uid", "0xUID", "--escrow-address", "0xESCROW"])

    assert result.exit_code == 0
    assert "0xUID" in result.output
    assert "ERC20EscrowObligation" in result.output
