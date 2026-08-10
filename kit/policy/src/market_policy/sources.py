"""General ways of obtaining named catalogue items.

These implementations are domain-neutral and item-neutral: each returns a
mapping of names to whatever the offering provider supplies, and the catalogue
that composes them decides what a well-formed item is.

The directory loader takes the symbol it looks for, because the repository
already uses two different file contracts — negotiation policies expose
``middleware`` and aggregation policies expose ``factory``. Parameterising it
keeps one loader honest about both instead of one loader silently serving the
wrong contract.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Generic, TypeVar, cast

#: The item type these sources yield. Each loader is item-neutral; the catalogue
#: composing them decides what a well-formed item is.
T = TypeVar("T")

logger = logging.getLogger(__name__)

#: Entry-point group through which a distribution may publish middlewares.
NEGOTIATION_MIDDLEWARE_GROUP = "market_policy.negotiation_middlewares"

__all__ = [
    "NEGOTIATION_MIDDLEWARE_GROUP",
    "DirectorySource",
    "EntryPointSource",
    "InlineSource",
    "default_policy_root",
]


def default_policy_root(leaf: str) -> Path:
    """The conventional operator policy directory for ``leaf``.

    Returned rather than consulted: a role decides whether to authorize a
    directory source at all, and this only says where the convention points.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "arkhai" / leaf


@dataclass(frozen=True)
class InlineSource(Generic[T]):
    """Items known when the offering package was built."""

    items: Mapping[str, T]
    label: str = "inline"

    def describe(self) -> str:
        return f"{self.label}({len(self.items)} items)"

    def load(self) -> Mapping[str, T]:
        return dict(self.items)


@dataclass(frozen=True)
class EntryPointSource(Generic[T]):
    """Items published by installed distributions.

    An entry point resolves to an arbitrary object, so the declared item type is
    a claim the composing catalogue's validator is responsible for checking.
    """

    group: str

    def describe(self) -> str:
        return f"entry-points({self.group})"

    def load(self) -> Mapping[str, T]:
        loaded: dict[str, T] = {}
        for entry_point in entry_points(group=self.group):
            # Deliberately unguarded. A distribution that declares an item and
            # cannot supply it is an incomplete install, and continuing past it
            # reports a missing item instead of a broken package.
            loaded[entry_point.name] = cast("T", entry_point.load())
        return loaded


@dataclass(frozen=True)
class DirectorySource(Generic[T]):
    """Items loaded from operator-supplied directories.

    Each immediate subdirectory of a root may contain ``policy.py`` exposing
    ``symbol``; the subdirectory name becomes the item name. Directories
    starting with ``.`` or ``_`` are skipped.

    A root that does not exist is skipped rather than failing, because a root
    is operator configuration that may legitimately be absent. A root that
    exists but whose module cannot be loaded fails: the operator asked for it.
    """

    roots: tuple[Path, ...]
    symbol: str
    label: str = "directories"

    @classmethod
    def from_paths(
        cls, paths: Iterable[str | Path], *, symbol: str, label: str = "directories"
    ) -> DirectorySource[T]:
        return cls(tuple(Path(path) for path in paths), symbol=symbol, label=label)

    def describe(self) -> str:
        roots = ", ".join(str(root) for root in self.roots) or "(no roots)"
        return f"{self.label}({roots}; symbol={self.symbol})"

    def load(self) -> Mapping[str, T]:
        loaded: dict[str, T] = {}
        for root in self.roots:
            if not root.is_dir():
                logger.debug("[policy] skipping absent policy root %s", root)
                continue
            for entry in sorted(root.iterdir()):
                if not entry.is_dir() or entry.name.startswith((".", "_")):
                    continue
                item = self._load_folder(entry)
                if item is not None:
                    loaded[entry.name] = item
        return loaded

    def _load_folder(self, folder: Path) -> T | None:
        policy_file = folder / "policy.py"
        if not policy_file.is_file():
            return None
        spec = importlib.util.spec_from_file_location(
            f"arkhai_file_policy_{folder.name}", policy_file
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load policy module at {policy_file}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        item = getattr(module, self.symbol, None)
        if item is None:
            raise AttributeError(f"{policy_file} defines no {self.symbol!r} symbol")
        return cast("T", item)
