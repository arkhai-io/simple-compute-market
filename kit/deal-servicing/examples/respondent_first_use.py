"""Try cooperative answers, contesting evidence and restart after a lost append."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures import record_signer
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.models import Filing, RespondentAfter
from market_deal_lifecycle.adapters import DisputeBinding, PaymentSelector
from market_deal_lifecycle.terms import DisputeAuthority
from market_identity import Ed25519Signer
from pydantic import SecretStr

from market_deal_servicing import (
    Classification, DeliveryRecord, EndSession, FinalRequest, RespondentPoller,
    SellerDeal, SellerSession, create_schema,
)
from market_deal_servicing.evidence import transaction


async def main():
    peer = MediationContractFake()
    authority = DisputeAuthority.model_validate(peer.authority)
    fixture = peer.data["filing"]["request"]
    seller = record_signer()
    buyer = Ed25519Signer(bytes([1]) * 32)  # Public development seed; never use on a public network.
    now = peer._clock
    agreement = {**fixture["agreement"], "seller": seller.identity.model_dump(mode="json")}
    binding = DisputeBinding("example", fixture["transaction"], authority)
    # Public deterministic fixture credentials; never use on a public network.
    async with MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payer")),
        transport=peer.transport(),
    ) as payer, MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
        transport=peer.transport(),
    ) as payee:
        adapter = MediationAdapter(binding, agreement, payee, clock=lambda: now)
        claim = {"kind": "delivery_end", "ended_at": now, "delivered": True, "cause": "payer"}
        for key, request in (("match", claim), ("contest", {**claim, "ended_at": now - 1})):
            await payer.file(Filing.model_validate({
                "transaction": binding.commitment_ref, "agreement": agreement, "request": request,
                "claim": "End delivery.", "items": [],
            }), idempotency_key=key)
        with TemporaryDirectory(prefix="respondent-") as root:
            path = Path(root) / "storefront.sqlite"
            with transaction(path) as conn:
                create_schema(conn)
                EndSession(conn).register(DeliveryRecord(
                    negotiation_id="example", seller=seller.identity, commitment_ref=binding.commitment_ref,
                    committed_at=now - 100, start_at=now - 100, term_end=now + 1000,
                    available_at=now - 50, progress="active",
                ))
                SellerSession(conn).register(SellerDeal(
                    negotiation_id="example", commitment_ref=binding.commitment_ref, domain="fixture",
                    buyer=buyer.identity, payment=PaymentSelector("fixture"), dispute=authority,
                ))
                EndSession(conn).record_end(FinalRequest(
                    negotiation_id="example", source_ref="buyer-surrender:fixture", ended_at=now,
                    observed_at=now, actor=buyer.identity, cause="buyer_surrender", source="end_delivery",
                ), now=now, classification=Classification(kind="buyer_surrender", evidence_refs=["fixture"]))

            def poller():
                return RespondentPoller(
                    path, authority=authority, account=peer.payee, read=adapter.respondent,
                    resolve=lambda case: ("example", adapter), signer=seller, clock=lambda: now,
                )

            assert len((await payee.respondent(RespondentAfter(after="", limit=100))).cases) == 2
            peer.lose_next_response = True
            lost = await poller().poll()
            assert lost["pending"] == 2 and lost["cursor"] == ""
            # Any append removes discovery, but its persisted page still retries
            # the same exact answer/key after the authority closes the case.
            peer.decide("case-fixture-1", [])
            recovered = await poller().poll()
            assert recovered["answered"] == 2 and recovered["pending"] == 0
            appended = [entry["entry"] for entry in peer.entries if entry["entry"]["kind"] == "appended"]
            assert len(appended) == 2
            assert "concurrence" in appended[0] and "concurrence" not in appended[1]
            assert appended[1]["items"] and all(entry["actor"] == peer.payee for entry in appended)
            assert not (await payee.respondent(RespondentAfter(after="", limit=100))).cases
            assert (await poller().poll())["answered"] == 0
            print("matching facts signed; mismatch contested; lost append recovers after closure; cursor advances only after answers")


if __name__ == "__main__":
    asyncio.run(main())
