"""What a pool's declared capacity backing means.

A pool declares ``capacity_backing``: ``backed`` when an admission authority
stands behind it, ``unbacked`` when none does. The label is what declarations,
listing bindings, projections, and published listings carry; its meaning lives
here, in one :class:`CapacityBacking` delegate per label, and nowhere else.

Every decision that differs between backed and unbacked supply is one of the
delegate's operations. A caller hands the delegate the work that would differ
and the delegate decides whether and how it runs, so no caller compares the
label or learns which backing it holds. That keeps a further category a change
to this module alone. The operations take callables rather than performing
effects because this package may import nothing that reserves, holds, or reads
availability.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Literal, TypeVar

from .vocabulary import (
    ADVERTISABLE_EXCEEDS_DELIVERABLE,
    ADVERTISABLE_MODES_POLICY_TAG,
    DELIVERABLE_MODES_POLICY_TAG,
    UNBACKED_POOL_DELIVERS,
    PoolDeclarationProblem,
)

CapacityBackingLabel = Literal["backed", "unbacked"]

_T = TypeVar("_T")
_C = TypeVar("_C")


class UnknownCapacityBackingError(ValueError):
    """A backing label no delegate is registered for.

    Refused rather than read as either backing: a durable or projected label
    this package does not recognize is a defect, not a category to guess.
    """

    def __init__(self, label: object) -> None:
        self.label = label
        super().__init__(
            f"unknown capacity_backing {label!r}; expected one of "
            f"{sorted(_REGISTRY)}"
        )


class CapacityNotAdmittedError(RuntimeError):
    """A capacity effect was asked of supply no admission authority stands behind.

    A conflict with the listing's backing, distinct from an identity fault such
    as an unknown site or a changed binding.
    """


class CapacityBacking:
    """The meaning of one backing label.

    Instances are the module-level :data:`BACKED` and :data:`UNBACKED`, obtained
    by label through :func:`capacity_backing`. Two delegates are equal only when
    they are the same instance, so a binding carrying one compares by backing.
    """

    __slots__ = ("label", "_admitted")

    def __init__(self, label: str, *, admitted: bool) -> None:
        self.label = label
        # Whether an admission authority stands behind supply of this backing.
        # Every operation below follows from it; it is never exposed, so a
        # caller cannot branch on it in place of asking the delegate to act.
        self._admitted = admitted

    def __repr__(self) -> str:
        return f"CapacityBacking({self.label!r})"

    def declaration_problems(
        self,
        advertisable: frozenset[str],
        deliverable: frozenset[str],
    ) -> tuple[PoolDeclarationProblem, ...]:
        """Problems relating a pool's advertisable and deliverable sets.

        Backed supply may advertise only what it delivers, or a buyer could
        reach admission for a mode the provider will refuse. Unbacked supply
        must deliver nothing: no layer reads backing at admission, so an empty
        deliverable set is what keeps every capacity path unreachable for it.
        """
        if self._admitted:
            excess = advertisable - deliverable
            if not excess:
                return ()
            return (
                PoolDeclarationProblem(
                    ADVERTISABLE_MODES_POLICY_TAG,
                    ADVERTISABLE_EXCEEDS_DELIVERABLE,
                    f"a backed pool may advertise only modes it delivers; "
                    f"{ADVERTISABLE_MODES_POLICY_TAG} names undelivered "
                    f"{', '.join(sorted(excess))}",
                ),
            )
        if not deliverable:
            return ()
        return (
            PoolDeclarationProblem(
                DELIVERABLE_MODES_POLICY_TAG,
                UNBACKED_POOL_DELIVERS,
                f"an unbacked pool must deliver nothing; "
                f"{DELIVERABLE_MODES_POLICY_TAG} names {', '.join(sorted(deliverable))}",
            ),
        )

    def require_admission(self, effect: str) -> None:
        """Refuse a capacity effect unless an admission authority stands behind it.

        A reservation against unbacked supply would be a record with nothing
        behind it, so the refusal comes before any site call.
        """
        if not self._admitted:
            raise CapacityNotAdmittedError(
                f"{effect} requires capacity-backed supply; this listing is "
                f"{self.label}"
            )

    async def place_hold(
        self, place: Callable[[], Awaitable[_T]]
    ) -> _T | None:
        """Run ``place`` where a hold can stand behind the supply, else nothing.

        Returns ``place()``'s result, or ``None`` without calling it, so the
        caller reports a hold that was not placed the same way either way.
        """
        if not self._admitted:
            return None
        return await place()

    def judge(
        self,
        declared: Callable[[], _T | None],
        available: Callable[[], _T | None],
    ) -> _T | None:
        """Judge supply against its declaration and, where it bounds it, availability.

        ``declared`` returns the caller's refusal, or ``None`` when the
        declaration fits. A refusal is returned as is. Otherwise availability is
        consulted only where it bounds the supply, and its result returned;
        where it does not, the result is ``None``. ``None`` always means the
        supply stands.
        """
        verdict = declared()
        if verdict is not None or not self._admitted:
            return verdict
        return available()

    async def judge_async(
        self,
        declared: Callable[[], Awaitable[_T | None]],
        available: Callable[[], Awaitable[_T | None]],
    ) -> _T | None:
        """:meth:`judge` over coroutine functions, deciding identically."""
        verdict = await declared()
        if verdict is not None or not self._admitted:
            return verdict
        return await available()

    def admissible_settlement(
        self,
        clauses: Iterable[_C],
        *,
        mechanism: Callable[[_C], str],
        fulfils_through_capacity: Callable[[str], bool],
    ) -> tuple[tuple[_C, ...], tuple[str, ...]]:
        """Split settlement clauses into those this supply may publish and dropped mechanisms.

        Backed supply keeps every clause. Unbacked supply keeps only clauses
        whose mechanism its domain does not fulfil through capacity: such a
        deal would take a buyer's funds and then reach a reservation nothing
        stands behind. ``fulfils_through_capacity`` is the domain's
        per-mechanism declaration. Dropped mechanisms are named once each, in
        clause order.
        """
        kept: list[_C] = []
        dropped: list[str] = []
        for clause in clauses:
            name = mechanism(clause)
            if self._admitted or not fulfils_through_capacity(name):
                kept.append(clause)
            elif name not in dropped:
                dropped.append(name)
        return tuple(kept), tuple(dropped)


BACKED = CapacityBacking("backed", admitted=True)
UNBACKED = CapacityBacking("unbacked", admitted=False)

_REGISTRY: dict[str, CapacityBacking] = {
    delegate.label: delegate for delegate in (BACKED, UNBACKED)
}


def capacity_backing(label: object) -> CapacityBacking:
    """The delegate a backing label selects, refusing a label with none."""
    delegate = _REGISTRY.get(label) if isinstance(label, str) else None
    if delegate is None:
        raise UnknownCapacityBackingError(label)
    return delegate


def capacity_backing_labels() -> frozenset[str]:
    """Every label a delegate is registered for."""
    return frozenset(_REGISTRY)


def labels_reconciled_by_availability() -> frozenset[str]:
    """Labels of supply that capacity-availability reconciliation may close or reopen.

    Source reconciliation applies to every listing; availability bounds only
    supply an admission authority stands behind.
    """
    return frozenset(
        label for label, delegate in _REGISTRY.items() if delegate._admitted
    )


def legacy_producer_backing() -> CapacityBacking:
    """The backing of supply from a producer that predates backing declarations.

    Before pools declared backing, every pool was admitted against capacity,
    so reading an older producer's pools this way reproduces the contract they
    were written under.
    """
    return BACKED


def admitted_backing() -> CapacityBacking:
    """The backing implied by a reservation a site admitted.

    A reservation exists only because an admission authority accepted it, so a
    binding synthesized for one that has no listing takes this backing.
    """
    return BACKED


__all__ = [
    "BACKED",
    "UNBACKED",
    "CapacityBacking",
    "CapacityBackingLabel",
    "CapacityNotAdmittedError",
    "UnknownCapacityBackingError",
    "admitted_backing",
    "capacity_backing",
    "capacity_backing_labels",
    "labels_reconciled_by_availability",
    "legacy_producer_backing",
]
