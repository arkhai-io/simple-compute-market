"""A loop controller whose loops start held, for tests that step them.

A bare-metal storefront's publication and site-projection timers run their first
cycle as soon as the app starts them. A test that steps those loops itself, or
whose runtime is configured with a registry it does not serve, composes its
runtime with this controller, so every timer starts held and runs nothing, as a
scenario holds a deployed storefront's loops before stepping them. A step runs
while held; resuming lets the timers run.
"""

from __future__ import annotations

from typing import Any

from market_storefront_kit import StorefrontLoopController

from arkhai_bare_metal_storefront.lifecycle_steps import bare_metal_loop_controller


def held_loop_controller(**options: Any) -> StorefrontLoopController:
    """The storefront's own loop controller, its pause already requested."""
    controller = bare_metal_loop_controller(**options)
    controller.request_pause(True)
    return controller
