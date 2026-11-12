"""Signed administrator dispatch over invocation-owned VM persistence.

The existing VM application fixture supplies deterministic development identities;
never use them on a public network. The entitled branch injects a future payment
adapter to qualify dispatch and notice ordering, not rate mandate execution.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

from market_arkhai_payments import PaymentSettlementData, derive_mandate, mandate_policy_for_agreement, transaction_id
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_core.schemas import derive_settlement_option_id
from market_deal_lifecycle.adapters import PaymentAdapterTable, PaymentSelector
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_contracts.models import Accepted, AuthorityView, PaymentEvent
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_identity import TrustedIdentitySet, canonical_json
from pydantic import SecretStr
from storefront_client import StorefrontClientError

import market_storefront.server  # noqa: F401 - controller composition order
import tests.conftest  # noqa: F401 - explicit public storefront domain selection
from market_storefront.controllers.admin_controller import router
from market_storefront.middleware.admin_identity import (
    administrator_identity_middleware,
    initialize_administrator_identities,
)
from tests.integration.test_payment_settlement import (
    NEGOTIATION,
    PAYEE,
    SELLER,
    _client, _config, SERVICE,
)
from tests.integration.test_payment_settlement import make as make


class Notice:
    supported_commands = frozenset({"notice"})

    def __init__(self, commitment_ref, effective_at):
        self.commitment_ref = commitment_ref
        self.effective_at = effective_at
        self.effective = False
        self.calls = []

    def validate(self, command):
        return None

    async def submit(self, command, keys):
        self.calls.append(command)
        return Accepted()

    async def read(self):
        events = [PaymentEvent(
            negotiation_id=NEGOTIATION, commitment_ref=self.commitment_ref,
            part="0", kind="stop", actor=PAYEE, at=self.effective_at, cause="payee",
            sequence=1, authority_record_ref="notice-stop-record",
        )] if self.effective else []
        return AuthorityView(outcome=Accepted(), events=events)


def approve_rate(h, *, entitled):
    """Lane-only approved command fixture; the installed delivery hook stays closed."""
    agreement, _ = h.lifecycle.accepted(NEGOTIATION)
    now = h.lifecycle.clock()
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
    agreement.update(start_utc=stamp, accepted_at=stamp)
    option = agreement["settlement"]
    option["settlement"].update(period="PT60S", reserve_ahead_seconds=120, approval_window="PT60S")
    option["price"]["rates"] = [{"field": "amount", "per": "hour", "value": 6000}]
    rights = {"payer": {"notice_seconds": 300, "settles_through": "started_period"}}
    if entitled:
        rights["payee"] = {"notice_seconds": 120, "settles_through": "started_period"}
    option["lifecycle"]["early_termination"] = {
        "version": 1, "entitlements": rights, "settles_through": "started_period",
    }
    option["option_id"] = derive_settlement_option_id(**{k: v for k, v in option.items() if k != "option_id"})
    mandate = derive_mandate(agreement, mandate_policy_for_agreement(agreement, _config()))
    h.data = PaymentSettlementData(mandate=mandate, transaction_id=transaction_id(mandate))
    h.payments.signer = SERVICE
    h.payments.observed_at = now
    h.payments.engine.fund(mandate.from_.root, "USD/2", 1_000_000)
    h.payments.receipt = h.payments.engine.approve(mandate, account=mandate.from_.root)
    with sqlite3.connect(h.db.db_path) as conn:
        conn.execute("UPDATE negotiation_threads SET agreement_bytes=?,settlement_data=? WHERE negotiation_id=?",
                     (json.dumps(agreement).encode(), json.dumps(h.data.to_wire()), NEGOTIATION))
    h.lifecycle.register(agreement, h.data, h.payments.receipt)
    h.delivery.starts.append(NEGOTIATION)


@pytest.mark.asyncio
@pytest.mark.parametrize("entitled,kind", [(False, None), (False, "failure"), (True, "failure"), (True, "preemption")])
async def test_admin_interrupt_obeys_entitlement_and_retries_filing_independently(make, entitled, kind):
    h = await make()
    if entitled:
        approve_rate(h, entitled=True)
    else:
        h.serve()
        await h.settle()
        await h.delivered()
    now = h.lifecycle.clock()
    notice = None
    mediation = None
    preemption = kind == "preemption"
    if not preemption:
        mediation = MediationContractFake()
        mediation.lose_next_response = True
        agreement, _ = h.lifecycle.accepted(NEGOTIATION)
        authority = decode_terms(agreement["settlement"]["lifecycle"]).adjudication.dispute
        teardown = asyncio.Event()

        async def physical(*args, **kwargs):
            result = await h.delivery.apply_end(*args, **kwargs)
            teardown.set()
            return result

        async def handle(request):
            if request.method == "POST":
                # The authority cannot answer until teardown has run. This
                # exposes an implementation which serializes filing before it.
                await asyncio.wait_for(teardown.wait(), timeout=5)
            return mediation.handle(request)

        h.lifecycle.end.physical = type("Physical", (), {"apply_end": staticmethod(physical)})()
        # Public deterministic fixture credential, never a live account token.
        client = MediationClient(
            authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
            transport=httpx.MockTransport(handle),
        )
        h.lifecycle.clients[canonical_json(authority)] = client
        h.lifecycle.credential_available = lambda candidate: candidate == authority
        h.lifecycle.seller.credential_available = h.lifecycle.credential_available
    if preemption:
        notice = Notice(h.data.transaction_id, now + 120)
        h.lifecycle.seller.payments = PaymentAdapterTable([
            (PaymentSelector("arkhai.payments.v1"), lambda _: notice),
        ])
    app = FastAPI()
    app.include_router(router)
    app.middleware("http")(administrator_identity_middleware)
    with patch(
        "market_storefront.middleware.admin_identity.get_administrator_configs",
        return_value={"operator": TrustedIdentitySet(identities=(SELLER.identity,))},
    ):
        initialize_administrator_identities(h.db.db_path)
        async with _client(SELLER, "admin", httpx.ASGITransport(app=app)) as client:
            async def interrupt(body):
                return await client.admin_interrupt_deal(NEGOTIATION, **body)

            body = {"reason": "development reclaim", "operation_key": "admin-demo", "interruption_kind": kind}
            preview = await interrupt(body | {"dry_run": True})
            assert preview["status"] == "dry_run"
            response = await interrupt(body)
            assert response["settlement_action"] == ("notice_stop" if preemption else "delivery_end_filing")
            retry = await interrupt(body)
            assert retry["delivery"]["recorded_end"] == response["delivery"]["recorded_end"]
            if not preemption:
                assert response["lifecycle_outcome"]["status"] == "unknown", response["lifecycle_outcome"]
                assert retry["lifecycle_outcome"]["status"] == "accepted"
                assert len(mediation.cases) == 1
            try:
                await interrupt(body | {"reason": "changed reason"})
            except StorefrontClientError as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("same-key content change was accepted")
    with transaction(h.db.db_path) as conn:
        end = EndSession(conn)
        requests = end.requests(NEGOTIATION)
        filings = [intent for intent in end.intents(NEGOTIATION) if intent.kind == "filing"]
        if preemption:
            assert notice.calls and all(command.kind == "notice" and command.at is None for command in notice.calls)
            assert requests == [] and filings == []
        else:
            assert len(requests) == len(filings) == 1
            assert requests[0].actor == SELLER.identity
            assert requests[0].administrator_reason == "development reclaim"
            assert filings[0].payload["payload"]["cause"] == "payee"
            assert filings[0].state == "done"
            assert end.view(NEGOTIATION).progress == "tearing_down"
    if notice is not None:
        async for _ in h.lifecycle.seller.watch(NEGOTIATION):
            pass
        with transaction(h.db.db_path) as conn:
            assert EndSession(conn).requests(NEGOTIATION) == []
        notice.effective = True
        h.lifecycle.clock = lambda: now + 121
        h.lifecycle.end.clock = h.lifecycle.clock
        async for _ in h.lifecycle.seller.watch(NEGOTIATION):
            pass
        with transaction(h.db.db_path) as conn:
            end = EndSession(conn)
            assert end.selected_end(NEGOTIATION).ended_at == now + 120
            assert not [intent for intent in end.intents(NEGOTIATION) if intent.kind == "filing"]
        await h.lifecycle.end.drive_physical(NEGOTIATION)


@pytest.mark.asyncio
@pytest.mark.parametrize("rate,kind", [(False, "preemption"), (True, None)])
async def test_admin_refuses_unentitled_preemption_and_unclassified_rate_before_effect(make, rate, kind):
    h = await make()
    if rate:
        approve_rate(h, entitled=True)
    else:
        h.serve()
        await h.settle()
    app = FastAPI()
    app.include_router(router)
    app.middleware("http")(administrator_identity_middleware)
    with patch("market_storefront.middleware.admin_identity.get_administrator_configs",
               return_value={"operator": TrustedIdentitySet(identities=(SELLER.identity,))}):
        initialize_administrator_identities(h.db.db_path)
        async with _client(SELLER, "admin", httpx.ASGITransport(app=app)) as client:
            with pytest.raises(StorefrontClientError) as refused:
                await client.admin_interrupt_deal(NEGOTIATION, interruption_kind=kind,
                                                 reason="hardware failure", operation_key="refused")
            assert refused.value.status_code == 409
    with transaction(h.db.db_path) as conn:
        assert EndSession(conn).requests(NEGOTIATION) == []
        assert EndSession(conn).intents(NEGOTIATION) == []
