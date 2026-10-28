from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from types import MappingProxyType, SimpleNamespace

import pytest
from market_alkahest import (
    ALKAHEST_CONFIG_KEY,
    ALKAHEST_MECHANISM_ID,
    AlkahestConditionalEscrowClient,
    AlkahestSettlementConfig,
    ChainProbeResult,
    create_alkahest_registration,
    verify_escrow_against_plan,
    wallet_account_address,
)
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.settlement_config import alkahest_preflight
from market_core.schemas import SettlementOption
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfigurationError,
    SettlementConfigurationRegistry,
    compile_settlement_clause,
    SettlementPublicationClause,
    settlement_clause_matches,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": False, "wallet": {"private_key": "secret"}},
        {"enabled": False, "chains": {}},
        {"enabled": False, "trusted_oracle_addresses": ["0x" + "11" * 20]},
        {"enabled": False, "oracle_gated": True, "trusted_oracle_addresses": ["bad"]},
    ],
)
def test_alkahest_config_rejects_foreign_or_invalid_fields(payload: dict) -> None:
    with pytest.raises(ValidationError):
        AlkahestSettlementConfig.model_validate(payload)


def test_the_probe_runs_every_thirty_seconds_with_five_second_calls_by_default() -> None:
    config = AlkahestSettlementConfig()

    assert config.probe_interval_seconds == 30.0
    assert config.rpc_timeout_seconds == 5.0
    assert AlkahestSettlementConfig.model_validate(
        {"probe_interval_seconds": 2, "rpc_timeout_seconds": "0.5"}
    ).rpc_timeout_seconds == 0.5


@pytest.mark.parametrize("key", ["probe_interval_seconds", "rpc_timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, "soon", float("inf")])
def test_a_probe_duration_that_is_not_positive_seconds_is_refused_by_key(key, value) -> None:
    with pytest.raises(ValidationError) as refused:
        AlkahestSettlementConfig.model_validate({key: value})

    assert refused.value.errors()[0]["loc"] == (key,)


@pytest.mark.asyncio
async def test_disabled_alkahest_preflight_does_not_touch_injected_resources() -> None:
    calls: list[str | None] = []
    resources = {"get_client": lambda chain: calls.append(chain)}

    status = await alkahest_preflight(AlkahestSettlementConfig(), resources, "seller")

    assert status.mechanism == ALKAHEST_MECHANISM_ID
    assert status.enabled is False
    assert status.ready is False
    # With no wallet injected it names the wallet, and it still calls no client.
    assert [blocker.code for blocker in status.blockers] == ["alkahest.wallet_missing"]
    assert calls == []


@pytest.mark.asyncio
async def test_enabled_alkahest_reports_sanitized_prerequisite_blockers() -> None:
    status = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=True),
        {},
        "buyer",
    )

    assert status.ready is False
    assert {(blocker.code, blocker.kind) for blocker in status.blockers} == {
        ("alkahest.wallet_missing", "configuration"),
        ("alkahest.chain_missing", "configuration"),
    }
    projection = status.model_dump_json()
    assert "private_key" not in projection
    assert "rpc_url" not in projection


# Anvil's first published development account, its key and the address the key
# signs as. Well-known development values; never use them on a public network.
WALLET_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
WALLET = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
ORACLE = "0x" + "22" * 20
OTHER_ACCOUNT = "0x" + "44" * 20


def _seller_resources(**overrides) -> dict:
    resources = {
        "wallet": {"address": WALLET, "private_key": WALLET_KEY},
        "chains": {"anvil": {"rpc_url": "http://anvil.test", "chain_id": 31337}},
        "chain_name": "anvil",
        "clients": {"anvil": object()},
        "deliverable_release_models": frozenset({"recipient", "oracle_gated"}),
        "signs_transactions": True,
    }
    resources.update(overrides)
    return resources


async def _blockers(config: AlkahestSettlementConfig, resources: dict) -> set:
    status = await alkahest_preflight(config, resources, "seller")
    assert status.ready is (not status.blockers)
    return {(blocker.code, blocker.kind) for blocker in status.blockers}


@pytest.mark.asyncio
async def test_a_complete_seller_section_is_ready() -> None:
    assert await _blockers(AlkahestSettlementConfig(enabled=True), _seller_resources()) == set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "resources", "expected"),
    [
        (
            {"oracle_gated": True},
            {},
            ("alkahest.oracle_policy_invalid", "configuration"),
        ),
        (
            {"oracle_gated": True, "trusted_oracle_addresses": [WALLET]},
            {},
            ("alkahest.oracle_is_seller_wallet", "configuration"),
        ),
        (
            {"interruptible": True},
            {"deliverable_release_models": frozenset({"interruptible"})},
            ("alkahest.interruptible_policy_invalid", "configuration"),
        ),
        (
            {"interruptible": True, "interruptible_oracle_addresses": [WALLET]},
            {"deliverable_release_models": frozenset({"interruptible"})},
            ("alkahest.oracle_is_seller_wallet", "configuration"),
        ),
        (
            {"interruptible": True, "interruptible_oracle_addresses": [ORACLE]},
            {},
            ("alkahest.release_model_undeliverable", "configuration"),
        ),
        (
            {},
            {"wallet": {"address": "", "private_key": ""}},
            ("alkahest.wallet_address_missing", "configuration"),
        ),
        (
            {},
            {"wallet": ""},
            ("alkahest.wallet_address_missing", "configuration"),
        ),
        (
            {},
            {"wallet": {"address": WALLET}},
            ("alkahest.wallet_key_missing", "configuration"),
        ),
        (
            {},
            {"chains": {}},
            ("alkahest.chains_missing", "configuration"),
        ),
    ],
    ids=[
        "oracle-gated-no-oracle",
        "trusted-oracle-is-wallet",
        "interruptible-no-oracle",
        "interruptible-oracle-is-wallet",
        "undeliverable-model",
        "no-address-and-no-key",
        "empty-bare-wallet",
        "no-wallet-key",
        "no-chains",
    ],
)
async def test_a_section_that_cannot_settle_names_its_configuration_blocker(
    policy: dict, resources: dict, expected: tuple[str, str]
) -> None:
    config = AlkahestSettlementConfig.model_validate({"enabled": True, **policy})

    assert expected in await _blockers(config, _seller_resources(**resources))


class _StubProbe:
    """The chain probe's read side: each chain's last result, set by the test."""

    def __init__(self, results: dict) -> None:
        self._results = results

    def result(self, chain_name):
        return self._results.get(chain_name)

    def public_results(self):
        return {
            name: result.public() if result is not None else None
            for name, result in self._results.items()
        }


_PROBED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (None, ("alkahest.chain_unreachable", "reachability")),
        ("alkahest.chain_unreachable", ("alkahest.chain_unreachable", "reachability")),
        ("alkahest.chain_id_mismatch", ("alkahest.chain_id_mismatch", "configuration")),
        ("alkahest.contract_missing", ("alkahest.contract_missing", "configuration")),
        (
            "alkahest.address_config_invalid",
            ("alkahest.address_config_invalid", "configuration"),
        ),
    ],
    ids=["unprobed", "unreachable", "chain-id-mismatch", "contract-missing", "address-config"],
)
async def test_each_chain_probe_result_is_read_as_its_blocker(result, expected) -> None:
    probe = _StubProbe(
        {"anvil": ChainProbeResult(result, _PROBED_AT) if result else None}
    )

    blockers = await _blockers(
        AlkahestSettlementConfig(enabled=True), _seller_resources(chain_probe=probe)
    )

    assert blockers == {expected}


@pytest.mark.asyncio
async def test_a_reachable_chain_raises_no_blocker_and_status_reports_its_probe() -> None:
    probe = _StubProbe({"anvil": ChainProbeResult("reachable", _PROBED_AT)})

    status = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=True),
        _seller_resources(chain_probe=probe),
        "seller",
    )

    assert status.ready is True
    assert status.public_details["chain_probe"] == {
        "anvil": {"result": "reachable", "probed_at": _PROBED_AT.isoformat()}
    }


@pytest.mark.asyncio
async def test_only_the_chains_the_clauses_select_are_read() -> None:
    probe = _StubProbe(
        {
            "anvil": ChainProbeResult("reachable", _PROBED_AT),
            "base_sepolia": ChainProbeResult("alkahest.chain_unreachable", _PROBED_AT),
        }
    )

    blockers = await _blockers(
        AlkahestSettlementConfig(enabled=True),
        _seller_resources(
            chain_probe=probe,
            chains={
                "anvil": {"rpc_url": "http://anvil.test"},
                "base_sepolia": {"rpc_url": "http://base.test"},
            },
            accepted_escrows=[{"chain_name": "anvil"}],
        ),
    )

    assert blockers == set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selection",
    [{}, {"default_chain": "anvil"}],
    ids=["no default", "a default chain"],
)
async def test_with_no_publication_input_every_configured_chain_is_judged(
    selection: dict,
) -> None:
    """Status asks with no publication input, and servicing an accepted deal
    needs whichever chain it was accepted on, so a down chain no clause
    publishes on is still reported."""
    probe = _StubProbe(
        {
            "anvil": ChainProbeResult("reachable", _PROBED_AT),
            "base_sepolia": ChainProbeResult("alkahest.chain_unreachable", _PROBED_AT),
        }
    )

    blockers = await _blockers(
        AlkahestSettlementConfig(enabled=True),
        _seller_resources(
            chain_probe=probe,
            chains={
                "anvil": {"rpc_url": "http://anvil.test"},
                "base_sepolia": {"rpc_url": "http://base.test"},
            },
            chain_name=None,
            **selection,
        ),
    )

    assert blockers == {("alkahest.chain_unreachable", "reachability")}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "resources", "expected"),
    [
        (
            {},
            {"chains": {"anvil": {"chain_id": 31337}}, "clients": {}},
            ("alkahest.rpc_missing", "configuration"),
        ),
        (
            {},
            {"require_asset": True},
            ("alkahest.asset_missing", "configuration"),
        ),
    ],
    ids=[
        "rpc-missing",
        "asset-missing",
    ],
)
async def test_each_chain_and_input_blocker_states_its_kind(
    policy: dict, resources: dict, expected: tuple[str, str]
) -> None:
    config = AlkahestSettlementConfig.model_validate({"enabled": True, **policy})

    assert expected in await _blockers(config, _seller_resources(**resources))


def test_the_address_books_parse_as_a_table_of_chain_to_book() -> None:
    config = AlkahestSettlementConfig.model_validate(
        {"address_books": {"anvil": "/etc/arkhai/alkahest/anvil.json"}}
    )

    assert config.address_books == {"anvil": "/etc/arkhai/alkahest/anvil.json"}
    assert AlkahestSettlementConfig().address_books == {}
    # A layered loader's own mapping type is a table too.
    assert AlkahestSettlementConfig.model_validate(
        {"address_books": MappingProxyType({"anvil": "/book.json"})}
    ).address_books == {"anvil": "/book.json"}


@pytest.mark.parametrize(
    "books",
    [
        {" anvil": "/book.json"},
        {"": "/book.json"},
        {"anvil": ""},
        {"anvil": " /book.json"},
        {"anvil": 7},
        ["anvil"],
    ],
    ids=["untrimmed-chain", "empty-chain", "empty-book", "untrimmed-book", "not-a-path", "a-list"],
)
def test_an_address_book_entry_that_is_not_a_chain_and_a_path_is_refused(books) -> None:
    with pytest.raises(ValidationError) as refused:
        AlkahestSettlementConfig.model_validate({"address_books": books})

    assert refused.value.errors()[0]["loc"][0] == "address_books"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False], ids=["enabled", "disabled"])
async def test_an_address_book_naming_no_configured_chain_is_a_blocker_naming_it(
    enabled: bool,
) -> None:
    book = str(anvil_address_book_path())
    config = AlkahestSettlementConfig(
        enabled=enabled, address_books={"anvil": book, "anvill": book}
    )

    status = await alkahest_preflight(config, _seller_resources(), "seller")

    (blocker,) = status.blockers
    assert (blocker.code, blocker.kind) == (
        "alkahest.address_book_chain_unknown",
        "configuration",
    )
    assert "'anvill'" in blocker.message
    assert "'anvil'," not in blocker.message


@pytest.mark.asyncio
async def test_a_buyers_address_book_naming_no_configured_chain_is_a_blocker() -> None:
    status = await alkahest_preflight(
        AlkahestSettlementConfig(
            enabled=True, address_books={"anvill": str(anvil_address_book_path())}
        ),
        {
            "wallet": {"address": WALLET},
            "chains": {"anvil": {"rpc_url": "http://anvil.test"}},
            "default_chain": "anvil",
        },
        "buyer",
    )

    assert [blocker.code for blocker in status.blockers] == [
        "alkahest.address_book_chain_unknown"
    ]


@pytest.mark.asyncio
async def test_address_book_keys_are_not_judged_without_a_chains_mapping() -> None:
    config = AlkahestSettlementConfig(
        enabled=True, address_books={"anvil": str(anvil_address_book_path())}
    )

    status = await alkahest_preflight(config, {"wallet": {"address": WALLET}}, "buyer")

    assert "alkahest.address_book_chain_unknown" not in {
        blocker.code for blocker in status.blockers
    }


@pytest.mark.asyncio
async def test_an_address_book_on_a_configured_chain_raises_no_blocker() -> None:
    config = AlkahestSettlementConfig(
        enabled=True, address_books={"anvil": str(anvil_address_book_path())}
    )

    assert await _blockers(config, _seller_resources()) == set()


@pytest.mark.asyncio
async def test_an_address_book_that_cannot_be_loaded_is_a_blocker() -> None:
    config = AlkahestSettlementConfig(
        enabled=True, address_books={"anvil": "/nonexistent/alkahest-addresses.json"}
    )

    assert await _blockers(config, _seller_resources()) == {
        ("alkahest.address_config_invalid", "configuration")
    }


@pytest.mark.asyncio
async def test_a_wallet_given_as_a_bare_address_is_read_as_one() -> None:
    # A bare address carries no key, so only a storefront that does not sign
    # with it reads it as complete.
    blockers = await _blockers(
        AlkahestSettlementConfig(enabled=True),
        _seller_resources(wallet=WALLET, signs_transactions=False),
    )

    assert blockers == set()


@pytest.mark.asyncio
async def test_the_address_names_another_account() -> None:
    """Readiness's part of spec scenario "The address names another account"."""
    blockers = await _blockers(
        AlkahestSettlementConfig(enabled=True),
        _seller_resources(wallet={"address": OTHER_ACCOUNT, "private_key": WALLET_KEY}),
    )

    assert blockers == {("alkahest.wallet_address_mismatch", "configuration")}


@pytest.mark.asyncio
async def test_an_address_differing_only_in_case_names_the_same_account() -> None:
    # Neither the checksummed form the key derives nor the lowercase fixture.
    uppercase = "0x" + WALLET[2:].upper()

    blockers = await _blockers(
        AlkahestSettlementConfig(enabled=True),
        _seller_resources(wallet={"address": uppercase, "private_key": WALLET_KEY}),
    )

    assert blockers == set()


@pytest.mark.asyncio
async def test_the_address_is_omitted() -> None:
    """The kit's part of spec scenario "The address is omitted": readiness and
    ``wallet_account_address`` read the key's account as the seller's."""
    wallet = {"private_key": WALLET_KEY}

    blockers = await _blockers(
        AlkahestSettlementConfig(enabled=True), _seller_resources(wallet=wallet)
    )

    assert blockers == set()
    assert wallet_account_address(wallet).lower() == WALLET
    assert wallet_account_address({"address": OTHER_ACCOUNT, "private_key": WALLET_KEY}) == (
        OTHER_ACCOUNT
    )
    assert wallet_account_address(OTHER_ACCOUNT) == OTHER_ACCOUNT
    assert wallet_account_address(None) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy",
    [
        {"oracle_gated": True, "trusted_oracle_addresses": [WALLET]},
        {"interruptible": True, "interruptible_oracle_addresses": [WALLET]},
    ],
    ids=["trusted-oracle", "interruptible-oracle"],
)
@pytest.mark.parametrize(
    "address", [OTHER_ACCOUNT, None], ids=["another-address", "no-address"]
)
async def test_the_oracle_is_the_signing_key(policy: dict, address: str | None) -> None:
    """Spec scenario "The oracle is the signing key": whatever address is
    configured, an oracle that is the key's account is the seller's own, and
    readiness is unready."""
    wallet = {"private_key": WALLET_KEY}
    if address is not None:
        wallet["address"] = address
    config = AlkahestSettlementConfig.model_validate({"enabled": True, **policy})

    blockers = await _blockers(
        config,
        _seller_resources(
            wallet=wallet,
            deliverable_release_models=frozenset({"oracle_gated", "interruptible"}),
        ),
    )

    assert ("alkahest.oracle_is_seller_wallet", "configuration") in blockers


@pytest.mark.asyncio
async def test_a_buyer_whose_address_is_not_its_keys_is_not_refused() -> None:
    status = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=True),
        {
            "wallet": {"address": OTHER_ACCOUNT, "private_key": WALLET_KEY},
            "chains": {"anvil": {"rpc_url": "http://anvil.test"}},
            "default_chain": "anvil",
        },
        "buyer",
    )

    assert status.ready is True


@pytest.mark.asyncio
async def test_a_buyer_preflight_needs_no_key_and_no_deliverable_models() -> None:
    status = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=True),
        {
            "wallet": {"address": WALLET},
            "chains": {"anvil": {"rpc_url": "http://anvil.test"}},
            "default_chain": "anvil",
        },
        "buyer",
    )

    assert status.ready is True


@pytest.mark.asyncio
async def test_a_buyer_is_never_compared_with_the_release_oracle() -> None:
    # An escrow pays the seller's wallet, never the buyer's, so a buyer whose
    # own wallet is the configured oracle is not refused for it.
    status = await alkahest_preflight(
        AlkahestSettlementConfig(
            enabled=True, oracle_gated=True, trusted_oracle_addresses=(WALLET,)
        ),
        {
            "wallet": {"address": WALLET},
            "chains": {"anvil": {"rpc_url": "http://anvil.test"}},
            "default_chain": "anvil",
        },
        "buyer",
    )

    assert status.ready is True


@pytest.mark.asyncio
async def test_ready_alkahest_preflight_is_observational_and_public_only() -> None:
    def forbid_client_access(_chain):
        raise AssertionError("preflight must not call a transaction client")

    resources = {
        "wallet": {"address": "0x" + "11" * 20, "private_key": "never-report"},
        "chains": {
            "ethereum_sepolia": {
                "rpc_url": "https://private-rpc.example/key",
                "chain_id": 11155111,
            }
        },
        "chain_name": "ethereum_sepolia",
        "get_client": forbid_client_access,
        "settlement_state": {"unchanged": True},
    }
    before = deepcopy(resources)

    status = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=True),
        resources,
        "seller",
    )

    assert status.ready is True
    assert resources == before
    projection = status.model_dump_json()
    assert "never-report" not in projection
    assert "private-rpc" not in projection
    assert status.public_details == {
        "oracle_gated": False,
        "interruptible": False,
        "chain": "ethereum_sepolia",
    }


@pytest.mark.asyncio
async def test_alkahest_preflight_admits_all_listing_chains_without_default() -> None:
    resources = {
        "wallet": {"address": "0x" + "11" * 20},
        "chains": {
            "chain-a": {"rpc_url": "https://a.example", "chain_id": 1},
            "chain-b": {"rpc_url": "https://b.example", "chain_id": 2},
        },
        "accepted_escrows": [
            {"chain_name": "chain-b"},
            {"chain_name": "chain-a"},
            {"chain_name": "chain-b"},
        ],
    }

    status = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=True),
        resources,
        "seller",
    )

    assert status.ready is True
    assert "chain" not in status.public_details


@pytest.mark.asyncio
async def test_a_complete_disabled_section_reports_nothing_beside_being_disabled() -> None:
    status = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=False),
        _seller_resources(chain_name=None, chain_probe=None),
        "seller",
    )

    assert (status.enabled, status.ready) == (False, False)
    assert status.blockers == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"wallet": {"address": WALLET}}, {"alkahest.wallet_key_missing"}),
        (
            {"wallet": {"address": OTHER_ACCOUNT, "private_key": WALLET_KEY}},
            {"alkahest.wallet_address_mismatch"},
        ),
        ({"chains": {}}, {"alkahest.chains_missing"}),
        (
            {"deliverable_release_models": frozenset({"recipient"})},
            {"alkahest.release_model_undeliverable"},
        ),
    ],
    ids=["key", "address", "chains", "release-model"],
)
async def test_a_disabled_section_names_what_would_stop_its_servicing(
    overrides, expected
) -> None:
    config = AlkahestSettlementConfig(
        enabled=False,
        oracle_gated=True,
        trusted_oracle_addresses=["0x" + "cd" * 20],
    )

    status = await alkahest_preflight(config, _seller_resources(**overrides), "seller")

    assert {(b.code, b.kind) for b in status.blockers} == {
        (code, "configuration") for code in expected
    }


@pytest.mark.asyncio
async def test_a_buyers_disabled_section_reports_nothing() -> None:
    status = await alkahest_preflight(AlkahestSettlementConfig(enabled=False), {}, "buyer")

    assert (status.enabled, status.ready, status.blockers) == (False, False, ())


def test_alkahest_registration_has_exact_contract_and_factory() -> None:
    registration = create_alkahest_registration()
    assert registration.mechanism_id == ALKAHEST_MECHANISM_ID
    assert registration.config_key == ALKAHEST_CONFIG_KEY
    assert registration.roles == frozenset({"buyer", "seller"})

    clients = {"ethereum_sepolia": object()}
    client = registration.client_factory(
        AlkahestSettlementConfig(enabled=False),
        {
            "clients": clients,
            "chains": {"ethereum_sepolia": {}},
            "chain_name": "ethereum_sepolia",
        },
        "buyer",
    )
    assert type(client) is AlkahestConditionalEscrowClient


@pytest.mark.asyncio
async def test_alkahest_option_builder_emits_canonical_buyer_choice() -> None:
    config = AlkahestSettlementConfig(enabled=True)
    resources = {
        "wallet": {"address": "0x" + "11" * 20},
        "chains": {"ethereum_sepolia": {"rpc_url": "https://rpc.example"}},
    }
    readiness = await alkahest_preflight(config, resources, "seller")
    registration = create_alkahest_registration()
    escrow = {
        "chain_name": "ethereum_sepolia",
        "escrow_address": "0x" + "22" * 20,
        "literal_fields": {"token": "0x" + "33" * 20},
        "rates": [{"field": "amount", "per": "hour", "value": "125"}],
    }

    publication = registration.option_builder(
        config,
        readiness,
        {"accepted_escrows": [escrow]},
        "seller",
    )

    assert publication["accepted_escrows"] == [escrow]
    option = publication["settlement_options"][0]
    assert option["mechanism"] == ALKAHEST_MECHANISM_ID
    assert len(option["option_id"]) == 64
    assert option["params"]["accepted_escrow"] == escrow
    assert registration.buyer_compatibility(
        config,
        option,
        {"chains": {"ethereum_sepolia"}},
    )


@pytest.mark.asyncio
async def test_alkahest_clause_projection_is_public_pure_and_identity_preserving() -> (
    None
):
    config = AlkahestSettlementConfig(enabled=True)
    registration = create_alkahest_registration()
    registry = SettlementConfigurationRegistry([registration])
    resources = {
        "wallet": {"address": "0x" + "11" * 20},
        "chains": {"base_sepolia": {"rpc_url": "https://rpc.example"}},
    }
    readiness = await alkahest_preflight(config, resources, "seller")
    wire = registration.option_builder(
        config,
        readiness,
        {
            "accepted_escrows": [
                {
                    "chain_name": "base_sepolia",
                    "escrow_kind": "erc20_escrow_obligation_default",
                    "escrow_address": "0x" + "22" * 20,
                    "literal_fields": {"token": "0x" + "33" * 20},
                    "rates": [{"field": "amount", "per": "hour", "value": "125"}],
                }
            ]
        },
        "seller",
    )["settlement_options"][0]
    option = SettlementOption.model_validate(wire)
    before = option.model_dump(mode="json")
    clause = compile_settlement_clause(
        "mechanism=alkahest alkahest.chain=base_sepolia "
        "alkahest.escrow_kind=erc20_escrow_obligation_default",
        registry,
    )

    assert settlement_clause_matches(clause, option, registry) is True
    assert option.model_dump(mode="json") == before
    assert option.option_id == wire["option_id"]


def test_alkahest_publication_input_rejects_secret_canary() -> None:
    registry = SettlementConfigurationRegistry([create_alkahest_registration()])
    config = registry.resolve(
        {
            "priority": [ALKAHEST_MECHANISM_ID],
            "alkahest": {"enabled": True},
        },
        role="seller",
    )

    value = registry.validate_publication_input(
        ALKAHEST_MECHANISM_ID,
        {
            "chain": "base_sepolia",
            "escrow_kind": "erc20_escrow_obligation_default",
        },
        config,
        role="seller",
    )

    assert value.model_dump(mode="json") == {
        "chain": "base_sepolia",
        "escrow_kind": "erc20_escrow_obligation_default",
    }
    with pytest.raises(SettlementConfigurationError, match="invalid publication input"):
        registry.validate_publication_input(
            ALKAHEST_MECHANISM_ID,
            {
                "chain": "base_sepolia",
                "escrow_kind": "erc20_escrow_obligation_default",
                "private_key": "canary",
            },
            config,
            role="seller",
        )


def test_alkahest_publication_clause_builds_exact_scaled_option(monkeypatch) -> None:
    registration = create_alkahest_registration()
    clause = SettlementPublicationClause(
        mechanism=ALKAHEST_MECHANISM_ID,
        asset="0x" + "12" * 20,
        rate="1.25",
        per="hour",
        mechanism_input={
            "chain": "base_sepolia",
            "escrow_kind": "erc20_escrow_obligation_default",
        },
    )
    monkeypatch.setattr(
        "market_alkahest.token.resolve_token",
        lambda *_args, **_kwargs: SimpleNamespace(
            contract_address=clause.asset,
            decimals=6,
        ),
    )
    monkeypatch.setattr(
        "market_alkahest.alkahest.get_erc20_escrow_obligation_default",
        lambda *_args, **_kwargs: "0x" + "34" * 20,
    )
    readiness = MechanismReadiness(
        mechanism=ALKAHEST_MECHANISM_ID,
        configured=True,
        enabled=True,
        ready=True,
    )

    artifacts = registration.option_builder(
        AlkahestSettlementConfig(enabled=True),
        readiness,
        {
            "publication_clause": clause,
            "chains": {
                "base_sepolia": {
                    "rpc_url": "https://rpc.example",
                    "chain_id": 84532,
                }
            },
        },
        "seller",
    )

    escrow = artifacts["accepted_escrows"][0]
    option = artifacts["settlement_options"][0]
    assert escrow == {
        "chain_name": "base_sepolia",
        "escrow_address": "0x" + "34" * 20,
        "literal_fields": {"token": clause.asset},
        "rates": [{"field": "amount", "per": "hour", "value": "1250000"}],
    }
    assert option["mechanism"] == ALKAHEST_MECHANISM_ID
    assert option["asset"] == clause.asset
    assert option["rates"] == escrow["rates"]
    assert option["params"] == {"accepted_escrow": escrow}


def _build_alkahest_option(monkeypatch, rate: str, decimals: int) -> dict:
    registration = create_alkahest_registration()
    clause = SettlementPublicationClause(
        mechanism=ALKAHEST_MECHANISM_ID,
        asset="0x" + "12" * 20,
        rate=rate,
        per="hour",
        mechanism_input={
            "chain": "base_sepolia",
            "escrow_kind": "erc20_escrow_obligation_default",
        },
    )
    monkeypatch.setattr(
        "market_alkahest.token.resolve_token",
        lambda *_args, **_kwargs: SimpleNamespace(
            contract_address=clause.asset,
            decimals=decimals,
        ),
    )
    monkeypatch.setattr(
        "market_alkahest.alkahest.get_erc20_escrow_obligation_default",
        lambda *_args, **_kwargs: "0x" + "34" * 20,
    )
    readiness = MechanismReadiness(
        mechanism=ALKAHEST_MECHANISM_ID,
        configured=True,
        enabled=True,
        ready=True,
    )
    return registration.option_builder(
        AlkahestSettlementConfig(enabled=True),
        readiness,
        {
            "publication_clause": clause,
            "chains": {
                "base_sepolia": {
                    "rpc_url": "https://rpc.example",
                    "chain_id": 84532,
                }
            },
        },
        "seller",
    )


def test_alkahest_rate_longer_than_a_decimal_context_scales_exactly(monkeypatch) -> None:
    # 40 significant digits: a 28-digit Decimal context would round the product.
    rate = "1234567890123456789012.123456789012345678"
    artifacts = _build_alkahest_option(monkeypatch, rate, 18)
    assert artifacts["settlement_options"][0]["rates"] == [
        {
            "field": "amount",
            "per": "hour",
            "value": "1234567890123456789012123456789012345678",
        }
    ]


def test_alkahest_long_rate_below_one_base_unit_is_refused(monkeypatch) -> None:
    rate = "1234567890123456789012.1234567890123456789"  # 19 decimal places
    with pytest.raises(ValueError, match="more than 18 decimal places"):
        _build_alkahest_option(monkeypatch, rate, 18)


def test_alkahest_rate_beyond_uint256_is_refused(monkeypatch) -> None:
    with pytest.raises(ValueError, match="uint256"):
        _build_alkahest_option(monkeypatch, str(2**256), 0)


def test_registration_verifies_settlement_against_the_accepted_plan() -> None:
    registration = create_alkahest_registration()
    assert registration.settlement_verifier is verify_escrow_against_plan
