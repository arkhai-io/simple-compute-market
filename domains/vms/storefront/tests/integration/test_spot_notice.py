"""Rate commands through the composed VM application and both operator clients."""

from contextlib import contextmanager
from copy import deepcopy
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from arkhai_vms_buyer.lifecycle import buyer_lifecycle
from market_arkhai_payments import PaymentApproval
from market_arkhai_payments.adapter import pinned_snapshot_verifier
from market_arkhai_payments.errors import PaymentsTransportError
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_arkhai_payments.rate_adapter import RatePaymentAdapter
from market_core.schemas import derive_settlement_option_id
from market_deal_lifecycle.adapters import submit_payment, PaymentAdapterTable, PaymentBinding
from market_deal_lifecycle_buyer import FileEvidenceStore
from market_deal_lifecycle_contracts.models import LifecycleCommand
from market_deal_lifecycle_client import SellerLifecycleClient, SyncSellerLifecycleClient
from market_deal_servicing import EndSession, create_lifecycle_router
from market_deal_servicing.evidence import transaction
from market_identity import TrustedIdentitySet
from storefront_client import SyncStorefrontClient, StorefrontClientError
from typer.testing import CliRunner

from tests.integration.test_payment_settlement import BUYER, SELLER, NEGOTIATION, PAYER, _config
from tests.integration.test_payment_settlement import make as make
from tests.integration.test_lifecycle_admin import approve_rate


class LossyPayments(FakePaymentsClient):
    lose = False

    def submit_event(self, transaction, event, *, request_id):
        stored = super().submit_event(transaction, event, request_id=request_id)
        if self.lose:
            self.lose = False
            raise PaymentsTransportError("answer lost after authority recorded stop")
        return stored


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["vms", "bare_metal"])
async def test_preempt_cli_recovers_pending_stop_and_an_earlier_payer_end(make, monkeypatch, domain):
    h = await make(payments=LossyPayments())
    approve_rate(h, entitled=True, payer_notice=0)
    await h.db.update_listing(listing_id="vm-payment-listing", settlement_options=[])
    if domain == "vms":
        from market_storefront.cli import app as cli
        from market_storefront.groups import deals as commands
    else:
        from arkhai_bare_metal_storefront.cli import app as cli
        from arkhai_bare_metal_storefront import deals_cli as commands
    trust = TrustedIdentitySet(identities=(SELLER.identity,))
    app = FastAPI()
    app.include_router(create_lifecycle_router(lambda _: h.lifecycle.routes(trust)))
    with TestClient(app) as server:
        def handle(request):
            answer = server.request(request.method, str(request.url), content=request.content, headers=request.headers)
            return httpx.Response(answer.status_code, content=answer.content, headers=answer.headers)

        @contextmanager
        def factory(_, signer=SELLER):
            with SyncStorefrontClient("http://testserver", signer=signer, caller_role="admin",
                                     expected_publishers=trust, transport=httpx.MockTransport(handle)) as core:
                yield SyncSellerLifecycleClient(core)

        monkeypatch.setattr(commands, "lifecycle_client", factory)
        now = h.payments.observed_at
        command = ["deals", "preempt", NEGOTIATION, "--operation-key", "notice", "--at", str(now + 1)]
        h.payments.lose = True
        first = CliRunner().invoke(cli, command)
        assert first.exit_code == 0 and json.loads(first.output)["outcome"]["status"] == "unknown", first.output
        with factory(None) as client:
            read, page = client.read(NEGOTIATION), client.list()
            assert read.authority.parts[0].pending_stop.at == now + 120
            assert page.deals[0].parts == read.authority.parts
        retry = CliRunner().invoke(cli, command)
        assert retry.exit_code == 0 and json.loads(retry.output)["outcome"]["records"][0]["at"] == now + 120
        changed = CliRunner().invoke(cli, command[:-1] + [str(now + 600)])
        assert changed.exit_code == 1 and "retry changes content" in changed.output
        with factory(None, signer=BUYER) as wrong:
            with pytest.raises(StorefrontClientError) as refused:
                wrong.notice(NEGOTIATION, operation_key="forbidden")
            assert refused.value.status_code == 403
        assert h.payments.count("submit_event") == 1
    async for _ in h.lifecycle.seller.watch(NEGOTIATION):
        pass
    with transaction(h.db.db_path) as conn:
        assert EndSession(conn).requests(NEGOTIATION) == []
    agreement, _ = h.lifecycle.accepted(NEGOTIATION)
    payer = RatePaymentAdapter(
        agreement, h.data, account=PAYER, client_for_owner=h.payments,
        verify_snapshot=pinned_snapshot_verifier(agreement, h.data, _config()),
        clock=lambda: h.payments.observed_at,
    )
    deal = h.lifecycle.seller._deal(NEGOTIATION)
    binding = PaymentBinding(NEGOTIATION, deal.payment)
    stop = LifecycleCommand(negotiation_id=NEGOTIATION, kind="stop", operation_key="buyer-earlier")
    assert (await submit_payment(stop, binding, PaymentAdapterTable([(binding.selector, lambda _: payer)]),
                                 FileEvidenceStore(h.lifecycle.path.parent / "payer"))).status == "accepted"
    async for _ in h.lifecycle.seller.watch(NEGOTIATION):
        pass
    with transaction(h.db.db_path) as conn:
        assert EndSession(conn).selected_end(NEGOTIATION).ended_at == now
        assert not [intent for intent in EndSession(conn).intents(NEGOTIATION) if intent.kind == "filing"]


@pytest.mark.asyncio
async def test_on_demand_refuses_notice_before_payment_effect(make):
    h = await make()
    approve_rate(h, entitled=False)
    agreement, _ = h.lifecycle.accepted(NEGOTIATION)
    current = deepcopy(agreement["settlement"])
    current["lifecycle"]["early_termination"]["entitlements"]["payee"] = {
        "notice_seconds": 30, "settles_through": "started_period",
    }
    current["option_id"] = derive_settlement_option_id(**{k: v for k, v in current.items() if k != "option_id"})
    await h.db.update_listing(listing_id="vm-payment-listing", settlement_options=[current])
    refused = await SellerLifecycleClient(h.administrator).notice(NEGOTIATION, operation_key="not-entitled")
    assert refused.outcome.status == "rejected" and "delivery_end" in refused.outcome.reason
    assert h.payments.count("submit_event") == 0


@pytest.mark.asyncio
async def test_vm_buyer_composition_stops_then_hints_and_retains_priced_notice(make, tmp_path):
    h = await make()
    approve_rate(h, entitled=True)
    agreement, _ = h.lifecycle.accepted(NEGOTIATION)
    approval = PaymentApproval(_config(), PAYER, client_for_owner=h.payments)
    async with buyer_lifecycle(
        agreement_bytes=json.dumps(agreement).encode(), settlement_data=h.data.to_wire(),
        seller_url="http://test", signer=BUYER,
        publishers=TrustedIdentitySet(identities=(SELLER.identity,)), approval=approval,
        store=FileEvidenceStore(tmp_path / "buyer"), transport=h.transport,
    ) as buyer:
        progress = await buyer.end(NEGOTIATION)
        assert progress.mode == "normal_stop" and progress.payment.status == "accepted"
        assert progress.payment.records[0].at == h.payments.observed_at + 300
        assert progress.hint.status == "accepted" and progress.acknowledgement is None
        assert (await buyer.read(NEGOTIATION)).authority.parts[0].pending_stop.at == h.payments.observed_at + 300
    with transaction(h.db.db_path) as conn:
        assert EndSession(conn).requests(NEGOTIATION) == []
    h.payments.observed_at += 300
    async for _ in h.lifecycle.seller.watch(NEGOTIATION):
        pass
    with transaction(h.db.db_path) as conn:
        assert EndSession(conn).selected_end(NEGOTIATION).ended_at == h.payments.observed_at
