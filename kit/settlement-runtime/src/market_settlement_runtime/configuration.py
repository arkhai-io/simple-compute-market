"""Typed, mechanism-neutral settlement configuration and registration."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from collections.abc import Mapping as MappingABC
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import (
    Any,
    Literal,
    get_args,
    get_origin,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretBytes,
    SecretStr,
    field_validator,
    model_validator,
)

from market_core.query_dsl import FieldDescriptor, field_reference_json
from market_core.schemas import SettlementOption
from .ports import ConditionalEscrowClient

SETTLEMENT_CONFIG_SCHEMA_VERSION = 1
SettlementRole = Literal["buyer", "seller"]


class SettlementConfigurationError(ValueError):
    """A settlement configuration or registration violates the common contract."""


class ReadinessBlocker(BaseModel):
    """A stable, public reason that a mechanism is not ready."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=512)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            raise ValueError("blocker code must be a stable identifier")
        return value

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        if any(character in value for character in ("\n", "\r", "\x00")):
            raise ValueError("blocker message must be a single public line")
        return value


class MechanismReadiness(BaseModel):
    """Sanitized observational readiness returned by a mechanism registration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mechanism: str = Field(min_length=1)
    configured: bool
    enabled: bool
    ready: bool
    blockers: tuple[ReadinessBlocker, ...] = ()
    capabilities: tuple[str, ...] = ()
    contract_version: str | None = None
    schema_version: str | None = None
    public_details: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("capabilities")
    @classmethod
    def _validate_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("capabilities must not contain duplicates")
        return value

    @field_validator("public_details")
    @classmethod
    def _validate_public_details(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not _is_public_value(dict(value)):
            raise ValueError("public_details must contain only JSON public values")
        return dict(value)

    @model_validator(mode="after")
    def _validate_state(self) -> MechanismReadiness:
        if self.enabled and not self.configured:
            raise ValueError("an unconfigured mechanism cannot be enabled")
        if self.ready and (not self.configured or not self.enabled):
            raise ValueError("a ready mechanism must be configured and enabled")
        if self.ready and self.blockers:
            raise ValueError("a ready mechanism cannot have blockers")
        return self

    def safe_projection(self) -> dict[str, Any]:
        """Return the complete public status representation."""
        return self.model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class SettlementConfig:
    """One resolved settlement root with typed installed mechanism sections."""

    schema_version: int = SETTLEMENT_CONFIG_SCHEMA_VERSION
    priority: tuple[str, ...] = ()
    mechanisms: Mapping[str, BaseModel] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "priority", tuple(self.priority))
        object.__setattr__(self, "mechanisms", MappingProxyType(dict(self.mechanisms)))

    def mechanism_config(self, config_key: str) -> BaseModel | None:
        return self.mechanisms.get(config_key)

    @property
    def configured_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.mechanisms))


def _section_enabled(section: BaseModel) -> bool:
    return bool(getattr(section, "enabled"))


PreflightCallback = Callable[
    [BaseModel, Mapping[str, Any], SettlementRole],
    MechanismReadiness | Awaitable[MechanismReadiness],
]
ClientFactory = Callable[
    [BaseModel, Mapping[str, Any], SettlementRole], ConditionalEscrowClient
]
OptionBuilder = Callable[
    [BaseModel, MechanismReadiness, Mapping[str, Any], SettlementRole], Any
]
BuyerCompatibilityHook = Callable[[BaseModel, Any, Mapping[str, Any]], bool]
SettlementClauseProjector = Callable[[SettlementOption], Any | None]
PublicationInputValidator = Callable[[BaseModel, BaseModel, SettlementRole], BaseModel]


@dataclass(frozen=True, slots=True)
class SettlementClauseField:
    """One role-scoped public option projection owned by a mechanism."""

    descriptor: FieldDescriptor
    roles: frozenset[SettlementRole]
    projector: SettlementClauseProjector = field(repr=False)

    def __post_init__(self) -> None:
        if not self.roles or not self.roles <= {"buyer", "seller"}:
            raise SettlementConfigurationError(
                f"settlement clause field {self.descriptor.name!r} has invalid roles"
            )


@dataclass(frozen=True, slots=True)
class RegisteredSettlementClauseField:
    """A validated field bound to its owning canonical mechanism."""

    mechanism_id: str
    config_key: str
    field: SettlementClauseField


@dataclass(frozen=True, slots=True)
class MechanismRegistration:
    """All common hooks supplied by an explicitly installed mechanism."""

    mechanism_id: str
    config_key: str
    config_model: type[BaseModel]
    roles: frozenset[SettlementRole]
    preflight: PreflightCallback
    client_factory: ClientFactory
    option_builder: OptionBuilder
    buyer_compatibility: BuyerCompatibilityHook
    clause_fields: tuple[SettlementClauseField, ...]
    publication_input_model: type[BaseModel]
    publication_input_validator: PublicationInputValidator
    command_group: Any | None = None
    public_detail_keys: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9.-]*\.v[1-9][0-9]*", self.mechanism_id):
            raise SettlementConfigurationError(
                f"invalid canonical settlement mechanism ID {self.mechanism_id!r}"
            )
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.config_key):
            raise SettlementConfigurationError(
                f"invalid settlement configuration key {self.config_key!r}"
            )
        if not self.roles or not self.roles <= {"buyer", "seller"}:
            raise SettlementConfigurationError(
                f"registration {self.mechanism_id!r} has invalid roles"
            )
        if not isinstance(self.config_model, type) or not issubclass(
            self.config_model, BaseModel
        ):
            raise SettlementConfigurationError("config_model must be a Pydantic model")
        enabled = self.config_model.model_fields.get("enabled")
        if (
            enabled is None
            or enabled.annotation is not bool
            or enabled.default is not False
        ):
            raise SettlementConfigurationError(
                f"{self.mechanism_id!r} config must declare enabled: bool = False"
            )
        if not isinstance(self.publication_input_model, type) or not issubclass(
            self.publication_input_model, BaseModel
        ):
            raise SettlementConfigurationError(
                "publication_input_model must be a Pydantic model"
            )
        if self.publication_input_model.model_config.get("extra") != "forbid":
            raise SettlementConfigurationError(
                f"{self.mechanism_id!r} publication input must forbid extra fields"
            )
        sensitive_inputs = sorted(
            name
            for name in self.publication_input_model.model_fields
            if _looks_sensitive_key(name)
        )
        if sensitive_inputs:
            raise SettlementConfigurationError(
                "publication input fields are sensitive: " + ", ".join(sensitive_inputs)
            )
        expected_prefix = f"{self.config_key}."
        for clause_field in self.clause_fields:
            if not clause_field.roles <= self.roles:
                raise SettlementConfigurationError(
                    f"settlement clause field {clause_field.descriptor.name!r} "
                    "declares a role not owned by its registration"
                )
            names = (
                clause_field.descriptor.name,
                *clause_field.descriptor.aliases,
            )
            unqualified = sorted(
                name for name in names if not name.startswith(expected_prefix)
            )
            if unqualified:
                raise SettlementConfigurationError(
                    f"settlement clause fields for {self.mechanism_id!r} must use "
                    f"the {expected_prefix!r} namespace: {', '.join(unqualified)}"
                )
            sensitive = sorted(name for name in names if _looks_sensitive_key(name))
            if sensitive:
                raise SettlementConfigurationError(
                    "settlement clause fields are sensitive: " + ", ".join(sensitive)
                )
        try:
            field_reference_json(
                clause_field.descriptor for clause_field in self.clause_fields
            )
        except ValueError as exc:
            raise SettlementConfigurationError(
                f"invalid settlement clause fields for {self.mechanism_id!r}: {exc}"
            ) from exc
        forbidden_details = sorted(
            key for key in self.public_detail_keys if _looks_sensitive_key(key)
        )
        if forbidden_details:
            raise SettlementConfigurationError(
                f"public detail keys are sensitive: {', '.join(forbidden_details)}"
            )


class SettlementConfigurationRegistry:
    """Deterministic configuration facade over the runtime's mechanism clients.

    This object has no obligation state, journal, retry policy, or lifecycle. It
    produces the client mapping consumed by the existing ``SettlementRuntime``.
    """

    def __init__(self, registrations: Iterable[MechanismRegistration] = ()) -> None:
        self._registrations: dict[str, MechanismRegistration] = {}
        self._config_keys: dict[str, str] = {}
        self._clause_names: dict[str, str] = {}
        for registration in registrations:
            self.register(registration)

    def register(self, registration: MechanismRegistration) -> None:
        if registration.mechanism_id in self._registrations:
            raise SettlementConfigurationError(
                f"duplicate settlement registration {registration.mechanism_id!r}"
            )
        existing = self._config_keys.get(registration.config_key)
        if existing is not None:
            raise SettlementConfigurationError(
                f"duplicate settlement config key {registration.config_key!r} "
                f"for {existing!r} and {registration.mechanism_id!r}"
            )
        for clause_field in registration.clause_fields:
            for name in (
                clause_field.descriptor.name,
                *clause_field.descriptor.aliases,
            ):
                owner = self._clause_names.get(name)
                if owner is not None:
                    raise SettlementConfigurationError(
                        f"duplicate settlement clause field {name!r} "
                        f"for {owner!r} and {registration.mechanism_id!r}"
                    )
        for clause_field in registration.clause_fields:
            for name in (
                clause_field.descriptor.name,
                *clause_field.descriptor.aliases,
            ):
                self._clause_names[name] = registration.mechanism_id
        self._registrations[registration.mechanism_id] = registration
        self._config_keys[registration.config_key] = registration.mechanism_id

    @property
    def registrations(self) -> tuple[MechanismRegistration, ...]:
        return tuple(self._registrations[key] for key in sorted(self._registrations))

    def registration(self, mechanism_id: str) -> MechanismRegistration:
        try:
            return self._registrations[mechanism_id]
        except KeyError as exc:
            raise SettlementConfigurationError(
                f"uninstalled settlement mechanism {mechanism_id!r}"
            ) from exc

    def canonical_mechanism_id(
        self,
        value: str,
        *,
        role: SettlementRole,
    ) -> str:
        """Resolve a configuration key or canonical ID for one role."""

        mechanism_id = self._config_keys.get(value, value)
        registration = self.registration(mechanism_id)
        if role not in registration.roles:
            raise SettlementConfigurationError(
                f"settlement mechanism {mechanism_id!r} does not apply to role {role!r}"
            )
        return mechanism_id

    def clause_fields(
        self,
        *,
        role: SettlementRole,
    ) -> tuple[RegisteredSettlementClauseField, ...]:
        """Return validated public projections in deterministic field order."""

        fields = (
            RegisteredSettlementClauseField(
                mechanism_id=registration.mechanism_id,
                config_key=registration.config_key,
                field=clause_field,
            )
            for registration in self.registrations
            for clause_field in registration.clause_fields
            if role in registration.roles and role in clause_field.roles
        )
        return tuple(sorted(fields, key=lambda item: item.field.descriptor.name))

    def validate_publication_input(
        self,
        mechanism_id: str,
        raw: Mapping[str, Any] | BaseModel,
        config: SettlementConfig,
        *,
        role: SettlementRole,
    ) -> BaseModel:
        """Strictly parse and mechanism-validate one public publication input."""

        registration = self.registration(mechanism_id)
        if role not in registration.roles:
            raise SettlementConfigurationError(
                f"settlement mechanism {mechanism_id!r} does not apply to role {role!r}"
            )
        section = config.mechanisms.get(registration.config_key)
        if section is None:
            raise SettlementConfigurationError(
                f"settlement mechanism {mechanism_id!r} has no configured section"
            )
        try:
            parsed = (
                raw
                if isinstance(raw, registration.publication_input_model)
                else registration.publication_input_model.model_validate(raw)
            )
            validated = registration.publication_input_validator(
                section,
                parsed,
                role,
            )
        except ValueError as exc:
            raise SettlementConfigurationError(
                f"invalid publication input for {mechanism_id!r}"
            ) from exc
        if not isinstance(validated, registration.publication_input_model):
            raise SettlementConfigurationError(
                f"publication validator for {mechanism_id!r} returned invalid type"
            )
        return validated

    def resolve(
        self,
        raw: Mapping[str, Any] | SettlementConfig,
        *,
        role: SettlementRole,
    ) -> SettlementConfig:
        """Strictly parse a direct raw ``[Settlement]`` table for one role."""
        if isinstance(raw, SettlementConfig):
            return self.validate(raw, role=role)
        if role not in ("buyer", "seller"):
            raise SettlementConfigurationError(f"unknown settlement role {role!r}")
        known_root = {"schema_version", "priority", *self._config_keys}
        unknown_root = sorted(str(key) for key in raw if key not in known_root)
        if unknown_root:
            raise SettlementConfigurationError(
                f"unknown Settlement keys: {', '.join(unknown_root)}"
            )
        schema_version = raw.get("schema_version", SETTLEMENT_CONFIG_SCHEMA_VERSION)
        if (
            type(schema_version) is not int
            or schema_version != SETTLEMENT_CONFIG_SCHEMA_VERSION
        ):
            raise SettlementConfigurationError(
                f"unsupported settlement schema_version {schema_version!r}; "
                f"expected {SETTLEMENT_CONFIG_SCHEMA_VERSION}"
            )
        priority_value = raw.get("priority", ())
        if not isinstance(priority_value, (list, tuple)):
            raise SettlementConfigurationError("Settlement.priority must be a list")
        priority = tuple(priority_value)
        if any(not isinstance(item, str) or not item for item in priority):
            raise SettlementConfigurationError(
                "Settlement.priority entries must be non-empty canonical IDs"
            )
        typed: dict[str, BaseModel] = {}
        for config_key in sorted(self._config_keys):
            if config_key not in raw:
                continue
            registration = self._registrations[self._config_keys[config_key]]
            if role not in registration.roles:
                raise SettlementConfigurationError(
                    f"Settlement.{config_key} does not apply to role {role!r}"
                )
            section = raw[config_key]
            if not isinstance(section, Mapping):
                raise SettlementConfigurationError(
                    f"Settlement.{config_key} must be a table"
                )
            _reject_unknown_model_keys(
                registration.config_model,
                section,
                path=f"Settlement.{config_key}",
                role=role,
            )
            try:
                typed[config_key] = registration.config_model.model_validate(section)
            except ValueError as exc:
                raise SettlementConfigurationError(
                    f"invalid Settlement.{config_key}"
                ) from exc
        return self.validate(
            SettlementConfig(
                schema_version=schema_version,
                priority=priority,
                mechanisms=typed,
            ),
            role=role,
        )

    def validate(
        self,
        config: SettlementConfig,
        *,
        role: SettlementRole,
    ) -> SettlementConfig:
        """Validate canonical priority against installed, typed registrations."""
        if config.schema_version != SETTLEMENT_CONFIG_SCHEMA_VERSION:
            raise SettlementConfigurationError(
                f"unsupported settlement schema_version {config.schema_version!r}"
            )
        duplicates = _duplicates(config.priority)
        if duplicates:
            raise SettlementConfigurationError(
                f"duplicate Settlement.priority mechanisms: {', '.join(duplicates)}"
            )
        enabled: set[str] = set()
        for config_key, section in sorted(config.mechanisms.items()):
            mechanism_id = self._config_keys.get(config_key)
            if mechanism_id is None:
                raise SettlementConfigurationError(
                    f"uninstalled settlement configuration section {config_key!r}"
                )
            registration = self._registrations[mechanism_id]
            if role not in registration.roles:
                raise SettlementConfigurationError(
                    f"settlement mechanism {mechanism_id!r} does not apply to role {role!r}"
                )
            if not isinstance(section, registration.config_model):
                raise SettlementConfigurationError(
                    f"Settlement.{config_key} must use {registration.config_model.__name__}"
                )
            if _section_enabled(section):
                enabled.add(mechanism_id)
        for mechanism_id in config.priority:
            registration = self.registration(mechanism_id)
            if role not in registration.roles:
                raise SettlementConfigurationError(
                    f"settlement mechanism {mechanism_id!r} does not apply to role {role!r}"
                )
            priority_section = config.mechanisms.get(registration.config_key)
            if priority_section is None:
                raise SettlementConfigurationError(
                    f"priority mechanism {mechanism_id!r} has no configured section"
                )
            if not _section_enabled(priority_section):
                raise SettlementConfigurationError(
                    f"priority mechanism {mechanism_id!r} is disabled"
                )
        omitted = sorted(enabled - set(config.priority))
        if omitted:
            raise SettlementConfigurationError(
                f"enabled mechanisms missing from Settlement.priority: {', '.join(omitted)}"
            )
        return config

    def ordered_registrations(
        self,
        config: SettlementConfig,
        *,
        role: SettlementRole,
    ) -> tuple[MechanismRegistration, ...]:
        """Return priority registrations, then remaining applicable ones by ID."""
        self.validate(config, role=role)
        remainder = sorted(
            mechanism_id
            for mechanism_id, registration in self._registrations.items()
            if role in registration.roles and mechanism_id not in config.priority
        )
        return tuple(
            self._registrations[item] for item in (*config.priority, *remainder)
        )

    async def ordered_readiness(
        self,
        config: SettlementConfig,
        *,
        role: SettlementRole,
        resources: Mapping[str, Any] | None = None,
    ) -> tuple[MechanismReadiness, ...]:
        """Run only observational preflight hooks in deterministic order."""
        shared_resources = resources or {}
        results: list[MechanismReadiness] = []
        for registration in self.ordered_registrations(config, role=role):
            section = config.mechanisms.get(registration.config_key)
            if section is None:
                results.append(
                    MechanismReadiness(
                        mechanism=registration.mechanism_id,
                        configured=False,
                        enabled=False,
                        ready=False,
                        blockers=(
                            ReadinessBlocker(
                                code="not_configured",
                                message="mechanism is not configured",
                            ),
                        ),
                    )
                )
                continue
            if not _section_enabled(section):
                results.append(
                    MechanismReadiness(
                        mechanism=registration.mechanism_id,
                        configured=True,
                        enabled=False,
                        ready=False,
                        blockers=(
                            ReadinessBlocker(
                                code="disabled", message="mechanism is disabled"
                            ),
                        ),
                    )
                )
                continue
            pending = registration.preflight(section, shared_resources, role)
            readiness = await pending if inspect.isawaitable(pending) else pending
            if not isinstance(readiness, MechanismReadiness):
                raise SettlementConfigurationError(
                    f"preflight for {registration.mechanism_id!r} returned invalid status"
                )
            self._validate_readiness(registration, section, readiness)
            results.append(readiness)
        return tuple(results)

    def create_client(
        self,
        mechanism_id: str,
        config: SettlementConfig,
        *,
        role: SettlementRole,
        resources: Mapping[str, Any] | None = None,
    ) -> ConditionalEscrowClient:
        """Dispatch one installed client factory without checking enabled/readiness."""
        registration = self.registration(mechanism_id)
        if role not in registration.roles:
            raise SettlementConfigurationError(
                f"settlement mechanism {mechanism_id!r} does not apply to role {role!r}"
            )
        section = config.mechanisms.get(registration.config_key)
        if section is None:
            raise SettlementConfigurationError(
                f"settlement mechanism {mechanism_id!r} has no configured section"
            )
        return registration.client_factory(section, resources or {}, role)

    def runtime_clients(
        self,
        config: SettlementConfig,
        *,
        role: SettlementRole,
        resources: Mapping[str, Any] | None = None,
    ) -> dict[str, ConditionalEscrowClient]:
        """Build the existing runtime client map, including disabled sections."""
        self.validate(config, role=role)
        return {
            registration.mechanism_id: self.create_client(
                registration.mechanism_id, config, role=role, resources=resources
            )
            for registration in self.ordered_registrations(config, role=role)
            if registration.config_key in config.mechanisms
        }

    def build_option(
        self,
        readiness: MechanismReadiness,
        config: SettlementConfig,
        *,
        role: SettlementRole,
        resources: Mapping[str, Any] | None = None,
    ) -> Any:
        """Dispatch an option builder only for a ready mechanism."""
        if not readiness.ready:
            raise SettlementConfigurationError(
                f"settlement mechanism {readiness.mechanism!r} is not ready"
            )
        registration = self.registration(readiness.mechanism)
        if role not in registration.roles:
            raise SettlementConfigurationError(
                f"settlement mechanism {readiness.mechanism!r} does not apply to role {role!r}"
            )
        section = config.mechanisms.get(registration.config_key)
        if section is None:
            raise SettlementConfigurationError(
                f"settlement mechanism {readiness.mechanism!r} has no configured section"
            )
        return registration.option_builder(section, readiness, resources or {}, role)

    def buyer_compatible(
        self,
        mechanism_id: str,
        option: Any,
        config: SettlementConfig,
        *,
        public_context: Mapping[str, Any] | None = None,
    ) -> bool:
        """Dispatch a resource-free mechanism-owned buyer compatibility hook."""
        registration = self.registration(mechanism_id)
        if "buyer" not in registration.roles:
            return False
        section = config.mechanisms.get(registration.config_key)
        if section is None or not _section_enabled(section):
            return False
        return registration.buyer_compatibility(section, option, public_context or {})

    def public_projection(
        self,
        config: SettlementConfig,
        *,
        role: SettlementRole,
    ) -> dict[str, Any]:
        """Return a source-free, secret-free resolved mechanism projection."""
        mechanisms: list[dict[str, Any]] = []
        for registration in self.ordered_registrations(config, role=role):
            section = config.mechanisms.get(registration.config_key)
            descriptors = [
                item.field.descriptor
                for item in self.clause_fields(role=role)
                if item.mechanism_id == registration.mechanism_id
            ]
            mechanisms.append(
                {
                    "mechanism": registration.mechanism_id,
                    "config_key": registration.config_key,
                    "configured": section is not None,
                    "enabled": bool(section is not None and _section_enabled(section)),
                    "clause_fields": field_reference_json(descriptors),
                    "publication_input_schema": (
                        registration.publication_input_model.model_json_schema()
                    ),
                }
            )
        return {
            "schema_version": config.schema_version,
            "priority": list(config.priority),
            "mechanisms": mechanisms,
        }

    def public_fingerprint(
        self,
        config: SettlementConfig,
        *,
        role: SettlementRole,
    ) -> str:
        """Hash only the source-free public projection with canonical JSON."""
        payload = json.dumps(
            self.public_projection(config, role=role),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"

    def _validate_readiness(
        self,
        registration: MechanismRegistration,
        section: BaseModel,
        readiness: MechanismReadiness,
    ) -> None:
        if readiness.mechanism != registration.mechanism_id:
            raise SettlementConfigurationError(
                f"preflight for {registration.mechanism_id!r} returned status for {readiness.mechanism!r}"
            )
        if not readiness.configured or not readiness.enabled:
            raise SettlementConfigurationError(
                f"enabled preflight for {registration.mechanism_id!r} returned inconsistent state"
            )
        unknown_details = sorted(
            set(readiness.public_details) - registration.public_detail_keys
        )
        if unknown_details:
            raise SettlementConfigurationError(
                f"preflight for {registration.mechanism_id!r} returned non-allowlisted public details: "
                f"{', '.join(unknown_details)}"
            )
        secret_values = _secret_values(section)
        public_payload = json.dumps(
            readiness.safe_projection(), sort_keys=True, ensure_ascii=True
        )
        if any(value and value in public_payload for value in secret_values):
            raise SettlementConfigurationError(
                f"preflight for {registration.mechanism_id!r} exposed a secret value"
            )


def _duplicates(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _field_aliases(name: str, field_info: Any) -> set[str]:
    aliases = {name}
    alias = getattr(field_info, "alias", None)
    if isinstance(alias, str):
        aliases.add(alias)
    return aliases


def _field_roles(field_info: Any) -> frozenset[str]:
    extra = field_info.json_schema_extra
    if isinstance(extra, Mapping):
        roles = extra.get("roles")
        if isinstance(roles, (list, tuple, set, frozenset)):
            return frozenset(str(role) for role in roles)
    return frozenset({"buyer", "seller"})


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for argument in get_args(annotation):
        nested = _nested_model(argument)
        if nested is not None:
            return nested
    return None


def _reject_unknown_model_keys(
    model: type[BaseModel],
    values: Mapping[str, Any],
    *,
    path: str,
    role: SettlementRole,
) -> None:
    aliases: dict[str, tuple[str, Any]] = {}
    for name, field_info in model.model_fields.items():
        for alias in _field_aliases(name, field_info):
            aliases[alias] = (name, field_info)
    unknown = sorted(str(key) for key in values if key not in aliases)
    if unknown:
        raise SettlementConfigurationError(f"unknown {path} keys: {', '.join(unknown)}")
    for key, value in values.items():
        name, field_info = aliases[key]
        if role not in _field_roles(field_info):
            raise SettlementConfigurationError(
                f"{path}.{name} does not apply to role {role!r}"
            )
        nested = _nested_model(field_info.annotation)
        container = _model_container(field_info.annotation)
        if nested is not None and container == "mapping" and isinstance(value, Mapping):
            for dynamic_key, item in value.items():
                if isinstance(item, Mapping):
                    _reject_unknown_model_keys(
                        nested,
                        item,
                        path=f"{path}.{name}.{dynamic_key}",
                        role=role,
                    )
        elif (
            nested is not None
            and container == "sequence"
            and isinstance(value, (list, tuple))
        ):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    _reject_unknown_model_keys(
                        nested, item, path=f"{path}.{name}[{index}]", role=role
                    )
        elif nested is not None and isinstance(value, Mapping):
            _reject_unknown_model_keys(nested, value, path=f"{path}.{name}", role=role)


def _model_container(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin in (dict, MappingABC):
        return "mapping"
    if origin in (list, tuple, Sequence, SequenceABC):
        return "sequence"
    for argument in get_args(annotation):
        nested = _model_container(argument)
        if nested != "direct":
            return nested
    return "direct"


def _field_is_secret(field_info: Any) -> bool:
    extra = field_info.json_schema_extra
    if isinstance(extra, Mapping) and extra.get("secret") is True:
        return True
    annotation = field_info.annotation
    if annotation in (SecretStr, SecretBytes):
        return True
    return any(
        argument in (SecretStr, SecretBytes) for argument in get_args(annotation)
    )


def _secret_values(model: BaseModel) -> set[str]:
    values: set[str] = set()
    for name, field_info in type(model).model_fields.items():
        value = getattr(model, name)
        if _field_is_secret(field_info):
            revealed = (
                value.get_secret_value()
                if isinstance(value, (SecretStr, SecretBytes))
                else value
            )
            if isinstance(revealed, bytes):
                values.add(revealed.decode("utf-8", errors="ignore"))
            elif revealed is not None:
                values.add(str(revealed))
        elif isinstance(value, BaseModel):
            values.update(_secret_values(value))
        elif isinstance(value, Mapping):
            for item in value.values():
                if isinstance(item, BaseModel):
                    values.update(_secret_values(item))
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, BaseModel):
                    values.update(_secret_values(item))
    return values


def _looks_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(
        token in normalized
        for token in (
            "secret",
            "password",
            "private_key",
            "credential",
            "access_token",
            "api_key",
            "webhook",
            "provider",
            "admin",
            "database",
        )
    )


def _is_public_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_public_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str)
            and not _looks_sensitive_key(key)
            and _is_public_value(item)
            for key, item in value.items()
        )
    return False
