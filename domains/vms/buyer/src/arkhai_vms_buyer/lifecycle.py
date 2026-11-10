"""VM composition of accepted deals, buyer authority ports and signed peer I/O."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential, MediationTransportError
from market_arkhai_mediation.contract import INTERFACE
from market_arkhai_payments import PaymentSettlementData
from market_arkhai_payments.adapter import PaymentAdapter
from market_arkhai_payments.receipts import verify_snapshot
from market_config.config_loader import load_user_config
from market_core.schemas import Agreement
from market_deal_lifecycle.adapters import (
    DisputeAdapterTable, DisputeBinding, PaymentAdapterTable, PaymentBinding, PaymentSelector,
)
from market_deal_lifecycle.configuration import dispute_config
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_buyer import BuyerDeal, BuyerLifecycle
from market_deal_lifecycle_client import LifecycleClient
from market_identity import Identity

from .evidence import evidence_store


def run_sync(action):
    """Run synchronous buyer commands safely even inside an existing event loop."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(action())).result()


class _MediationPort:
    """Resolve credentials only at I/O; absence cannot prevent physical surrender."""

    def __init__(self, authority, credential):
        self.authority, self.credential, self.client = authority, credential, None

    async def _call(self, method, *args, **kwargs):
        if self.client is None:
            if self.credential is None:
                raise MediationTransportError("Agreement authority has no configured buyer credential")
            try:
                self.client = MediationClient(self.authority, MediationCredential(
                    self.authority.identity, token=self.credential.resolve(),
                ), ca_bundle=self.credential.ca_bundle_path)
            except ValueError as exc:
                raise MediationTransportError("Agreement authority credential is unavailable") from exc
            except OSError as exc:
                # The client loads its CA bundle when built; one it cannot load
                # is answered as unreachable, like a missing credential.
                raise MediationTransportError(
                    "the CA bundle the Agreement authority's credential names could not be loaded"
                ) from exc
        return await getattr(self.client, method)(*args, **kwargs)

    async def file(self, *args, **kwargs):
        return await self._call("file", *args, **kwargs)

    async def case(self, *args, **kwargs):
        return await self._call("case", *args, **kwargs)

    async def append(self, *args, **kwargs):
        return await self._call("append", *args, **kwargs)

    async def read_record(self, *args, **kwargs):
        return await self._call("read_record", *args, **kwargs)

    async def close(self):
        if self.client is not None:
            await self.client.close()


class _EvidencePeer(LifecycleClient):
    def __init__(self, *args, store, **kwargs):
        self.store = store
        super().__init__(*args, capture=store.capture, **kwargs)

    async def read(self, negotiation_id, **kwargs):
        result = await super().read(negotiation_id, **kwargs)
        for report in result.delivery.site_reports:
            # Without independent site trust these bytes are a kept seller
            # assertion, not a buyer-verified site or financial authority fact.
            await self.store.put(negotiation_id, report.model_copy(update={
                "classification": "seller_assertion",
            }))
        return result


@asynccontextmanager
async def buyer_lifecycle(
    *, agreement_bytes, settlement_data, seller_url, signer, publishers,
    approval=None, commitment_ref=None, store=None, transport=None, timeout=60, disputes=None,
):
    raw = json.loads(agreement_bytes)
    agreement = Agreement.model_validate(raw)
    if Identity.model_validate(agreement.buyer) != signer.identity:
        raise ValueError("profile signer differs from accepted buyer")
    option = agreement.settlement
    if option is None or option.settlement_schema not in {"arkhai.payments.v1", "alkahest.v1"}:
        raise ValueError("VM delivery lifecycle requires an accepted purchase settlement")
    mechanism = option.settlement_schema
    payment = None
    if mechanism == "arkhai.payments.v1":
        # Approval checks current admission policy before commitment. Recovery
        # binds the kept mandate instead: policy removed since commitment cannot
        # prevent surrender or reinterpret its accepted transaction identity.
        data = PaymentSettlementData.parse(settlement_data)
        data.require_bound_to(raw)
        commitment_ref = data.transaction_id
        if approval is not None:
            if approval.payer_account != data.mandate.from_.root:
                raise ValueError("payment credential names another accepted payer")
            payment = PaymentAdapter(
                raw, data, account=approval.payer_account, client_for_owner=approval._client_for_owner,
                verify_snapshot=lambda signed, floor: verify_snapshot(
                    signed, approval.config.receipt_trust, mandate=data.mandate, agreement_json=raw,
                    livemode=approval.config.livemode, minimum_sequence=floor,
                ),
            )
    if not commitment_ref:
        raise ValueError("delivery lifecycle requires a retained settlement commitment")
    terms = decode_terms(option.lifecycle)
    dispute = DisputeBinding(agreement.negotiation_id, commitment_ref, terms.adjudication.dispute) if terms else None
    store = store or evidence_store()
    mediation = None
    dispute_entries = []
    if dispute is not None and dispute.authority.interface == INTERFACE:
        config = disputes if disputes is not None else dispute_config(load_user_config(), role="buyer")
        mediation = _MediationPort(dispute.authority, config.credential_for(dispute.authority))
        adapter = MediationAdapter(dispute, raw, mediation)
        dispute_entries = [(INTERFACE, lambda _: adapter)]
    deal = BuyerDeal(
        agreement.negotiation_id, commitment_ref,
        PaymentBinding(agreement.negotiation_id, PaymentSelector(mechanism)), dispute,
        Identity.model_validate(agreement.buyer), Identity.model_validate(agreement.seller),
    )
    try:
        async with _EvidencePeer(
            seller_url, signer, publishers, store=store, timeout=timeout, transport=transport,
        ) as peer:
            yield BuyerLifecycle(
                deal=lambda _: deal, peer=peer, operations=store, evidence=store,
                end_journal=store.end_journal,
                payments=PaymentAdapterTable([(deal.payment.selector, lambda _: payment)] if payment else []),
                disputes=DisputeAdapterTable(dispute_entries),
            )
    finally:
        if mediation is not None:
            await mediation.close()
