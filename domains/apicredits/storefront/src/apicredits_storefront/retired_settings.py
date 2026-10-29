"""Settings the storefront no longer reads, and what an operator states instead.

A renamed or removed setting refuses startup (`startup_refusal`), naming the key
that replaced it or why nothing does: running at a default the operator did not
choose, or with a setting the storefront no longer honours, would change its
behaviour silently, where a refusal says what to change. No values schema is
generated from this storefront's settings, so the refusal at startup is where a
retired key is caught.
"""

from __future__ import annotations

from collections.abc import Mapping

from dynaconf import Dynaconf

from apicredits_storefront.utils.config import retired_address_book_problems, settings

RETIRED_SETTINGS_HEADING = "the storefront states retired settings"

#: Settings the storefront has renamed, each to the key that replaced it.
RENAMED_SETTINGS: Mapping[str, str] = {
    "claims_sweep_interval": "settlement_servicing_interval_seconds",
}

_NO_CREDITS_WAIT = (
    "the storefront starts without waiting for its credits service; its listing "
    "seed waits for the service, and each call to it is retried"
)

#: Settings the storefront has removed, each with why nothing replaces it.
REMOVED_SETTINGS: Mapping[str, str] = {
    "credits.fail_on_unreachable": _NO_CREDITS_WAIT,
    "credits.preflight_timeout": _NO_CREDITS_WAIT,
}


def retired_setting_problems(source: Dynaconf | None = None) -> list[str]:
    """Name each renamed or removed setting the configuration still states, in
    any spelling, with the key that replaced it or why nothing does, the
    retired Alkahest address-book keys among them."""

    active = settings if source is None else source
    return [
        f"{retired} was renamed {replacement}; state {replacement} instead"
        for retired, replacement in RENAMED_SETTINGS.items()
        if active.get(retired) is not None
    ] + [
        f"{retired} was removed: {reason}"
        for retired, reason in REMOVED_SETTINGS.items()
        if active.get(retired) is not None
    ] + retired_address_book_problems(active)


__all__ = [
    "REMOVED_SETTINGS",
    "RENAMED_SETTINGS",
    "RETIRED_SETTINGS_HEADING",
    "retired_setting_problems",
]
