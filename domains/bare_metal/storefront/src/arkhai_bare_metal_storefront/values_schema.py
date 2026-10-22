"""Generate the Helm values-schema definition for the bare-metal storefront's ``config``.

The generator is ``market_config.values_schema``; this module supplies what is
the bare-metal storefront's own: its typed settings, the settlement mechanisms
it registers, the delivery sinks its environment installs, and the one schema
file it writes, its own chart's.

Every setting the storefront reads is typed (:mod:`.config`), so the definition
is closed at every level its models are: a key the storefront does not read is
refused in any spelling, as is every field a model marks secret, such as the
wallet's private key, which belongs in the Secret overlay. The loader itself
ignores such a key, so a misspelling is caught where the configuration is
written, by the chart, and an older release still starts on configuration a
newer one wrote. ``[Settlement]`` is closed to the mechanisms the storefront
registers, and ``[Delivery]`` is typed instance by instance by the sinks
installed here that declare their settings model, found by discovery; an
instance of any other sink stays open.

Run it from the repository root, or pass that root as ``--root``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from market_config.values_schema import (
    accepting_null,
    any_case,
    main as generator_main,
    model_fragment,
    settlement_fragment,
    sink_typed_section,
)
from market_delivery import SINK_KEY, discover_sink_settings_models

from .config import BareMetalStorefrontSettings
from .settlement_composition import build_bare_metal_settlement_registry

DEFINITION = "storefrontServiceConfig"
ROLE = "seller"

#: The schema file carrying the definition, relative to the repository root.
SCHEMA_FILES = ("helm/charts/bare-metal-storefront/values.schema.json",)

# ``[Delivery]``'s own settings: one entry per key in the delivery kit's
# ``RESERVED_SECTION_KEYS``, which the kit states as names only.
DELIVERY_SETTINGS: dict[str, Any] = {
    "enabled": {"type": "array", "items": {"type": "string"}},
    "timeout_seconds": {"type": "number"},
    "origins": {
        "type": "object",
        "additionalProperties": {"type": "array", "items": {"type": "string"}},
    },
}


def storefront_config_definition(role: str = ROLE) -> dict[str, Any]:
    """Return the generated definition for the chart's ``config``.

    The settings model types the whole document; its two open mappings,
    ``[Settlement]`` and ``[Delivery]``, which the settlement and delivery kits
    read, are typed here by what those kits register and discover. It accepts
    ``null`` wherever it accepts a key, since a values file's ``null`` removes the
    key; a key it refuses stays refused.
    """
    definition = model_fragment(BareMetalStorefrontSettings, role=role)
    sinks, _warnings = discover_sink_settings_models()
    fields = definition["patternProperties"]
    fields[any_case("settlement")] = settlement_fragment(
        build_bare_metal_settlement_registry().registrations, role=role
    )
    fields[any_case("delivery")] = sink_typed_section(
        sinks, sink_key=SINK_KEY, section_fields=DELIVERY_SETTINGS, role=role
    )
    return accepting_null(definition)


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
