"""Buyer-side policy objects: the interface to concrete escrow parameters.

A negotiation *middleware* (negotiation_middleware.py) is just the
per-round decision function. A buyer **policy** is the whole interface
to a deal's concrete escrow parameters
(ARCHITECTURE.md, "Buyer negotiation policy surface"): it declares which escrow
formats it can negotiate, which middleware chain runs the rounds, what
CLI parameters exist (and whether they are transparent like
``--max-price`` or opaque like ``--budget``), and how raw parameter
values plus a listing become the chain's numeric inputs.

This module owns only the protocol and the registry — concrete policy
objects are registered by domain packages (the VM domain registers
``listed_price`` and ``bisection``), exactly like middlewares.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from market_policy.catalogue import CatalogueBuilder, CatalogueItemTypeError


@dataclass(frozen=True)
class PolicyParam:
    """One CLI parameter a policy contributes to ``buy``/``negotiate``.

    ``name`` is the python identifier (``initial_price``); the flag is
    derived (``--initial-price``) unless ``flag`` overrides it. The CLI
    layer materializes these as typer options at app-assembly time and
    hands the collected values back to the policy's ``derive_prices``.
    """

    name: str
    annotation: Any = Optional[float]
    default: Any = None
    help: str = ""
    flag: str | None = None

    @property
    def cli_flag(self) -> str:
        return self.flag or "--" + self.name.replace("_", "-")


@dataclass(frozen=True)
class BuyerPolicy:
    """A named buyer negotiation policy.

    ``middlewares`` is the rest of the chain after the pinned-shape
    guard the loader prepends. ``compatible`` judges one listing
    ``accepted_escrows`` entry — tuple selection offers the policy only
    formats it claims. ``derive_prices`` turns raw CLI parameter values
    plus the candidate listings into the per-hour (initial, max) pair
    in base units, or ``(None, None)`` when underivable or declined;
    policies with no scalar notion may leave it None. It receives the
    caller's canonical interactivity disposition as ``interactive=``
    (core computes it from --yes + TTY; a policy never re-derives it
    from the environment) and may prompt only when it is True.
    """

    name: str
    middlewares: tuple[str, ...]
    cli_params: tuple[PolicyParam, ...] = ()
    compatible: Callable[[dict[str, Any]], bool] = field(
        default=lambda entry: True,
    )
    derive_prices: Callable[..., tuple[int | None, int | None]] | None = None


DEFAULT_BUYER_POLICY = "listed_price"

#: Names a buyer policy catalogue in errors.
BUYER_POLICY_KIND = "buyer policy"


def require_buyer_policy(name: str, item: object) -> None:
    """Reject an offering that is not a :class:`BuyerPolicy`."""
    if not isinstance(item, BuyerPolicy):
        raise CatalogueItemTypeError(
            f"{name!r} is {type(item).__name__}, not a BuyerPolicy"
        )


def buyer_policy_catalogue_builder() -> CatalogueBuilder[BuyerPolicy]:
    """A builder that validates buyer policies and names them in errors.

    Replaces a module-level registry whose registration was last-write-wins and
    whose lookup failure told the reader to check whether a domain plugin was
    installed — a domain reference inside the generic policy layer, and a guess
    at the cause. A composed catalogue names what it was composed with.
    """
    return CatalogueBuilder[BuyerPolicy](
        kind=BUYER_POLICY_KIND, validate=require_buyer_policy
    )


def inject_policy_cli_params(fn: Any, policy: BuyerPolicy) -> Any:
    """Materialize the policy's parameters as CLI flags on a verb.

    Replaces ``fn.__signature__`` so the CLI framework (typer inspects
    signatures) surfaces one option per ``PolicyParam`` plus the
    ``--policy-param name=value`` escape hatch; collected values land in
    the function's ``**kwargs``. Parameters whose names the verb already
    defines are skipped — the verb's own definition wins.
    """
    import inspect

    import typer

    sig = inspect.signature(fn)
    params = [
        p
        for p in sig.parameters.values()
        if p.kind is not inspect.Parameter.VAR_KEYWORD
    ]
    taken = {p.name for p in params}
    for pp in policy.cli_params:
        if pp.name in taken:
            continue
        params.append(
            inspect.Parameter(
                pp.name,
                inspect.Parameter.KEYWORD_ONLY,
                default=typer.Option(pp.default, pp.cli_flag, help=pp.help),
                annotation=pp.annotation,
            )
        )
    if "policy_param" not in taken:
        params.append(
            inspect.Parameter(
                "policy_param",
                inspect.Parameter.KEYWORD_ONLY,
                default=typer.Option(
                    None,
                    "--policy-param",
                    "-P",
                    help="Extra negotiation-policy parameter as name=value. "
                    "Repeatable — the escape hatch for policy knobs "
                    "without a named flag; values reach the policy "
                    "chain's context verbatim.",
                ),
                annotation=Optional[list[str]],
            )
        )
    fn.__signature__ = sig.replace(parameters=params)
    return fn
