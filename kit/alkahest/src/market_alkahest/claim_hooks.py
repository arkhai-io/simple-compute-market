"""Alkahest implementation of the conditional-escrow runtime port.

The adapter preserves the existing codec-dispatched Alkahest calls while
keeping chain clients and address configuration injected by composition roots.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from market_settlement_runtime.models import (
    ConditionOutcome,
    EffectOutcome,
    MaterializationOutcome,
    StatusOutcome,
)

logger = logging.getLogger(__name__)


def _demand_bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        encoded = value[2:] if value.startswith("0x") else value
        try:
            return bytes.fromhex(encoded)
        except ValueError:
            return None
    return None


def _value(source: Any, name: str, default: Any = None) -> Any:
    return (
        source.get(name, default)
        if isinstance(source, Mapping)
        else getattr(source, name, default)
    )


def _receipt_ref(receipt: Any) -> str | None:
    """Reduce an SDK receipt to an opaque, public-safe reference."""
    if receipt is None:
        return None
    if isinstance(receipt, (str, int)):
        return str(receipt)
    if isinstance(receipt, Mapping):
        for key in ("transaction_hash", "transactionHash", "tx_hash", "hash", "uid"):
            candidate = receipt.get(key)
            if isinstance(candidate, (str, int)):
                return str(candidate)
    try:
        encoded = json.dumps(
            receipt, default=str, separators=(",", ":"), sort_keys=True
        ).encode()
    except (TypeError, ValueError):
        encoded = repr(receipt).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class _ConditionResult:
    decision: Literal["pending", "ready", "failed", "manual_required"]
    receipt_ref: str | None = None
    last_error: str | None = None


class AlkahestConditionalEscrowClient:
    """Concrete ``ConditionalEscrowClient`` backed by Alkahest codecs.

    Trusted-oracle request markers are round-tripped through mechanism state,
    making each stable check operation request once and poll thereafter.
    """

    def __init__(
        self,
        *,
        get_client: Callable[[str | None], Any],
        chain_config_paths: Mapping[str, str | None] | None = None,
        default_chain: str | None = None,
        arbitration_probe_timeout: float = 5.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if arbitration_probe_timeout <= 0:
            raise ValueError("arbitration_probe_timeout must be positive")
        self._get_client = get_client
        self._config_paths = dict(chain_config_paths or {})
        self._default_chain = default_chain
        self._probe_timeout = arbitration_probe_timeout
        self._clock = clock

    async def materialize(
        self, obligation: dict[str, Any], *, operation_ref: str
    ) -> MaterializationOutcome:
        try:
            chain, client, params, escrow_address = self._context(obligation)
            codec = self._escrow_codec(chain, escrow_address)
            obligation_data = params.get("obligation_data")
            if not isinstance(obligation_data, dict):
                raise ValueError("alkahest obligation_data must be an object")
            expiration_unix = int(obligation["expiration_unix"])
        except (KeyError, TypeError, ValueError) as exc:
            return MaterializationOutcome(
                mechanism_ref="",
                status="manual_required",
                mechanism_state=self._state({}, operation_ref),
                last_error=str(exc),
            )
        from market_alkahest.txlock import chain_tx_lock

        async with chain_tx_lock(None):
            mechanism_ref = await codec.create_obligation(
                client, obligation_data, expiration_unix
            )
        return MaterializationOutcome(
            mechanism_ref=mechanism_ref,
            status="ready",
            condition_anchor=mechanism_ref,
            receipt=self._receipt(operation_ref, codec.kind),
            mechanism_state=self._state({}, operation_ref, codec.kind),
        )

    async def get_status(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> StatusOutcome:
        try:
            chain, client, _, escrow_address = self._context(obligation)
            from market_alkahest.alkahest import get_escrow_obligation_with_codec

            codec, decoded = await get_escrow_obligation_with_codec(
                client,
                mechanism_ref,
                chain_name=chain or "",
                config_path=self._config_paths.get(chain or ""),
                escrow_address=escrow_address,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._manual_status(
                mechanism_ref, operation_ref, mechanism_state, str(exc)
            )

        state = self._state(mechanism_state, operation_ref, codec.kind)
        attestation = _value(decoded, "attestation")
        if attestation is None:
            return StatusOutcome(
                status="failed",
                mechanism_ref=mechanism_ref,
                condition_anchor=mechanism_ref,
                receipt=self._receipt(operation_ref, codec.kind),
                mechanism_state=state,
                last_error="alkahest get_obligation returned no attestation",
            )
        uid = _value(attestation, "uid")
        if uid and str(uid).lower() != mechanism_ref.lower():
            return self._manual_status(
                mechanism_ref,
                operation_ref,
                state,
                "alkahest attestation UID does not match the mechanism reference",
                codec.kind,
            )
        try:
            revoked = int(_value(attestation, "revocation_time", 0) or 0)
            expiration = int(_value(attestation, "expiration_time", 0) or 0)
        except (TypeError, ValueError):
            return self._manual_status(
                mechanism_ref,
                operation_ref,
                state,
                "alkahest attestation lifecycle fields are malformed",
                codec.kind,
            )
        if revoked:
            return self._manual_status(
                mechanism_ref,
                operation_ref,
                state,
                "alkahest attestation is revoked; chain state cannot distinguish collection from reclaim without the operation receipt",
                codec.kind,
            )
        if expiration == 0:
            return self._manual_status(
                mechanism_ref,
                operation_ref,
                state,
                "alkahest escrow attestation has no expiration",
                codec.kind,
            )
        return StatusOutcome(
            status="expired" if self._clock() >= expiration else "ready",
            mechanism_ref=mechanism_ref,
            condition_anchor=mechanism_ref,
            receipt=self._receipt(operation_ref, codec.kind),
            mechanism_state=state,
        )

    async def check(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        fulfillment_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> ConditionOutcome:
        del mechanism_ref
        try:
            chain, _, params, _ = self._context(obligation)
            obligation_data = params.get("obligation_data") or {}
            if not isinstance(obligation_data, Mapping):
                raise ValueError("alkahest obligation_data must be an object")
            arbiter = obligation_data.get("arbiter")
            if not arbiter:
                result = _ConditionResult("ready")
                state = self._state(mechanism_state, operation_ref)
            else:
                result, state = await self._check_arbiter(
                    chain,
                    str(arbiter),
                    _demand_bytes(obligation_data.get("demand")),
                    fulfillment_ref,
                    operation_ref,
                    mechanism_state,
                )
        except (KeyError, TypeError, ValueError) as exc:
            return ConditionOutcome(
                decision="manual_required",
                mechanism_state=self._state(mechanism_state, operation_ref),
                last_error=str(exc),
            )
        receipt = {"operation_ref": operation_ref}
        if result.receipt_ref is not None:
            receipt["receipt"] = result.receipt_ref
        return ConditionOutcome(
            decision=result.decision,
            receipt=receipt,
            mechanism_state=state,
            last_error=result.last_error,
        )

    async def collect(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        fulfillment_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> EffectOutcome:
        from market_alkahest.claims import collect_escrow_with_codec
        from market_alkahest.txlock import chain_tx_lock

        chain, client, _, address = self._context(obligation)
        async with chain_tx_lock(None):
            codec, provider_receipt = await collect_escrow_with_codec(
                client,
                mechanism_ref,
                fulfillment_ref,
                chain_name=chain or "",
                config_path=self._config_paths.get(chain or ""),
                escrow_address=address,
            )
        return EffectOutcome(
            receipt=self._receipt(operation_ref, codec.kind, provider_receipt),
            mechanism_state=self._state(mechanism_state, operation_ref, codec.kind),
        )

    async def reclaim_expired(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
        mechanism_options: Mapping[str, Any] | None = None,
    ) -> EffectOutcome:
        # An on-chain reclaim returns the escrow to the address that funded it,
        # which the chain already knows, so no caller input reaches this codec.
        from market_alkahest.alkahest import reclaim_expired_escrow_with_codec
        from market_alkahest.txlock import chain_tx_lock

        chain, client, _, address = self._context(obligation)
        async with chain_tx_lock(None):
            codec, provider_receipt = await reclaim_expired_escrow_with_codec(
                client,
                mechanism_ref,
                chain_name=chain or "",
                config_path=self._config_paths.get(chain or ""),
                escrow_address=address,
            )
        return EffectOutcome(
            receipt=self._receipt(operation_ref, codec.kind, provider_receipt),
            mechanism_state=self._state(mechanism_state, operation_ref, codec.kind),
        )

    async def _check_arbiter(
        self,
        chain: str | None,
        arbiter: str,
        demand: bytes | None,
        fulfillment_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> tuple[_ConditionResult, dict[str, Any]]:
        from market_alkahest.alkahest import get_arbiter_codec_for

        codec = get_arbiter_codec_for(
            chain or "",
            arbiter,
            config_path=self._config_paths.get(chain or ""),
        )
        state = self._state(mechanism_state, operation_ref)
        if codec.kind == "recipient_arbiter":
            return _ConditionResult("ready"), state
        if codec.kind == "trusted_oracle_arbiter":
            if demand is None:
                raise ValueError(
                    "trusted_oracle_arbiter condition without demand bytes"
                )
            return await self._check_trusted_oracle(
                chain, demand, fulfillment_ref, operation_ref, state
            )
        if codec.kind == "all_arbiter":
            if demand is None:
                raise ValueError("all_arbiter condition without demand bytes")
            from market_alkahest.claims import AllArbiterCodec

            tree = AllArbiterCodec().decode_demand_data(demand)
            for child_arbiter, child_demand in zip(tree["arbiters"], tree["demands"]):
                result, state = await self._check_arbiter(
                    chain,
                    child_arbiter,
                    child_demand,
                    fulfillment_ref,
                    operation_ref,
                    state,
                )
                if result.decision != "ready":
                    return result, state
            return _ConditionResult("ready"), state
        return _ConditionResult(
            "manual_required",
            last_error=f"no condition policy for arbiter kind {codec.kind!r}",
        ), state

    async def _check_trusted_oracle(
        self,
        chain: str | None,
        demand: bytes,
        fulfillment_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> tuple[_ConditionResult, dict[str, Any]]:
        from market_alkahest.claims import (
            TrustedOracleArbiterCodec,
            arbitration_status,
            request_arbitration,
        )

        client = self._client(chain)
        decoded = TrustedOracleArbiterCodec().decode_demand_data(demand)
        oracle, oracle_demand = decoded["oracle"], decoded["data"]
        request_key = hashlib.sha256(
            b"\x00".join(
                (fulfillment_ref.encode(), str(oracle).lower().encode(), oracle_demand)
            )
        ).hexdigest()
        state = self._state(mechanism_state, operation_ref)
        adapter_state = dict(state.get("alkahest") or {})
        requested = dict(adapter_state.get("arbitration_requests") or {})
        receipt_ref = None
        if requested.get(request_key) != operation_ref:
            from market_alkahest.txlock import chain_tx_lock

            async with chain_tx_lock(None):
                request_receipt = await request_arbitration(
                    client,
                    fulfillment_uid=fulfillment_ref,
                    oracle=oracle,
                    demand=oracle_demand,
                )
            requested[request_key] = operation_ref
            adapter_state["arbitration_requests"] = requested
            state["alkahest"] = adapter_state
            receipt_ref = _receipt_ref(request_receipt)
            logger.info(
                "[SETTLEMENT] arbitration requested operation_ref=%s", operation_ref
            )
        try:
            event = await arbitration_status(
                client,
                fulfillment_uid=fulfillment_ref,
                oracle=oracle,
                demand=oracle_demand,
                timeout_seconds=self._probe_timeout,
            )
        except Exception as exc:
            return _ConditionResult(
                "pending",
                receipt_ref,
                f"alkahest arbitration status failed: {exc}",
            ), state
        if event is None or getattr(event, "decision", None) is False:
            return _ConditionResult("pending", receipt_ref), state
        return _ConditionResult("ready", receipt_ref), state

    def _context(
        self, obligation: dict[str, Any]
    ) -> tuple[str | None, Any, dict[str, Any], str | None]:
        params = obligation.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("alkahest obligation params must be an object")
        chain = params.get("chain_name") or self._default_chain
        address = params.get("escrow_contract")
        if address and str(address).startswith("0x") and set(str(address)[2:]) <= {"0"}:
            address = None
        return chain, self._client(chain), params, address

    def _client(self, chain: str | None) -> Any:
        client = self._get_client(chain)
        if client is None:
            raise ValueError(f"no alkahest client configured for chain {chain!r}")
        return client

    def _escrow_codec(self, chain: str | None, address: str | None) -> Any:
        if not address:
            raise ValueError(
                "alkahest materialization requires a deployed escrow_contract"
            )
        from market_alkahest.alkahest import get_escrow_codec_for

        return get_escrow_codec_for(
            chain or "",
            address,
            config_path=self._config_paths.get(chain or ""),
        )

    @staticmethod
    def _receipt(
        operation_ref: str, kind: str, provider_receipt: Any = None
    ) -> dict[str, Any]:
        result = {"operation_ref": operation_ref, "escrow_kind": kind}
        provider_ref = _receipt_ref(provider_receipt)
        if provider_ref is not None:
            result["receipt"] = provider_ref
        return result

    @staticmethod
    def _state(
        state: Mapping[str, Any], operation_ref: str, kind: str | None = None
    ) -> dict[str, Any]:
        result = dict(state)
        adapter_state = dict(result.get("alkahest") or {})
        adapter_state["last_operation_ref"] = operation_ref
        if kind is not None:
            adapter_state["escrow_kind"] = kind
        result["alkahest"] = adapter_state
        return result

    def _manual_status(
        self,
        mechanism_ref: str,
        operation_ref: str,
        state: Mapping[str, Any],
        error: str,
        kind: str | None = None,
    ) -> StatusOutcome:
        return StatusOutcome(
            status="manual_required",
            mechanism_ref=mechanism_ref,
            condition_anchor=mechanism_ref,
            receipt=self._receipt(operation_ref, kind)
            if kind
            else {"operation_ref": operation_ref},
            mechanism_state=self._state(state, operation_ref, kind),
            last_error=error,
        )
