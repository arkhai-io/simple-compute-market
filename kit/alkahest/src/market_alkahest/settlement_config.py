"""Typed configuration and registration for the Alkahest settlement mechanism."""

from __future__ import annotations

import hashlib
import inspect
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
    SettlementRole,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .claim_hooks import AlkahestConditionalEscrowClient

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
    oracle_gated: bool = False
    trusted_oracle_addresses: tuple[str, ...] = ()
    interruptible: bool = False
    interruptible_oracle_addresses: tuple[str, ...] = ()

    @field_validator("address_config_path")
    @classmethod
    def validate_address_config_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("address_config_path must be non-empty and trimmed")
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


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _blocker(code: str, message: str) -> ReadinessBlocker:
    return ReadinessBlocker(code=code, message=message)


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _selected_chain_names(resources: Mapping[str, Any]) -> tuple[str, ...]:
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
    selected = resources.get("chain_name") or resources.get("default_chain")
    if selected is None and len(chains) == 1:
        selected = next(iter(chains))
    if not isinstance(selected, str) or selected not in chains:
        return ()
    return (selected,)


def _validate_address_file(path: str) -> bool:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict)


async def alkahest_preflight(
    section: BaseModel,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> MechanismReadiness:
    """Observe Alkahest prerequisites without submitting a transaction."""

    del role
    config = AlkahestSettlementConfig.model_validate(section)
    if not config.enabled:
        return MechanismReadiness(
            mechanism=ALKAHEST_MECHANISM_ID,
            configured=True,
            enabled=False,
            ready=False,
            capabilities=("conditional-escrow.v1", "evm.v1"),
            contract_version="alkahest.v1",
            schema_version="1",
            public_details={},
        )

    blockers: list[ReadinessBlocker] = []
    wallet = resources.get("wallet")
    has_composed_client = bool(resources.get("get_client") or resources.get("clients"))
    if wallet is None and not resources.get("wallet_ready") and not has_composed_client:
        blockers.append(
            _blocker(
                "alkahest.wallet_missing", "an injected settlement wallet is required"
            )
        )
    elif wallet is not None and not (_value(wallet, "address") or has_composed_client):
        blockers.append(
            _blocker(
                "alkahest.wallet_address_missing",
                "the settlement wallet has no address",
            )
        )

    chains = resources.get("chains")
    chain_names = _selected_chain_names(resources)
    if not chain_names or not isinstance(chains, Mapping):
        blockers.append(
            _blocker(
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
                    _blocker(
                        "alkahest.rpc_missing",
                        "a selected settlement chain has no RPC client",
                    )
                )
            configured_chain_id = _value(chain, "chain_id")
            observed = resources.get("observed_chain_id")
            if isinstance(observed, Mapping):
                observed = observed.get(chain_name)
            if configured_chain_id is not None and observed is not None:
                if int(configured_chain_id) != int(observed):
                    blockers.append(
                        _blocker(
                            "alkahest.chain_id_mismatch",
                            "a selected RPC reports a different chain identity",
                        )
                    )

    if config.address_config_path and not _validate_address_file(
        config.address_config_path
    ):
        blockers.append(
            _blocker(
                "alkahest.address_config_invalid",
                "the Alkahest address configuration cannot be loaded",
            )
        )

    deployed = resources.get("deployed_contracts")
    if isinstance(deployed, Mapping) and any(
        value is not True for value in deployed.values()
    ):
        blockers.append(
            _blocker(
                "alkahest.contract_missing",
                "one or more required Alkahest contracts are not deployed",
            )
        )
    probe = resources.get("contract_probe")
    required_addresses = resources.get("required_addresses")
    if (
        callable(probe)
        and isinstance(required_addresses, Mapping)
        and required_addresses
    ):
        for chain_name in chain_names:
            try:
                result = await _await_if_needed(
                    probe(chain_name, dict(required_addresses))
                )
            except Exception:
                result = None
            if not isinstance(result, Mapping) or any(
                value is not True for value in result.values()
            ):
                blockers.append(
                    _blocker(
                        "alkahest.contract_probe_failed",
                        "required Alkahest deployments could not be verified",
                    )
                )
                break

    if resources.get("require_asset") and not resources.get("asset"):
        blockers.append(
            _blocker("alkahest.asset_missing", "a settlement asset must be selected")
        )
    if config.oracle_gated and not config.trusted_oracle_addresses:
        blockers.append(
            _blocker(
                "alkahest.oracle_policy_invalid",
                "oracle-gated settlement requires a trusted oracle address",
            )
        )
    if config.interruptible and not config.interruptible_oracle_addresses:
        blockers.append(
            _blocker(
                "alkahest.interruptible_policy_invalid",
                "interruptible settlement requires an oracle address",
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
    chain_config_paths: dict[str, str | None] = {}
    if isinstance(chains, Mapping):
        chain_config_paths = dict.fromkeys(chains, config.address_config_path)
    return AlkahestConditionalEscrowClient(
        get_client=get_client,
        chain_config_paths=chain_config_paths,
        default_chain=resources.get("chain_name") or resources.get("default_chain"),
        arbitration_probe_timeout=float(
            resources.get("arbitration_probe_timeout", 5.0)
        ),
    )


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
    accepted = resources.get("accepted_escrows")
    if not isinstance(accepted, (list, tuple)) or not accepted:
        raise ValueError("Alkahest publication requires accepted escrows")
    escrow_wires = [
        value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)
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


def create_alkahest_registration() -> MechanismRegistration:
    """Return the explicit common-contract registration for Alkahest."""

    return MechanismRegistration(
        mechanism_id=ALKAHEST_MECHANISM_ID,
        config_key=ALKAHEST_CONFIG_KEY,
        config_model=AlkahestSettlementConfig,
        roles=frozenset({"buyer", "seller"}),
        preflight=alkahest_preflight,
        client_factory=alkahest_client_factory,
        option_builder=alkahest_option_builder,
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
            {"chain", "asset", "oracle_gated", "interruptible"}
        ),
    )


__all__ = [
    "ALKAHEST_CONFIG_KEY",
    "AlkahestPublicationInput",
    "alkahest_chain_projection",
    "alkahest_escrow_kind_projection",
    "validate_alkahest_publication_input",
    "ALKAHEST_MECHANISM_ID",
    "AlkahestSettlementConfig",
    "alkahest_buyer_compatibility",
    "alkahest_client_factory",
    "alkahest_option_builder",
    "alkahest_preflight",
    "create_alkahest_registration",
]
