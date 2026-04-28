import json
import copy
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
        "trivial_arbiter": "0x50EDa6c29C740bfbA6875422287025D985b96b7b",
        "trusted_oracle_arbiter": "0x3664b11BcCCeCA27C21BBAB43548961eD14d4D6D",
        "intrinsics_arbiter": "0x24aAFec3f86CAd330600dD2397DEB8498D44bfd9",
        "intrinsics_arbiter_2": "0x51a28Ad45BE6eb6fd6D76af56a7D62ECd99547C7",
        "erc8004_arbiter": "0x67B23406dd9e9EA884B3d14746ef73106b1C35d6",
        "any_arbiter": "0xaaC3465f340C7A2841A120F81Ce6744cda00d263",
        "all_arbiter": "0x0D95c1Cd62cd9C7cCCB237a3Ae08aA61Ed83381f",
        "attester_arbiter": "0xB0d19784373EC5FDd2E44A2b594B10FE9bBecC94",
        "expiration_time_after_arbiter": "0x05Ae296859454612a9a346B2EeBE6915319993Ec",
        "expiration_time_before_arbiter": "0x698008cC7F4714D331Aa27278BfE6B74FA925cF7",
        "expiration_time_equal_arbiter": "0x4d05EA86C2C0af7CA94dc71Da45aba9368e664e4",
        "recipient_arbiter": "0xE6CB55B60b6B47B45de05df75B48D656E4bD3730",
        "ref_uid_arbiter": "0xdEc95668f431639AAE975CfA9101Bb2A5b5803F6",
        "revocable_arbiter": "0x550eF7e901F612914651f3c92c0798eBab037AF6",
        "schema_arbiter": "0xc15Ef82Adf03820dA8a0705200602107a06652BE",
        "time_after_arbiter": "0xd88274b04194bebA06B32D3F67265e4b530F4C4d",
        "time_before_arbiter": "0xEC177a4FA6c42B1EA2bbEC70F3FFaE2aCD94e4aF",
        "time_equal_arbiter": "0x0E16A9f94aD457214d5e8AdD30c64D8c6FD4a416",
        "uid_arbiter": "0x0Be4E6D777D5C1AE3DDF338AF2398A279571511b",
        "exclusive_revocable_confirmation_arbiter": "0xBA0e678f4F1a62f5d737F9289B7e1F2F8580DD8D",
        "exclusive_unrevocable_confirmation_arbiter": "0x141Bfd94A1C2B2728dF693657d1C7589b06A139E",
        "nonexclusive_revocable_confirmation_arbiter": "0xB78A1870C5412EBa6042a5b1dE895E8f879AbeC6",
        "nonexclusive_unrevocable_confirmation_arbiter": "0x74FaFAAEa1bA879E73Cd7e38ec6F3ff86554D4B7",
    },
    "string_obligation_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "obligation": "0x544873C22A3228798F91a71C4ef7a9bFe96E7CE0",
    },
    "commit_reveal_obligation_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "obligation": "0x447b11ce03237f0C674eF7F16c913c3B2e8ef494",
    },
    "erc20_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "barter_utils": "0x946Ef4E912897B4A24b9250513dfeE3fc4303Dde",
        "escrow_obligation_nontierable": "0x1Fe964348Ec42D9Bb1A072503ce8b4744266FF43",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x8d13d7542E64D9Da29AB66B6E9b4a6583C64b3F6",
    },
    "erc721_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "barter_utils": "0x707f280Fa738b4cc175A369d450f2f603094cbAf",
        "escrow_obligation_nontierable": "0x7675a56b2880EF059cFC725E715E1139D689c07B",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x9Daf829f183cA46ad2146F489E7d14335C9B59a9",
    },
    "erc1155_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "barter_utils": "0x4E4F0F883B1fEC20F219E0c8D2ec0061FE3c1328",
        "escrow_obligation_nontierable": "0xB8A3107DA5428a34f818ea4229233fBAe59C16F2",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0x6f71429bD940Bf3345780a8E5F5cf3BcdffE80C1",
    },
    "native_token_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "barter_utils": "0xaaB70Cfc37C5E73e185E2976609A82Ba22A4310d",
        "escrow_obligation_nontierable": "0x8a1172D32B8cEf14094cF1E7d6F3d1A36D949FDe",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0xAB1E9714fbD4f9B5546e891B7Ba392b08c44c37A",
    },
    "token_bundle_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "barter_utils": "0x47C033F49D5A1559AC48f27571204a29b8E728b8",
        "escrow_obligation_nontierable": "0x38e8E5684aFB24A88cD9B276032bCBD19C4b9d6e",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "payment_obligation": "0xFa5446475De31fa3c6457E2b62EA5a8F8172Cd29",
    },
    "attestation_addresses": {
        "eas": "0x4200000000000000000000000000000000000021",
        "eas_schema_registry": "0x4200000000000000000000000000000000000020",
        "barter_utils": "0x84D390BCd90d5f65D14ff66f6860DCa45e776666",
        "escrow_obligation_nontierable": "0x9D133Cbd51270a2A410465F82dAFFD6c1C87322D",
        "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
        "escrow_obligation_2_nontierable": "0xa076e9ca47f192E6AfB67817608E382074CF0Dcf",
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
            f"Unsupported chain network '{network}'. "
            f"Supported values: {sorted(SUPPORTED_NETWORKS)}"
        )
    return network


@lru_cache(maxsize=8)
def _load_override_config_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("alkahest address config path must point to a JSON object")
    return data


def _load_override_config(
    config_path: str | None,
) -> dict[str, Any] | None:
    if config_path and config_path.strip():
        normalized_path = str(Path(config_path).expanduser().resolve())
        # Return a copy so callers cannot mutate cached state.
        return copy.deepcopy(_load_override_config_cached(normalized_path))
    return None


def prewarm_alkahest_address_config_cache(config_path: str | None) -> None:
    """Eagerly load/validate the configured address override JSON (if any).

    ``config_path=None`` is a valid input (no override) — callers pass
    their resolved config value explicitly; nothing is read from env.
    """
    _load_override_config(config_path)


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


def get_trusted_oracle_arbiter(
    chain_name: str,
    *,
    config_path: str | None = None,
) -> str:
    selected = get_alkahest_network(chain_name)
    override = _load_override_config(config_path)
    if override is not None:
        return str(override["arbiters_addresses"]["trusted_oracle_arbiter"])
    if selected in NETWORK_ADDRESS_CONFIGS:
        return str(
            NETWORK_ADDRESS_CONFIGS[selected]["arbiters_addresses"][
                "trusted_oracle_arbiter"
            ]
        )

    raise ValueError(
        "chain_name='anvil' requires an explicit alkahest_address_config_path "
        "with deployed local addresses."
    )


def get_recipient_arbiter(
    chain_name: str,
    *,
    config_path: str | None = None,
) -> str:
    """Resolve the RecipientArbiter address for the selected network.

    Mirrors ``get_trusted_oracle_arbiter``. Used when the escrow demand is
    "the fulfillment attestation's recipient must equal X" — the simplest
    non-oracle gating scheme available. For compute deals, X is the
    seller's wallet, because ``StringObligation.doObligation`` sets the
    fulfillment attestation's recipient to ``msg.sender`` (the seller).
    """
    selected = get_alkahest_network(chain_name)
    override = _load_override_config(config_path)
    if override is not None:
        return str(override["arbiters_addresses"]["recipient_arbiter"])
    if selected in NETWORK_ADDRESS_CONFIGS:
        return str(
            NETWORK_ADDRESS_CONFIGS[selected]["arbiters_addresses"][
                "recipient_arbiter"
            ]
        )

    raise ValueError(
        "chain_name='anvil' requires an explicit alkahest_address_config_path "
        "with deployed local addresses."
    )


def encode_recipient_demand(recipient_address: str) -> bytes:
    """ABI-encode RecipientArbiter.DemandData{address recipient}.

    alkahest_py exposes TrustedOracleArbiterDemandData but no analogous
    encoder for RecipientArbiter, so we encode the tuple directly. The
    solidity struct is a single-field struct, which abi.encodes as a
    padded 32-byte address (same as abi.encode(address)).
    """
    from eth_abi import encode as _abi_encode
    from eth_abi.exceptions import EncodingError

    if (
        not isinstance(recipient_address, str)
        or not recipient_address.startswith("0x")
        or len(recipient_address) != 42
    ):
        raise ValueError(
            f"recipient_address must be a 0x-prefixed 20-byte hex string, got {recipient_address!r}"
        )
    # Catch eth_abi's own errors (malformed hex characters, checksum issues)
    # and re-raise as ValueError so callers have a single exception type.
    try:
        return _abi_encode(["address"], [recipient_address])
    except EncodingError as exc:
        raise ValueError(
            f"recipient_address {recipient_address!r} is not valid hex: {exc}"
        ) from exc
