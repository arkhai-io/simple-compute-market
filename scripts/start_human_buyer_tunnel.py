#!/usr/bin/env python3
"""Open or verify the local IAP tunnel used by the human buyer sandbox."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import urllib.request


DEFAULT_PROJECT = "sms-canary-20260320-011902"
DEFAULT_ZONE = "us-east4-c"
DEFAULT_INSTANCE = "sms-seller"

FORWARDS: tuple[tuple[str, str, str], ...] = (
    ("registry", "28080:10.243.0.219:18080", "/health"),
    ("provisioning", "28081:10.243.0.115:8081", "/health"),
    ("buyer_agent_card", "28001:10.243.0.117:8000", "/.well-known/agent-card.json"),
    ("seller_agent_card", "28002:10.243.0.68:8000", "/.well-known/agent-card.json"),
)


def build_tunnel_command(*, project: str, zone: str, instance: str) -> list[str]:
    command = [
        "gcloud",
        "compute",
        "ssh",
        instance,
        "--project",
        project,
        "--zone",
        zone,
        "--tunnel-through-iap",
        "--",
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
    ]
    for _, spec, _ in FORWARDS:
        command.extend(["-L", spec])
    return command


def _fetch_status(url: str, timeout: float) -> int:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return int(response.status)


def check_tunnel_health(*, timeout: float = 5.0) -> dict[str, int]:
    statuses: dict[str, int] = {}
    for name, spec, path in FORWARDS:
        local_port = spec.split(":", 1)[0]
        statuses[name] = _fetch_status(f"http://127.0.0.1:{local_port}{path}", timeout)
    return statuses


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Print, open, or verify the local gcloud IAP tunnel used by the human "
            "buyer sandbox."
        )
    )
    parser.add_argument("mode", choices=("command", "open", "check"))
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--zone", default=DEFAULT_ZONE)
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.mode == "command":
        print(shlex.join(build_tunnel_command(project=args.project, zone=args.zone, instance=args.instance)))
        return 0

    if args.mode == "open":
        command = build_tunnel_command(project=args.project, zone=args.zone, instance=args.instance)
        os.execvp(command[0], command)

    statuses = check_tunnel_health(timeout=args.timeout)
    print(json.dumps(statuses, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
