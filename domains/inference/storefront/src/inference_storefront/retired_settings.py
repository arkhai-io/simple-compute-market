"""Settings the storefront does not read, and why nothing replaces them.

A removed setting refuses startup (`startup_refusal`): running with a setting
the storefront does not honour would change its behaviour silently, where a
refusal says what to change.
"""

from __future__ import annotations

from collections.abc import Mapping

from dynaconf import Dynaconf

from inference_storefront.utils.config import settings

RETIRED_SETTINGS_HEADING = "the storefront states retired settings"

_NO_AUTHORITY_WAIT = (
    "the storefront starts without waiting for its inference authority; its "
    "listing seed waits for the authority, and each call to it is retried"
)

#: Settings the storefront has removed, each with why nothing replaces it.
REMOVED_SETTINGS: Mapping[str, str] = {
    "credits.fail_on_unreachable": _NO_AUTHORITY_WAIT,
    "credits.preflight_timeout": _NO_AUTHORITY_WAIT,
}


def retired_setting_problems(source: Dynaconf | None = None) -> list[str]:
    """Name each removed setting the configuration still states, in any spelling."""
    active = settings if source is None else source
    return [
        f"{retired} was removed: {reason}"
        for retired, reason in REMOVED_SETTINGS.items()
        if active.get(retired) is not None
    ]


__all__ = ["REMOVED_SETTINGS", "RETIRED_SETTINGS_HEADING", "retired_setting_problems"]
