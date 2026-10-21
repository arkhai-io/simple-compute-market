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
    CYCLE_STAGES,
    CycleError,
    CycleOutcome,
    DEFAULT_CYCLE_STAGE,
    HELD_POLL_SECONDS,
    LoopNotFound,
    LoopSnapshot,
    LoopStep,
    PreviewNotOffered,
    QUIESCENCE_TIMEOUT_SECONDS,
    STEP_TRIGGER,
    StorefrontLoopController,
    TIMER_TRIGGER,
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
    "CYCLE_STAGES",
    "CycleError",
    "CycleOutcome",
    "DEFAULT_CYCLE_STAGE",
    "HELD_POLL_SECONDS",
    "LifecycleRouteError",
    "LoopNotFound",
    "LoopSnapshot",
    "LoopStep",
    "PreviewNotOffered",
    "QUIESCENCE_TIMEOUT_SECONDS",
    "STEP_TRIGGER",
    "StorefrontLifecycleRouteService",
    "StorefrontLoopController",
    "TIMER_TRIGGER",
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
