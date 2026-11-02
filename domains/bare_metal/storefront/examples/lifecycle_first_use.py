"""Drive the mounted bare-metal lifecycle using the existing regression setup.

Run after make reinit, from the storefront directory:
PYTHONPATH=tests uv run --find-links ../../../.dist python examples/lifecycle_first_use.py
The setup is checkout-owned, uses public deterministic fixture identities, and
must never be deployed on a public network.
"""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from integration.test_payment_settlement_client import ADMIN, BUYER, SELLER, harness
from market_arkhai_mediation.claims import verify_claim
from market_arkhai_mediation.models import DeliveryEndClaim, SignedDeliveryEndClaim
from market_deal_lifecycle_client import LifecycleClient, LifecycleClientError
from market_deal_lifecycle_contracts.models import CommitMessage, ListDealsRequest
from market_identity import TrustedIdentitySet, canonical_json


async def main():
    with TemporaryDirectory(prefix="bare-metal-lifecycle-") as root:
        setup = harness.__wrapped__(Path(root), True)
        state = await anext(setup)
        try:
            transport = httpx.ASGITransport(app=state.app)
            trust = TrustedIdentitySet(identities=(SELLER.identity,))
            async with LifecycleClient("http://test", BUYER, trust, transport=transport) as client:
                state.serve()
                message = CommitMessage(
                    negotiation_id=state.negotiation_id,
                    commitment_ref=state.data.transaction_id, operation_key="first-use-commit",
                )
                assert (await client.commit(message)).outcome.status == "accepted"
                assert (await client.commit(message)).outcome.status == "accepted"
                assert len(state.provisioning.begin_calls) == 1
                kept = await state.runtime.lifecycle.evidence.read(state.negotiation_id)
                assert any(item.kind == "verified_market_envelope" for item in kept.items)
                deals = await state.runtime.lifecycle.seller.list(ListDealsRequest())
                assert state.negotiation_id in {deal.negotiation_id for deal in deals.deals}
                ack = await client.end_delivery(state.negotiation_id, operation_key="first-use-end")
                again = await client.end_delivery(state.negotiation_id, operation_key="first-use-end")
                assert ack.receipt_at == again.receipt_at
                assert again.delivery.progress == "tearing_down"
                assert len(state.provisioning.terminated) == 1
                assert ack.signed_delivery_end_claim is not None
                assert verify_claim(
                    SignedDeliveryEndClaim.model_validate(ack.signed_delivery_end_claim),
                    agreement=hashlib.sha256(canonical_json(json.loads(base64.b64decode(state.opened["agreement_bytes"])))).hexdigest(),
                    seller=SELLER.identity,
                    claim=DeliveryEndClaim(kind="delivery_end", ended_at=ack.receipt_at, delivered=True, cause="payer"),
                )
                read = await client.read(state.negotiation_id)
                assert read.delivery.recorded_end.cause == "buyer_surrender"
            async with LifecycleClient("http://test", ADMIN, trust, transport=transport) as client:
                try:
                    await client.end_delivery(state.negotiation_id, operation_key="wrong-buyer")
                except LifecycleClientError as exc:
                    assert exc.status_code == 403
                else:
                    raise AssertionError("wrong buyer was admitted")
            print("hosted commit replays once; list and exact acceptance evidence retained; signed surrender replays once; wrong buyer refuses")
        finally:
            await setup.aclose()


if __name__ == "__main__":
    asyncio.run(main())
