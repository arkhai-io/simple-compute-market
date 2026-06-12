"""Buyer-side policy objects: the interface to concrete escrow parameters.

A negotiation *middleware* (negotiation_middleware.py) is just the
per-round decision function. A buyer **policy** is the whole interface
to a deal's concrete escrow parameters
(design-negotiation-policy-surface.md): it declares which escrow
formats it can negotiate, which middleware chain runs the rounds, what
CLI parameters exist (and whether they are transparent like
``--max-price`` or opaque like ``--budget``), and how raw parameter
values plus a listing become the chain's numeric inputs.

This module owns only the protocol and the registry — concrete policy
objects are registered by domain packages (the VM domain registers
``listed_price`` and ``bisection``), exactly like middlewares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


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

    ``middlewares`` is the terminal chain (the loader prepends the
    pinned-shape guard). ``compatible`` judges one listing
    ``accepted_escrows`` entry — tuple selection offers the policy only
    formats it claims. ``derive_prices`` turns raw CLI parameter values
    plus the candidate listings into the per-hour (initial, max) pair
    in base units, or ``(None, None)`` when underivable; policies with
    no scalar notion may leave it None.
    """

    name: str
    middlewares: tuple[str, ...]
    cli_params: tuple[PolicyParam, ...] = ()
    compatible: Callable[[dict[str, Any]], bool] = field(
        default=lambda entry: True,
    )
    derive_prices: Optional[
        Callable[..., tuple[Optional[int], Optional[int]]]
    ] = None


_REGISTRY: dict[str, BuyerPolicy] = {}

DEFAULT_BUYER_POLICY = "listed_price"


def register_buyer_policy(policy: BuyerPolicy) -> BuyerPolicy:
    """Register a policy under its name (last registration wins)."""
    _REGISTRY[policy.name] = policy
    return policy


def get_buyer_policy(name: str) -> BuyerPolicy:
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "<none registered>"
        raise KeyError(
            f"Unknown buyer policy {name!r}. Registered: {known}. "
            f"Policies register on domain-package import — is the "
            f"domain plugin installed?"
        ) from None


def buyer_policy_names() -> list[str]:
    return sorted(_REGISTRY)
