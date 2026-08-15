"""Immutable storefront-domain registrations and record bindings.

The registry is constructed once by a composition root.  Request and recovery
paths resolve contracts only from persisted :class:`StorefrontDomainBinding`
values; public payload fields are assertions, never selectors.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from market_core import (
    ContractVersion,
    DomainCapability,
    DomainContractValidationError,
    DomainIdentity,
    MarketDomainContract,
    validate_domain_contracts,
)


REQUIRED_STOREFRONT_CAPABILITIES = frozenset(
    {
        DomainCapability.STOREFRONT,
        DomainCapability.PUBLICATION,
        DomainCapability.SETTLEMENT,
        DomainCapability.FULFILLMENT,
    }
)


class StorefrontDomainRegistryError(ValueError):
    """Configured storefront registrations are incomplete or ambiguous."""


class StorefrontDomainBindingError(LookupError):
    """A durable record does not resolve to its exact configured contract."""


def _nonempty(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise StorefrontDomainRegistryError(f"{field} must be a non-empty trimmed string")
    return value


@dataclass(frozen=True, order=True)
class DomainContractKey:
    """Stable domain identity plus the core contract API version."""

    domain_identity: DomainIdentity
    contract_version: ContractVersion

    def __post_init__(self) -> None:
        if not isinstance(self.domain_identity, DomainIdentity):
            raise StorefrontDomainRegistryError(
                "domain_identity must be a canonical DomainIdentity"
            )
        if not isinstance(self.contract_version, ContractVersion):
            raise StorefrontDomainRegistryError(
                "contract_version must be a ContractVersion"
            )


@dataclass(frozen=True, order=True)
class StorefrontDomainBinding:
    """Serializable, secret-free domain ownership copied across lifecycle rows."""

    offering_mode: str
    domain_identity: DomainIdentity
    contract_major: int
    contract_minor: int

    def __post_init__(self) -> None:
        _nonempty(self.offering_mode, field="offering_mode")
        if not isinstance(self.domain_identity, DomainIdentity):
            object.__setattr__(
                self,
                "domain_identity",
                DomainIdentity(str(self.domain_identity)),
            )
        ContractVersion(self.contract_major, self.contract_minor)

    @property
    def contract_version(self) -> ContractVersion:
        return ContractVersion(self.contract_major, self.contract_minor)

    @property
    def contract_key(self) -> DomainContractKey:
        return DomainContractKey(self.domain_identity, self.contract_version)

    def as_record(self) -> dict[str, str | int]:
        return {
            "offering_mode": self.offering_mode,
            "domain_identity": str(self.domain_identity),
            "contract_major": self.contract_major,
            "contract_minor": self.contract_minor,
        }

_FORBIDDEN_SOURCE_KEY_PARTS = (
    "credential",
    "header",
    "private",
    "provider",
    "secret",
    "ssh",
    "token",
    "url",
)


def _validate_source_value(value: object, *, path: str) -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_source_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise StorefrontDomainRegistryError(
                    f"{path} keys must be non-empty strings"
                )
            normalized = key.lower()
            if any(part in normalized for part in _FORBIDDEN_SOURCE_KEY_PARTS):
                raise StorefrontDomainRegistryError(
                    f"{path}.{key} is not allowed in a public-safe source envelope"
                )
            _validate_source_value(item, path=f"{path}.{key}")
        return
    raise StorefrontDomainRegistryError(
        f"{path} contains unsupported {type(value).__name__}"
    )


def canonical_source_envelope(value: Mapping[str, object]) -> str:
    """Validate and canonicalize a public-safe versioned source envelope."""

    if not isinstance(value, Mapping):
        raise StorefrontDomainRegistryError("source envelope must be a mapping")
    normalized = dict(value)
    kind = normalized.get("kind")
    schema_version = normalized.get("schema_version")
    if not isinstance(kind, str) or not kind.strip():
        raise StorefrontDomainRegistryError(
            "source envelope kind must be a non-empty string"
        )
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    ):
        raise StorefrontDomainRegistryError(
            "source envelope schema_version must be an integer >= 1"
        )
    _validate_source_value(normalized, path="source_envelope")
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def build_storefront_derivation_key(
    *,
    site_id: str,
    offering_mode: str,
    binding: StorefrontDomainBinding,
    source_identity: object,
) -> str:
    """Build an unambiguous fixed-size identity for a domain publication source."""

    _nonempty(site_id, field="site_id")
    if offering_mode != binding.offering_mode:
        raise StorefrontDomainRegistryError(
            "derivation offering_mode must equal the durable domain binding"
        )
    canonical = json.dumps(
        [
            site_id,
            offering_mode,
            str(binding.domain_identity),
            binding.contract_major,
            binding.contract_minor,
            source_identity,
        ],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "storefront-derivation.v1:" + hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class StorefrontListingBinding:
    """Trusted common publication mapping for one durable listing."""

    listing_id: str
    site_id: str
    binding: StorefrontDomainBinding
    derivation_key: str
    source_envelope_json: str
    last_reconciled_at: str
    pool_id: str | None = None
    physical_resource_id: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.listing_id, field="listing_id")
        _nonempty(self.site_id, field="site_id")
        _nonempty(self.derivation_key, field="derivation_key")
        _nonempty(self.last_reconciled_at, field="last_reconciled_at")
        if self.pool_id is not None:
            _nonempty(self.pool_id, field="pool_id")
        if self.physical_resource_id is not None:
            _nonempty(self.physical_resource_id, field="physical_resource_id")
        try:
            parsed = json.loads(self.source_envelope_json)
        except (TypeError, ValueError) as exc:
            raise StorefrontDomainRegistryError(
                "source_envelope_json must contain canonical JSON"
            ) from exc
        canonical = canonical_source_envelope(parsed)
        if canonical != self.source_envelope_json:
            raise StorefrontDomainRegistryError(
                "source_envelope_json must use canonical JSON encoding"
            )

    @classmethod
    def from_source_envelope(
        cls,
        *,
        listing_id: str,
        site_id: str,
        binding: StorefrontDomainBinding,
        derivation_key: str,
        source_envelope: Mapping[str, object],
        last_reconciled_at: str,
        pool_id: str | None = None,
        physical_resource_id: str | None = None,
    ) -> "StorefrontListingBinding":
        return cls(
            listing_id=listing_id,
            site_id=site_id,
            binding=binding,
            derivation_key=derivation_key,
            source_envelope_json=canonical_source_envelope(source_envelope),
            last_reconciled_at=last_reconciled_at,
            pool_id=pool_id,
            physical_resource_id=physical_resource_id,
        )

    def as_record(self) -> dict[str, object]:
        """Return columns in the canonical SQLite insertion order."""

        return {
            "listing_id": self.listing_id,
            "site_id": self.site_id,
            "pool_id": self.pool_id,
            "physical_resource_id": self.physical_resource_id,
            **self.binding.as_record(),
            "derivation_key": self.derivation_key,
            "source_envelope_json": self.source_envelope_json,
            "last_reconciled_at": self.last_reconciled_at,
        }


@dataclass(frozen=True)
class StorefrontThreadBinding:
    """Listing binding copied into a negotiation before domain policy runs."""

    negotiation_id: str
    listing_id: str
    site_id: str
    binding: StorefrontDomainBinding

    def __post_init__(self) -> None:
        _nonempty(self.negotiation_id, field="negotiation_id")
        _nonempty(self.listing_id, field="listing_id")
        _nonempty(self.site_id, field="site_id")


def bind_fulfillment_context(
    context: Mapping[str, object],
    *,
    thread_binding: StorefrontThreadBinding,
) -> dict[str, object]:
    """Copy the accepted thread binding into a domain fulfillment context."""

    result = dict(context)
    projection = {
        "negotiation_id": thread_binding.negotiation_id,
        "listing_id": thread_binding.listing_id,
        "site_id": thread_binding.site_id,
        **thread_binding.binding.as_record(),
    }
    existing = result.get("storefront_domain_binding")
    if existing is not None and existing != projection:
        raise StorefrontDomainBindingError(
            "fulfillment context contains a conflicting domain binding"
        )
    result["storefront_domain_binding"] = projection
    return result

@dataclass(frozen=True)
class PreparedStorefrontDomainArtifact:
    """Codec-validated canonical artifact ready for atomic persistence."""

    artifact_slot: str
    binding: StorefrontDomainBinding
    artifact_json: str

    def __post_init__(self) -> None:
        _nonempty(self.artifact_slot, field="artifact_slot")
        try:
            parsed = json.loads(self.artifact_json)
        except (TypeError, ValueError) as exc:
            raise StorefrontDomainRegistryError(
                "artifact_json must contain canonical JSON"
            ) from exc
        canonical = json.dumps(
            parsed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if canonical != self.artifact_json:
            raise StorefrontDomainRegistryError(
                "artifact_json must use canonical JSON encoding"
            )


@dataclass(frozen=True)
class StorefrontDomainRegistration:
    """One installed contribution bound to one pool offering mode."""

    offering_mode: str
    contract: MarketDomainContract
    contribution_id: str

    def __post_init__(self) -> None:
        _nonempty(self.offering_mode, field="offering_mode")
        _nonempty(self.contribution_id, field="contribution_id")
        if not isinstance(self.contract, MarketDomainContract):
            raise StorefrontDomainRegistryError(
                "contract must be a MarketDomainContract, got "
                f"{type(self.contract).__name__}"
            )

    @property
    def contract_key(self) -> DomainContractKey:
        return DomainContractKey(
            self.contract.identity,
            self.contract.contract_version,
        )

    @property
    def binding(self) -> StorefrontDomainBinding:
        return StorefrontDomainBinding(
            offering_mode=self.offering_mode,
            domain_identity=self.contract.identity,
            contract_major=self.contract.contract_version.major,
            contract_minor=self.contract.contract_version.minor,
        )


@dataclass(frozen=True, order=True)
class StorefrontDomainProjection:
    """Public-safe startup/status projection with no contract callables."""

    contribution_id: str
    offering_mode: str
    domain_identity: str
    contract_version: str


class StorefrontDomainRegistry:
    """Frozen lookup of complete storefront contracts.

    Lookup returns the exact registration or contract object supplied during
    startup.  It never imports a contribution or reconstructs a contract from
    strings stored in a record.
    """

    __slots__ = (
        "_registrations",
        "_by_binding",
        "_by_contract_key",
        "_by_mode",
        "_by_contribution",
    )

    def __init__(self, registrations: Iterable[StorefrontDomainRegistration]) -> None:
        supplied = tuple(registrations)
        if not supplied:
            raise StorefrontDomainRegistryError(
                "at least one storefront domain registration is required"
            )
        try:
            validated = validate_domain_contracts(
                registration.contract for registration in supplied
            )
        except DomainContractValidationError as exc:
            raise StorefrontDomainRegistryError(str(exc)) from exc
        if len(validated) != len(supplied):
            raise StorefrontDomainRegistryError("domain contract validation was incomplete")

        by_binding: dict[StorefrontDomainBinding, StorefrontDomainRegistration] = {}
        by_contract_key: dict[DomainContractKey, StorefrontDomainRegistration] = {}
        by_mode: dict[str, StorefrontDomainRegistration] = {}
        by_contribution: dict[str, StorefrontDomainRegistration] = {}
        for registration in supplied:
            missing = REQUIRED_STOREFRONT_CAPABILITIES.difference(
                registration.contract.declared_capabilities
            )
            if missing:
                names = ", ".join(sorted(capability.value for capability in missing))
                raise StorefrontDomainRegistryError(
                    f"storefront contribution {registration.contribution_id!r} "
                    f"for domain {registration.contract.identity!s} is missing required "
                    f"capabilities: {names}"
                )
            if registration.offering_mode in by_mode:
                previous = by_mode[registration.offering_mode]
                raise StorefrontDomainRegistryError(
                    f"duplicate storefront offering mode {registration.offering_mode!r}: "
                    f"{previous.contribution_id!r} and {registration.contribution_id!r}"
                )
            if registration.contribution_id in by_contribution:
                raise StorefrontDomainRegistryError(
                    f"duplicate storefront contribution id "
                    f"{registration.contribution_id!r}"
                )
            if registration.contract_key in by_contract_key:
                previous = by_contract_key[registration.contract_key]
                raise StorefrontDomainRegistryError(
                    f"duplicate storefront domain contract "
                    f"{registration.contract.identity!s}@"
                    f"{registration.contract.contract_version}: "
                    f"{previous.contribution_id!r} and {registration.contribution_id!r}"
                )
            binding = registration.binding
            by_binding[binding] = registration
            by_contract_key[registration.contract_key] = registration
            by_mode[registration.offering_mode] = registration
            by_contribution[registration.contribution_id] = registration

        self._registrations = supplied
        self._by_binding = MappingProxyType(by_binding)
        self._by_contract_key = MappingProxyType(by_contract_key)
        self._by_mode = MappingProxyType(by_mode)
        self._by_contribution = MappingProxyType(by_contribution)

    @property
    def registrations(self) -> tuple[StorefrontDomainRegistration, ...]:
        return self._registrations

    @property
    def bindings(self) -> tuple[StorefrontDomainBinding, ...]:
        return tuple(registration.binding for registration in self._registrations)

    @property
    def by_offering_mode(self) -> Mapping[str, StorefrontDomainRegistration]:
        return self._by_mode

    def resolve_mode(self, offering_mode: str) -> StorefrontDomainRegistration:
        """Resolve an explicit new-work mode to its pre-registered contract."""

        try:
            return self._by_mode[offering_mode]
        except KeyError as exc:
            raise StorefrontDomainBindingError(
                f"unknown storefront offering mode {offering_mode!r}"
            ) from exc

    def projection(self) -> tuple[StorefrontDomainProjection, ...]:
        return tuple(
            StorefrontDomainProjection(
                contribution_id=registration.contribution_id,
                offering_mode=registration.offering_mode,
                domain_identity=str(registration.contract.identity),
                contract_version=str(registration.contract.contract_version),
            )
            for registration in self._registrations
        )

    def resolve_registration(
        self,
        binding: StorefrontDomainBinding,
    ) -> StorefrontDomainRegistration:
        if not isinstance(binding, StorefrontDomainBinding):
            raise StorefrontDomainBindingError(
                "domain selection requires a StorefrontDomainBinding"
            )
        registration = self._by_binding.get(binding)
        if registration is not None:
            return registration
        registered_key = self._by_contract_key.get(binding.contract_key)
        if registered_key is None:
            raise StorefrontDomainBindingError(
                f"unknown storefront domain binding "
                f"{binding.domain_identity!s}@{binding.contract_version} "
                f"for offering mode {binding.offering_mode!r}"
            )
        raise StorefrontDomainBindingError(
            f"storefront domain binding mode {binding.offering_mode!r} does not "
            f"match configured mode {registered_key.offering_mode!r} for "
            f"{binding.domain_identity!s}@{binding.contract_version}"
        )

    def resolve(self, binding: StorefrontDomainBinding) -> MarketDomainContract:
        return self.resolve_registration(binding).contract

    def registration_for_contribution(
        self,
        contribution_id: str,
    ) -> StorefrontDomainRegistration:
        try:
            return self._by_contribution[contribution_id]
        except KeyError as exc:
            raise StorefrontDomainBindingError(
                f"unknown storefront contribution {contribution_id!r}"
            ) from exc

    def registration_for_contract(
        self,
        contract: MarketDomainContract,
    ) -> StorefrontDomainRegistration:
        """Return the exact pre-registered object; reconstructed peers fail."""
        if not isinstance(contract, MarketDomainContract):
            raise StorefrontDomainBindingError(
                "contract resolution requires the exact startup-owned "
                "MarketDomainContract object"
            )

        key = DomainContractKey(
            contract.identity,
            contract.contract_version,
        )
        registration = self._by_contract_key.get(key)
        if registration is None or registration.contract is not contract:
            raise StorefrontDomainBindingError(
                "market-domain contract is not the exact startup-owned object"
            )
        return registration
