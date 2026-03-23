#!/usr/bin/env python3
"""Compatibility wrapper for the canonical local ERC-8004 deploy command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import bootstrap_local_dev  # type: ignore[import-not-found]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    output_path = Path(args.output) if args.output else None
    artifact = bootstrap_local_dev.deploy_local_contracts(
        rpc_url=args.rpc_url,
        output_path=output_path,
    )
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
