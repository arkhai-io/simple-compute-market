"""`fund_accepted_obligation` runs for real; only the chain call is controlled.

The address config is resolved, the `AlkahestClient` is constructed, and the
escrow codec is looked up from the accepted obligation's own contract address —
all by the production function. Only `create_obligation`, the one call that needs
a node, is replaced.

`base_sepolia` is used because its deployed address set ships with the kit, so
the codec resolves offline. It is a fixture chain here and nothing is sent to it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from arkhai_bare_metal_buyer import escrow as buyer_escrow
from arkhai_bare_metal_buyer.escrow import (
    BareMetalEscrowError,
    fund_accepted_obligation,
    funding_address,
)
from market_alkahest.alkahest import get_erc20_escrow_obligation_default

CHAIN = "base_sepolia"
TOKEN = "0x00000000000000000000000000000000000000aa"
FIXTURE_KEY = "0x" + "11" * 32
CREATED_UID = "0xcreated"


def _escrow_contract() -> str:
    return get_erc20_escrow_obligation_default(CHAIN)


def _obligation(**overrides: Any) -> dict[str, Any]:
    obligation = {
        "payer": "buyer",
        "claimant": "seller",
        "amount": "1000",
        "asset": TOKEN,
        "expiration_unix": 2_000_000_000,
        "mechanism": "alkahest.v1",
        "params": {
            "chain_name": CHAIN,
            "escrow_contract": _escrow_contract(),
            "obligation_data": {
                "token": TOKEN,
                "amount": "1000",
                "arbiter": "0x00000000000000000000000000000000000000bb",
                "demand": "0x00",
            },
        },
    }
    obligation.update(overrides)
    return obligation


@pytest.fixture()
def chain(monkeypatch):
    """A configured chain, as `market_config` would resolve one."""
    from market_config.config_loader import ChainConfig

    configured = ChainConfig(
        name=CHAIN,
        rpc_url="http://127.0.0.1:1",
        chain_id=84532,
        alkahest_address_config_path=None,
    )
    monkeypatch.setattr(
        buyer_escrow, "chains_from_config", lambda: {CHAIN: configured}
    )
    return configured


@pytest.fixture()
def created(monkeypatch):
    """Replace only the call that needs a node, and record what it received."""
    calls: list[tuple[dict, int]] = []
    config_paths: list[str | None] = []

    from market_alkahest import alkahest as kit

    original = kit.get_escrow_kind_codec_by_address

    def patched(address, chain_name, *, config_path=None):
        # Record what production passed, then resolve against the bundled set:
        # the operator's real file is not present in an offline test.
        config_paths.append(config_path)
        codec = original(address, chain_name, config_path=None)

        async def create_obligation(client, obligation_data, expiration_unix):
            calls.append((dict(obligation_data), int(expiration_unix)))
            assert client is not None, "a real client must be constructed"
            return CREATED_UID

        return SimpleNamespace(kind=codec.kind, create_obligation=create_obligation)

    monkeypatch.setattr(kit, "get_escrow_kind_codec_by_address", patched)
    return SimpleNamespace(calls=calls, config_paths=config_paths)


def test_the_accepted_obligation_is_funded_through_its_own_codec(chain, created) -> None:
    uid = fund_accepted_obligation(_obligation(), private_key=FIXTURE_KEY)

    assert uid == CREATED_UID
    assert len(created.calls) == 1
    obligation_data, expiration = created.calls[0]
    # Funded verbatim: whatever the acceptance check let through is what is sent.
    assert obligation_data == _obligation()["params"]["obligation_data"]
    assert expiration == 2_000_000_000


def test_the_operator_address_config_reaches_the_codec(monkeypatch, created) -> None:
    """A misread config field would silently use the bundled address set.

    That is exactly the defect this guards: `ChainConfig` names the field
    `alkahest_address_config_path`, and reading any other name resolved to None
    while looking like it worked.
    """
    from market_config.config_loader import ChainConfig
    from market_alkahest import alkahest as kit

    configured_path = "/fixture/alkahest-addresses.json"
    seen: list[str | None] = []

    # Both consumers are recorded: the prewarm that reads the file, and the
    # address resolution. The codec lookup is recorded by the `created` fixture.
    monkeypatch.setattr(
        kit,
        "prewarm_alkahest_address_config_cache",
        lambda config_path=None: seen.append(config_path),
    )
    original = kit.resolve_alkahest_address_config

    def record(network, *, config_path=None):
        seen.append(config_path)
        return original(network, config_path=None)

    monkeypatch.setattr(kit, "resolve_alkahest_address_config", record)
    monkeypatch.setattr(
        buyer_escrow,
        "chains_from_config",
        lambda: {
            CHAIN: ChainConfig(
                name=CHAIN,
                rpc_url="http://127.0.0.1:1",
                chain_id=84532,
                alkahest_address_config_path=configured_path,
            )
        },
    )

    fund_accepted_obligation(_obligation(), private_key=FIXTURE_KEY)

    # The configured path everywhere, never None: reading the wrong attribute
    # name produced None here and quietly used the bundled address set.
    assert seen and all(item == configured_path for item in seen), seen
    assert created.config_paths == [configured_path]
    # The field the SDK actually defines must exist, or the read above is a
    # silent no-op again.
    assert hasattr(
        ChainConfig(name=CHAIN, rpc_url="u", chain_id=1),
        "alkahest_address_config_path",
    )


def test_a_chain_the_kit_does_not_know_is_refused(chain, created) -> None:
    from market_config.config_loader import ChainConfig

    obligation = _obligation()
    obligation["params"]["chain_name"] = "not-a-real-network"

    with pytest.raises(ValueError):
        fund_accepted_obligation(
            obligation,
            private_key=FIXTURE_KEY,
            chain=ChainConfig(name="x", rpc_url="http://127.0.0.1:1", chain_id=1),
        )
    assert created.calls == []


def test_the_funding_address_is_derived_from_the_key() -> None:
    assert funding_address(FIXTURE_KEY).startswith("0x")
    assert funding_address(FIXTURE_KEY) == funding_address(FIXTURE_KEY)

    with pytest.raises(BareMetalEscrowError):
        funding_address("not-a-key")
