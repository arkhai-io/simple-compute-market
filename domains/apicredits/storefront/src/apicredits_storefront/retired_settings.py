"""Settings the storefront no longer reads, and what an operator states instead.

A renamed setting refuses startup (`startup_refusal`), naming the key that
replaced it: running at a default the operator did not choose would change the
storefront's behaviour silently, where a refusal says what to change. No values
schema is generated from this storefront's settings, so the refusal at startup
is where a renamed key is caught.
"""

from __future__ import annotations

from collections.abc import Mapping

from dynaconf import Dynaconf

from apicredits_storefront.utils.config import settings

RETIRED_SETTINGS_HEADING = "the storefront states retired settings"

#: Settings the storefront has renamed, each to the key that replaced it.
RENAMED_SETTINGS: Mapping[str, str] = {
    "claims_sweep_interval": "settlement_servicing_interval_seconds",
}


def retired_setting_problems(source: Dynaconf | None = None) -> list[str]:
    """Name each renamed setting the configuration still states, in any
    spelling, with the key that replaced it."""

    active = settings if source is None else source
    return [
        f"{retired} was renamed {replacement}; state {replacement} instead"
        for retired, replacement in RENAMED_SETTINGS.items()
        if active.get(retired) is not None
    ]


__all__ = [
    "RENAMED_SETTINGS",
    "RETIRED_SETTINGS_HEADING",
    "retired_setting_problems",
]
