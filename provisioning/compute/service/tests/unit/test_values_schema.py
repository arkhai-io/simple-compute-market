"""The provisioning chart's ``[Events]`` definition is the one the service's models give.

A drift test: the definition committed in the chart's values schema must equal
the one generated from ``EventsSettings`` and the settings models of the sinks
the service installs, so a model or a sink changing without
``make helm-values-schema`` fails here.
"""

from __future__ import annotations

from pathlib import Path

from compute_provisioning_service.values_schema import (
    DEFINITION,
    SCHEMA_FILES,
    events_definition,
)
from market_config.values_schema import stale_files

REPOSITORY = Path(__file__).resolve().parents[5]


def test_the_chart_carries_the_generated_events_definition() -> None:
    paths = [REPOSITORY / relative for relative in SCHEMA_FILES]
    assert stale_files(paths, events_definition(), name=DEFINITION) == []
