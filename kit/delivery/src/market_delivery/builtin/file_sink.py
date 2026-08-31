"""Append each event to a local file as one JSON line."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..events import DeliveryEvent
from ..sinks import DeliveryError, DeliverySink, SinkSettings


class FileSinkSettings(SinkSettings):
    path: str


def build_file_sink(settings: Mapping[str, Any]) -> DeliverySink:
    """Configure the append-a-line sink; the path is expanded, not created."""

    config = FileSinkSettings.model_validate(dict(settings))
    target = Path(config.path).expanduser()

    def deliver_to_file(event: DeliveryEvent) -> None:
        line = json.dumps(event.payload(), ensure_ascii=False, sort_keys=True)
        try:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            raise DeliveryError(f"could not append to the configured file ({exc.strerror})") from exc

    return deliver_to_file


__all__ = ["FileSinkSettings", "build_file_sink"]
