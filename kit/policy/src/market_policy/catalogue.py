"""Composition of named items from explicit sources into one immutable catalogue.

A catalogue answers one question for one composed role: which names may this
role resolve, and to what? It is built once from a declared list of sources and
frozen. Resolution is a pure lookup that neither loads nor caches, so what a
role can resolve does not depend on what it has already resolved, nor on which
modules happened to be imported first.

Composition is where the failures surface. A source that cannot load, an item
that fails validation, and a name offered twice are each errors raised by
:meth:`CatalogueBuilder.build`, before the composing role serves requests.

Nothing here is specific to negotiation. Callers supply the validator for their
item type through the factory that builds their builder, so a catalogue of
middlewares, of buyer policies, or of identity verifiers all use this machinery
and each keeps its own notion of a well-formed item.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Generic, Protocol, TypeVar, runtime_checkable

#: The item type a catalogue holds. Invariant: a catalogue both accepts items
#: from its sources and hands them back to callers.
T = TypeVar("T")

__all__ = [
    "Catalogue",
    "CatalogueBuilder",
    "CatalogueConflictError",
    "CatalogueItemTypeError",
    "CatalogueSource",
    "CatalogueSourceError",
    "ItemValidator",
    "UnknownCatalogueEntryError",
    "require_callable_item",
]


class CatalogueSourceError(RuntimeError):
    """A declared source could not be loaded."""


class CatalogueConflictError(ValueError):
    """Two sources offered the same name."""


class CatalogueItemTypeError(TypeError):
    """A source offered an item its catalogue rejects."""


class UnknownCatalogueEntryError(KeyError):
    """A caller asked for a name no source offered."""

    def __str__(self) -> str:
        # KeyError's repr quotes its argument, which mangles a message that
        # lists the available names.
        return self.args[0] if self.args else ""


@runtime_checkable
class CatalogueSource(Protocol[T]):
    """One way of obtaining named items of type ``T``."""

    def describe(self) -> str:
        """Identify this source in composition errors.

        The description is the only handle an operator has on where an item
        came from, so it must distinguish two instances of the same source
        type.
        """

    def load(self) -> Mapping[str, T]:
        """Return the items this source offers.

        Raises on failure rather than returning a partial mapping: a provider
        that offers an item it cannot supply is broken, and silently narrowing
        the offer hides that.
        """


#: Raises when ``item`` is not well formed for its catalogue. Receives the name
#: and the offered item; the caller adds source attribution.
#:
#: Typed against ``object`` rather than ``T`` because a validator's job is to
#: establish that an unvalidated value *is* a ``T``; it cannot presuppose it.
ItemValidator = Callable[[str, object], None]


def require_callable_item(name: str, item: object) -> None:
    """Reject an item that is not callable. The common case."""
    if not callable(item):
        raise CatalogueItemTypeError(
            f"{name!r} is {type(item).__name__}, which is not callable"
        )


@dataclass(frozen=True)
class Catalogue(Mapping[str, T]):
    """Every item available to one composed role.

    Construct through :class:`CatalogueBuilder`; the validation that makes this
    value trustworthy happens there.
    """

    kind: str
    _by_name: Mapping[str, T]
    _provenance: Mapping[str, str]

    def __getitem__(self, name: str) -> T:
        try:
            return self._by_name[name]
        except KeyError:
            raise self._unknown(name) from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._by_name)

    def __len__(self) -> int:
        return len(self._by_name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_name))

    def provenance(self, name: str) -> str:
        """Describe the source that offered ``name``."""
        try:
            return self._provenance[name]
        except KeyError:
            raise self._unknown(name) from None

    def resolve(self, names: Sequence[str]) -> list[T]:
        """Resolve names to items, in the order given."""
        missing = [name for name in names if name not in self._by_name]
        if missing:
            raise self._unknown(*missing)
        return [self._by_name[name] for name in names]

    def _unknown(self, *missing: str) -> UnknownCatalogueEntryError:
        offered = ", ".join(self.names()) or "(none)"
        return UnknownCatalogueEntryError(
            f"unknown {self.kind}: {', '.join(sorted(missing))}. "
            f"Offered by the composed catalogue: {offered}."
        )


@dataclass
class CatalogueBuilder(Generic[T]):
    """Accumulates sources, then loads and validates them once.

    ``kind`` names what is being catalogued, so errors read in the caller's
    vocabulary. ``validate`` decides what a well-formed item is; both are
    supplied by the factory that builds this builder rather than hardcoded
    here, because validation is the part most likely to differ per catalogue.

    The builder is mutable and single-use; the catalogue it produces is not.
    """

    kind: str
    validate: ItemValidator | None = None
    _loaders: list[CatalogueSource[T]] = field(default_factory=list)

    def add_loader(self, loader: CatalogueSource[T]) -> CatalogueBuilder[T]:
        """Declare a source. Nothing is loaded until :meth:`build`."""
        self._loaders.append(loader)
        return self

    def add_loaders(self, loaders: Sequence[CatalogueSource[T]]) -> CatalogueBuilder[T]:
        for loader in loaders:
            self.add_loader(loader)
        return self

    def build(self) -> Catalogue[T]:
        """Load every declared source and return the frozen catalogue."""
        merged: dict[str, T] = {}
        provenance: dict[str, str] = {}

        for loader in self._loaders:
            described = loader.describe()
            try:
                offered = loader.load()
            except Exception as exc:
                raise CatalogueSourceError(
                    f"{self.kind} source {described} failed to load: {exc}"
                ) from exc

            for name, item in offered.items():
                if self.validate is not None:
                    try:
                        self.validate(name, item)
                    except CatalogueItemTypeError as exc:
                        raise CatalogueItemTypeError(
                            f"{self.kind} source {described} offered {exc}"
                        ) from exc
                if name in merged:
                    raise CatalogueConflictError(
                        f"{self.kind} {name!r} is offered by both "
                        f"{provenance[name]} and {described}. Compose one of "
                        "them out; a name resolves to exactly one item."
                    )
                merged[name] = item
                provenance[name] = described

        return Catalogue(
            kind=self.kind,
            _by_name=MappingProxyType(merged),
            _provenance=MappingProxyType(provenance),
        )
