"""Composition-owned rate servicing declaration, independent of offer contents.

A composition declares, per mechanism, the ``settles_through`` treatments it has
qualified against that mechanism's payment authority — named as the payment
authority names them, ``charged``, ``returned`` or ``prorated`` — and whether it
services a separate setup charge. Absent or empty means no rate servicing.

The declaration admits new offers and acceptances only. Accepted-deal
continuation must not use it to decide whether existing work is still serviced:
withdrawing a treatment withdraws offers, never work already owed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from market_core.schemas import SettlementOption
from market_deal_lifecycle.terms import PARTIAL_PERIOD, LifecycleTerms
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

TREATMENTS = frozenset(PARTIAL_PERIOD.values())
#: The payment authority's names for the ``settles_through`` treatments, which
#: are ``TREATMENTS``.
Treatment = Literal["charged", "returned", "prorated"]


class RateServicingTable(BaseModel):
    """One mechanism's table under a seller's ``[Settlement].rate_servicing``.

    The configuration schema renders this model, so the table has one
    definition.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    treatments: list[Treatment] = Field(default_factory=list)
    setup: StrictBool = False


class RateServicingUnavailable(ValueError):
    """The selected rate option is not serviceable here; the buyer must refetch."""


@dataclass(frozen=True)
class RateServicingDeclaration:
    """The treatments one mechanism's rate servicing is qualified for."""

    mechanism: str
    treatments: frozenset[str] = frozenset()
    setup: bool = False

    def __post_init__(self) -> None:
        if not self.mechanism.strip():
            raise ValueError("rate servicing requires a mechanism")
        treatments = frozenset(self.treatments)
        unknown = sorted(treatments - TREATMENTS)
        if unknown:
            raise ValueError(
                f"unknown rate servicing treatments {unknown}; expected some of {sorted(TREATMENTS)}"
            )
        object.__setattr__(self, "treatments", treatments)


def option_treatments(option: SettlementOption) -> frozenset[str]:
    """The treatments an option's lifecycle names, on an entitlement or at its end."""
    if option.lifecycle is None:
        return frozenset()
    early = LifecycleTerms.model_validate(option.lifecycle).early_termination
    if early is None:
        return frozenset()
    named = [early.settles_through, *(item.settles_through for item in early.entitlements.values())]
    return frozenset(PARTIAL_PERIOD[value] for value in named)


@dataclass(frozen=True)
class RateServicing:
    """The composition's declarations, keyed by mechanism ID.

    Composition supplies them, never a listing or request. Publication and
    acceptance share one object, so a withdrawal is checked again at acceptance.
    """

    declarations: Mapping[str, RateServicingDeclaration] = field(default_factory=dict)

    @classmethod
    def from_tables(
        cls, tables: Mapping[str, Any], *, mechanism_for: Mapping[str, str],
    ) -> RateServicing:
        """Read the ``rate_servicing`` tables of a ``[Settlement]`` root.

        Each table is keyed by an installed mechanism's configuration key, which
        ``mechanism_for`` maps to its mechanism ID, and is a
        :class:`RateServicingTable`. Any other key, or a key naming no installed
        mechanism, is refused rather than ignored.
        """
        declarations: dict[str, RateServicingDeclaration] = {}
        for key, table in tables.items():
            mechanism = mechanism_for.get(key)
            if mechanism is None:
                raise ValueError(f"rate_servicing.{key} names no installed mechanism")
            if not isinstance(table, Mapping):
                raise ValueError(f"rate_servicing.{key} must be a table")
            try:
                parsed = RateServicingTable.model_validate(dict(table))
            except ValidationError as exc:
                problem = exc.errors()[0]
                where = ".".join(str(part) for part in problem["loc"])
                raise ValueError(f"rate_servicing.{key}.{where}: {problem['msg']}") from None
            declarations[mechanism] = RateServicingDeclaration(
                mechanism, frozenset(parsed.treatments), parsed.setup,
            )
        return cls(declarations)

    def select(self, mechanism: str) -> RateServicingDeclaration:
        """The mechanism's declaration; an absent or empty one services nothing."""
        declared = self.declarations.get(mechanism)
        if declared is None or declared.mechanism != mechanism or not declared.treatments:
            raise RateServicingUnavailable(
                f"settlement_option_withdrawn_refetch: rate servicing is undeclared for {mechanism!r}"
            )
        return declared

    def require(
        self, mechanism: str, treatments: Iterable[str], *, setup: bool,
    ) -> RateServicingDeclaration:
        """Refuse any treatment, or a setup charge, the declaration does not qualify."""
        declared = self.select(mechanism)
        undeclared = sorted(frozenset(treatments) - declared.treatments)
        if undeclared:
            raise RateServicingUnavailable(
                "settlement_option_withdrawn_refetch: rate servicing for "
                f"{mechanism!r} does not declare {', '.join(undeclared)}"
            )
        if setup and not declared.setup:
            raise RateServicingUnavailable(
                "settlement_option_withdrawn_refetch: rate servicing for "
                f"{mechanism!r} does not declare a setup charge"
            )
        return declared

    def require_option(self, option: SettlementOption | Mapping[str, Any]) -> None:
        """Refuse a rate option whose treatments or setup charge are undeclared.

        A once option passes untouched. Either rate marker requires servicing
        even if the other is malformed or absent: the mechanism codec still owns
        period parsing, and an unreadable rate must never slip through as a once
        option. A ``setup_amount`` beside a rate marker is a setup charge.
        """
        selected = SettlementOption.model_validate(option)
        settlement = selected.settlement
        if not ("period" in settlement or "reserve_ahead_seconds" in settlement):
            return
        self.require(
            selected.settlement_schema, option_treatments(selected),
            setup=settlement.get("setup_amount") is not None,
        )
