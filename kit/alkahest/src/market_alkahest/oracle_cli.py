"""``alkahest-oracle`` — manual trusted-oracle operations.

The first oracle-gated settlement plans defer to an arbitrary third
party both sides trust, which is assumed to ``arbitrate()`` true at the
end of a lease unless a dispute was raised. This CLI is that oracle's
manual tool (and the test harness's): record a decision for a
fulfillment, or check what has been arbitrated so far.

An automated oracle *service* (arbitrate true at lease end on a timer,
park disputes for a human) is the production follow-up; the on-chain
alternatives — a heartbeat-verifying arbiter contract, or the splitter
contracts with per-interval escrows — are recorded in the lifecycle
design doc as future plan shapes.

stdlib argparse on purpose: the kit ships no CLI framework.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def _build_client(private_key: str, rpc_url: str, chain_name: str, config_path: str | None):
    from alkahest_py import AlkahestClient

    from .alkahest import (
        get_alkahest_network,
        prewarm_alkahest_address_config_cache,
        resolve_alkahest_address_config,
    )

    prewarm_alkahest_address_config_cache(config_path)
    network = get_alkahest_network(chain_name)
    address_config = resolve_alkahest_address_config(network, config_path=config_path)
    return AlkahestClient(
        private_key=private_key,
        rpc_url=rpc_url,
        address_config=address_config,
    )


def _demand_bytes(value: str) -> bytes:
    s = value[2:] if value.startswith("0x") else value
    return bytes.fromhex(s) if s else b""


async def _arbitrate(args: argparse.Namespace) -> int:
    from .claims import arbitrate, arbitration_status

    client = _build_client(
        args.private_key, args.rpc_url, args.chain, args.address_config
    )
    receipt = await arbitrate(
        client,
        obligation_uid=args.fulfillment,
        demand=_demand_bytes(args.demand),
        decision=args.decision == "true",
    )
    print(json.dumps({
        "fulfillment": args.fulfillment,
        "decision": args.decision == "true",
        "receipt": str(receipt),
    }))
    # Read back the resulting ArbitrationMade as confirmation.
    event = await arbitration_status(
        client,
        fulfillment_uid=args.fulfillment,
        demand=_demand_bytes(args.demand),
        timeout_seconds=10.0,
    )
    if event is not None:
        print(json.dumps({"arbitration_made": True,
                          "decision": bool(getattr(event, "decision", True))}))
    return 0


async def _status(args: argparse.Namespace) -> int:
    from .claims import arbitration_status

    client = _build_client(
        args.private_key, args.rpc_url, args.chain, args.address_config
    )
    event = await arbitration_status(
        client,
        fulfillment_uid=args.fulfillment,
        demand=_demand_bytes(args.demand),
        timeout_seconds=args.timeout,
    )
    if event is None:
        print(json.dumps({"arbitration_made": False}))
        return 1
    print(json.dumps({"arbitration_made": True,
                      "decision": bool(getattr(event, "decision", True))}))
    return 0


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--private-key", required=True, help="Oracle wallet private key.")
    p.add_argument("--rpc-url", required=True)
    p.add_argument("--chain", required=True, help="Alkahest chain name (e.g. base_sepolia, anvil).")
    p.add_argument("--address-config", default=None, help="Alkahest address-config path (required for anvil).")
    p.add_argument("--fulfillment", required=True, help="Fulfillment obligation UID.")
    p.add_argument("--demand", default="0x", help="TrustedOracleArbiter demand `data` bytes (hex; default empty).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alkahest-oracle", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    arb = sub.add_parser("arbitrate", help="Record a decision for a fulfillment.")
    _common(arb)
    arb.add_argument("--decision", choices=("true", "false"), required=True)
    arb.set_defaults(func=_arbitrate)

    st = sub.add_parser("status", help="Check whether an arbitration exists.")
    _common(st)
    st.add_argument("--timeout", type=float, default=10.0)
    st.set_defaults(func=_status)

    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
