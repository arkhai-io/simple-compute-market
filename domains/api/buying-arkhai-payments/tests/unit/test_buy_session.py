"""The payments buy session reads the payer account once, only while payments is enabled."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from arkhai_api_buying.stages import BuyRequest
from rich.console import Console

from arkhai_api_buying_arkhai_payments.stage import PaymentBuyerStage

ACCOUNT = "00000000-0000-4000-8000-000000000011"


def _request(enabled: bool) -> BuyRequest:
    return BuyRequest(
        identity=SimpleNamespace(),
        settlement=SimpleNamespace(),
        policy=SimpleNamespace(),
        enabled=enabled,
        options={},
        assume_yes=True,
        console=Console(),
    )


def test_an_enabled_session_reads_the_configured_section():
    reads: list[str] = []

    def config():
        reads.append("read")
        return {"example": {"payer_account": ACCOUNT}}

    session = PaymentBuyerStage("example", load_config=config).open_buy(_request(True))
    session.prepare()
    assert session.available and reads == ["read"]
    assert session.missing() == ()
    assert session.scale_explicit_prices(2, 3, []) == (2, 3)
    assert session.run_fields() == {} and session.header_rows() == ()


def test_a_disabled_session_reads_no_account():
    def config():
        raise AssertionError("payer account read")

    session = PaymentBuyerStage("example", load_config=config).open_buy(_request(False))
    assert not session.available


def test_an_invalid_account_refuses_the_buy():
    stage = PaymentBuyerStage("example", load_config=lambda: {"example": {"payer_account": "nope"}})
    with pytest.raises(ValueError):
        stage.open_buy(_request(True))


def test_acceptance_needs_the_agreement_and_its_mandate():
    stage = PaymentBuyerStage("example")
    with pytest.raises(ValueError, match="exact Agreement"):
        stage.validate_acceptance(SimpleNamespace(agreement=None, agreement_bytes=None))
    with pytest.raises(ValueError, match="mandate"):
        stage.validate_acceptance(
            SimpleNamespace(agreement={"a": 1}, agreement_bytes="b", settlement_data={})
        )
