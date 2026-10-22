"""The release conditions a listing advertises, per release model and chain.

Each chain's arbiters come from an address book written for the test, so the
expected address is the one the book names. Every address here is a
deterministic development value and must never be used on a public network.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from market_alkahest import (
    INTERRUPTIBLE_RELEASE,
    ORACLE_GATED_RELEASE,
    RECIPIENT_RELEASE,
    AlkahestSettlementConfig,
    ReleaseModelError,
    configured_release_model,
    publication_release_conditions,
    release_conditions,
    require_deliverable_release_model,
)
from market_settlement_runtime import SettlementPublicationClause

WALLET = "0x" + "AB" * 20
ORACLE = "0x" + "CD" * 20
OTHER_ORACLE = "0x" + "EF" * 20

ARBITERS = {
    "anvil": {
        "recipient_arbiter": "0x" + "A1" * 20,
        "trusted_oracle_arbiter": "0x" + "A2" * 20,
        "erc20_splitter": "0x" + "A3" * 20,
    },
    "base_sepolia": {
        "recipient_arbiter": "0x" + "B1" * 20,
        "trusted_oracle_arbiter": "0x" + "B2" * 20,
        "erc20_splitter": "0x" + "B3" * 20,
    },
}


@pytest.fixture
def chains(tmp_path):
    """Both chains, one configured as a mapping and one as an object."""
    paths = {}
    for name, arbiters in ARBITERS.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"arbiters_addresses": arbiters}), encoding="utf-8")
        paths[name] = str(path)
    return {
        "anvil": {"rpc_url": "http://anvil.test", "alkahest_address_config_path": paths["anvil"]},
        "base_sepolia": SimpleNamespace(
            name="base_sepolia", alkahest_address_config_path=paths["base_sepolia"]
        ),
    }


def _config(**policy) -> AlkahestSettlementConfig:
    return AlkahestSettlementConfig.model_validate({"enabled": True, **policy})


def _conditions(config, chains, names=("anvil", "base_sepolia")):
    return release_conditions(
        config, chain_names=names, chains=chains, wallet_address=WALLET
    )


@pytest.mark.parametrize("config", [None, _config()], ids=["no-section", "default"])
def test_the_recipient_model_releases_to_the_seller_wallet_on_each_chain(config, chains):
    assert _conditions(config, chains) == [
        {
            "chain_name": name,
            "arbiter": ARBITERS[name]["recipient_arbiter"].lower(),
            "demand_data": {"recipient": WALLET.lower()},
        }
        for name in ("anvil", "base_sepolia")
    ]


def test_the_oracle_gated_model_names_the_first_trusted_oracle(chains):
    config = _config(oracle_gated=True, trusted_oracle_addresses=[ORACLE, OTHER_ORACLE])

    assert _conditions(config, chains, ["anvil"]) == [
        {
            "chain_name": "anvil",
            "arbiter": ARBITERS["anvil"]["trusted_oracle_arbiter"].lower(),
            "demand_data": {"oracle": ORACLE.lower(), "data": "0x"},
        }
    ]


def test_the_interruptible_model_names_its_configured_refund_authority(chains):
    config = _config(interruptible=True, interruptible_oracle_addresses=[ORACLE])

    assert _conditions(config, chains, ["base_sepolia"]) == [
        {
            "chain_name": "base_sepolia",
            "arbiter": ARBITERS["base_sepolia"]["erc20_splitter"].lower(),
            "demand_data": {"oracle": ORACLE.lower(), "data": "0x"},
        }
    ]


def test_the_interruptible_model_falls_back_to_the_seller_wallet(chains):
    (condition,) = _conditions(_config(interruptible=True), chains, ["anvil"])

    assert condition["arbiter"] == ARBITERS["anvil"]["erc20_splitter"].lower()
    assert condition["demand_data"] == {"oracle": WALLET.lower(), "data": "0x"}


def test_conditions_are_one_per_chain_in_chain_order(chains):
    conditions = _conditions(None, chains, ["base_sepolia", "anvil", "base_sepolia"])

    assert [item["chain_name"] for item in conditions] == ["anvil", "base_sepolia"]


def test_no_chain_derives_nothing():
    assert release_conditions(None, chain_names=(), chains={}, wallet_address=WALLET) == []


def test_an_unconfigured_chain_is_refused(chains):
    with pytest.raises(ValueError, match="unknown chain 'ethereum_sepolia'"):
        _conditions(None, chains, ["anvil", "ethereum_sepolia"])


def test_an_oracle_gated_model_without_an_oracle_is_refused(chains):
    with pytest.raises(ValueError, match="requires a trusted oracle"):
        _conditions(_config(oracle_gated=True), chains, ["anvil"])


def test_the_seller_wallet_cannot_be_its_own_oracle(chains):
    """The party collecting cannot also be the party deciding collection."""
    config = _config(oracle_gated=True, trusted_oracle_addresses=[WALLET])

    with pytest.raises(ValueError, match="equals the storefront wallet"):
        _conditions(config, chains, ["anvil"])


def test_oracle_gated_and_interruptible_are_mutually_exclusive(chains):
    config = _config(
        oracle_gated=True, trusted_oracle_addresses=[ORACLE], interruptible=True
    )

    with pytest.raises(ReleaseModelError, match="mutually exclusive"):
        configured_release_model(config)
    with pytest.raises(ReleaseModelError, match="mutually exclusive"):
        _conditions(config, chains, ["anvil"])
    with pytest.raises(ReleaseModelError, match="mutually exclusive"):
        require_deliverable_release_model(config, {RECIPIENT_RELEASE})


@pytest.mark.parametrize(
    ("policy", "model"),
    [
        ({}, RECIPIENT_RELEASE),
        ({"oracle_gated": True, "trusted_oracle_addresses": [ORACLE]}, ORACLE_GATED_RELEASE),
        ({"interruptible": True}, INTERRUPTIBLE_RELEASE),
    ],
)
def test_each_section_selects_one_model(policy, model):
    assert configured_release_model(_config(**policy)) == model


def test_a_model_the_domain_declares_is_returned():
    config = _config(oracle_gated=True, trusted_oracle_addresses=[ORACLE])

    assert (
        require_deliverable_release_model(
            config, {RECIPIENT_RELEASE, ORACLE_GATED_RELEASE}
        )
        == ORACLE_GATED_RELEASE
    )
    assert require_deliverable_release_model(None, {RECIPIENT_RELEASE}) == RECIPIENT_RELEASE


def test_a_model_the_domain_does_not_declare_is_refused_by_name():
    with pytest.raises(ReleaseModelError, match="'interruptible' release model"):
        require_deliverable_release_model(
            _config(interruptible=True), {RECIPIENT_RELEASE, ORACLE_GATED_RELEASE}
        )


def test_a_declaration_naming_an_unknown_model_is_refused():
    with pytest.raises(ValueError, match="unknown Alkahest release models"):
        require_deliverable_release_model(None, {RECIPIENT_RELEASE, "escrowless"})


def _clause(mechanism: str, **mechanism_input) -> SettlementPublicationClause:
    return SettlementPublicationClause(
        mechanism=mechanism,
        asset="0x" + "11" * 20,
        rate="1",
        per="hour",
        mechanism_input=mechanism_input,
    )


def test_publication_derives_a_condition_for_each_alkahest_clause_chain(chains):
    clauses = [
        _clause("alkahest.v1", chain="base_sepolia", escrow_kind="erc20_escrow_obligation_default"),
        _clause("alkahest.v1", chain="anvil", escrow_kind="erc20_escrow_obligation_default"),
        _clause("alkahest.v1", chain="anvil", escrow_kind="erc20_escrow_obligation_default"),
        _clause("arkhai.payments.v1", payee_account="seller"),
    ]

    conditions = publication_release_conditions(
        None, clauses, chains=chains, wallet_address=WALLET
    )

    assert conditions == _conditions(None, chains)


def test_publication_without_an_alkahest_clause_advertises_no_condition():
    clauses = [_clause("arkhai.payments.v1", payee_account="seller")]

    assert (
        publication_release_conditions(None, clauses, chains={}, wallet_address=WALLET)
        == []
    )
