"""Typed configuration and registration for the Alkahest settlement mechanism."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from market_settlement_runtime import (
    ComparisonOperator,
    FieldDescriptor,
    MechanismReadiness,
    MechanismRegistration,
    QueryValueType,
    ReadinessBlocker,
    SettlementClauseField,
    SettlementPublicationClause,
    SettlementRole,
    decimal_rate_to_base_units,
)
from market_config.config_loader import derive_wallet_address
from market_config.setting_types import PositiveSeconds
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .chain_probe import (
    ADDRESS_CONFIG_INVALID,
    CHAIN_ID_MISMATCH,
    CHAIN_UNREACHABLE,
    CONTRACT_MISSING,
    DEFAULT_PROBE_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
)
from .claim_hooks import AlkahestConditionalEscrowClient
from .escrow_verification import verify_escrow_against_plan

ALKAHEST_MECHANISM_ID = "alkahest.v1"
ALKAHEST_CONFIG_KEY = "alkahest"
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ESCROW_KIND = re.compile(r"^[a-z][a-z0-9_]*$")
_CLAUSE_OPERATORS = frozenset(
    {
        ComparisonOperator.EQUAL,
        ComparisonOperator.NOT_EQUAL,
        ComparisonOperator.IN,
        ComparisonOperator.NOT_IN,
    }
)


class AlkahestPublicationInput(BaseModel):
    """Public Alkahest fields accepted from one publication clause."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    chain: str = Field(min_length=1, max_length=128)
    escrow_kind: str = Field(min_length=1, max_length=128)

    @field_validator("chain")
    @classmethod
    def validate_chain(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("chain must be trimmed")
        return value

    @field_validator("escrow_kind")
    @classmethod
    def validate_escrow_kind(cls, value: str) -> str:
        if not _ESCROW_KIND.fullmatch(value):
            raise ValueError("escrow_kind must be a canonical lowercase identifier")
        return value


class AlkahestSettlementConfig(BaseModel):
    """Alkahest-owned policy; identity, wallet, and chains are injected resources."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool = False
    address_config_path: str | None = None
    #: Each configured chain's address book, by chain name; a chain's book is
    #: resolved through :func:`alkahest_address_book`.
    address_books: dict[str, str] = Field(default_factory=dict)
    oracle_gated: bool = False
    trusted_oracle_addresses: tuple[str, ...] = ()
    interruptible: bool = False
    interruptible_oracle_addresses: tuple[str, ...] = ()
    #: How often each configured chain is probed, at most.
    probe_interval_seconds: PositiveSeconds = Field(
        default=DEFAULT_PROBE_INTERVAL_SECONDS, json_schema_extra={"roles": ["seller"]}
    )
    #: The bound on each JSON-RPC call a probe makes.
    rpc_timeout_seconds: PositiveSeconds = Field(
        default=DEFAULT_TIMEOUT_SECONDS, json_schema_extra={"roles": ["seller"]}
    )

    @field_validator("address_config_path")
    @classmethod
    def validate_address_config_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("address_config_path must be non-empty and trimmed")
        return value

    @field_validator("address_books", mode="before")
    @classmethod
    def accept_configuration_tables(cls, value: Any) -> Any:
        # A layered loader may hand the table over as its own mapping type.
        return dict(value) if isinstance(value, Mapping) else value

    @field_validator("address_books")
    @classmethod
    def validate_address_books(cls, value: dict[str, str]) -> dict[str, str]:
        for chain_name, path in value.items():
            if not chain_name or chain_name != chain_name.strip():
                raise ValueError("address_books keys must be non-empty, trimmed chain names")
            if not path or path != path.strip():
                raise ValueError(
                    f"address_books.{chain_name} must be a non-empty, trimmed path"
                )
        return value

    @field_validator(
        "trusted_oracle_addresses",
        "interruptible_oracle_addresses",
        mode="before",
    )
    @classmethod
    def accept_toml_address_lists(cls, values: Any) -> Any:
        return tuple(values) if isinstance(values, list) else values

    @field_validator("trusted_oracle_addresses", "interruptible_oracle_addresses")
    @classmethod
    def validate_oracle_addresses(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            if not _EVM_ADDRESS.fullmatch(value):
                raise ValueError(
                    "oracle addresses must be 20-byte hexadecimal addresses"
                )
            normalized.append(value.lower())
        if len(set(normalized)) != len(normalized):
            raise ValueError("oracle addresses must be unique")
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_oracle_policy(self) -> AlkahestSettlementConfig:
        if not self.oracle_gated and self.trusted_oracle_addresses:
            raise ValueError("trusted_oracle_addresses requires oracle_gated")
        if not self.interruptible and self.interruptible_oracle_addresses:
            raise ValueError("interruptible_oracle_addresses requires interruptible")
        return self


RECIPIENT_RELEASE = "recipient"
ORACLE_GATED_RELEASE = "oracle_gated"
INTERRUPTIBLE_RELEASE = "interruptible"
RELEASE_MODELS: frozenset[str] = frozenset(
    {RECIPIENT_RELEASE, ORACLE_GATED_RELEASE, INTERRUPTIBLE_RELEASE}
)


class ReleaseModelError(ValueError):
    """The configured release model is contradictory or cannot be delivered."""


def configured_release_model(config: AlkahestSettlementConfig | None) -> str:
    """The release model ``config`` selects; no section selects ``recipient``.

    Raises ``ReleaseModelError`` when the section selects both the oracle-gated
    and the interruptible model, since an escrow has one arbiter.
    """
    if config is None:
        return RECIPIENT_RELEASE
    if config.oracle_gated and config.interruptible:
        raise ReleaseModelError(
            "Settlement.alkahest oracle and interruptible policies are mutually "
            "exclusive"
        )
    if config.oracle_gated:
        return ORACLE_GATED_RELEASE
    if config.interruptible:
        return INTERRUPTIBLE_RELEASE
    return RECIPIENT_RELEASE


def alkahest_address_book(
    section: AlkahestSettlementConfig | Mapping[str, Any] | None, chain_name: str
) -> str | None:
    """The address book Alkahest uses on ``chain_name``.

    ``section`` is the role's ``[Settlement.alkahest]``, parsed or not, or
    ``None`` where the role configures none. Answers ``None`` for a chain the
    section names no book for.
    """
    if section is None:
        return None
    config = (
        section
        if isinstance(section, AlkahestSettlementConfig)
        else AlkahestSettlementConfig.model_validate(section)
    )
    return config.address_books.get(chain_name)


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _configuration_blocker(code: str, message: str) -> ReadinessBlocker:
    return ReadinessBlocker(code=code, message=message, kind="configuration")


def _reachability_blocker(code: str, message: str) -> ReadinessBlocker:
    return ReadinessBlocker(code=code, message=message, kind="reachability")


def _configured_wallet_address(wallet: Any) -> str:
    # A composing storefront may pass its wallet as a mapping or object with an
    # ``address``, or as the bare address string.
    if isinstance(wallet, str):
        return wallet.strip()
    value = _value(wallet, "address")
    return value.strip() if isinstance(value, str) else ""


def _wallet_key(wallet: Any) -> str:
    if isinstance(wallet, str):
        return ""
    value = _value(wallet, "private_key")
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    return value.strip() if isinstance(value, str) else ""


def _signing_address(wallet: Any) -> str:
    """The address the wallet's key signs as; empty with no key it can read."""
    return derive_wallet_address(_wallet_key(wallet)) or ""


def wallet_account_address(wallet: Any) -> str:
    """The account a seller wallet names: its address, else its key's.

    ``wallet`` is a mapping or object with ``address`` and ``private_key``, or a
    bare address. A wallet stating no address is the account its key signs as,
    so every place that names the seller's address names that account. A wallet
    stating an address that is not its key's is not reconciled here; Alkahest
    readiness reports it as ``alkahest.wallet_address_mismatch``.
    """
    if wallet is None:
        return ""
    return _configured_wallet_address(wallet) or _signing_address(wallet)


def _release_model_blockers(
    config: AlkahestSettlementConfig,
    *,
    role: SettlementRole,
    seller_accounts: frozenset[str],
    deliverable: Any,
) -> list[ReadinessBlocker]:
    """The blockers under which no deal could settle on the configured release model.

    Each is configuration: the section parses, but no escrow released under it
    could pay the seller, so the mechanism is unready rather than the storefront
    stopped. Only a seller's wallet is the one an escrow pays, so the oracle is
    compared with the wallet for the seller role alone, and with both the
    address it names and the account its key signs as, since either is the
    party collecting.
    """
    blockers: list[ReadinessBlocker] = []
    accounts = seller_accounts if role == "seller" else frozenset()
    if config.oracle_gated and not config.trusted_oracle_addresses:
        blockers.append(
            _configuration_blocker(
                "alkahest.oracle_policy_invalid",
                "oracle-gated settlement requires a trusted oracle address",
            )
        )
    if config.interruptible and not config.interruptible_oracle_addresses:
        blockers.append(
            _configuration_blocker(
                "alkahest.interruptible_policy_invalid",
                "interruptible settlement requires an oracle address",
            )
        )
    # The party collecting an escrow cannot also decide whether it collects.
    oracles = (
        config.trusted_oracle_addresses[:1] if config.oracle_gated else ()
    ) + (config.interruptible_oracle_addresses[:1] if config.interruptible else ())
    if any(oracle in accounts for oracle in oracles):
        blockers.append(
            _configuration_blocker(
                "alkahest.oracle_is_seller_wallet",
                "the configured release oracle is the seller wallet",
            )
        )
    if deliverable is not None:
        try:
            model = configured_release_model(config)
        except ReleaseModelError:
            # Not a blocker: a section selecting two release models is
            # incoherent, and its composer refuses it at startup through
            # ``configured_release_model`` before readiness runs.
            model = None
        if model is not None and model not in set(deliverable):
            blockers.append(
                _configuration_blocker(
                    "alkahest.release_model_undeliverable",
                    f"the configured {model!r} release model is not one this "
                    "storefront's domain delivers",
                )
            )
    return blockers


def _chain_probe_blockers(
    chain_probe: Any, chain_names: tuple[str, ...]
) -> list[ReadinessBlocker]:
    """The blocker each selected chain's last probe result raises.

    Readiness reads the probe's last results and calls no chain. A chain not yet
    probed, or whose last probe could not reach it, is unknown rather than
    ruled out. A buyer composes no probe and so reports no chain blocker.
    """
    if chain_probe is None:
        return []
    blockers: list[ReadinessBlocker] = []
    for chain_name in chain_names:
        result = chain_probe.result(chain_name)
        if result is None:
            blockers.append(
                _reachability_blocker(
                    CHAIN_UNREACHABLE, "a selected settlement chain has not been probed yet"
                )
            )
        elif result.result == CHAIN_UNREACHABLE:
            blockers.append(
                _reachability_blocker(
                    CHAIN_UNREACHABLE, "a selected settlement chain could not be reached"
                )
            )
        elif not result.reachable:
            blockers.append(
                _configuration_blocker(result.result, _PROBE_MESSAGES[result.result])
            )
    # One blocker per code: two chains failing alike are one public reason.
    return list({blocker.code: blocker for blocker in blockers}.values())


_PROBE_MESSAGES = {
    CHAIN_ID_MISMATCH: "a selected RPC reports a different chain identity",
    CONTRACT_MISSING: "one or more required Alkahest contracts are not deployed",
    ADDRESS_CONFIG_INVALID: "a selected chain's Alkahest address configuration cannot be resolved",
}


def _selected_chain_names(resources: Mapping[str, Any]) -> tuple[str, ...]:
    """The chains readiness judges.

    What is being published names its chains: escrows a listing publishes, or
    one ``chain_name``. With no publication input, readiness answers whether
    Alkahest can serve everything the storefront configures, so it judges every
    configured chain: servicing an accepted deal needs whichever chain the deal
    was accepted on. A composition's ``default_chain`` selects nothing here.
    """
    chains = resources.get("chains")
    if not isinstance(chains, Mapping) or not chains:
        return ()
    accepted = resources.get("accepted_escrows")
    if isinstance(accepted, (list, tuple)) and accepted:
        names: list[str] = []
        for escrow in accepted:
            name = _value(escrow, "chain_name") or _value(escrow, "chain")
            if not isinstance(name, str) or name not in chains:
                return ()
            if name not in names:
                names.append(name)
        return tuple(names)
    selected = resources.get("chain_name")
    if selected is None:
        return tuple(str(name) for name in chains)
    if not isinstance(selected, str) or selected not in chains:
        return ()
    return (selected,)


def _validate_address_file(path: str) -> bool:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict)


def _wallet_blockers(
    wallet: Any, *, role: SettlementRole, signs: bool
) -> tuple[ReadinessBlocker, ...]:
    if wallet is None:
        return (
            _configuration_blocker(
                "alkahest.wallet_missing", "an injected settlement wallet is required"
            ),
        )
    blockers: list[ReadinessBlocker] = []
    configured = _configured_wallet_address(wallet)
    signing = _signing_address(wallet)
    if not (configured or signing):
        blockers.append(
            _configuration_blocker(
                "alkahest.wallet_address_missing",
                "the settlement wallet has no address",
            )
        )
    # A seller's address is the recipient its release conditions name, and its
    # key signs the attestation, collection, and refunds: two accounts would
    # leave collection reverting or paying an account the listing never named.
    # A buyer's address names nothing an escrow pays, so a buyer is not judged.
    if (
        role == "seller"
        and configured
        and signing
        and configured.lower() != signing.lower()
    ):
        blockers.append(
            _configuration_blocker(
                "alkahest.wallet_address_mismatch",
                "the settlement wallet's address is not the account its key signs as",
            )
        )
    if signs and not _wallet_key(wallet):
        blockers.append(
            _configuration_blocker(
                "alkahest.wallet_key_missing",
                "the settlement wallet has no private key to sign with",
            )
        )
    return tuple(blockers)


def _chains_missing_blocker() -> ReadinessBlocker:
    return _configuration_blocker(
        "alkahest.chains_missing",
        "no settlement chain is configured under [Chains]",
    )


def _address_config_blockers(
    config: AlkahestSettlementConfig, chains: Any
) -> tuple[ReadinessBlocker, ...]:
    """A book that names no configured chain, and a book that cannot be loaded.

    A book under a name no chain carries would be read by nothing, so the
    chain it was meant for would silently go without it. Where the
    composition passes no chains mapping there is nothing to compare with.
    """
    blockers: list[ReadinessBlocker] = []
    unknown = (
        [name for name in config.address_books if name not in chains]
        if isinstance(chains, Mapping)
        else []
    )
    if unknown:
        # One blocker per code, naming every such key.
        blockers.append(
            _configuration_blocker(
                "alkahest.address_book_chain_unknown",
                "Settlement.alkahest.address_books names "
                + ", ".join(repr(name) for name in sorted(unknown))
                + ", which is not a configured settlement chain",
            )
        )
    paths = (config.address_config_path, *config.address_books.values())
    if any(path and not _validate_address_file(path) for path in paths):
        blockers.append(
            _configuration_blocker(
                "alkahest.address_config_invalid",
                "the Alkahest address configuration cannot be loaded",
            )
        )
    return tuple(blockers)


async def alkahest_preflight(
    section: BaseModel,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> MechanismReadiness:
    """Observe Alkahest prerequisites without submitting a transaction.

    A section that parses but under which no deal could settle is reported
    through configuration blockers, never refused, so a storefront that cannot
    settle through Alkahest still runs its other mechanisms. A section that
    selects both the oracle-gated and the interruptible model is incoherent
    rather than unusable; its composer refuses it at startup, and readiness does
    not report it. The composing storefront supplies, beside its wallet and
    chains:

    - ``deliverable_release_models``: the release models its domain's Alkahest
      seller stage delivers; a configured model outside them is a blocker;
    - ``signs_transactions``: true where the storefront submits transactions
      with the seller wallet's key, so a missing key or no configured chain is
      a blocker;
    - ``chain_probe``: its :class:`~market_alkahest.chain_probe.AlkahestChainProbe`,
      whose last result per selected chain readiness reads; readiness makes no
      chain call of its own.

    A buyer supplies none of them. A wallet stating no address is read as the
    account its key signs as (:func:`wallet_account_address`); a seller's wallet
    whose address and key name two accounts is a blocker, a buyer's is not.

    A seller's disabled section publishes nothing, so it reports only the
    blockers that do not concern publication: its wallet, key, and chains,
    which servicing the deals accepted under it needs; its address
    configuration; and its release model, so a seller re-enabling it learns
    first that it could not settle. A buyer's disabled section reports none.
    """

    config = AlkahestSettlementConfig.model_validate(section)
    wallet = resources.get("wallet")
    seller_accounts = (
        frozenset(
            address.lower()
            for address in (_configured_wallet_address(wallet), _signing_address(wallet))
            if address
        )
        if wallet is not None
        else frozenset()
    )
    signs = bool(resources.get("signs_transactions"))
    chains = resources.get("chains")
    chains_missing = signs and not (isinstance(chains, Mapping) and chains)
    if not config.enabled:
        return MechanismReadiness(
            mechanism=ALKAHEST_MECHANISM_ID,
            configured=True,
            enabled=False,
            ready=False,
            blockers=(
                (
                    *_wallet_blockers(wallet, role=role, signs=signs),
                    *((_chains_missing_blocker(),) if chains_missing else ()),
                    *_address_config_blockers(config, chains),
                    *_release_model_blockers(
                        config,
                        role=role,
                        seller_accounts=seller_accounts,
                        deliverable=resources.get("deliverable_release_models"),
                    ),
                )
                if role == "seller"
                else ()
            ),
            capabilities=("conditional-escrow.v1", "evm.v1"),
            contract_version="alkahest.v1",
            schema_version="1",
            public_details={},
        )

    blockers: list[ReadinessBlocker] = list(
        _wallet_blockers(wallet, role=role, signs=signs)
    )
    chain_names = _selected_chain_names(resources)
    if chains_missing:
        blockers.append(_chains_missing_blocker())
    elif not chain_names or not isinstance(chains, Mapping):
        blockers.append(
            _configuration_blocker(
                "alkahest.chain_missing",
                "each published escrow must select a configured settlement chain",
            )
        )
    else:
        for chain_name in chain_names:
            chain = chains[chain_name]
            client_present = resources.get("get_client") is not None or (
                isinstance(resources.get("clients"), Mapping)
                and resources["clients"].get(chain_name) is not None
            )
            if (
                not _value(chain, "rpc_url")
                and not _value(chain, "client")
                and not client_present
            ):
                blockers.append(
                    _configuration_blocker(
                        "alkahest.rpc_missing",
                        "a selected settlement chain has no RPC client",
                    )
                )
        blockers.extend(_chain_probe_blockers(resources.get("chain_probe"), chain_names))

    blockers.extend(_address_config_blockers(config, chains))

    if resources.get("require_asset") and not resources.get("asset"):
        blockers.append(
            _configuration_blocker(
                "alkahest.asset_missing", "a settlement asset must be selected"
            )
        )
    blockers.extend(
        _release_model_blockers(
            config,
            role=role,
            seller_accounts=seller_accounts,
            deliverable=resources.get("deliverable_release_models"),
        )
    )

    details: dict[str, Any] = {
        "oracle_gated": config.oracle_gated,
        "interruptible": config.interruptible,
    }
    if len(chain_names) == 1:
        details["chain"] = chain_names[0]
    if isinstance(resources.get("asset"), str):
        details["asset"] = resources["asset"]
    chain_probe = resources.get("chain_probe")
    if chain_probe is not None:
        details["chain_probe"] = chain_probe.public_results()
    return MechanismReadiness(
        mechanism=ALKAHEST_MECHANISM_ID,
        configured=True,
        enabled=True,
        ready=not blockers,
        blockers=tuple(blockers),
        capabilities=("conditional-escrow.v1", "evm.v1"),
        contract_version="alkahest.v1",
        schema_version="1",
        public_details=details,
    )


def alkahest_client_factory(
    section: BaseModel,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> AlkahestConditionalEscrowClient:
    """Build the exact Alkahest runtime adapter from injected chain clients."""

    del role
    config = AlkahestSettlementConfig.model_validate(section)
    get_client = resources.get("get_client")
    clients = resources.get("clients")
    if not callable(get_client):
        if not isinstance(clients, Mapping):
            raise ValueError(
                "Alkahest client construction requires injected chain clients"
            )

        def get_client(chain: str | None) -> Any:
            return clients.get(chain or "")

    chains = resources.get("chains")
    # Claims on each chain are serviced against that chain's own book.
    chain_config_paths: dict[str, str | None] = {}
    if isinstance(chains, Mapping):
        chain_config_paths = {
            name: alkahest_address_book(config, name) for name in chains
        }
    return AlkahestConditionalEscrowClient(
        get_client=get_client,
        chain_config_paths=chain_config_paths,
        default_chain=resources.get("chain_name") or resources.get("default_chain"),
        arbitration_probe_timeout=float(
            resources.get("arbitration_probe_timeout", 5.0)
        ),
    )


def _resource_value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _alkahest_escrow_from_clause(
    config: AlkahestSettlementConfig,
    clause: SettlementPublicationClause,
    resources: Mapping[str, Any],
) -> dict[str, Any]:
    publication = AlkahestPublicationInput.model_validate(clause.mechanism_input)
    chains = resources.get("chains")
    chain = chains.get(publication.chain) if isinstance(chains, Mapping) else None
    if chain is None:
        raise ValueError(
            f"Alkahest publication references unknown chain {publication.chain!r}"
        )
    if publication.escrow_kind != "erc20_escrow_obligation_default":
        raise ValueError(
            f"unsupported Alkahest escrow kind {publication.escrow_kind!r}"
        )
    rpc_url = _resource_value(chain, "rpc_url")
    chain_id = _resource_value(chain, "chain_id")
    address_config_path = alkahest_address_book(config, publication.chain)
    # Registration and clause validation remain dependency-light. Load the
    # chain client and token resolver only when materializing a public option.
    from .alkahest import get_erc20_escrow_obligation_default
    from .token import TokenResolutionError, resolve_token

    try:
        token = resolve_token(
            clause.asset,
            rpc_url=rpc_url,
            chain_id=chain_id,
        )
    except TokenResolutionError as exc:
        raise ValueError(
            f"Alkahest asset {clause.asset!r} is unsupported on "
            f"chain {publication.chain!r}: {exc}"
        ) from exc
    rates: list[dict[str, Any]] = []
    if clause.rate is not None:
        try:
            base_units = decimal_rate_to_base_units(clause.rate, token.decimals)
        except ValueError as exc:
            raise ValueError(f"Alkahest rate {clause.rate!r}: {exc}") from exc
        rates.append(
            {
                "field": "amount",
                "per": clause.per,
                "value": str(base_units),
            }
        )
    escrow_address = get_erc20_escrow_obligation_default(
        publication.chain,
        config_path=address_config_path,
    )
    return {
        "chain_name": publication.chain,
        "escrow_address": escrow_address.lower(),
        "literal_fields": {"token": token.contract_address.lower()},
        "rates": rates,
    }


def alkahest_option_builder(
    section: BaseModel,
    readiness: MechanismReadiness,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> dict[str, list[Any]]:
    """Build canonical choices while preserving legacy escrow publication data."""

    del role
    config = AlkahestSettlementConfig.model_validate(section)
    if not config.enabled or not readiness.ready:
        raise ValueError("Alkahest settlement is not ready for publication")
    raw_clause = resources.get("publication_clause")
    if raw_clause is not None:
        clause = SettlementPublicationClause.model_validate(raw_clause)
        if clause.mechanism != ALKAHEST_MECHANISM_ID:
            raise ValueError("publication clause does not select Alkahest")
        escrow_wires = [_alkahest_escrow_from_clause(config, clause, resources)]
    else:
        accepted = resources.get("accepted_escrows")
        if not isinstance(accepted, (list, tuple)) or not accepted:
            raise ValueError("Alkahest publication requires accepted escrows")
        escrow_wires = [
            value.model_dump(mode="json")
            if hasattr(value, "model_dump")
            else dict(value)
            for value in accepted
        ]
    options: list[dict[str, Any]] = []
    for escrow in escrow_wires:
        literals = escrow.get("literal_fields")
        if not isinstance(literals, Mapping):
            literals = {}
        asset = (
            literals.get("token")
            or literals.get("asset")
            or escrow.get("asset")
            or "native"
        )
        rates: list[dict[str, Any]] = []
        for raw_rate in escrow.get("rates") or []:
            rate = (
                raw_rate.model_dump(mode="json")
                if hasattr(raw_rate, "model_dump")
                else dict(raw_rate)
            )
            if "value" in rate:
                rate["value"] = str(rate["value"])
            rates.append(rate)
        params = {"accepted_escrow": escrow}
        identity_payload = {
            "mechanism": ALKAHEST_MECHANISM_ID,
            "asset": str(asset),
            "rates": rates,
            "params": params,
        }
        encoded = json.dumps(
            identity_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        options.append(
            {
                "option_id": hashlib.sha256(encoded).hexdigest(),
                **identity_payload,
            }
        )
    return {"accepted_escrows": escrow_wires, "settlement_options": options}


def alkahest_buyer_compatibility(
    section: BaseModel,
    option: Any,
    public_context: Mapping[str, Any],
) -> bool:
    config = AlkahestSettlementConfig.model_validate(section)
    if not config.enabled or _value(option, "mechanism") != ALKAHEST_MECHANISM_ID:
        return False
    params = _value(option, "params", {})
    escrow = params.get("accepted_escrow", {}) if isinstance(params, Mapping) else {}
    chain_name = _value(escrow, "chain_name") or _value(escrow, "chain")
    allowed = public_context.get("chains")
    return (
        not isinstance(allowed, (set, frozenset, tuple, list)) or chain_name in allowed
    )


def _alkahest_escrow(option: Any) -> Mapping[str, Any] | None:
    params = _value(option, "params", {})
    if not isinstance(params, Mapping):
        return None
    escrow = params.get("accepted_escrow")
    return escrow if isinstance(escrow, Mapping) else None


def alkahest_chain_projection(option: Any) -> str | None:
    """Project only the chain identifier carried by the advertised escrow."""

    escrow = _alkahest_escrow(option)
    value = (
        _value(escrow, "chain_name") or _value(escrow, "chain")
        if escrow is not None
        else None
    )
    return value if isinstance(value, str) and value else None


def alkahest_escrow_kind_projection(option: Any) -> str | None:
    """Project only an explicitly advertised public escrow kind."""

    escrow = _alkahest_escrow(option)
    value = (
        _value(escrow, "escrow_kind") or _value(escrow, "kind")
        if escrow is not None
        else None
    )
    return value if isinstance(value, str) and value else None


def validate_alkahest_publication_input(
    section: BaseModel,
    value: BaseModel,
    role: SettlementRole,
) -> BaseModel:
    """Validate typed public clause input without chain access."""

    AlkahestSettlementConfig.model_validate(section)
    if role != "seller":
        raise ValueError("Alkahest publication input is seller-owned")
    return AlkahestPublicationInput.model_validate(value)


def create_alkahest_registration(
    *, command_group: Any | None = None
) -> MechanismRegistration:
    """Return the explicit common-contract registration for Alkahest."""

    return MechanismRegistration(
        mechanism_id=ALKAHEST_MECHANISM_ID,
        config_key=ALKAHEST_CONFIG_KEY,
        config_model=AlkahestSettlementConfig,
        roles=frozenset({"buyer", "seller"}),
        negotiates_scalar_amount=True,
        preflight=alkahest_preflight,
        client_factory=alkahest_client_factory,
        option_builder=alkahest_option_builder,
        # A deal's escrow is verified against the plan committed when it was
        # accepted, never the listing as it now stands.
        settlement_verifier=verify_escrow_against_plan,
        command_group=command_group,
        clause_fields=(
            SettlementClauseField(
                descriptor=FieldDescriptor(
                    name="alkahest.chain",
                    value_type=QueryValueType.STRING,
                    operators=_CLAUSE_OPERATORS,
                    description="advertised Alkahest chain",
                ),
                roles=frozenset({"buyer", "seller"}),
                projector=alkahest_chain_projection,
            ),
            SettlementClauseField(
                descriptor=FieldDescriptor(
                    name="alkahest.escrow_kind",
                    value_type=QueryValueType.STRING,
                    operators=_CLAUSE_OPERATORS,
                    description="advertised Alkahest escrow kind",
                ),
                roles=frozenset({"buyer", "seller"}),
                projector=alkahest_escrow_kind_projection,
            ),
        ),
        publication_input_model=AlkahestPublicationInput,
        publication_input_validator=validate_alkahest_publication_input,
        buyer_compatibility=alkahest_buyer_compatibility,
        public_detail_keys=frozenset(
            {"chain", "asset", "oracle_gated", "interruptible", "chain_probe"}
        ),
    )


__all__ = [
    "INTERRUPTIBLE_RELEASE",
    "ORACLE_GATED_RELEASE",
    "RECIPIENT_RELEASE",
    "RELEASE_MODELS",
    "ReleaseModelError",
    "configured_release_model",
    "ALKAHEST_CONFIG_KEY",
    "AlkahestPublicationInput",
    "alkahest_chain_projection",
    "alkahest_escrow_kind_projection",
    "validate_alkahest_publication_input",
    "ALKAHEST_MECHANISM_ID",
    "AlkahestSettlementConfig",
    "alkahest_address_book",
    "alkahest_buyer_compatibility",
    "alkahest_client_factory",
    "alkahest_option_builder",
    "alkahest_preflight",
    "create_alkahest_registration",
    "wallet_account_address",
]
