"""Settings the storefront no longer reads, and what an operator states instead.

One catalogue serves every place a retired key is refused: the generated values
schema refuses each in an agent's `config`, in any spelling, and `market-storefront
config set` refuses to write one. A renamed or removed setting also refuses
startup: running at a default the operator did not choose, or with a switch the
storefront no longer honours, would change behaviour silently. The retired
inventory settings do not refuse startup, because no setting replaces them;
their inventory is declared at provisioning.

This module reads no configuration and imports nothing heavier than the standard
library, so the command line can consult it without loading the storefront.
"""

from __future__ import annotations

from collections.abc import Mapping

_INVENTORY_UPGRADE_GUIDE = 'docs/seller-quickstart.md, "Upgrading from CSV inventory"'

#: Physical inventory, the pricing templates its rows referred to, and the switch
#: that read listings from it: declared at provisioning now, so no setting
#: replaces them and no command migrates them.
RETIRED_INVENTORY_SETTINGS: tuple[str, ...] = (
    "resources_csv_path",
    "resources_csv_inline",
    "escrow_templates",
    "capacity.use_site_projection_for_listings",
)

#: Settings the storefront has renamed, each to the key that replaced it.
RENAMED_SETTINGS: Mapping[str, str] = {
    "claims_sweep_interval": "settlement_servicing_interval_seconds",
}

_NO_PROVISIONING_WAIT = (
    "the storefront starts without waiting for its provisioning service; a site "
    "it cannot reach is reported in system status, and each call to it is retried"
)

#: Settings the storefront has removed, each with why nothing replaces it.
REMOVED_SETTINGS: Mapping[str, str] = {
    "enable_registry_discovery": (
        "the storefront always publishes to every [registry].urls entry, and one "
        "that cannot publish refuses to start"
    ),
    "provisioning.identity": (
        "every site's responses are verified against the principals of the "
        "[Identity.service_peers] entry bound to that site, which rotate through "
        "the storefront's identity routes"
    ),
    "provisioning.fail_on_unreachable": _NO_PROVISIONING_WAIT,
    "provisioning.preflight_timeout": _NO_PROVISIONING_WAIT,
}

#: Every retired key, as a dotted path.
RETIRED_KEYS: tuple[str, ...] = (
    *RETIRED_INVENTORY_SETTINGS,
    *RENAMED_SETTINGS,
    *REMOVED_SETTINGS,
)


def retired_setting(key: str) -> str | None:
    """The retired key ``key`` names or lies under, in any spelling, if any."""

    normalized = key.strip().lower()
    for retired in RETIRED_KEYS:
        if normalized == retired or normalized.startswith(f"{retired}."):
            return retired
    return None


def retired_setting_explanation(retired: str) -> str:
    """Why ``retired`` is refused, naming what replaces it where anything does."""

    if retired in RENAMED_SETTINGS:
        replacement = RENAMED_SETTINGS[retired]
        return f"{retired} was renamed {replacement}; state {replacement} instead"
    if retired in REMOVED_SETTINGS:
        return f"{retired} was removed: {REMOVED_SETTINGS[retired]}"
    if retired in RETIRED_INVENTORY_SETTINGS:
        return (
            f"{retired} was removed: the storefront reads inventory only from its "
            f"sites' provisioning services. See {_INVENTORY_UPGRADE_GUIDE}."
        )
    raise KeyError(retired)


__all__ = [
    "REMOVED_SETTINGS",
    "RENAMED_SETTINGS",
    "RETIRED_INVENTORY_SETTINGS",
    "RETIRED_KEYS",
    "retired_setting",
    "retired_setting_explanation",
]
