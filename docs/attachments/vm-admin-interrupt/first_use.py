"""Signed administrator dispatch over invocation-owned VM persistence.

The existing VM application fixture supplies deterministic development identities;
never use them on a public network. The entitled branch injects a future payment
adapter to qualify dispatch and notice ordering, not rate mandate execution.
"""

import asyncio
import copy
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
import tests.conftest  # noqa: F401 - explicit public storefront domain selection
import market_storefront.server  # noqa: F401 - controller composition order
from fastapi import FastAPI
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_core.schemas import derive_settlement_option_id
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle.adapters import PaymentAdapterTable, PaymentSelector
from market_deal_lifecycle_contracts.models import Accepted, AuthorityView, PaymentEvent
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_identity import TrustedIdentitySet, canonical_json
from market_storefront.controllers.admin_controller import router
from market_storefront.middleware.admin_identity import (
    administrator_identity_middleware, initialize_administrator_identities,
)
from storefront_client import StorefrontClientError
from tests.integration.test_payment_settlement import (
    _client, _harness, NEGOTIATION, PAYEE, SELLER,
)


class Notice:
    supported_commands = frozenset({"stop"})

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


async def run(path, *, entitled):
    h = await _harness(path)
    h.serve()
    await h.settle()
    await h.delivered()
    now = h.lifecycle.clock()
    notice = None
    mediation = None
    if not entitled:
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
            authority, MediationCredential(authority.identity, "DEMO_MEDIATION_TOKEN"),
            environ={"DEMO_MEDIATION_TOKEN": "fixture-payee"}, transport=httpx.MockTransport(handle),
        )
        h.lifecycle.clients[canonical_json(authority)] = client
        h.lifecycle.credential_available = lambda candidate: candidate == authority
        h.lifecycle.seller.credential_available = h.lifecycle.credential_available
    if entitled:
        agreement, _ = h.lifecycle.accepted(NEGOTIATION)
        agreement = copy.deepcopy(agreement)
        agreement["settlement"]["lifecycle"]["early_termination"] = {
            "version": 1,
            "entitlements": {"payee": {"notice_seconds": 120, "settles_through": "last_boundary"}},
            "settles_through": "last_boundary",
        }
        option = agreement["settlement"]
        option["option_id"] = derive_settlement_option_id(**{
            key: value for key, value in option.items() if key != "option_id"
        })
        # Install only the accepted option projection needed by admin dispatch.
        # The current once adapter deliberately cannot approve a rate mandate.
        with sqlite3.connect(h.db.db_path) as conn:
            conn.execute(
                "UPDATE negotiation_threads SET agreement_bytes=? WHERE negotiation_id=?",
                (json.dumps(agreement).encode(), NEGOTIATION),
            )
        notice = Notice(h.data.transaction_id, now + 120)
        h.lifecycle.seller.payments = PaymentAdapterTable([
            (PaymentSelector("arkhai.payments.v1"), lambda _: notice),
        ])
    app = FastAPI()
    app.include_router(router)
    app.middleware("http")(administrator_identity_middleware)
    try:
        with patch(
            "market_storefront.middleware.admin_identity.get_administrator_configs",
            return_value={"operator": TrustedIdentitySet(identities=(SELLER.identity,))},
        ):
            initialize_administrator_identities(h.db.db_path)
            async with _client(SELLER, "admin", httpx.ASGITransport(app=app)) as client:
                async def interrupt(body):
                    return await client.authenticated_request(
                        "POST", "/api/v1/admin/deals/" + NEGOTIATION + "/interrupt",
                        role="admin", operation="admin_interrupt_deal", resource=NEGOTIATION,
                        body=body,
                    )

                body = {"reason": "development reclaim", "operation_key": "admin-demo"}
                preview = await interrupt(body | {"dry_run": True})
                assert preview["status"] == "dry_run"
                response = await interrupt(body)
                assert response["settlement_action"] == ("notice_stop" if entitled else "delivery_end_filing")
                retry = await interrupt(body)
                assert retry["delivery"]["recorded_end"] == response["delivery"]["recorded_end"]
                if not entitled:
                    assert response["lifecycle_outcome"]["status"] == "unknown"
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
            if entitled:
                assert notice.calls and all(command.kind == "stop" and command.at is None for command in notice.calls)
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
            print("entitled: notice submitted; no early local end; authority effective instant governs; no filing")
        else:
            print("unentitled: attributed end; teardown independent of lost filing response; same-key retry yields one accepted case")
    finally:
        await h.coordinator.stop()
        await h.lifecycle.close()
        await h.buyer.close()
        await h.seller.close()
        await h.administrator.close()


async def main():
    for entitled in (False, True):
        with tempfile.TemporaryDirectory() as tmp:
            await run(Path(tmp), entitled=entitled)


if __name__ == "__main__":
    asyncio.run(main())
