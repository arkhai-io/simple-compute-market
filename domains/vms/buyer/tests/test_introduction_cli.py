"""VM buyers reach settlement by introduction through the mechanism's commands."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer
from arkhai_vms_buyer import introduction_cli
from arkhai_vms_buyer.cli import register
from arkhai_vms_buyer.settlement_composition import buyer_settlement_registry
from core_buyer.introductions import IntroductionPayloadsDeleted
from market_core.schemas import derive_settlement_option_id


def test_the_mechanism_commands_and_request_introduction_are_registered() -> None:

    app = typer.Typer()
    register(app)
    names = {command.name for command in app.registered_commands}
    assert "request-introduction" in names
    contact = buyer_settlement_registry().registration("contact-exchange.v1")
    assert contact.command_group is not None
    commands = {command.name for command in contact.command_group.registered_commands}
    assert commands == {"introduce", "introduction"}


def test_the_deleted_outcome_is_the_transports() -> None:
    assert introduction_cli.IntroductionContext.deleted_error is IntroductionPayloadsDeleted


def _listing(option: dict) -> dict:
    return {
        "storefront_url": "https://seller.invalid",
        "publisher_id": "publisher-1",
        "publisher_principals": {
            "identities": [{"scheme": "eip191", "identifier": "0x" + "22" * 20}]
        },
        "settlement_options": [option],
    }


def _option(mechanism: str, rates: list) -> dict:

    params = {"profile": "default"}
    return {
        "option_id": derive_settlement_option_id(
            mechanism=mechanism, asset="introduction", rates=rates, params=params
        ),
        "mechanism": mechanism,
        "asset": "introduction",
        "rates": rates,
        "params": params,
    }


@pytest.mark.parametrize(
    ("option", "message"),
    [
        (_option("alkahest.v1", []), "not a rateless introduction"),
        (_option("contact-exchange.v1", []), None),
    ],
)
def test_only_an_advertised_rateless_introduction_is_negotiated(
    monkeypatch, option: dict, message: str | None
) -> None:
    identity = SimpleNamespace(profile_id="profile-1", principal=None, signer=object())
    monkeypatch.setattr(introduction_cli, "resolve_fresh_buyer_identity", lambda: identity)
    monkeypatch.setattr(
        introduction_cli,
        "_trusted_listing",
        lambda listing_id, signer: (_listing(option), "https://registry.invalid", "registry-a"),
    )
    negotiated: list[dict] = []

    class Stop(Exception):
        pass

    def fake_negotiate(**kwargs):
        negotiated.append(kwargs)
        raise Stop

    monkeypatch.setattr(introduction_cli, "negotiate_with_seller", fake_negotiate)
    monkeypatch.setattr(
        introduction_cli.RunLog, "start", classmethod(lambda cls, **kwargs: SimpleNamespace())
    )
    if message is not None:
        with pytest.raises(typer.BadParameter, match=message):
            introduction_cli.request_introduction("listing-1", option_id=option["option_id"])
        assert negotiated == []
        return
    with pytest.raises(Stop):
        introduction_cli.request_introduction(
            "listing-1",
            option_id=option["option_id"],
            duration_seconds=3600,
            expiration_seconds=3600,
            max_rounds=10,
        )
    (call,) = negotiated
    assert call["initial_price"] == 0.0 and call["max_price"] == 0.0
    assert call["provision_terms"].ssh_public_key == ""
    assert call["settlement_selection"].mechanism == "contact-exchange.v1"
