"""Bare-metal composition of retained agreements and the buyer lifecycle ports."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hashlib
import json

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential, MediationTransportError
from market_arkhai_mediation.contract import INTERFACE
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM, PaymentSettlementData
from market_arkhai_payments.adapter import PaymentAdapter
from market_arkhai_payments.receipts import verify_snapshot
from market_core.schemas import Agreement
from market_deal_lifecycle.adapters import (
    DisputeAdapterTable, DisputeBinding, PaymentAdapterTable, PaymentBinding, PaymentSelector,
)
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_buyer import BuyerDeal, BuyerLifecycle
from market_deal_lifecycle_client import LifecycleClient
from market_identity import Identity, canonical_json

from .evidence import evidence_store


def run_sync(action):
    """Keep a synchronous command independent of its caller's event loop."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(action())).result()


class _MediationPort:
    """Local claim verification does not depend on an available credential.

    Resolve authentication only at network I/O, so a missing credential cannot
    prevent physical surrender or discard its durable filing for later retry.
    """

    def __init__(self, authority, credential):
        self.authority = authority
        self.credential = credential
        self.client = None

    async def _call(self, method, *args, **kwargs):
        if self.client is None:
            if self.credential is None:
                raise MediationTransportError("the Agreement authority has no configured buyer credential")
            try:
                self.client = MediationClient(self.authority, MediationCredential(
                    self.authority.identity, token=self.credential.resolve(),
                ))
            except ValueError as exc:
                raise MediationTransportError("the Agreement authority credential is unavailable") from exc
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


@asynccontextmanager
async def buyer_lifecycle(*, agreement_bytes, settlement_data, seller_url, signer,
                          publishers, config, approval=None, store=None, transport=None):
    """Use accepted bytes, profile identity and fresh publisher trust, not defaults."""
    raw = json.loads(agreement_bytes)
    agreement = Agreement.model_validate(raw)
    if Identity.model_validate(agreement.buyer) != signer.identity:
        raise ValueError("profile signer differs from the accepted buyer")
    option = agreement.settlement
    if option is None:
        raise ValueError("lifecycle requires an accepted settlement option")
    mechanism = option.settlement_schema
    commitment = hashlib.sha256(canonical_json(raw)).hexdigest()
    payment = None
    if mechanism == ARKHAI_PAYMENTS_MECHANISM:
        # Recovery binds accepted terms, not today's admission policy. Physical
        # surrender remains available when no financial capability is configured.
        data = PaymentSettlementData.parse(settlement_data)
        data.require_bound_to(raw)
        commitment = data.transaction_id
        if approval is not None:
            if approval.payer_account != data.mandate.from_.root:
                raise ValueError("payment credential names another accepted payer")
            payment = PaymentAdapter(
                raw, data, account=approval.payer_account,
                client_for_owner=approval._client_for_owner,
                verify_snapshot=lambda signed, floor: verify_snapshot(
                    signed, approval.config.receipt_trust, mandate=data.mandate,
                    agreement_json=raw, livemode=approval.config.livemode,
                    minimum_sequence=floor,
                ),
            )
    terms = decode_terms(option.lifecycle)
    dispute = (DisputeBinding(agreement.negotiation_id, commitment, terms.adjudication.dispute)
               if terms else None)
    store = store or evidence_store()
    mediation = None
    disputes = []
    if dispute is not None and dispute.authority.interface == INTERFACE:
        mediation = _MediationPort(dispute.authority, config.disputes.credential_for(dispute.authority))
        adapter = MediationAdapter(dispute, raw, mediation)
        disputes = [(INTERFACE, lambda _: adapter)]
    deal = BuyerDeal(
        agreement.negotiation_id, commitment,
        PaymentBinding(agreement.negotiation_id, PaymentSelector(mechanism)), dispute,
        Identity.model_validate(agreement.buyer), Identity.model_validate(agreement.seller),
    )
    try:
        async with LifecycleClient(seller_url, signer, publishers, capture=store.capture,
                                   timeout=config.timeout_seconds, transport=transport) as peer:
            yield BuyerLifecycle(
                deal=lambda negotiation_id: deal, peer=peer, operations=store,
                payments=PaymentAdapterTable([(deal.payment.selector, lambda _: payment)] if payment else []),
                disputes=DisputeAdapterTable(disputes), evidence=store,
                end_journal=store.end_journal,
            )
    finally:
        if mediation is not None:
            await mediation.close()
