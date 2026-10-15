"""Generate the Helm values-schema definition for a VM storefront agent's ``config``.

The generator is ``market_config.values_schema``; this module supplies what is
the VM storefront's own: the sections it types, the settlement mechanisms it
registers, the delivery sinks its environment installs, the keys it has
retired, and the schema files it writes.

``[Delivery]`` is typed by the sinks installed here that declare their settings
model, found by discovery; no sink is named in this module, and an instance of
any other sink stays open. The definition is generated in this storefront's
locked environment, so the sinks it types are the sinks this storefront's image
installs.

The definition is written, under :data:`DEFINITION`, into the storefront chart's
schema and into the umbrella's definition of its storefront agents. Run it from
the repository root, or pass that root as ``--root``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from market_config.values_schema import (
    config_definition,
    main as generator_main,
    model_fragment,
    settlement_fragment,
    sink_typed_section,
)
from market_delivery import SINK_KEY, discover_sink_settings_models

from market_storefront.settlement_composition import (
    build_storefront_settlement_registry,
)
from market_storefront.utils.config import (
    IdentityConfigDeclaration,
    RegistryConfigDeclaration,
    WalletConfigDeclaration,
)

DEFINITION = "storefrontServiceConfig"
ROLE = "seller"

#: The schema files carrying the definition, relative to the repository root.
SCHEMA_FILES = (
    "helm/values.schema.json",
    "helm/charts/storefront/values.schema.json",
)

#: Keys the storefront no longer reads, refused in an agent's ``config``.
RETIRED_KEYS: tuple[str, ...] = ()

# ``[Delivery]``'s own settings: one entry per key in the delivery kit's
# ``RESERVED_SECTION_KEYS``.
_DELIVERY_SETTINGS: dict[str, Any] = {
    "enabled": {"type": "array", "items": {"type": "string"}},
    "timeout_seconds": {"type": "number"},
    "origins": {
        "type": "object",
        "additionalProperties": {"type": "array", "items": {"type": "string"}},
    },
}


def storefront_config_definition(role: str = ROLE) -> dict[str, Any]:
    """Return the generated definition for an agent's ``config``."""
    sinks, _warnings = discover_sink_settings_models()
    sections: dict[str, Any] = {
        "delivery": sink_typed_section(
            sinks, sink_key=SINK_KEY, section_fields=_DELIVERY_SETTINGS, role=role
        ),
        "identity": model_fragment(IdentityConfigDeclaration, role=role),
        "registry": model_fragment(RegistryConfigDeclaration, role=role),
        "settlement": settlement_fragment(
            build_storefront_settlement_registry().registrations, role=role
        ),
        "wallet": model_fragment(WalletConfigDeclaration, role=role),
    }
    return config_definition(sections, retired=RETIRED_KEYS)


def main(argv: Sequence[str] | None = None) -> int:
    return generator_main(
        argv,
        build_definition=storefront_config_definition,
        name=DEFINITION,
        schema_files=SCHEMA_FILES,
        description=__doc__.splitlines()[0],
    )


if __name__ == "__main__":
    raise SystemExit(main())
