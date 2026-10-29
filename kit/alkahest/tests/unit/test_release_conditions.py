"""The release conditions a listing advertises, per release model and chain.

Each chain's arbiters come from an address book written for the test and named
in ``[Settlement.alkahest.address_books]``, so the expected address is the one
the book names. Every address here is a deterministic development value and
must never be used on a public network.
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
    escrow_release_conditions,
    release_conditions,
)
from market_alkahest.alkahest import get_recipient_arbiter
from market_settlement_runtime import MechanismReadiness, ReadinessBlocker

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
def books(tmp_path) -> dict[str, str]:
    """Each chain's address book, written for the test, by chain name."""
    paths = {}
    for name, arbiters in ARBITERS.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"arbiters_addresses": arbiters}), encoding="utf-8")
        paths[name] = str(path)
    return paths


# Both chains, one configured as a mapping and one as an object. A chain table
# names no address book.
CHAINS = {
    "anvil": {"rpc_url": "http://anvil.test"},
    "base_sepolia": SimpleNamespace(name="base_sepolia"),
}


@pytest.fixture
def chains():
    return CHAINS


@pytest.fixture
def _config(books):
    def config(**policy) -> AlkahestSettlementConfig:
        return AlkahestSettlementConfig.model_validate(
            {"enabled": True, "address_books": books, **policy}
        )

    return config


def _conditions(config, chains, names=("anvil", "base_sepolia")):
    return release_conditions(
        config, chain_names=names, chains=chains, wallet_address=WALLET
    )


def test_the_recipient_model_releases_to_the_seller_wallet_on_each_chain(_config, chains):
    assert _conditions(_config(), chains) == [
        {
            "chain_name": name,
            "arbiter": ARBITERS[name]["recipient_arbiter"].lower(),
            "demand_data": {"recipient": WALLET.lower()},
        }
        for name in ("anvil", "base_sepolia")
    ]


def test_a_chain_the_table_names_no_book_for_uses_the_sdks_addresses(books, chains):
    """Spec scenario "A seller trades on two chains", for publication's release
    conditions: ``anvil``'s arbiter comes from its book, and ``base_sepolia``'s
    from the SDK's built-in addresses."""
    config = AlkahestSettlementConfig(enabled=True, address_books={"anvil": books["anvil"]})

    conditions = _conditions(config, chains)

    assert [item["arbiter"] for item in conditions] == [
        ARBITERS["anvil"]["recipient_arbiter"].lower(),
        get_recipient_arbiter("base_sepolia", config_path=None).lower(),
    ]


def test_the_oracle_gated_model_names_the_first_trusted_oracle(_config, chains):
    config = _config(oracle_gated=True, trusted_oracle_addresses=[ORACLE, OTHER_ORACLE])

    assert _conditions(config, chains, ["anvil"]) == [
        {
            "chain_name": "anvil",
            "arbiter": ARBITERS["anvil"]["trusted_oracle_arbiter"].lower(),
            "demand_data": {"oracle": ORACLE.lower(), "data": "0x"},
        }
    ]


def test_the_interruptible_model_names_its_configured_refund_authority(_config, chains):
    config = _config(interruptible=True, interruptible_oracle_addresses=[ORACLE])

    assert _conditions(config, chains, ["base_sepolia"]) == [
        {
            "chain_name": "base_sepolia",
            "arbiter": ARBITERS["base_sepolia"]["erc20_splitter"].lower(),
            "demand_data": {"oracle": ORACLE.lower(), "data": "0x"},
        }
    ]


def test_an_interruptible_model_without_its_oracle_is_refused(_config, chains):
    """No condition stands in for a missing oracle, the seller wallet least of all."""
    with pytest.raises(ValueError, match="requires an interruptible oracle"):
        _conditions(_config(interruptible=True), chains, ["anvil"])


def test_the_seller_wallet_cannot_be_its_own_interruptible_oracle(_config, chains):
    config = _config(interruptible=True, interruptible_oracle_addresses=[WALLET])

    with pytest.raises(ValueError, match="equals the storefront wallet"):
        _conditions(config, chains, ["anvil"])


def test_conditions_are_one_per_chain_in_chain_order(_config, chains):
    conditions = _conditions(_config(), chains, ["base_sepolia", "anvil", "base_sepolia"])

    assert [item["chain_name"] for item in conditions] == ["anvil", "base_sepolia"]


def test_no_chain_derives_nothing():
    assert release_conditions(None, chain_names=(), chains={}, wallet_address=WALLET) == []


def test_an_unconfigured_chain_is_refused(chains):
    with pytest.raises(ValueError, match="unknown chain 'ethereum_sepolia'"):
        _conditions(None, chains, ["anvil", "ethereum_sepolia"])


def test_an_oracle_gated_model_without_an_oracle_is_refused(_config, chains):
    with pytest.raises(ValueError, match="requires a trusted oracle"):
        _conditions(_config(oracle_gated=True), chains, ["anvil"])


def test_the_seller_wallet_cannot_be_its_own_oracle(_config, chains):
    """The party collecting cannot also be the party deciding collection."""
    config = _config(oracle_gated=True, trusted_oracle_addresses=[WALLET])

    with pytest.raises(ValueError, match="equals the storefront wallet"):
        _conditions(config, chains, ["anvil"])


def test_oracle_gated_and_interruptible_are_mutually_exclusive(_config, chains):
    config = _config(
        oracle_gated=True, trusted_oracle_addresses=[ORACLE], interruptible=True
    )

    with pytest.raises(ReleaseModelError, match="mutually exclusive"):
        configured_release_model(config)
    with pytest.raises(ReleaseModelError, match="mutually exclusive"):
        _conditions(config, chains, ["anvil"])


@pytest.mark.parametrize(
    ("policy", "model"),
    [
        ({}, RECIPIENT_RELEASE),
        ({"oracle_gated": True, "trusted_oracle_addresses": [ORACLE]}, ORACLE_GATED_RELEASE),
        ({"interruptible": True}, INTERRUPTIBLE_RELEASE),
    ],
)
def test_each_section_selects_one_model(_config, policy, model):
    assert configured_release_model(_config(**policy)) == model


def _escrow(chain_name: str) -> dict:
    """An Alkahest escrow in the publication form, on ``chain_name``."""
    return {
        "chain_name": chain_name,
        "escrow_address": "0x" + "22" * 20,
        "literal_fields": {"token": "0x" + "11" * 20},
    }


def test_published_escrows_derive_a_condition_for_each_chain_they_name(_config, chains):
    escrows = [_escrow("base_sepolia"), _escrow("anvil"), _escrow("anvil")]

    conditions = escrow_release_conditions(
        _config(), escrows, readiness=_ready(), chains=chains, wallet_address=WALLET
    )

    assert conditions == _conditions(_config(), chains)


def test_a_listing_publishing_no_escrow_advertises_no_condition():
    assert (
        escrow_release_conditions(
            None, [], readiness=_ready(), chains={}, wallet_address=WALLET
        )
        == []
    )


def test_a_published_escrow_on_an_unconfigured_chain_is_refused(chains):
    """Nothing could settle it, so no condition is derived for it."""
    with pytest.raises(ValueError, match="unknown chain 'ethereum_sepolia'"):
        escrow_release_conditions(
            None,
            [_escrow("anvil"), _escrow("ethereum_sepolia")],
            readiness=_ready(),
            chains=chains,
            wallet_address=WALLET,
        )


@pytest.mark.parametrize(
    "readiness",
    [
        (),
        (
            MechanismReadiness(
                mechanism="alkahest.v1",
                configured=True,
                enabled=True,
                ready=False,
                blockers=(
                    ReadinessBlocker(
                        code="alkahest.oracle_policy_invalid",
                        message="oracle-gated settlement requires a trusted oracle address",
                        kind="configuration",
                    ),
                ),
            ),
        ),
    ],
    ids=["no-alkahest-readiness", "alkahest-unready"],
)
def test_no_condition_is_advertised_while_alkahest_is_unready(_config, chains, readiness):
    """An unready mechanism publishes no escrow, so nothing is advertised.

    The section here would refuse derivation outright, and the second escrow's
    chain is not configured; readiness keeps either refusal from being reached.
    """
    escrows = [_escrow("anvil"), _escrow("ethereum_sepolia")]

    assert (
        escrow_release_conditions(
            _config(oracle_gated=True),
            escrows,
            readiness=readiness,
            chains=chains,
            wallet_address=WALLET,
        )
        == []
    )


def _ready() -> tuple[MechanismReadiness, ...]:
    return (
        MechanismReadiness(
            mechanism="alkahest.v1", configured=True, enabled=True, ready=True
        ),
    )
