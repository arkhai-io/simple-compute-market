#!/usr/bin/env python3
"""Validate and optionally enroll a compute host through the checked-in IaC surface."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
IAC_ROOT = ROOT / "compute-provisioning-iac"
DEFAULT_INVENTORY_PATH = IAC_ROOT / "ansible/inventory/hosts"
DEFAULT_ARTIFACTS_DIR = ROOT / "artifacts"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from role_contracts import build_artifact


def parse_kvm_inventory(path: Path) -> dict[str, dict[str, str]]:
    hosts: dict[str, dict[str, str]] = {}
    in_kvm_hosts = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_kvm_hosts = stripped == "[kvm_hosts]"
            continue
        if not in_kvm_hosts:
            continue
        parts = stripped.split()
        alias = parts[0]
        metadata = {"host_alias": alias}
        for token in parts[1:]:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            metadata[key] = value
        hosts[alias] = {
            "host_alias": alias,
            "ansible_host": metadata.get("ansible_host", ""),
            "ansible_user": metadata.get("ansible_user", ""),
            "gpus": metadata.get("gpus", ""),
        }
    return hosts


def build_host_commands(
    *,
    kvm_host: str,
    inventory_path: Path,
    run_acceptance: bool,
    vm_name: str,
    skip_host_kit: bool,
    extra_vars_file: Path | None,
) -> list[list[str]]:
    commands: list[list[str]] = [
        ["make", "validate-inventory"],
        ["make", "validate-playbooks"],
        ["make", "validate-tests"],
    ]
    if run_acceptance:
        acceptance = [
            "./scripts/run_acceptance_validation.sh",
            "--kvm-host",
            kvm_host,
            "--inventory",
            str(inventory_path),
            "--vm-name",
            vm_name,
        ]
        if extra_vars_file is not None:
            acceptance.extend(["--extra-vars-file", str(extra_vars_file)])
        if skip_host_kit:
            acceptance.append("--skip-host-kit")
        commands.append(acceptance)
    return commands


def build_host_artifact(
    *,
    action: str,
    status: str,
    request_url: str,
    auth_url: str,
    host_alias: str,
    details: dict[str, object],
) -> dict[str, object]:
    merged_details = {"host_alias": host_alias, **details}
    return build_artifact(
        role="host",
        action=action,
        status=status,
        request_url=request_url,
        auth_url=auth_url,
        correlation={"vm_target": host_alias},
        details=merged_details,
    )


def _run_command(command: list[str], *, cwd: Path) -> None:
    print(f"[run] ({cwd}) {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def _write_artifact(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def run_host_flow(
    *,
    action: str,
    kvm_host: str,
    inventory_path: Path,
    run_acceptance: bool,
    vm_name: str,
    skip_host_kit: bool,
    extra_vars_file: Path | None,
    artifact_path: Path | None,
) -> dict[str, Any]:
    hosts = parse_kvm_inventory(inventory_path)
    host_details = hosts.get(kvm_host)
    if host_details is None:
        raise SystemExit(f"KVM host {kvm_host!r} was not found in {inventory_path}")

    commands = build_host_commands(
        kvm_host=kvm_host,
        inventory_path=inventory_path,
        run_acceptance=run_acceptance or action == "enroll",
        vm_name=vm_name,
        skip_host_kit=skip_host_kit,
        extra_vars_file=extra_vars_file,
    )
    for command in commands:
        _run_command(command, cwd=IAC_ROOT)

    artifact = build_host_artifact(
        action=action,
        status="succeeded",
        request_url=f"ansible://{kvm_host}",
        auth_url=f"ansible://{kvm_host}",
        host_alias=kvm_host,
        details={
            **host_details,
            "inventory_path": str(inventory_path),
            "run_acceptance": run_acceptance or action == "enroll",
            "vm_name": vm_name,
            "extra_vars_file": str(extra_vars_file) if extra_vars_file is not None else None,
        },
    )
    if artifact_path is not None:
        artifact["artifact_path"] = str(_write_artifact(artifact_path, artifact))
    return artifact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("check-ready", "enroll"):
        subparser = subparsers.add_parser(
            name,
            help=(
                "Run repo-local IaC validation and optionally acceptance validation "
                "for a host."
            ),
        )
        subparser.add_argument("--kvm-host", required=True)
        subparser.add_argument("--inventory-path", type=Path, default=DEFAULT_INVENTORY_PATH)
        subparser.add_argument("--run-acceptance", action="store_true")
        subparser.add_argument("--vm-name", default="iac-acceptance-host")
        subparser.add_argument("--skip-host-kit", action="store_true")
        subparser.add_argument("--extra-vars-file", type=Path)
        subparser.add_argument("--artifact-path", type=Path, default=DEFAULT_ARTIFACTS_DIR / f"host-{name}.json")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_host_flow(
        action=args.command,
        kvm_host=args.kvm_host,
        inventory_path=args.inventory_path.expanduser(),
        run_acceptance=args.run_acceptance,
        vm_name=args.vm_name,
        skip_host_kit=args.skip_host_kit,
        extra_vars_file=args.extra_vars_file.expanduser() if args.extra_vars_file else None,
        artifact_path=args.artifact_path.expanduser() if args.artifact_path else None,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
