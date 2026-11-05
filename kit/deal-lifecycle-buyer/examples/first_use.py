"""Exercise the buyer half through injected authority and storefront seams."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from market_deal_lifecycle.adapters import (
    DisputeAdapterTable, DisputeBinding, PaymentAdapterTable, PaymentBinding, PaymentSelector,
)
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, CaseRecord, DeliveryView, FilingAnswer, LifecycleCommand,
    LifecycleRead, OpenExtension, PartHold, Pending, SubmitResponse, Unknown,
)
from market_deal_lifecycle_buyer import BuyerDeal, BuyerLifecycle, FileEvidenceStore


async def main():
    authority = DisputeAuthority(interface="example.dispute.v1", origin="https://dispute.example",
                                 account="example-authority", record_key="example-key", params={})
    binding = DisputeBinding("example", "example-commitment", authority)
    deal = BuyerDeal("example", "example-commitment", PaymentBinding("example", PaymentSelector("example.payment.v1")), binding)
    sent = []
    hints = []

    class Payment:
        supported_commands = frozenset({"stop"})

        def validate(self, command):
            return None

        async def submit(self, command, keys):
            sent.append(("payment", command, keys))
            return Accepted()

        async def read(self):
            return AuthorityView(outcome=Accepted(), state="running", extensions=[
                OpenExtension(part="held", extension_ref="extension-example", case_ref="case-example", until=None),
            ])

    class Dispute:
        supported_commands = frozenset({"dispute", "append"})
        supported_intents = frozenset()
        answer = Accepted(filing=FilingAnswer(case_ref="case-example", record_ref="record-example", parts=[
            PartHold(part="held", status="held", reason="extended", extension_ref="extension-example"),
            PartHold(part="paid", status="not_held", reason="paid out"),
        ]))

        def validate_request(self, request):
            return None

        def build_append(self, case_ref, items):
            return {"case_ref": case_ref, "items": []}

        async def submit(self, command, request, keys):
            sent.append(("dispute", command, keys))
            return self.answer

        async def read(self):
            return AuthorityView(outcome=Accepted(), cases=[
                CaseRecord(case_ref="case-example", state="filed", record_ref="record-example"),
            ])

    class Peer:
        available = True

        async def read(self, negotiation_id):
            return LifecycleRead(negotiation_id=negotiation_id, commitment_ref=deal.commitment_ref,
                                 authority=AuthorityView(outcome=Unknown(reason="seller authority view is not used")),
                                 delivery=DeliveryView(progress="active"))

        async def hint(self, message):
            hints.append(message)
            if not self.available:
                raise OSError("storefront unavailable")
            return SubmitResponse(outcome=Accepted())

    peer = Peer()
    dispute = Dispute()
    notices = []

    async def observe(message, outcome):
        notices.append(outcome)

    with TemporaryDirectory() as root:
        payments = PaymentAdapterTable([(deal.payment.selector, lambda _: Payment())])
        disputes = DisputeAdapterTable([(authority.interface, lambda _: dispute)])

        def half(payments=payments):
            return BuyerLifecycle(deal=lambda _: deal, payments=payments, disputes=disputes,
                                  operations=FileEvidenceStore(Path(root)), peer=peer, observe_hint=observe)

        command = LifecycleCommand(negotiation_id="example", kind="dispute", operation_key="filing-example",
                                   payload={"interface": authority.interface, "payload": {"claim": "outage"}})
        answer = await half().submit(command)
        assert answer is dispute.answer and answer.filing.parts[1].status == "not_held"
        assert [row[0] for row in sent] == ["dispute"]
        assert len(hints) == 1
        first_key = sent[-1][2].filing()
        assert (await half().submit(command)) is answer
        assert sent[-1][2].filing() == first_key and hints[0] == hints[1]
        before = len(sent)
        assert (await half().submit(command.model_copy(update={"at": 1}))).status == "rejected"
        assert len(sent) == before
        dispute.answer = Pending(reason="authority could not complete extension")
        assert (await half().submit(command)).status == "pending"
        dispute.answer = Unknown(reason="filing answer lost")
        assert (await half().submit(command)).status == "unknown"
        read = await half().read("example")
        assert read.authority.cases[0].case_ref == "case-example"
        assert read.authority.extensions[0].part == "held"
        assert read.authority.state == "running" and read.delivery.progress == "active"
        # A late filing is sent; only the authority decides its admissibility.
        late = command.model_copy(update={"operation_key": "late-example", "at": 999999})
        dispute.answer = answer
        peer.available = False
        assert (await half().submit(late)) is answer
        assert notices[-1].status == "unknown"
        assert (await half().append("example", operation_key="append-example", case_ref="case-example", items=[])) is answer
        assert sent[-1][1].payload == {"case_ref": "case-example", "items": []}
        assert (await half().submit(LifecycleCommand(negotiation_id="example", kind="stop", operation_key="stop-example"))).status == "accepted"
        assert sent[-1][0] == "payment"
        no_adapter = await half(PaymentAdapterTable([])).read("example")
        assert no_adapter.authority.outcome.status == "rejected" and "example.payment.v1" in no_adapter.authority.outcome.reason
        assert no_adapter.delivery == read.delivery
    print("filing outcomes preserved; mixed parts, pending extension, lost answer/read, late filing, stable retries, append, payment dispatch, independent hints and delivery-only read passed")


asyncio.run(main())
