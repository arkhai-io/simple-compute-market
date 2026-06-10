"""Buyer schema-plugin contract and entry-point discovery.

The buyer executable is core-owned: one ``market`` binary, many registry
schemas. A registry/schema maintainer ships a package that exposes a
:class:`BuyerSchemaPlugin` through the ``market.buyer_plugins`` entry-point
group; the core CLI discovers it at startup and lets it register its
commands (named filter flags, rendering, negotiation/settlement UX) onto
the shared verb skeleton.

The dependency direction is inverted on purpose: core discovers plugins
by contract and never imports ``domains.*``. Without any plugin installed
the binary offers only generic ``--filter`` passthrough and raw listing
output — never a concrete buy experience.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Callable, Iterable

#: Entry-point group a schema package publishes its plugin under, e.g.::
#:
#:     [project.entry-points."market.buyer_plugins"]
#:     vms = "domains.vms.buyer.cli:plugin"
PLUGIN_GROUP = "market.buyer_plugins"


@dataclass(frozen=True)
class BuyerSchemaPlugin:
    """One registry schema's buyer-side CLI contribution.

    ``register`` receives the core Typer app and adds the schema's
    commands/sub-apps to it. Command names a plugin registers take
    precedence over the core generic fallbacks (the fallback for a verb
    is only installed when no plugin claimed that verb).
    """

    schema_id: str
    register: Callable[[Any], None]
    #: Distribution name to report a version for under ``--version``
    #: (e.g. ``"market-buyer"``). None means "don't try".
    distribution: str | None = None


@dataclass(frozen=True)
class LoadedPlugin:
    """A discovered plugin plus where it came from."""

    plugin: BuyerSchemaPlugin
    entry_point_name: str = ""
    load_errors: list[str] = field(default_factory=list)


def _iter_entry_points() -> Iterable[Any]:
    return entry_points(group=PLUGIN_GROUP)


def discover_plugins() -> list[BuyerSchemaPlugin]:
    """Load every installed buyer schema plugin.

    A plugin that fails to import or exposes the wrong type is skipped
    with a warning on stderr rather than breaking the whole CLI — one
    broken schema package must not take down ``market`` for the others.
    """
    plugins: list[BuyerSchemaPlugin] = []
    for ep in _iter_entry_points():
        try:
            loaded = ep.load()
        except Exception as exc:  # noqa: BLE001 — isolate broken plugins
            print(
                f"[market] skipping buyer plugin {ep.name!r}: failed to load ({exc})",
                file=sys.stderr,
            )
            continue
        if not isinstance(loaded, BuyerSchemaPlugin):
            print(
                f"[market] skipping buyer plugin {ep.name!r}: entry point must "
                f"resolve to a BuyerSchemaPlugin, got {type(loaded).__name__}",
                file=sys.stderr,
            )
            continue
        plugins.append(loaded)
    return plugins
