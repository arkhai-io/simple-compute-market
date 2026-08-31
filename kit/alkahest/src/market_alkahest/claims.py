"""Alkahest conditional-escrow primitives: arbiters and collection.

The settlement-runtime adapter uses this module to drive an Alkahest
obligation from immutable fulfillment to collection:

* ``TrustedOracleArbiter`` supplies an asynchronous condition whose result is
  recorded through ``ArbitrationMade``;
* ``AllArbiter`` recursively composes those conditions with
  ``RecipientArbiter``;
* bounded oracle probes let the shared servicing worker poll without blocking;
* collection dispatches through the same escrow codec registry as reclaim.

This module owns contract calls and codecs. Composition roots own the oracle,
domain evidence, servicing policy, and terminal actions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .alkahest import (
    AgreementContext,
    EscrowKindCodec,
    _arbiter_address,
    get_erc20_splitter,
    get_escrow_codec_for,
    get_native_token_splitter,
    get_trusted_oracle_arbiter,
    register_arbiter_codec,
)
from .alkahest import _ESCROW_KIND_CODECS

logger = logging.getLogger(__name__)


def get_all_arbiter(
    chain_name: str,
    *,
    config_path: str | None = None,
) -> str:
    """Resolve the AllArbiter (conjunction) address for the network."""
    return _arbiter_address(
        chain_name, config_path=config_path, arbiter_field="all_arbiter"
    )


def _demand_bytes(value: Any) -> bytes:
    """Coerce a demand value (bytes | 0x-hex str) to bytes."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        s = value[2:] if value.startswith("0x") else value
        return bytes.fromhex(s)
    raise ValueError(f"demand must be bytes or hex string, got {type(value).__name__}")


class TrustedOracleArbiterCodec:
    """``TrustedOracleArbiter.DemandData = (address oracle, bytes data)``.

    Collection through this arbiter is asynchronous: ``checkObligation``
    returns the named oracle's latest decision for the (obligation, demand)
    key, so the settlement adapter requests arbitration once and then polls
    ``ArbitrationMade`` before collecting.
    """

    kind = "trusted_oracle_arbiter"

    def resolve_address(self, chain_name: str, *, config_path: str | None) -> str:
        return get_trusted_oracle_arbiter(chain_name, config_path=config_path)

    def encode_demand(self, agreement: AgreementContext) -> bytes:
        raise ValueError(
            "trusted_oracle_arbiter demands are not derivable from the "
            "agreement context alone — encode explicit demand_data "
            "{'oracle': <address>, 'data': <bytes|hex>} instead"
        )

    def encode_demand_data(self, demand_data: dict[str, Any]) -> bytes:
        from alkahest_py import TrustedOracleArbiterDemandData

        oracle = demand_data.get("oracle")
        if not oracle:
            raise ValueError("trusted_oracle_arbiter demand_data requires 'oracle'")
        data = _demand_bytes(demand_data.get("data") or b"")
        return bytes(
            TrustedOracleArbiterDemandData(oracle=oracle, data=data).encode_self()
        )

    def decode_demand_data(self, demand: bytes) -> dict[str, Any]:
        from alkahest_py import TrustedOracleArbiterDemandData

        decoded = TrustedOracleArbiterDemandData.decode(_demand_bytes(demand))
        return {"oracle": decoded.oracle, "data": bytes(decoded.data)}


class AllArbiterCodec:
    """``AllArbiter.DemandData = (address[] arbiters, bytes[] demands)``.

    The obligation passes only when every child microcondition passes.
    Children arrive pre-encoded — composing a tree is calling this
    codec with the child codecs' outputs.
    """

    kind = "all_arbiter"

    def resolve_address(self, chain_name: str, *, config_path: str | None) -> str:
        return get_all_arbiter(chain_name, config_path=config_path)

    def encode_demand(self, agreement: AgreementContext) -> bytes:
        raise ValueError(
            "all_arbiter demands are not derivable from the agreement "
            "context alone — encode explicit demand_data "
            "{'arbiters': [addr...], 'demands': [bytes|hex...]} instead"
        )

    def encode_demand_data(self, demand_data: dict[str, Any]) -> bytes:
        from alkahest_py import alkahest_py as _alkahest_ext

        arbiters = list(demand_data.get("arbiters") or [])
        demands = [_demand_bytes(d) for d in (demand_data.get("demands") or [])]
        if len(arbiters) != len(demands):
            raise ValueError(
                f"all_arbiter demand_data length mismatch: "
                f"{len(arbiters)} arbiters vs {len(demands)} demands"
            )
        if not arbiters:
            raise ValueError("all_arbiter demand_data requires at least one child")
        return bytes(_alkahest_ext.AllArbiter.encode(arbiters, demands))

    def decode_demand_data(self, demand: bytes) -> dict[str, Any]:
        from eth_abi import decode as _abi_decode

        (decoded,) = _abi_decode(["(address[],bytes[])"], _demand_bytes(demand))
        arbiters, demands = decoded
        return {
            "arbiters": [str(a) for a in arbiters],
            "demands": [bytes(d) for d in demands],
        }


class _SplitterArbiterCodec:
    """Base codec for ``BaseSplitter.SplitterDemandData``.

    Splitters wrap an escrow and later distribute it according to an
    oracle-provided split. Their demand data is the same shape as
    TrustedOracleArbiter, but the contract interprets a true decision
    as a set of settlement splits rather than an all-or-nothing release.
    """

    kind: str

    def encode_demand(self, agreement: AgreementContext) -> bytes:
        raise ValueError(
            f"{self.kind} demands are not derivable from the agreement "
            "context alone — encode explicit demand_data "
            "{'oracle': <address>, 'data': <bytes|hex>} instead"
        )

    def encode_demand_data(self, demand_data: dict[str, Any]) -> bytes:
        from alkahest_py import alkahest_py as _alkahest_ext

        oracle = demand_data.get("oracle")
        if not oracle:
            raise ValueError(f"{self.kind} demand_data requires 'oracle'")
        data = _demand_bytes(demand_data.get("data") or b"")
        return bytes(
            _alkahest_ext.PySplitterDemandData(oracle=oracle, data=data).encode_self()
        )

    def decode_demand_data(self, demand: bytes) -> dict[str, Any]:
        from alkahest_py import alkahest_py as _alkahest_ext

        decoded = _alkahest_ext.PySplitterDemandData.decode(_demand_bytes(demand))
        return {"oracle": decoded.oracle, "data": bytes(decoded.data)}


class ERC20SplitterArbiterCodec(_SplitterArbiterCodec):
    """ERC20 splitter demand codec."""

    kind = "erc20_splitter"

    def resolve_address(self, chain_name: str, *, config_path: str | None) -> str:
        return get_erc20_splitter(chain_name, config_path=config_path)


class NativeTokenSplitterArbiterCodec(_SplitterArbiterCodec):
    """Native-token splitter demand codec."""

    kind = "native_token_splitter"

    def resolve_address(self, chain_name: str, *, config_path: str | None) -> str:
        return get_native_token_splitter(chain_name, config_path=config_path)


register_arbiter_codec(TrustedOracleArbiterCodec())
register_arbiter_codec(AllArbiterCodec())
register_arbiter_codec(ERC20SplitterArbiterCodec())
register_arbiter_codec(NativeTokenSplitterArbiterCodec())


# ---------------------------------------------------------------------------
# Oracle interaction
# ---------------------------------------------------------------------------


async def request_arbitration(
    client: Any,
    *,
    fulfillment_uid: str,
    oracle: str,
    demand: bytes | str,
) -> Any:
    """Ask ``oracle`` to arbitrate the fulfillment.

    Re-requesting emits another ``ArbitrationRequested`` event, so the adapter
    journals a request marker before polling and the shared runtime persists it.
    """
    return await client.oracle.request_arbitration(
        fulfillment_uid, oracle, _demand_bytes(demand)
    )


async def arbitration_status(
    client: Any,
    *,
    fulfillment_uid: str,
    oracle: str | None = None,
    demand: bytes | str | None = None,
    from_block: int | None = 0,
    timeout_seconds: float = 5.0,
) -> Any | None:
    """Bounded probe for an ``ArbitrationMade`` event.

    Wraps the SDK's ``wait_for_arbitration`` (which scans from
    ``from_block`` and then subscribes) in a timeout so shared servicing can
    poll without blocking its sweep. Returns the event when an arbitration
    exists and ``None`` while no decision has been made.
    """
    try:
        return await asyncio.wait_for(
            client.oracle.wait_for_arbitration(
                fulfillment_uid,
                _demand_bytes(demand) if demand is not None else None,
                oracle,
                from_block,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        return None


async def arbitrate(
    client: Any,
    *,
    obligation_uid: str,
    demand: bytes | str | None,
    decision: bool,
) -> Any:
    """Oracle-side: record a decision for (obligation, demand).

    Kit owns the call shape; *operating* an oracle (what evidence to
    verify before deciding) is domain-side tooling by design.
    """
    return await client.oracle.arbitrate(
        obligation_uid,
        _demand_bytes(demand) if demand is not None else None,
        decision,
    )


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


async def collect_escrow_with_codec(
    client: Any,
    uid: str,
    fulfillment_uid: str,
    *,
    chain_name: str,
    config_path: str | None = None,
    escrow_address: str | None = None,
) -> tuple[EscrowKindCodec, Any]:
    """Run ``collect`` via the matching escrow codec.

    Mirror of ``reclaim_expired_escrow_with_codec``: dispatch by escrow
    address when known, otherwise try every codec resolvable on the
    chain. Reverts surface as exceptions — a collect against an
    unsatisfied condition tree is the engine's signal to keep waiting.
    """
    if escrow_address:
        codec = get_escrow_codec_for(
            chain_name,
            escrow_address,
            config_path=config_path,
        )
        return codec, await codec.collect(client, uid, fulfillment_uid)

    errors: list[str] = []
    for codec in _ESCROW_KIND_CODECS.values():
        try:
            codec.resolve_address(chain_name, config_path=config_path)
        except Exception:
            continue
        try:
            return codec, await codec.collect(client, uid, fulfillment_uid)
        except Exception as exc:
            errors.append(f"{codec.kind}: {exc}")
    raise RuntimeError(
        f"Could not collect escrow {uid!r} with any registered codec on "
        f"chain={chain_name!r}: {'; '.join(errors) or 'no codecs resolvable'}"
    )
