"""The provisioning chart's values-schema definition of the ``[Events]`` section.

Generated from the service's typed ``EventsSettings`` and the settings models of
the delivery sinks it installs, so the chart's public ``config`` refuses each
secret sink setting — a webhook's URL, an Apprise URL, a mail password — which
belongs in the runtime Secret's overlay, and a sink instance's misspelled
setting, as the service would. ``make helm-values-schema`` writes it; the
service's drift test fails when a model or an installed sink changes without
it.

    python -m compute_provisioning_service.values_schema write --root <repository>
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any

from market_config.values_schema import any_case, main, model_fragment, sink_typed_section
from market_delivery import SINK_KEY, discover_sink_settings_models

from compute_provisioning_service.services.operator_events import EventsSettings

#: The definition's name in the chart's values schema.
DEFINITION = "provisioningEvents"

#: The schema files this service's chart carries, from the repository root.
SCHEMA_FILES = ("helm/charts/provisioning/values.schema.json",)

#: The role a field's ``roles`` annotation would name; no events field has one.
_ROLE = "provisioning"


def events_definition() -> dict[str, Any]:
    """The ``Events`` section, closed, its sink instances typed by their sink."""
    models, _warnings = discover_sink_settings_models()
    definition = model_fragment(EventsSettings, role=_ROLE)
    patterns = dict(definition.get("patternProperties", {}))
    patterns[any_case("sinks")] = sink_typed_section(
        models,
        sink_key=SINK_KEY,
        section_fields={
            "enabled": {"type": "array", "items": {"type": "string"}},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
        },
        role=_ROLE,
    )
    definition["patternProperties"] = patterns
    return definition


def run(argv: Sequence[str] | None = None) -> int:
    return main(
        argv,
        build_definition=events_definition,
        name=DEFINITION,
        schema_files=SCHEMA_FILES,
        description="Write or check the provisioning chart's [Events] definition.",
    )


if __name__ == "__main__":
    sys.exit(run())
