"""Alkahest StringObligation publication with exact attestation readback."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .txlock import chain_tx_lock

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _value(source: Any, name: str) -> Any:
    return (
        source.get(name)
        if isinstance(source, Mapping)
        else getattr(source, name, None)
    )


class AlkahestStringFulfillmentPublisher:
    """Publish and confirm seller-recipient StringObligation evidence.

    Submission and confirmation are separate operations so callers can persist
    the returned UID before a readback failure. The RecipientArbiter trusts only
    the fulfillment attestation's recipient; evidence content remains a durable
    audit binding rather than an on-chain physical-term predicate.
    """

    def __init__(self, *, client: Any, publisher_address: str) -> None:
        if _ADDRESS.fullmatch(publisher_address) is None:
            raise ValueError("publisher_address must be a 20-byte hex address")
        self._client = client
        self._publisher_address = publisher_address.lower()

    @property
    def publisher_address(self) -> str:
        return self._publisher_address

    async def submit_fulfillment(
        self,
        *,
        condition_anchor: str,
        evidence: str,
    ) -> str:
        if not condition_anchor or not evidence:
            raise ValueError("condition_anchor and evidence must be non-empty")
        async with chain_tx_lock(None):
            uid = await self._client.string_obligation.do_obligation(
                evidence,
                condition_anchor,
            )
        if not isinstance(uid, str) or not uid:
            raise RuntimeError("StringObligation returned no fulfillment UID")
        return uid

    async def confirm_fulfillment(
        self,
        *,
        fulfillment_uid: str,
        condition_anchor: str,
        evidence: str,
    ) -> str:
        fetched = await self._client.string_obligation.get_obligation(fulfillment_uid)
        attestation = _value(fetched, "attestation")
        data = _value(fetched, "data")
        if attestation is None or data is None:
            raise ValueError("fulfillment attestation readback is incomplete")
        actual_uid = _value(attestation, "uid")
        ref_uid = _value(attestation, "ref_uid")
        recipient = _value(attestation, "recipient")
        revoked = _value(attestation, "revocation_time")
        if (
            not isinstance(actual_uid, str)
            or actual_uid.lower() != fulfillment_uid.lower()
        ):
            raise ValueError("fulfillment attestation UID does not match")
        if not isinstance(ref_uid, str) or ref_uid.lower() != condition_anchor.lower():
            raise ValueError("fulfillment attestation condition anchor does not match")
        if (
            not isinstance(recipient, str)
            or recipient.lower() != self._publisher_address
        ):
            raise ValueError(
                "fulfillment attestation recipient does not match publisher"
            )
        if isinstance(revoked, bool) or not isinstance(revoked, int) or revoked != 0:
            raise ValueError("fulfillment attestation is revoked or malformed")
        if _value(data, "item") != evidence:
            raise ValueError("fulfillment evidence does not match durable intent")
        return fulfillment_uid

    async def publish_fulfillment(
        self,
        *,
        condition_anchor: str,
        evidence: str | None,
    ) -> str:
        if evidence is None:
            raise ValueError("fulfillment evidence must be present")
        uid = await self.submit_fulfillment(
            condition_anchor=condition_anchor,
            evidence=evidence,
        )
        return await self.confirm_fulfillment(
            fulfillment_uid=uid,
            condition_anchor=condition_anchor,
            evidence=evidence,
        )


__all__ = ["AlkahestStringFulfillmentPublisher"]
