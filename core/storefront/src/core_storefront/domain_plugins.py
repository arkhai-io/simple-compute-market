"""Startup-only discovery of complete storefront domain contributions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from market_core import ContractVersion, DomainIdentity, MarketDomainContract

from .domain_registry import (
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
    StorefrontDomainRegistryError,
)


STOREFRONT_CONTRIBUTION_GROUP = "market.storefront_contributions"


@dataclass(frozen=True)
class StorefrontDomainContribution:
    """Installed composition contribution for one complete storefront contract."""

    contribution_id: str
    build_contract: Callable[[], MarketDomainContract]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.contribution_id, str)
            or not self.contribution_id.strip()
            or self.contribution_id != self.contribution_id.strip()
        ):
            raise ValueError("contribution_id must be a non-empty trimmed string")
        if not callable(self.build_contract):
            raise TypeError("build_contract must be callable")


@dataclass(frozen=True)
class StorefrontContributionSelection:
    """Public configuration assertions for one installed contribution."""

    contribution_id: str
    offering_mode: str
    domain_identity: DomainIdentity
    contract_version: ContractVersion

    def __post_init__(self) -> None:
        for field_name in ("contribution_id", "offering_mode"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
            ):
                raise ValueError(f"{field_name} must be a non-empty trimmed string")
        if not isinstance(self.domain_identity, DomainIdentity):
            object.__setattr__(
                self,
                "domain_identity",
                DomainIdentity(str(self.domain_identity)),
            )
        if not isinstance(self.contract_version, ContractVersion):
            raise TypeError("contract_version must be a ContractVersion")

def parse_storefront_contribution_selections(
    value: Any,
) -> tuple[StorefrontContributionSelection, ...]:
    """Parse the exact, public ``[[storefront_domains]]`` configuration."""

    if not isinstance(value, (list, tuple)) or not value:
        raise StorefrontDomainRegistryError(
            "storefront_domains must be a non-empty array of tables"
        )
    allowed = {
        "contribution",
        "offering_mode",
        "domain_identity",
        "contract_version",
    }
    selections: list[StorefrontContributionSelection] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise StorefrontDomainRegistryError(
                f"storefront_domains[{index}] must be a table"
            )
        normalized = {str(key).lower(): item for key, item in raw.items()}
        unknown = sorted(set(normalized) - allowed)
        missing = sorted(allowed - set(normalized))
        if unknown or missing:
            detail = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if unknown:
                detail.append("unknown " + ", ".join(unknown))
            raise StorefrontDomainRegistryError(
                f"storefront_domains[{index}] has invalid keys: "
                + "; ".join(detail)
            )
        version_text = normalized["contract_version"]
        if not isinstance(version_text, str):
            raise StorefrontDomainRegistryError(
                f"storefront_domains[{index}].contract_version must be major.minor"
            )
        version_parts = version_text.split(".")
        if (
            len(version_parts) != 2
            or not all(part.isdigit() for part in version_parts)
        ):
            raise StorefrontDomainRegistryError(
                f"storefront_domains[{index}].contract_version must be major.minor"
            )
        try:
            selections.append(
                StorefrontContributionSelection(
                    contribution_id=normalized["contribution"],
                    offering_mode=normalized["offering_mode"],
                    domain_identity=DomainIdentity(normalized["domain_identity"]),
                    contract_version=ContractVersion(
                        int(version_parts[0]), int(version_parts[1])
                    ),
                )
            )
        except (TypeError, ValueError) as exc:
            raise StorefrontDomainRegistryError(
                f"storefront_domains[{index}] is invalid: {exc}"
            ) from exc
    return tuple(selections)


def _installed_entry_points() -> tuple[EntryPoint, ...]:
    return tuple(entry_points(group=STOREFRONT_CONTRIBUTION_GROUP))


def _entry_point_index(installed: Iterable[EntryPoint]) -> dict[str, EntryPoint]:
    result: dict[str, EntryPoint] = {}
    providers: dict[str, list[str]] = {}
    for entry_point in installed:
        providers.setdefault(entry_point.name, []).append(entry_point.value)
        result.setdefault(entry_point.name, entry_point)
    duplicate = next(
        ((name, values) for name, values in providers.items() if len(values) > 1),
        None,
    )
    if duplicate is not None:
        name, values = duplicate
        raise StorefrontDomainRegistryError(
            f"multiple storefront contributions named {name!r}: "
            + ", ".join(sorted(values))
        )
    return result


def _load_contribution(
    entry_point: Any,
    *,
    expected_id: str,
) -> StorefrontDomainContribution:
    loaded = entry_point.load()
    if not isinstance(loaded, StorefrontDomainContribution):
        raise StorefrontDomainRegistryError(
            f"storefront contribution {expected_id!r} must export "
            f"StorefrontDomainContribution, got {type(loaded).__name__}"
        )
    if loaded.contribution_id != expected_id:
        raise StorefrontDomainRegistryError(
            f"storefront contribution entry point {expected_id!r} exports "
            f"mismatched id {loaded.contribution_id!r}"
        )
    return loaded


def discover_storefront_domain_registry(
    selections: Iterable[StorefrontContributionSelection],
    *,
    installed: Iterable[EntryPoint] | None = None,
) -> StorefrontDomainRegistry:
    """Load configured contributions once and return a frozen exact registry."""

    configured = tuple(selections)
    if not configured:
        raise StorefrontDomainRegistryError(
            "at least one storefront contribution selection is required"
        )
    index = _entry_point_index(
        _installed_entry_points() if installed is None else tuple(installed)
    )
    registrations: list[StorefrontDomainRegistration] = []
    for selection in configured:
        entry_point = index.get(selection.contribution_id)
        if entry_point is None:
            available = ", ".join(sorted(index)) or "(none)"
            raise StorefrontDomainRegistryError(
                f"storefront contribution {selection.contribution_id!r} is not "
                f"installed; available: {available}"
            )
        contribution = _load_contribution(
            entry_point,
            expected_id=selection.contribution_id,
        )
        contract = contribution.build_contract()
        if not isinstance(contract, MarketDomainContract):
            raise StorefrontDomainRegistryError(
                f"storefront contribution {selection.contribution_id!r} returned "
                f"{type(contract).__name__}, expected MarketDomainContract"
            )
        if contract.identity != selection.domain_identity:
            raise StorefrontDomainRegistryError(
                f"storefront contribution {selection.contribution_id!r} returned "
                f"domain {contract.identity!s}, configured "
                f"{selection.domain_identity!s}"
            )
        if contract.contract_version != selection.contract_version:
            raise StorefrontDomainRegistryError(
                f"storefront contribution {selection.contribution_id!r} returned "
                f"contract {contract.contract_version}, configured "
                f"{selection.contract_version}"
            )
        registrations.append(
            StorefrontDomainRegistration(
                offering_mode=selection.offering_mode,
                contract=contract,
                contribution_id=selection.contribution_id,
            )
        )
    return StorefrontDomainRegistry(registrations)


def list_installed_storefront_contributions() -> tuple[str, ...]:
    """Return metadata names without importing contribution implementations."""

    return tuple(sorted(_entry_point_index(_installed_entry_points())))
