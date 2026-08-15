from __future__ import annotations

from typing import Literal

from market_hosted_settlement import (
    ConditionDescriptor,
    EasFulfillmentRef,
    PortableRemoteFulfillmentRef,
    canonical_json,
)

EvidenceMode = Literal["eas.v1", "portable-remote.v1"]


def encode_hosted_fulfillment_ref(
    *,
    condition: ConditionDescriptor,
    fulfillment_uid: str,
    evidence_mode: EvidenceMode,
    resolver_id: str,
) -> str:
    """Project only condition-selected public evidence into the hosted wire type.

    The function deliberately accepts no generic fulfillment result, connection
    details, credentials, URL, headers, or provider fields. Callers can therefore
    only bind the immutable public UID produced by the selected resolver.
    """
    configured_resolver = condition.evaluator.resolver_id
    if configured_resolver is not None and resolver_id != configured_resolver:
        raise ValueError("fulfillment resolver does not match accepted condition")
    ref: EasFulfillmentRef | PortableRemoteFulfillmentRef
    if evidence_mode == "eas.v1":
        if condition.evaluator.kind.value != "alkahest.evm-arbiter.v1":
            raise ValueError("EAS fulfillment is restricted to EVM arbiter conditions")
        ref = EasFulfillmentRef(resolver_id=resolver_id, uid=fulfillment_uid)
    elif evidence_mode == "portable-remote.v1":
        ref = PortableRemoteFulfillmentRef(
            resolver_id=resolver_id,
            uid=fulfillment_uid,
        )
    else:
        raise ValueError("unsupported hosted fulfillment evidence mode")
    return canonical_json(ref.model_dump(mode="json")).decode()
