import json
import copy
import os
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

NETWORK_ANVIL = "anvil"
NETWORK_BASE_SEPOLIA = "base_sepolia"
NETWORK_ETHEREUM_SEPOLIA = "ethereum_sepolia"
NETWORK_ETHEREUM_MAINNET = "ethereum_mainnet"
SUPPORTED_NETWORKS = {
    NETWORK_ANVIL,
    NETWORK_BASE_SEPOLIA,
    NETWORK_ETHEREUM_SEPOLIA,
    NETWORK_ETHEREUM_MAINNET,
}


BASE_SEPOLIA_ADDRESSES: dict[str, Any] = {
    "arbiters_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "trivial_arbiter": "0x7D4bCD84901cEC903105564f63BE70432448B222",
        "trusted_oracle_arbiter": "0x361E0950534F4a54A39F8C4f1f642C323f6e66B9",
        "intrinsics_arbiter": "0x0000000000000000000000000000000000000000",
        "intrinsics_arbiter_2": "0x0000000000000000000000000000000000000000",
        "erc8004_arbiter": "0x0000000000000000000000000000000000000000",
        "any_arbiter": "0x0000000000000000000000000000000000000000",
        "all_arbiter": "0x0000000000000000000000000000000000000000",
        "attester_arbiter": "0x0000000000000000000000000000000000000000",
        "expiration_time_after_arbiter": "0x0000000000000000000000000000000000000000",
        "expiration_time_before_arbiter": "0x0000000000000000000000000000000000000000",
        "expiration_time_equal_arbiter": "0x0000000000000000000000000000000000000000",
        "recipient_arbiter": "0x0000000000000000000000000000000000000000",
        "ref_uid_arbiter": "0x0000000000000000000000000000000000000000",
        "revocable_arbiter": "0x0000000000000000000000000000000000000000",
        "schema_arbiter": "0x0000000000000000000000000000000000000000",
        "time_after_arbiter": "0x0000000000000000000000000000000000000000",
        "time_before_arbiter": "0x0000000000000000000000000000000000000000",
        "time_equal_arbiter": "0x0000000000000000000000000000000000000000",
        "uid_arbiter": "0x0000000000000000000000000000000000000000",
        "exclusive_revocable_confirmation_arbiter": "0x0000000000000000000000000000000000000000",
        "exclusive_unrevocable_confirmation_arbiter": "0x0000000000000000000000000000000000000000",
        "nonexclusive_revocable_confirmation_arbiter": "0x0000000000000000000000000000000000000000",
        "nonexclusive_unrevocable_confirmation_arbiter": "0x0000000000000000000000000000000000000000",
    },
    "string_obligation_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "obligation": "0x4edEa259C8E014eeEd583D1a863e020190B21Db7",
    },
    "commit_reveal_obligation_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "obligation": "0x447b11ce03237f0C674eF7F16c913c3B2e8ef494",
    },
    "erc20_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "barter_utils": "0x5C624f8FbbB377378cDfE8B627384A917FE839db",
        "escrow_obligation_nontierable": "0xFa76421cEe6aee41adc7f6a475b9Ef3776d500F0",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0xE95d3931E15E4d96cE1d2Dd336DcEad35A708bdB",
    },
    "erc721_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "barter_utils": "0x01414CC4a4c7b7fa9F551907ee89c867c7a74d29",
        "escrow_obligation_nontierable": "0xF3C3dC387e00FE76CCF7549634aa694D466de5AA",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x9DFe20Ded52D0F9e535F546f87d83B473DefC5B2",
    },
    "erc1155_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "barter_utils": "0x70a9Ce33CF0f7487A8a33B1447455047A90F3998",
        "escrow_obligation_nontierable": "0x4e7d759Df6204d901fb6FD82248FEa64f129bfa3",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x799048b0772381A095aa37305C1D85f26b8445C7",
    },
    "native_token_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "barter_utils": "0x0000000000000000000000000000000000000000",
        "escrow_obligation_nontierable": "0x0000000000000000000000000000000000000000",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x0000000000000000000000000000000000000000",
    },
    "token_bundle_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "barter_utils": "0xb03633005C763feAD6993541Cab2a10FA79828c1",
        "escrow_obligation_nontierable": "0xf63e97217f71C4cdbA643c8EFc9F152486560542",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0xd192685E79F760fA769614d22916528254FD4937",
    },
    "attestation_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "eas_schema_registry": "0x4200000000000000000000000000000000000020",
        "barter_utils": "0xfFA2bf5Fc4270e9AFd20Aa2C87b3B100489DF97a",
        "escrow_obligation_nontierable": "0x021d28E9eBc935Bf21fe5Ff48cAAbE126Ed706aB",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "escrow_obligation_2_nontierable": "0x5f177293F46d938316229A07E31bC65d64D58c9b",
        "escrow_obligation_2_tierable": "0x0000000000000000000000000000000000000000",
    },
}


ETHEREUM_SEPOLIA_ADDRESSES: dict[str, Any] = {
    "arbiters_addresses": {
        "eas": "0xC2679fBD37d54388Ce493F1DB75320D236e1815e",
        "trivial_arbiter": "0x594E79466b6ac01C6416C929e428264a4bdF0C92",
        "trusted_oracle_arbiter": "0x3B2a812E3eb3B729D40d866Da16c2BB2b6cDd2f2",
        "intrinsics_arbiter": "0xaabdDAa76651d20922d1F561f924a40F6fE7710c",
        "intrinsics_arbiter_2": "0xF486f9a62eeb085e99828e1D706bBA5dfC1bD1fD",
        "erc8004_arbiter": "0x367fEd55E65bd0FCCF8F966A04989AB61E1b5A49",
        "any_arbiter": "0xe968dFA581B8aBb94eC5F24d0b56163DE69511fD",
        "all_arbiter": "0x847F69d27E4F1A8a115aCa3F4358B079706dc9CE",
        "attester_arbiter": "0x6CC4068d471E96A1669097918e18017f5764f72a",
        "expiration_time_after_arbiter": "0x309509db364526C7aE202eA9ED94a398a0819d38",
        "expiration_time_before_arbiter": "0xFAf8a07709dB9f90d0A0415876CfE00D904cd40B",
        "expiration_time_equal_arbiter": "0x7c782ac7741BB78DB7491Ee222af0a04f7f2bc0b",
        "recipient_arbiter": "0xF1C9E20078A13816ACdDF3153e2eAaDd93Fd6E57",
        "ref_uid_arbiter": "0xE9ee2c57B18283b66d342D33d63C55f1427f9e9B",
        "revocable_arbiter": "0xeda25079f76ef93c54cC042116Be8D88E49D3439",
        "schema_arbiter": "0x913eAdD13dcCdeD9CD5518075083b6C7A9574A8c",
        "time_after_arbiter": "0x0ea9e144FfDc6456E5cE8d1f75c686112e8f29c5",
        "time_before_arbiter": "0x68A6e6022ab9984Ee1A9A6cee384FF2aE8be5264",
        "time_equal_arbiter": "0x208385Fb349c01af2CfA8C6b86F633F6642718e2",
        "uid_arbiter": "0xae4fa2D5d7EDD6Aaf697dC0c98EDb921F0fEc058",
        "exclusive_revocable_confirmation_arbiter": "0x941044D43F9d75dfA8Ad24880B9B9cAD6e116a66",
        "exclusive_unrevocable_confirmation_arbiter": "0x16aeE626D398B547eDD5fa4BdAA638524C92921d",
        "nonexclusive_revocable_confirmation_arbiter": "0xe483EDA58b5f9Eba06A1ad0151dA5e4a5fFC8300",
        "nonexclusive_unrevocable_confirmation_arbiter": "0x01666d869918aDDDED1B30eF2d36f3C990F09BDE",
    },
    "string_obligation_addresses": {
        "eas": "0xC2679fBD37d54388Ce493F1DB75320D236e1815e",
        "obligation": "0xC51C938f5497be8157DAf8CCc3Eb11Afb8b752C0",
    },
    "commit_reveal_obligation_addresses": {
        "eas": "0xC2679fBD37d54388Ce493F1DB75320D236e1815e",
        "obligation": "0x9fD6D7A3B4e4b5dD75c50F5f16Deba46162127C3",
    },
    "erc20_addresses": {
        "eas": "0xC2679fBD37d54388Ce493F1DB75320D236e1815e",
        "barter_utils": "0x5bf7c8b0d60d05af0a3De531EB876De271E80dbc",
        "escrow_obligation_nontierable": "0xB2c808911E84E80156101983897Da7c80e13cB47",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0xb822aA07F55a8B75Ee133ede1f21C4E49DE7952f",
    },
    "erc721_addresses": {
        "eas": "0xC2679fBD37d54388Ce493F1DB75320D236e1815e",
        "barter_utils": "0xEB0C0c41F708B8b3556a6F44a1a015a6832C2d2C",
        "escrow_obligation_nontierable": "0x2A7df117e45D93d34a7893CC3aE8B105Ae0B561C",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x59A9c929778Ad2cC4D5DB6151bDEf0F9Fa7A068C",
    },
    "erc1155_addresses": {
        "eas": "0xC2679fBD37d54388Ce493F1DB75320D236e1815e",
        "barter_utils": "0x52De4B30721b3E3660A79da7491a9B2F8a9cB1D5",
        "escrow_obligation_nontierable": "0xf04d9CA943f57353A3A735494E503280C1cD5e77",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x52748DD0E39eD6eA9f626179b5eb512302adA7D9",
    },
    "native_token_addresses": {
        "eas": "0xC2679fBD37d54388Ce493F1DB75320D236e1815e",
        "barter_utils": "0xA42032D8BFeE2302cC6F80ff51D283Ffc5a4081f",
        "escrow_obligation_nontierable": "0x9bA50DB048d1E5db034377abf97F92496D027C71",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0xf60db64506E366a0A6c1f4cF9D849Adc7bB886D6",
    },
    "token_bundle_addresses": {
        "eas": "0xC2679fBD37d54388Ce493F1DB75320D236e1815e",
        "barter_utils": "0xA7EacA68Bffc9443eA08fd58633Eeed3f5EE8A92",
        "escrow_obligation_nontierable": "0x677Aa9e1CD9D05f57FbCa2327155EA7479ec7Ac3",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x36Fcf1Ddee838a94B1358285A11e8bbbb90eD9A1",
    },
    "attestation_addresses": {
        "eas": "0xC2679fBD37d54388Ce493F1DB75320D236e1815e",
        "eas_schema_registry": "0x0a7E2Ff54e76B8E6659aedc9103FB21c038050D0",
        "barter_utils": "0x5E6602F080E9B37267aa52306c699ae54Cd71056",
        "escrow_obligation_nontierable": "0x6eb7792D821f32914Be75901F1b4269B13Efad2e",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "escrow_obligation_2_nontierable": "0x1A7c6F951e0a33F4910dbe56a200Eb413AEca17b",
        "escrow_obligation_2_tierable": "0x0000000000000000000000000000000000000000",
    },
}


ETHEREUM_MAINNET_ADDRESSES: dict[str, Any] = {
    "arbiters_addresses": {
        "eas": "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        "trivial_arbiter": "0x594E79466b6ac01C6416C929e428264a4bdF0C92",
        "trusted_oracle_arbiter": "0x3B2a812E3eb3B729D40d866Da16c2BB2b6cDd2f2",
        "intrinsics_arbiter": "0xaabdDAa76651d20922d1F561f924a40F6fE7710c",
        "intrinsics_arbiter_2": "0xF486f9a62eeb085e99828e1D706bBA5dfC1bD1fD",
        "erc8004_arbiter": "0xBE7fE4d7CEb2140eeBdf01e12D198AEBAdC1F54D",
        "any_arbiter": "0xe968dFA581B8aBb94eC5F24d0b56163DE69511fD",
        "all_arbiter": "0x847F69d27E4F1A8a115aCa3F4358B079706dc9CE",
        "attester_arbiter": "0x6CC4068d471E96A1669097918e18017f5764f72a",
        "expiration_time_after_arbiter": "0x309509db364526C7aE202eA9ED94a398a0819d38",
        "expiration_time_before_arbiter": "0xFAf8a07709dB9f90d0A0415876CfE00D904cd40B",
        "expiration_time_equal_arbiter": "0x7c782ac7741BB78DB7491Ee222af0a04f7f2bc0b",
        "recipient_arbiter": "0xF1C9E20078A13816ACdDF3153e2eAaDd93Fd6E57",
        "ref_uid_arbiter": "0xE9ee2c57B18283b66d342D33d63C55f1427f9e9B",
        "revocable_arbiter": "0xeda25079f76ef93c54cC042116Be8D88E49D3439",
        "schema_arbiter": "0x913eAdD13dcCdeD9CD5518075083b6C7A9574A8c",
        "time_after_arbiter": "0x0ea9e144FfDc6456E5cE8d1f75c686112e8f29c5",
        "time_before_arbiter": "0x68A6e6022ab9984Ee1A9A6cee384FF2aE8be5264",
        "time_equal_arbiter": "0x208385Fb349c01af2CfA8C6b86F633F6642718e2",
        "uid_arbiter": "0xae4fa2D5d7EDD6Aaf697dC0c98EDb921F0fEc058",
        "exclusive_revocable_confirmation_arbiter": "0x941044D43F9d75dfA8Ad24880B9B9cAD6e116a66",
        "exclusive_unrevocable_confirmation_arbiter": "0x16aeE626D398B547eDD5fa4BdAA638524C92921d",
        "nonexclusive_revocable_confirmation_arbiter": "0xe483EDA58b5f9Eba06A1ad0151dA5e4a5fFC8300",
        "nonexclusive_unrevocable_confirmation_arbiter": "0x01666d869918aDDDED1B30eF2d36f3C990F09BDE",
    },
    "string_obligation_addresses": {
        "eas": "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        "obligation": "0xC51C938f5497be8157DAf8CCc3Eb11Afb8b752C0",
    },
    "commit_reveal_obligation_addresses": {
        "eas": "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        "obligation": "0x05d9Aa2A6AE38619b864Ff7f87A8f94301ecAB42",
    },
    "erc20_addresses": {
        "eas": "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        "barter_utils": "0x5bf7c8b0d60d05af0a3De531EB876De271E80dbc",
        "escrow_obligation_nontierable": "0xB2c808911E84E80156101983897Da7c80e13cB47",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0xb822aA07F55a8B75Ee133ede1f21C4E49DE7952f",
    },
    "erc721_addresses": {
        "eas": "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        "barter_utils": "0xEB0C0c41F708B8b3556a6F44a1a015a6832C2d2C",
        "escrow_obligation_nontierable": "0x2A7df117e45D93d34a7893CC3aE8B105Ae0B561C",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x59A9c929778Ad2cC4D5DB6151bDEf0F9Fa7A068C",
    },
    "erc1155_addresses": {
        "eas": "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        "barter_utils": "0x52De4B30721b3E3660A79da7491a9B2F8a9cB1D5",
        "escrow_obligation_nontierable": "0xf04d9CA943f57353A3A735494E503280C1cD5e77",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x52748DD0E39eD6eA9f626179b5eb512302adA7D9",
    },
    "native_token_addresses": {
        "eas": "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        "barter_utils": "0xA42032D8BFeE2302cC6F80ff51D283Ffc5a4081f",
        "escrow_obligation_nontierable": "0x9bA50DB048d1E5db034377abf97F92496D027C71",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0xf60db64506E366a0A6c1f4cF9D849Adc7bB886D6",
    },
    "token_bundle_addresses": {
        "eas": "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        "barter_utils": "0xA7EacA68Bffc9443eA08fd58633Eeed3f5EE8A92",
        "escrow_obligation_nontierable": "0x677Aa9e1CD9D05f57FbCa2327155EA7479ec7Ac3",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x36Fcf1Ddee838a94B1358285A11e8bbbb90eD9A1",
    },
    "attestation_addresses": {
        "eas": "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        "eas_schema_registry": "0xA7b39296258348C78294F95B872b282326A97BDF",
        "barter_utils": "0x5E6602F080E9B37267aa52306c699ae54Cd71056",
        "escrow_obligation_nontierable": "0x6eb7792D821f32914Be75901F1b4269B13Efad2e",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "escrow_obligation_2_nontierable": "0x1A7c6F951e0a33F4910dbe56a200Eb413AEca17b",
        "escrow_obligation_2_tierable": "0x0000000000000000000000000000000000000000",
    },
}

NETWORK_ADDRESS_CONFIGS: dict[str, dict[str, Any]] = {
    NETWORK_BASE_SEPOLIA: BASE_SEPOLIA_ADDRESSES,
    NETWORK_ETHEREUM_SEPOLIA: ETHEREUM_SEPOLIA_ADDRESSES,
    NETWORK_ETHEREUM_MAINNET: ETHEREUM_MAINNET_ADDRESSES,
}


def _dict_to_namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _dict_to_namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_dict_to_namespace(item) for item in value]
    return value


def get_alkahest_network(value: str | None) -> str:
    network = (value or NETWORK_BASE_SEPOLIA).strip().lower()
    if network not in SUPPORTED_NETWORKS:
        raise ValueError(
            f"Unsupported CHAIN_NAME '{network}'. "
            f"Supported values: {sorted(SUPPORTED_NETWORKS)}"
        )
    return network


@lru_cache(maxsize=8)
def _load_override_config_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("ALKAHEST_ADDRESS_CONFIG_PATH must point to a JSON object")
    return data


def _load_override_config(
    config_path: str | None,
) -> dict[str, Any] | None:
    if config_path and config_path.strip():
        normalized_path = str(Path(config_path).expanduser().resolve())
        # Return a copy so callers cannot mutate cached state.
        return copy.deepcopy(_load_override_config_cached(normalized_path))
    return None


def prewarm_alkahest_address_config_cache(config_path: str | None = None) -> None:
    """Eagerly load/validate the configured address override JSON (if any)."""
    _load_override_config(
        config_path if config_path is not None else os.getenv("ALKAHEST_ADDRESS_CONFIG_PATH")
    )


def resolve_alkahest_address_config(
    network: str,
    *,
    config_path: str | None = None,
) -> Any | None:
    selected = get_alkahest_network(network)
    override = _load_override_config(config_path)
    if override is not None:
        return _dict_to_namespace(override)

    # Base Sepolia is the Alkahest SDK's built-in default network config, so
    # returning None here intentionally tells the client to use those SDK
    # defaults rather than duplicating the address block in this service.
    if selected == NETWORK_BASE_SEPOLIA:
        return None
    if selected == NETWORK_ETHEREUM_SEPOLIA:
        return _dict_to_namespace(ETHEREUM_SEPOLIA_ADDRESSES)
    if selected == NETWORK_ETHEREUM_MAINNET:
        return _dict_to_namespace(ETHEREUM_MAINNET_ADDRESSES)

    raise ValueError(
        "CHAIN_NAME=anvil requires ALKAHEST_ADDRESS_CONFIG_PATH "
        "with deployed local addresses."
    )


def get_trusted_oracle_arbiter() -> str:
    selected = get_alkahest_network(os.getenv("CHAIN_NAME", "ethereum_sepolia"))
    override = _load_override_config(os.getenv("ALKAHEST_ADDRESS_CONFIG_PATH"))
    if override is not None:
        return str(override["arbiters_addresses"]["trusted_oracle_arbiter"])
    if selected in NETWORK_ADDRESS_CONFIGS:
        return str(
            NETWORK_ADDRESS_CONFIGS[selected]["arbiters_addresses"][
                "trusted_oracle_arbiter"
            ]
        )

    raise ValueError(
        "CHAIN_NAME=anvil requires ALKAHEST_ADDRESS_CONFIG_PATH "
        "with deployed local addresses."
    )
