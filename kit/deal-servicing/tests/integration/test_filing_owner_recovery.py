"""A semantic owner with an unknown write blocks, but never rejects, equivalent callers."""

import asyncio

import httpx

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.adapters import DisputeAdapterTable, PaymentAdapterTable, PaymentSelector
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_servicing import DealWatch, DeliveryRecord, EndSession, SellerDeal, SellerServicing, SellerSession
from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import Classification, FinalRequest
from pydantic import SecretStr
from test_review_fix_a import BUYER, SELLER


def test_unresolved_original_remains_retryable_until_both_callers_adopt(tmp_path):
    async def drive():
        path = tmp_path / "servicing.sqlite"
        peer = MediationContractFake()
        fail = [True]

        def handle(request):
            if request.method == "POST" and request.url.path == "/cases" and fail[0]:
                fail[0] = False
                raise httpx.ConnectError("outage before the authority receives the filing", request=request)
            return peer.handle(request)

        authority = DisputeAuthority.model_validate(peer.authority)
        fixture = peer.data["filing"]["request"]
        start = 1800000000
        async with MediationClient(
            authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
            transport=httpx.MockTransport(handle),
        ) as client:
            def service():
                return SellerServicing(
                    path, payments=PaymentAdapterTable([]),
                    disputes=DisputeAdapterTable([(authority.interface, lambda binding: MediationAdapter(
                        binding, fixture["agreement"], client, clock=lambda: start + 1800,
                    ))]), credential_available=lambda _: True, clock=lambda: start + 1800,
                    watch_factory=lambda deal, payment, dispute: DealWatch(
                        path, negotiation_id="deal", commitment_ref=deal.commitment_ref,
                        payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
                        seller_account=peer.payee, actor=lambda _: SELLER.identity, clock=lambda: start + 1800,
                    ),
                )

            with transaction(path) as conn:
                end = EndSession(conn)
                end.register(DeliveryRecord(
                    negotiation_id="deal", seller=SELLER.identity, commitment_ref=fixture["transaction"],
                    start_at=start, term_end=start + 3600, committed_at=start,
                ))
                SellerSession(conn).register(SellerDeal(
                    negotiation_id="deal", commitment_ref=fixture["transaction"], domain="fixture",
                    buyer=BUYER.identity, payment=PaymentSelector("fixture.payment"), dispute=authority, once_only=True,
                ))
                # Earlier evidence received late is a real revision, but both
                # never-delivered corrections have the same Agreement-start basis.
                for source, at in (("first", start + 600), ("earlier", start + 500)):
                    request = FinalRequest(
                        negotiation_id="deal", source_ref=source, observed_at=start + 1800, ended_at=at,
                        actor=SELLER.identity, cause="operator_end", source="administrator", evidence_refs=[source],
                    )
                    end.record_end(
                        request, now=start + 1800,
                        classification=Classification(kind="unentitled_withdrawal", evidence_refs=[source]),
                        filing_intent=end.failure_filing(request, now=start + 1800, delivered=False),
                    )
            first = await service().dispatch_filings("deal")
            assert [item.outcome.status for item in first] == ["unknown", "pending"]
            with transaction(path) as conn:
                assert all(i.state == "pending" for i in EndSession(conn).intents("deal") if i.kind == "filing")
            recovered = await service().dispatch_filings("deal")
            assert [item.outcome.status for item in recovered] == ["accepted", "accepted"]
            assert len({item.outcome.filing.case_ref for item in recovered}) == len(peer.cases) == 1
            assert (await service().read("deal")).authority.state != "repair_required"

    asyncio.run(drive())
