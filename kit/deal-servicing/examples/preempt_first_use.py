"""Lane-only seller preemption first use; no rate delivery is installed or offered.

Sends the seller's notice through the typed seller lifecycle client, the client
both compute storefronts' ``deals preempt`` verb delegates to, against signed
lifecycle routes backed by the vendored payment authority and mediation contract
doubles. The options are the shipped presets, approved by a default buyer under
a lane-only servicing declaration. Every identity and credential below is a
public deterministic development fixture, never usable on a public network. All
state belongs to this invocation and is removed on exit.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import tomllib
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import INTERFACE
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_payments import PaymentAdapter, PaymentApproval, PaymentSettlementData
from market_arkhai_payments.adapter import pinned_snapshot_verifier
from market_arkhai_payments.errors import MandatePolicyError, PaymentsTransportError
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_arkhai_payments.presets import PaymentsRatePresetHelper, rate_context
from market_arkhai_payments.settlement_config import ArkhaiPaymentsConfig
from market_core.schemas import Agreement
from market_deal_lifecycle.adapters import DisputeAdapterTable, PaymentAdapterTable, PaymentSelector
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_contracts.models import Accepted, LifecycleCommand, SubmitResponse
from market_deal_lifecycle_client import SyncSellerLifecycleClient
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import SettlementPublicationClause
from market_settlement_runtime.buyer_terms import BuyerTermsPolicy
from market_settlement_runtime.rate_publication import RatePresetRefusal, derive_rate_preset
from market_settlement_runtime.rate_servicing import RateServicing, RateServicingDeclaration
from pydantic import SecretStr
from storefront_client import StorefrontClientError, SyncStorefrontClient

from market_deal_servicing import (
    DealWatch, DeliveryRecord, EndSession, LifecycleRouteBinding, LifecycleRouteServices,
    SellerDeal, SellerServicing, SellerSession, SQLiteOperationStore, create_lifecycle_router, create_schema,
)
from market_deal_servicing.evidence import transaction

MECHANISM = "arkhai.payments.v1"
PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"


class LossyPayments(FakePaymentsClient):
    lose = False

    def submit_event(self, transaction, event, *, request_id):
        result = super().submit_event(transaction, event, request_id=request_id)
        if self.lose:
            self.lose = False
            raise PaymentsTransportError("fixture response lost after authority recorded stop")
        return result


def main(output: Path | None, profile_path: Path) -> None:
    profile = tomllib.loads(profile_path.read_text())
    if (profile["profile"] != "lane-only" or profile["double_selector"] != "in-process"
            or not profile["setup_opt_out"] or profile["payments"]["livemode"]):
        raise ValueError("preemption fixture requires the lane-only in-process test profile with setup opted out")

    now = int(time.time())
    buyer, seller, administrator, receipt_signer = (Ed25519Signer(bytes([n]) * 32) for n in (1, 2, 3, 7))
    mediation = MediationContractFake()
    entry = DisputeEntry.model_validate({
        **profile["authority"],
        "advertisement": {"mechanisms": [MECHANISM], "minimum_dispute_window_seconds": 0,
                          "minimum_case_hold_seconds": None},
    })
    # This declaration is confined to approval/command fixtures. No installed
    # storefront publication or delivery composition receives it.
    servicing = RateServicing({MECHANISM: RateServicingDeclaration(
        MECHANISM, frozenset(profile["servicing"]["treatments"]),
    )})
    config = ArkhaiPaymentsConfig(
        enabled=True, service_identity=receipt_signer.identity, development_auth=True,
        **profile["payments"],
    )
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
    observations: dict[str, Any] = {
        "evidence_class": "lane-double evidence", "profile": "lane-only", "double_selector": "in-process",
        "declared_treatments": sorted(profile["servicing"]["treatments"]), "setup_amount": None, "livemode": False,
    }

    def accepted(name: str, payee_notice: int | None, *, charged: bool = False) -> tuple[dict, Any]:
        recurring: dict[str, Any] = {**profile["recurring"], "setup_amount": None, "payee_notice_seconds": payee_notice}
        if charged:
            recurring |= {"payee_settles_through": "started_period", "settles_through": "started_period"}
        clause = SettlementPublicationClause.model_validate({
            "mechanism": MECHANISM, "asset": "USD/2", "rate": "60", "per": "hour",
            "mechanism_input": {"asset": "USD/2", "payee_account": PAYEE,
                                "approval_window": "PT60S", "dispute_window_seconds": 3600},
            "recurring": recurring,
        })
        option = derive_rate_preset(
            clause, helper=PaymentsRatePresetHelper(), servicing=servicing, authorities=(entry,),
            max_duration_seconds=3600, available_until_utc=None, delivery_deadline_seconds=30,
            now=datetime.fromtimestamp(now, timezone.utc), default_penalty_periods=24,
        )
        if isinstance(option, RatePresetRefusal):
            raise RuntimeError(option)
        agreement = Agreement.model_validate({
            "negotiation_id": name, "listing_id": "lane-only", "listing_hash": "a" * 64,
            "buyer": buyer.identity.model_dump(mode="json"), "seller": seller.identity.model_dump(mode="json"),
            "settlement": option, "settlement_params": {"payer_account": PAYER},
            "amount": 100, "asset": "USD/2", "duration_seconds": 3600,
            "accepted_at": stamp, "start_utc": stamp,
            "provision_terms": {"kind": "example.v1", "version": 1, "payload": {}},
        }).model_dump(mode="json", exclude_none=True)
        return agreement, PaymentSettlementData.for_agreement(agreement, config, rate_servicing=servicing)

    # The charged variant: a default buyer refuses each charged term, and a
    # buyer approves only by waiving each one by name.
    charged = profile["charged"]
    agreement, data = accepted(charged["name"], charged["payee_notice_seconds"], charged=True)
    try:
        PaymentApproval(config, PAYER).check(json.dumps(agreement), data.to_wire())
    except MandatePolicyError as exc:
        observations["charged_default_buyer"] = str(exc)
    else:
        raise AssertionError("a default buyer must refuse a charged payee stop and term end")
    policy = BuyerTermsPolicy(AuthoritySelection(
        {"": (entry,)}, contexts={MECHANISM: rate_context((entry,), decode_terms(agreement["settlement"]["lifecycle"]))},
    ), waivers=frozenset(charged["waivers"]))
    PaymentApproval(config, PAYER, terms_policy=policy).check(json.dumps(agreement), data.to_wire())
    observations["charged_waived_buyer"] = {"approved": True, "waivers": sorted(charged["waivers"])}

    with TemporaryDirectory(prefix="spot-preempt-") as root:
        path = Path(root) / "seller.sqlite"
        with sqlite3.connect(path) as conn:
            create_schema(conn)
        agreements, adapters, doubles = {}, {}, {}
        for product_config in profile["products"]:
            product = product_config["name"]
            agreement, data = accepted(product, product_config.get("payee_notice_seconds"))
            # The shipped presets reach a default buyer, with no waiver.
            PaymentApproval(config, PAYER).check(json.dumps(agreement), data.to_wire())
            fake = LossyPayments(signer=receipt_signer, observed_at=now)
            fake.engine.fund(PAYER, "USD/2", 1_000_000)
            fake.receipt = fake.engine.approve(data.mandate, account=PAYER)
            adapter = PaymentAdapter(
                agreement, data, account=PAYEE, client_for_owner=fake,
                verify_snapshot=pinned_snapshot_verifier(agreement, data, config), clock=lambda: now,
            )
            agreements[product], adapters[product], doubles[product] = agreement, adapter, fake
            terms = decode_terms(agreement["settlement"]["lifecycle"])
            with transaction(path) as conn:
                EndSession(conn).register(DeliveryRecord(
                    negotiation_id=product, seller=seller.identity, commitment_ref=data.transaction_id,
                    start_at=now, committed_at=now, term_end=now + 3600,
                ))
                SellerSession(conn).register(SellerDeal(
                    negotiation_id=product, buyer=buyer.identity, commitment_ref=data.transaction_id,
                    domain="lane-only", payment=PaymentSelector(MECHANISM), dispute=entry.authority,
                    entitlements=terms.early_termination.model_dump(mode="json")["entitlements"],
                ))
            try:
                PaymentSettlementData.for_agreement(agreement, config)
            except ValueError:
                pass
            else:
                raise AssertionError("delivery/publication without the installed rate hook must refuse")
        observations["default_buyer"] = {"approved": sorted(agreements)}

        async def peer(_):
            return SubmitResponse(outcome=Accepted())

        async def mediation_read(binding):
            async with MediationClient(
                binding.authority, MediationCredential(binding.authority.identity, token=SecretStr("fixture-payee")),
                transport=mediation.transport(),
            ) as client:
                return await MediationAdapter(binding, agreements[binding.negotiation_id], client).read()

        class DisputeRead:
            def __init__(self, binding):
                self.binding = binding

            async def read(self):
                return await mediation_read(self.binding)

        service = SellerServicing(
            path, payments=PaymentAdapterTable([(PaymentSelector(MECHANISM), lambda b: adapters[b.negotiation_id])]),
            disputes=DisputeAdapterTable([(INTERFACE, DisputeRead)]), credential_available=lambda _: True,
            clock=lambda: now,
            watch_factory=lambda deal, payment, dispute: DealWatch(
                path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
                payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding, seller_account=PAYEE,
                actor=lambda _: seller.identity, clock=lambda: now,
            ),
        )
        services = LifecycleRouteServices(
            seller=service, signer=seller, administrators=TrustedIdentitySet(identities=(administrator.identity,)),
            binding=lambda nid: LifecycleRouteBinding(buyer=buyer.identity, seller=seller.identity, settlement=True),
            peer=peer,
        )
        application = FastAPI()
        application.include_router(create_lifecycle_router(lambda _: services))
        trust = TrustedIdentitySet(identities=(seller.identity,))
        with TestClient(application) as server:
            def handle(request):
                response = server.request(request.method, str(request.url), content=request.content, headers=request.headers)
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)

            @contextmanager
            def lifecycle_client(signer=administrator) -> Iterator[SyncSellerLifecycleClient]:
                with SyncStorefrontClient(
                    "http://testserver", signer=signer, caller_role="admin", expected_publishers=trust,
                    transport=httpx.MockTransport(handle),
                ) as core:
                    yield SyncSellerLifecycleClient(core)

            with lifecycle_client() as client:
                observations.update(notice_observations(client, now, doubles))
            with lifecycle_client(signer=buyer) as stranger:
                try:
                    stranger.notice("spot", operation_key="wrong-actor")
                except StorefrontClientError as exc:
                    assert exc.status_code == 403
                else:
                    raise AssertionError("buyer acted as seller administrator")
            observations.update({"delivery_without_rate_hook": "refused", "wrong_actor": "403"})

        # A payer's earlier effective stop remains controlling when the seller
        # repeats its original notice, even without a running storefront.
        payer = PaymentAdapter(
            agreements["spot"], adapters["spot"].data, account=PAYER, client_for_owner=doubles["spot"],
            verify_snapshot=pinned_snapshot_verifier(agreements["spot"], adapters["spot"].data, config),
            clock=lambda: now,
        )
        stop = LifecycleCommand(negotiation_id="spot", kind="stop", operation_key="buyer-stop", payload={"part": "0"})
        buyer_operations = Path(root) / "buyer.sqlite"
        with sqlite3.connect(buyer_operations) as conn:
            create_schema(conn)
        keys = OperationKeys("spot", "buyer-stop", SQLiteOperationStore(buyer_operations))
        assert asyncio.run(payer.submit(stop, keys)).status == "accepted"
        replay = asyncio.run(service.submit(LifecycleCommand(
            negotiation_id="spot", kind="notice", operation_key="fixture-notice", at=now + 1,
        ), actor=administrator.identity))
        assert replay.status == "accepted" and replay.records[0].actor == PAYER and replay.records[0].at == now
        observations["earlier_buyer_stop"] = replay.model_dump(mode="json")
    rendered = json.dumps(observations, indent=2) + "\n"
    if output:
        output.write_text(rendered)
    print(rendered, end="")


def notice_observations(client: SyncSellerLifecycleClient, now: int, doubles: dict[str, LossyPayments]) -> dict:
    """The seller's notice through the typed client: a lost response, its retry, and its refusals."""
    doubles["spot"].lose = True
    first = client.notice("spot", operation_key="fixture-notice", at=now + 1)
    assert first.outcome.status == "unknown", first
    pending = client.read("spot")
    listing = client.list()
    # The authority's notice minimum, not the requested instant, sets the stop.
    assert pending.authority.parts[0].pending_stop.at == now + 30
    assert listing.deals[1].parts[0].pending_stop == pending.authority.parts[0].pending_stop
    retry = client.notice("spot", operation_key="fixture-notice", at=now + 1)
    assert retry.outcome.status == "accepted" and retry.outcome.records[0].at == now + 30, retry
    refused = client.notice("on-demand", operation_key="fixture-refusal")
    assert refused.outcome.status == "rejected" and "delivery_end" in refused.outcome.reason, refused
    assert doubles["on-demand"].count("submit_event") == 0
    changed = client.notice("spot", operation_key="fixture-notice", at=now + 300)
    assert changed.outcome.status == "rejected" and "retry changes content" in changed.outcome.reason, changed
    return {
        "lost_response": first.model_dump(mode="json"), "same_key_retry": retry.model_dump(mode="json"),
        "pending_read": pending.model_dump(mode="json"), "list": listing.model_dump(mode="json"),
        "on_demand_refusal": refused.model_dump(mode="json"), "changed_retry": changed.model_dump(mode="json"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profile", type=Path, default=Path(__file__).with_name("preempt.lane.toml"))
    args = parser.parse_args()
    main(args.output, args.profile)
