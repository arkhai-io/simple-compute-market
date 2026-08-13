"""Mechanism-neutral buyer settlement admission and selection."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from market_core.schemas import SettlementOption, SettlementSelection
from market_settlement_runtime import (
    MechanismRegistration,
    SettlementConfig,
    SettlementConfigurationRegistry,
)


@dataclass(frozen=True, slots=True)
class SelectedSettlementOption:
    """An advertised option admitted by one installed buyer registration."""

    option: SettlementOption
    selection: SettlementSelection
    registration: MechanismRegistration = field(repr=False)


def _decode_options(value: Any) -> tuple[SettlementOption, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("settlement_options is not valid JSON") from exc
    if not isinstance(value, (list, tuple)):
        raise ValueError("settlement_options must be an array")
    return tuple(SettlementOption.model_validate(option) for option in value)


@dataclass(frozen=True, slots=True)
class BuyerSettlementPolicy:
    """Select only installed, enabled, compatible advertised mechanisms.

    Compatibility runs before accepted Terms and is deliberately resource-free.
    Mechanism clients and any wallet/chain dependencies are constructed only by
    the caller after this policy returns a concrete registration.
    """

    config: SettlementConfig
    registry: SettlementConfigurationRegistry = field(repr=False)
    public_context: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.registry.validate(self.config, role="buyer")

    def ordered_registrations(self) -> tuple[MechanismRegistration, ...]:
        return tuple(self.registry.ordered_registrations(self.config, role="buyer"))

    def compatible_options(
        self,
        advertised: Iterable[SettlementOption | Mapping[str, Any]],
        *,
        option_id: str | None = None,
        asset: str | None = None,
    ) -> tuple[tuple[MechanismRegistration, SettlementOption], ...]:
        """Return candidates ordered by configured mechanism policy."""

        decoded = tuple(SettlementOption.model_validate(option) for option in advertised)
        by_mechanism: dict[str, list[SettlementOption]] = {}
        for option in decoded:
            if option_id is not None and option.option_id != option_id:
                continue
            if asset is not None and option.asset != asset:
                continue
            by_mechanism.setdefault(option.mechanism, []).append(option)

        admitted: list[tuple[MechanismRegistration, SettlementOption]] = []
        for registration in self.ordered_registrations():
            section = self.config.mechanism_config(registration.config_key)
            if section is None or not bool(getattr(section, "enabled", False)):
                continue
            for option in sorted(
                by_mechanism.get(registration.mechanism_id, ()),
                key=lambda candidate: candidate.option_id,
            ):
                if self.registry.buyer_compatible(
                    registration.mechanism_id,
                    option,
                    self.config,
                    public_context=self.public_context,
                ):
                    admitted.append((registration, option))
        return tuple(admitted)

    def select(
        self,
        listing: Mapping[str, Any],
        *,
        expiration_unix: int,
        option_id: str | None = None,
        asset: str | None = None,
    ) -> SelectedSettlementOption | None:
        """Select the first policy-compatible advertised option."""

        candidates = self.compatible_options(
            _decode_options(listing.get("settlement_options")),
            option_id=option_id,
            asset=asset,
        )
        if not candidates:
            return None
        registration, option = candidates[0]
        return SelectedSettlementOption(
            option=option,
            selection=SettlementSelection(
                mechanism=option.mechanism,
                option_id=option.option_id,
                expiration_unix=expiration_unix,
            ),
            registration=registration,
        )

    def public_run_metadata(self) -> dict[str, Any]:
        """Return the allowlisted settlement configuration run-log projection."""

        mechanisms = tuple(
            registration.mechanism_id
            for registration in self.ordered_registrations()
            if (
                (section := self.config.mechanism_config(registration.config_key))
                is not None
                and bool(getattr(section, "enabled", False))
            )
        )
        return {
            "settlement_config_schema_version": self.config.schema_version,
            "settlement_public_mechanisms": list(mechanisms),
            "settlement_public_fingerprint": self.registry.public_fingerprint(
                self.config,
                role="buyer",
            ),
        }
