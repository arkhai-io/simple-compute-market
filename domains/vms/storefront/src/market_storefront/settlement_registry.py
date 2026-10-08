"""The settlement mechanisms the VM storefront installs.

One registry for the runtime composition and for configuration commands, so a
command validating a role file cannot drift from what the storefront runs. It
imports only the mechanism kits: configuration commands must not initialize
the process-global storefront settings.
"""

from __future__ import annotations

from market_alkahest import create_alkahest_registration
from market_arkhai_payments import create_arkhai_payments_registration
from market_contact_exchange import create_contact_exchange_registration
from market_settlement_runtime import SettlementConfigurationRegistry


def build_storefront_settlement_registry() -> SettlementConfigurationRegistry:
    return SettlementConfigurationRegistry(
        (
            create_alkahest_registration(),
            create_arkhai_payments_registration(),
            create_contact_exchange_registration(),
        )
    )


def installed_settlement_mechanisms() -> dict[str, str]:
    """Each installed mechanism's identifier and its `[Settlement]` key."""
    return {
        registration.mechanism_id: registration.config_key
        for registration in build_storefront_settlement_registry().registrations
    }
