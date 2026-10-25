"""The buyer composition reads every mechanism step through the stage table it is given."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from market_core import SettlementStageTable
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer

import inspect

from arkhai_api_buying.settlement_composition import BuyerSettlementComposition
from arkhai_api_buying.stages import StageOption
from tests.bundles import CONTRIBUTIONS

# Deterministic development keys for these tests only; never used on any network.
BUYER = Ed25519Signer(bytes(range(32))).identity
SELLER = Ed25519Signer(bytes(range(1, 33))).identity


class Codec:
    def encode_proposal(self, proposal: Any) -> dict[str, Any]:
        return {"encoded": proposal}

    def decode_proposal(self, value: Any) -> Any:
        return ("proposal", value)

    def decode_terms(self, value: Any) -> Any:
        return ("terms", value)


class Stage:
    def __init__(self, mechanism_id: str, *, codec: Any = None, options: tuple = ()) -> None:
        self.mechanism_id = mechanism_id
        self.escrow_codec = codec
        self.options = options
        self.accepted: list[Any] = []

    def chain_config_paths(self) -> dict[str, str | None]:
        return {self.mechanism_id: None}

    def validate_acceptance(self, outcome: Any) -> None:
        self.accepted.append(outcome)


def _agreement(mechanism: str) -> dict[str, Any]:
    option = SettlementOption(
        mechanism=mechanism,
        asset="USD",
        rates=[],
        params={},
        option_id=derive_settlement_option_id(mechanism=mechanism, asset="USD", rates=[], params={}),
    )
    return Agreement(
        negotiation_id="neg-1", listing_id="listing-1", listing_hash="0" * 64,
        buyer=BUYER.model_dump(mode="json"), seller=SELLER.model_dump(mode="json"),
        settlement=option, amount=1, asset="USD", duration_seconds=0,
        start_utc="2026-01-01T00:00:00Z", accepted_at="2026-01-01T00:00:00Z",
    ).model_dump(mode="json")


def _composition(*stages: Stage) -> BuyerSettlementComposition:
    return BuyerSettlementComposition(
        CONTRIBUTIONS, SettlementStageTable({stage.mechanism_id: stage for stage in stages})
    )


def test_the_accepted_mechanism_selects_its_stage():
    first, second = Stage("first.v1"), Stage("second.v1")
    composition = _composition(first, second)

    assert composition.stage(_agreement("second.v1")) is second
    outcome = SimpleNamespace(agreement=_agreement("first.v1"))
    composition.validate_acceptance(outcome)
    assert first.accepted == [outcome] and second.accepted == []


def test_an_unknown_mechanism_is_refused_naming_the_bundle_noun():
    with pytest.raises(ValueError, match="unsupported accepted example settlement mechanism"):
        _composition(Stage("first.v1")).stage(_agreement("other.v1"))


def test_the_escrow_codec_is_the_one_stage_that_supplies_one():
    codec = Codec()
    composition = _composition(Stage("first.v1"), Stage("escrow.v1", codec=codec))
    assert composition.escrow_codec is codec


def test_a_table_without_an_escrow_stage_refuses_to_encode_one():
    composition = _composition(Stage("first.v1"))
    with pytest.raises(ValueError, match="negotiates an escrow proposal"):
        composition.escrow_codec.encode_proposal({})


def test_two_escrow_stages_are_refused():
    with pytest.raises(ValueError, match="at most one"):
        _composition(Stage("a.v1", codec=Codec()), Stage("b.v1", codec=Codec()))


class Session:
    def __init__(self, proposal: Any) -> None:
        self.proposal = proposal
        self.asked = 0

    def propose(self, listing: Any, *, expiration_unix: int) -> Any:
        self.asked += 1
        return self.proposal


def _policy(order: list[str], enabled: set[str]) -> Any:
    registrations = [SimpleNamespace(mechanism_id=m, config_key=m) for m in order]
    registry = SimpleNamespace(ordered_registrations=lambda config, role: registrations)
    config = SimpleNamespace(
        mechanism_config=lambda key: SimpleNamespace(enabled=key in enabled)
    )
    return SimpleNamespace(registry=registry, config=config)


def test_proposals_follow_priority_and_skip_disabled_and_empty_sessions():
    composition = _composition(Stage("a.v1"), Stage("b.v1"), Stage("c.v1"))
    disabled, empty, chosen = Session("a"), Session(None), Session("c")
    sessions = {"a.v1": disabled, "b.v1": empty, "c.v1": chosen}

    selected = composition.select_proposal(
        _policy(["a.v1", "b.v1", "c.v1"], {"b.v1", "c.v1"}), {}, sessions, expiration_unix=1,
    )

    assert selected == "c"
    assert (disabled.asked, empty.asked, chosen.asked) == (0, 1, 1)


def test_no_enabled_proposal_selects_nothing():
    composition = _composition(Stage("a.v1"))
    assert composition.select_proposal(
        _policy(["a.v1"], set()), {}, {"a.v1": Session("a")}, expiration_unix=1,
    ) is None


def test_a_legacy_settlement_table_is_refused_before_resolution():
    with pytest.raises(ValueError, match="legacy"):
        _composition(Stage("a.v1")).resolve_policy({"settlement": {}})


def test_the_bundle_refuses_an_empty_name():
    with pytest.raises(ValueError, match="noun"):
        replace(CONTRIBUTIONS, noun=" ")
    assert CONTRIBUTIONS.command_path == "market example"


def test_a_table_entry_must_hold_the_stage_it_is_keyed_by():
    with pytest.raises(ValueError, match="holds the"):
        BuyerSettlementComposition(CONTRIBUTIONS, SettlementStageTable({"a.v1": Stage("b.v1")}))


def _option(command: str, name: str) -> StageOption:
    return StageOption(command=command, name=name, flags=(f"--{name}",), annotation=str | None, help=name)


def test_stage_options_join_a_command_and_are_split_from_its_other_values():
    composition = _composition(
        Stage("a.v1", options=(_option("buy", "alpha"), _option("settle", "alpha"))),
        Stage("b.v1", options=(_option("buy", "beta"),)),
    )

    def command(quantity: int = 1, **values: Any) -> None: ...

    composition.add_options(command, "buy")
    assert list(inspect.signature(command).parameters) == ["quantity", "alpha", "beta"]
    options, rest = composition.split_options({"alpha": "x", "initial_price": 2}, "buy")
    assert options == {"alpha": "x", "beta": None}
    assert rest == {"initial_price": 2}
    assert [option.name for option in composition.options("settle")] == ["alpha"]


def test_two_stages_cannot_contribute_one_commands_option():
    with pytest.raises(ValueError, match="two buyer stages"):
        _composition(
            Stage("a.v1", options=(_option("buy", "alpha"),)),
            Stage("b.v1", options=(_option("buy", "alpha"),)),
        )


def test_the_chain_configuration_merges_every_stages():
    assert _composition(Stage("a.v1"), Stage("b.v1")).chain_config_paths() == {"a.v1": None, "b.v1": None}

