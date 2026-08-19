"""Hand each event to a local program on its standard input.

The general escape hatch, and so the one with the sharpest constraints: an
explicit argument list, no shell, the event on standard input, and never any
event content interpolated into an argument. What it runs is what the operator
configured -- the same trust boundary their shell profile occupies.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from typing import Any

from ..events import DeliveryEvent
from ..sinks import DeliveryError, DeliverySink, SinkSettings


class CommandSinkSettings(SinkSettings):
    argv: tuple[str, ...]
    send: str = "json"

    def normalized_argv(self) -> list[str]:
        if not self.argv:
            raise ValueError("command sink requires a non-empty argv")
        return [str(part) for part in self.argv]


def build_command_sink(settings: Mapping[str, Any]) -> DeliverySink:
    """Configure the run-a-program sink."""

    config = CommandSinkSettings.model_validate(dict(settings))
    if config.send not in {"json", "text"}:
        raise ValueError("command sink send must be 'json' or 'text'")
    argv = config.normalized_argv()
    timeout = config.timeout_seconds

    def deliver_to_command(event: DeliveryEvent) -> None:
        if config.send == "text":
            payload = event.rendered
        else:
            payload = json.dumps(event.payload(), ensure_ascii=False, sort_keys=True)
        try:
            completed = subprocess.run(  # noqa: S603 - argv-only, never a shell
                argv,
                input=payload.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise DeliveryError("the configured program was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise DeliveryError("the configured program timed out") from exc
        except OSError as exc:
            raise DeliveryError(
                f"the configured program could not be run ({exc.strerror})"
            ) from exc
        if completed.returncode != 0:
            raise DeliveryError(
                f"the configured program exited with status {completed.returncode}"
            )

    return deliver_to_command


__all__ = ["CommandSinkSettings", "build_command_sink"]
