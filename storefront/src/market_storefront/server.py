"""Storefront ASGI application entry point.

Builds the final Starlette app by composing:

1. The existing ``a2a_app`` routes from ``agent.py`` (negotiate, settle,
   listings/create, listings/close, alerts, well-known endpoints).
2. New controller routes (system health, listings API, negotiations API,
   admin controls).
3. ``AdminAuthMiddleware`` — enforces ``X-Admin-Key`` on admin routes.

Global pause state
------------------
``_GLOBALLY_PAUSED`` is the module-level flag read by
``sync_negotiation.start_sync_negotiation``.  It is toggled by
``AdminController`` via the ``set_paused`` / ``get_paused`` callables
passed at construction time.

The flag lives here (not in ``agent.py``) to break the circular import
that would arise if ``sync_negotiation`` imported from ``agent``.
``sync_negotiation`` imports ``is_globally_paused`` from this module.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.routing import Route

from market_storefront.agent import a2a_app, _startup_tasks
from market_storefront.utils.config import CONFIG
from market_storefront.utils.sqlite_client import get_sqlite_client
from market_storefront.middleware.admin_auth import AdminAuthMiddleware
from market_storefront.controllers.system_controller import SystemController
from market_storefront.controllers.admin_controller import AdminController
from market_storefront.controllers.listings_controller import ListingsController
from market_storefront.controllers.negotiations_controller import NegotiationsController

# ---------------------------------------------------------------------------
# Global pause flag — toggled by AdminController, read by sync_negotiation
# ---------------------------------------------------------------------------

_GLOBALLY_PAUSED: bool = False


def is_globally_paused() -> bool:
    """Return the current global pause state.

    Imported by ``sync_negotiation.start_sync_negotiation`` to gate new
    negotiations without a direct dependency on ``agent.py``.
    """
    return _GLOBALLY_PAUSED


def _set_globally_paused(value: bool) -> None:
    global _GLOBALLY_PAUSED
    _GLOBALLY_PAUSED = value


# ---------------------------------------------------------------------------
# Build the combined route list
# ---------------------------------------------------------------------------

def _build_routes() -> list[Route]:
    sqlite_client = get_sqlite_client()

    system_ctrl = SystemController(
        sqlite_client=sqlite_client,
        globally_paused_fn=is_globally_paused,
    )
    admin_ctrl = AdminController(
        sqlite_client=sqlite_client,
        get_paused_fn=is_globally_paused,
        set_paused_fn=_set_globally_paused,
    )
    listings_ctrl = ListingsController(sqlite_client=sqlite_client)
    negotiations_ctrl = NegotiationsController(sqlite_client=sqlite_client)

    routes: list[Route] = []
    routes.extend(system_ctrl.routes())
    routes.extend(admin_ctrl.routes())
    routes.extend(listings_ctrl.routes())
    routes.extend(negotiations_ctrl.routes())
    # Existing agent routes last (includes /negotiate/*, /settle/*, /listings/create…)
    routes.extend(a2a_app.routes)
    return routes


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = Starlette(routes=_build_routes())

# Add admin auth middleware — protects /admin/* and admin-only resource actions.
app.add_middleware(
    AdminAuthMiddleware,
    admin_api_key=CONFIG.admin_api_key,
)


@app.on_event("startup")
async def startup_event() -> None:
    """Start background tasks on server startup."""
    await _startup_tasks()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=CONFIG.port)

