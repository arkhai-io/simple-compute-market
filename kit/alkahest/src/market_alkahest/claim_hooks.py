"""Alkahest mechanism hooks for the deal-servicing engine.

The claims engine (``core_storefront.settlement_lifecycle``) is
mechanism-generic; this module is the ``alkahest.v1`` implementation of
its hook contract, shared by every domain that collects scalar escrows:

* ``check_conditions`` classifies the escrow's arbiter tree (via the
  kit's arbiter-codec registry) and reports whether collection would
  pass: RecipientArbiter conditions are ready as soon as a fulfillment
  exists; TrustedOracleArbiter conditions get an arbitration request
  (once — recorded in the claim's ``mechanism_state``) and then poll
  for ``ArbitrationMade``; AllArbiter recurses over its children.
* ``collect`` runs the kit's codec-dispatched collection.

What the hooks read from the claim: ``claim_ref`` (the escrow uid),
``fulfillment_ref`` (the fulfillment uid), and the obligation's
``params`` (``chain_name``, ``escrow_contract``,
``obligation_data.arbiter`` / ``obligation_data.demand``). Claims whose
obligation carries no arbiter (legacy deals predating the plan carrier)
are treated as ready and collected by trying — a revert just means the
engine retries later.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _demand_bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        s = value[2:] if value.startswith("0x") else value
        try:
            return bytes.fromhex(s)
        except ValueError:
            return None
    return None


class AlkahestClaimHooks:
    """``MechanismHooks`` for ``alkahest.v1`` obligations.

    ``get_client`` resolves a chain name to a connected AlkahestClient
    (or ``None`` when the storefront has no client for that chain — the
    hooks then raise, which the engine turns into backoff, never silent
    success).
    """

    def __init__(
        self,
        *,
        get_client: Callable[[str | None], Any],
        chain_config_paths: dict[str, str | None] | None = None,
        default_chain: str | None = None,
        arbitration_probe_timeout: float = 5.0,
    ) -> None:
        self._get_client = get_client
        self._config_paths = dict(chain_config_paths or {})
        self._default_chain = default_chain
        self._probe_timeout = arbitration_probe_timeout

    # -- hook contract ---------------------------------------------------

    async def check_conditions(self, claim: Any) -> str:
        params = (claim.obligation or {}).get("params") or {}
        obligation_data = params.get("obligation_data") or {}
        arbiter = obligation_data.get("arbiter")
        if not arbiter:
            # Pre-plan deal: no stored demand tree. Today's deals are
            # RecipientArbiter-gated, whose condition is satisfied by the
            # fulfillment itself — collect-by-trying covers the rest.
            return "ready"
        chain = self._chain_of(claim)
        demand = _demand_bytes(obligation_data.get("demand"))
        return await self._check_arbiter(
            claim,
            chain=chain,
            arbiter=arbiter,
            demand=demand,
        )

    async def collect(self, claim: Any) -> dict[str, Any]:
        from market_alkahest.claims import collect_escrow_with_codec

        chain = self._chain_of(claim)
        client = self._get_client(chain)
        if client is None:
            raise RuntimeError(f"no alkahest client configured for chain {chain!r}")
        if not claim.fulfillment_ref:
            raise RuntimeError("claim has no fulfillment_ref to collect against")
        params = (claim.obligation or {}).get("params") or {}
        escrow_address = params.get("escrow_contract")
        if not escrow_address or set(escrow_address[2:]) <= {"0"}:
            # Placeholder/absent contract address (some flows pin a zero
            # address and resolve the real contract elsewhere): fall back
            # to the dispatcher's try-every-codec scan.
            escrow_address = None
        from market_alkahest.txlock import chain_tx_lock

        async with chain_tx_lock(None):
            codec, receipt = await collect_escrow_with_codec(
                client,
                claim.claim_ref,
                claim.fulfillment_ref,
                chain_name=chain,
                config_path=self._config_paths.get(chain),
                escrow_address=escrow_address,
            )
        return {"escrow_kind": codec.kind, "receipt": str(receipt)}

    # -- classification ----------------------------------------------------

    async def _check_arbiter(
        self,
        claim: Any,
        *,
        chain: str | None,
        arbiter: str,
        demand: bytes | None,
    ) -> str:
        from market_alkahest.alkahest import get_arbiter_codec_for

        codec = get_arbiter_codec_for(
            chain or "",
            arbiter,
            config_path=self._config_paths.get(chain or ""),
        )
        kind = codec.kind

        if kind == "recipient_arbiter":
            return "ready"

        if kind == "trusted_oracle_arbiter":
            if demand is None:
                raise ValueError(
                    "trusted_oracle_arbiter condition without demand bytes"
                )
            return await self._check_trusted_oracle(claim, chain=chain, demand=demand)

        if kind == "all_arbiter":
            if demand is None:
                raise ValueError("all_arbiter condition without demand bytes")
            from market_alkahest.claims import AllArbiterCodec

            tree = AllArbiterCodec().decode_demand_data(demand)
            for child_arbiter, child_demand in zip(
                tree["arbiters"], tree["demands"]
            ):
                status = await self._check_arbiter(
                    claim,
                    chain=chain,
                    arbiter=child_arbiter,
                    demand=child_demand,
                )
                if status != "ready":
                    return status
            return "ready"

        raise ValueError(f"no condition policy for arbiter kind {kind!r}")

    async def _check_trusted_oracle(
        self, claim: Any, *, chain: str | None, demand: bytes
    ) -> str:
        from market_alkahest.claims import (
            TrustedOracleArbiterCodec,
            arbitration_status,
            request_arbitration,
        )

        client = self._get_client(chain)
        if client is None:
            raise RuntimeError(f"no alkahest client configured for chain {chain!r}")
        if not claim.fulfillment_ref:
            raise RuntimeError("trusted-oracle condition without a fulfillment_ref")

        decoded = TrustedOracleArbiterCodec().decode_demand_data(demand)
        oracle = decoded["oracle"]

        requested_for = claim.mechanism_state.get("arbitration_requested_for")
        if requested_for != claim.fulfillment_ref:
            from market_alkahest.txlock import chain_tx_lock

            async with chain_tx_lock(None):
                await request_arbitration(
                    client,
                    fulfillment_uid=claim.fulfillment_ref,
                    oracle=oracle,
                    demand=decoded["data"],
                )
            claim.mechanism_state["arbitration_requested_for"] = claim.fulfillment_ref
            logger.info(
                "[CLAIMS] arbitration requested for %s (oracle=%s)",
                claim.claim_ref, oracle,
            )

        event = await arbitration_status(
            client,
            fulfillment_uid=claim.fulfillment_ref,
            oracle=oracle,
            demand=decoded["data"],
            timeout_seconds=self._probe_timeout,
        )
        if event is None:
            return "pending"
        decision = getattr(event, "decision", None)
        if decision is False:
            # A false arbitration isn't terminal — oracles may re-arbitrate
            # (e.g. once missing heartbeats resume). The expiration grace
            # bounds how long we keep asking.
            return "pending"
        return "ready"

    # -- helpers -----------------------------------------------------------

    def _chain_of(self, claim: Any) -> str | None:
        params = (claim.obligation or {}).get("params") or {}
        return params.get("chain_name") or self._default_chain
