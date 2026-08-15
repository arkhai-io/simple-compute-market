"""Mechanism-neutral buyer settlement admission and selection."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from market_core.schemas import SettlementOption, SettlementSelection
from market_settlement_runtime import (
    CompiledSettlementClause,
    MechanismRegistration,
    SettlementConfig,
    SettlementConfigurationRegistry,
    compile_settlement_clause,
    select_settlement_candidates,
)


@dataclass(frozen=True, slots=True)
class SelectedSettlementOption:
    """An advertised option admitted by one installed buyer registration."""

    option: SettlementOption
    selection: SettlementSelection
    registration: MechanismRegistration = field(repr=False)
    clause_index: int | None = None


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
class SettlementClauseStage:
    """Survivor count for one ordered local settlement clause."""

    index: int
    clause: str
    listing_count: int
    option_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "clause": self.clause,
            "listing_count": self.listing_count,
            "option_count": self.option_count,
        }


@dataclass(frozen=True, slots=True)
class BuyerSettlementExplanation:
    """Deterministic, public-only trace of local settlement selection."""

    resource_listing_count: int
    advertised_option_count: int
    compatible_listing_count: int
    compatible_option_count: int
    clauses: tuple[SettlementClauseStage, ...]
    winning_clause_index: int | None
    policy_mechanism: str | None
    policy_listing_count: int
    selected_option_id: str | None
    rejection_categories: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_listing_count": self.resource_listing_count,
            "advertised_option_count": self.advertised_option_count,
            "installed_enabled_compatibility": {
                "listing_count": self.compatible_listing_count,
                "option_count": self.compatible_option_count,
            },
            "clause_survivors": [stage.to_dict() for stage in self.clauses],
            "winning_clause_index": self.winning_clause_index,
            "policy_ordering": {
                "mechanism": self.policy_mechanism,
                "listing_count": self.policy_listing_count,
            },
            "selected_option_id": self.selected_option_id,
            "rejection_categories": dict(sorted(self.rejection_categories.items())),
        }


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
        return tuple(
            registration
            for registration in self.registry.ordered_registrations(
                self.config,
                role="buyer",
            )
            if (
                (section := self.config.mechanisms.get(registration.config_key))
                is not None
                and bool(getattr(section, "enabled", False))
            )
        )

    def compile_clauses(
        self,
        sources: Iterable[str],
    ) -> tuple[CompiledSettlementClause, ...]:
        """Compile ordered buyer clauses against installed registrations."""

        return tuple(
            compile_settlement_clause(source, self.registry, role="buyer")
            for source in sources
        )

    def compatible_options(
        self,
        advertised: Iterable[SettlementOption | Mapping[str, Any]],
        *,
        clauses: Iterable[str | CompiledSettlementClause] = (),
    ) -> tuple[tuple[MechanismRegistration, SettlementOption], ...]:
        """Return first-clause survivors in configured mechanism order."""

        result = select_settlement_candidates(
            advertised,
            registry=self.registry,
            config=self.config,
            clauses=clauses,
            public_context=self.public_context,
        )
        return tuple(
            (candidate.registration, candidate.option)
            for candidate in result.candidates
        )

    def select(
        self,
        listing: Mapping[str, Any],
        *,
        expiration_unix: int,
        clauses: Iterable[str | CompiledSettlementClause] = (),
    ) -> SelectedSettlementOption | None:
        """Select the first compatible option from the first surviving clause."""

        result = select_settlement_candidates(
            _decode_options(listing.get("settlement_options")),
            registry=self.registry,
            config=self.config,
            clauses=clauses,
            public_context=self.public_context,
        )
        if not result.candidates:
            return None
        candidate = result.candidates[0]
        option = candidate.option
        return SelectedSettlementOption(
            option=option,
            selection=SettlementSelection(
                mechanism=option.mechanism,
                option_id=option.option_id,
                expiration_unix=expiration_unix,
            ),
            registration=candidate.registration,
            clause_index=result.matched_clause_index,
        )

    def select_listings(
        self,
        listings: Iterable[Mapping[str, Any]],
        *,
        expiration_unix: int,
        clauses: Iterable[str | CompiledSettlementClause] = (),
    ) -> tuple[tuple[Mapping[str, Any], SelectedSettlementOption], ...]:
        """Apply clause ordering and mechanism priority across listings."""

        ordered_clauses = tuple(clauses)
        selected = tuple(
            (listing, choice)
            for listing in listings
            if (
                choice := self.select(
                    listing,
                    expiration_unix=expiration_unix,
                    clauses=ordered_clauses,
                )
            )
            is not None
        )
        if ordered_clauses and selected:
            first_clause = min(
                choice.clause_index
                for _, choice in selected
                if choice.clause_index is not None
            )
            selected = tuple(
                (listing, choice)
                for listing, choice in selected
                if choice.clause_index == first_clause
            )
        preferred_mechanism = next(
            (
                registration.mechanism_id
                for registration in self.ordered_registrations()
                if any(
                    choice.selection.mechanism == registration.mechanism_id
                    for _, choice in selected
                )
            ),
            None,
        )
        if preferred_mechanism is None:
            return ()
        return tuple(
            (listing, choice)
            for listing, choice in selected
            if choice.selection.mechanism == preferred_mechanism
        )

    def explain_listings(
        self,
        listings: Iterable[Mapping[str, Any]],
        *,
        expiration_unix: int,
        clauses: Iterable[str | CompiledSettlementClause] = (),
    ) -> BuyerSettlementExplanation:
        """Trace read-only admission, clause ordering, and policy selection."""

        listing_set = tuple(listings)
        compiled = tuple(
            clause
            if isinstance(clause, CompiledSettlementClause)
            else compile_settlement_clause(clause, self.registry, role="buyer")
            for clause in clauses
        )
        decoded = tuple(
            _decode_options(listing.get("settlement_options"))
            for listing in listing_set
        )
        compatible = tuple(self.compatible_options(options) for options in decoded)
        compatible_listing_count = sum(bool(options) for options in compatible)
        stages: list[SettlementClauseStage] = []
        for index, clause in enumerate(compiled):
            survivors = tuple(
                self.compatible_options(options, clauses=(clause,))
                for options in decoded
            )
            stages.append(
                SettlementClauseStage(
                    index=index,
                    clause=clause.render(),
                    listing_count=sum(bool(options) for options in survivors),
                    option_count=sum(len(options) for options in survivors),
                )
            )

        selected = self.select_listings(
            listing_set,
            expiration_unix=expiration_unix,
            clauses=compiled,
        )
        winning_clause_index = next(
            (stage.index for stage in stages if stage.option_count),
            None,
        )
        policy_mechanism = selected[0][1].selection.mechanism if selected else None

        rejection_categories = {
            "no_settlement_options": sum(not options for options in decoded),
            "installed_enabled_incompatible": sum(
                bool(advertised) and not admitted
                for advertised, admitted in zip(decoded, compatible, strict=True)
            ),
            "clause_mismatch": sum(
                compatible_listing_count - stage.listing_count for stage in stages
            ),
            "mechanism_mismatch": self._field_mismatch_count(
                "mechanism", compiled, decoded, compatible
            ),
            "asset_mismatch": self._field_mismatch_count(
                "asset", compiled, decoded, compatible
            ),
        }
        return BuyerSettlementExplanation(
            resource_listing_count=len(listing_set),
            advertised_option_count=sum(len(options) for options in decoded),
            compatible_listing_count=compatible_listing_count,
            compatible_option_count=sum(len(options) for options in compatible),
            clauses=tuple(stages),
            winning_clause_index=winning_clause_index,
            policy_mechanism=policy_mechanism,
            policy_listing_count=len(selected),
            selected_option_id=(
                selected[0][1].option.option_id if len(selected) == 1 else None
            ),
            rejection_categories=rejection_categories,
        )

    def _field_mismatch_count(
        self,
        field_name: str,
        clauses: tuple[CompiledSettlementClause, ...],
        decoded: tuple[tuple[SettlementOption, ...], ...],
        compatible: tuple[
            tuple[tuple[MechanismRegistration, SettlementOption], ...], ...
        ],
    ) -> int:
        count = 0
        for clause in clauses:
            predicates = tuple(
                type(clause.query)((comparison,)).render()
                for comparison in clause.query.comparisons
                if comparison.field == field_name
            )
            if not predicates:
                continue
            field_clause = compile_settlement_clause(
                " ".join(predicates),
                self.registry,
                role="buyer",
            )
            for advertised, admitted in zip(decoded, compatible, strict=True):
                if admitted and not self.compatible_options(
                    advertised,
                    clauses=(field_clause,),
                ):
                    count += 1
        return count

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
