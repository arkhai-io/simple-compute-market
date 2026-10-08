"""Reusable composition and lifecycle mechanisms for storefront roles."""

from .alkahest_clients import (
    AlkahestChain,
    AlkahestClientPolicy,
    build_alkahest_clients,
)
from .composition import (
    StorefrontComposition,
    StorefrontContainer,
    StorefrontRouteHooks,
    StorefrontServiceHooks,
    build_composed_storefront_app,
    build_storefront_lifespan,
    get_storefront_container,
)
from .lifecycle import (
    HELD_POLL_SECONDS,
    LoopNotFound,
    LoopStep,
    PreviewNotOffered,
    QUIESCENCE_TIMEOUT_SECONDS,
    StorefrontLoopController,
)
from .deal_control_routes import (
    DealControlRouteError,
    NegotiationControlRouteService,
    StageEventRouteService,
    opening_proposal,
)
from .lifecycle_routes import LifecycleRouteError, StorefrontLifecycleRouteService
from .trading_pause import TradingPause, TradingPauseRouteService
from .negotiation_watchdog import (
    NegotiationRepository,
    NegotiationWatchdogPolicy,
    parse_timestamp,
    run_negotiation_watchdog,
    stale_negotiations,
    sweep_stale_negotiations,
)

__all__ = [
    "DealControlRouteError",
    "NegotiationControlRouteService",
    "StageEventRouteService",
    "opening_proposal",
    "AlkahestChain",
    "AlkahestClientPolicy",
    "HELD_POLL_SECONDS",
    "LifecycleRouteError",
    "LoopNotFound",
    "LoopStep",
    "PreviewNotOffered",
    "QUIESCENCE_TIMEOUT_SECONDS",
    "StorefrontLifecycleRouteService",
    "StorefrontLoopController",
    "NegotiationRepository",
    "NegotiationWatchdogPolicy",
    "StorefrontComposition",
    "StorefrontContainer",
    "StorefrontRouteHooks",
    "StorefrontServiceHooks",
    "TradingPause",
    "TradingPauseRouteService",
    "build_alkahest_clients",
    "build_composed_storefront_app",
    "build_storefront_lifespan",
    "get_storefront_container",
    "parse_timestamp",
    "run_negotiation_watchdog",
    "stale_negotiations",
    "sweep_stale_negotiations",
]
