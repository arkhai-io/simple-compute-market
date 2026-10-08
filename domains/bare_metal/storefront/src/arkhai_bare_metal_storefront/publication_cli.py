"""One-shot publication command wiring.

The command composes; the publication cycle decides. See
``publication_composition`` for how a cycle is composed from a running
storefront, which the administrator's publication step shares.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from pydantic_core import to_jsonable_python

from .publication import BareMetalPublicationCycle
from .publication_composition import compose_publication_cycle
from .runtime import BareMetalStorefrontRuntime, build_runtime_from_environment


def run_publication_once(
    *,
    runtime: BareMetalStorefrontRuntime | None = None,
    environ: Mapping[str, str] | None = None,
    cycle_factory: Callable[..., BareMetalPublicationCycle] = BareMetalPublicationCycle,
) -> dict[str, Any]:
    """Run one publication pass and report what it did."""
    runtime = runtime or build_runtime_from_environment()
    cycle = compose_publication_cycle(
        runtime, environ=environ, cycle_factory=cycle_factory
    )
    return to_jsonable_python(asyncio.run(cycle.run()))


__all__ = ["run_publication_once"]
