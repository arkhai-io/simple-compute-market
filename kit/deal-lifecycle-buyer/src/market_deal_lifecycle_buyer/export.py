"""One exportable case, preserving the Agreement and each original evidence body."""

import base64
import hashlib
import json
from collections.abc import Callable
from typing import Any

from market_deal_lifecycle.terms import LifecycleTerms
from market_deal_lifecycle_contracts.models import CasePayload

from market_deal_lifecycle_buyer.store import FileEvidenceStore


async def export_case(
    store: FileEvidenceStore,
    negotiation_id: str,
    *,
    claim: str,
    requested_outcome: dict[str, Any],
    terms_from_agreement: Callable[[bytes], LifecycleTerms | dict | None],
    commitment_ref: str | None = None,
) -> CasePayload:
    record, commitment, acceptance = await store.case_material(negotiation_id, commitment_ref)
    raw = base64.b64decode(json.loads(acceptance.body)["agreement_bytes"], validate=True)
    agreement = json.loads(raw)
    if not isinstance(agreement, dict) or agreement.get("negotiation_id") != negotiation_id:
        raise ValueError("acceptance names another negotiation")
    terms = terms_from_agreement(raw)
    if isinstance(terms, LifecycleTerms):
        terms = terms.model_dump(mode="json")
    items = []
    for item in record.items:
        context = dict(item.context)
        if not context.get("producer"):
            raise ValueError("case evidence omitted its producer")
        digest = hashlib.sha256(item.body).hexdigest()
        if context.get("digest", digest) != digest:
            raise ValueError("case evidence digest differs from its original bytes")
        context["digest"] = digest
        items.append(item.model_copy(update={"context": context}))
    return CasePayload(
        negotiation_id=negotiation_id, commitment_ref=commitment,
        agreement=base64.b64encode(raw), items=items,
        request={"terms": terms, "claim": claim, "request": requested_outcome},
    )
