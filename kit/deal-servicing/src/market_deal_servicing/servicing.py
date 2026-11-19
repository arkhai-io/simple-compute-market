"""One kit-owned order for servicing a page of a storefront's deals.

A storefront's servicing loop runs :meth:`ServicingCycle.cycle`. The cycle
first discovers counterparty cases, once per dispute authority, then runs each
deal's steps in one order: the authorities read, the domain's recovery steps,
the physical end, local reconciliation, site-report correction, filing dispatch
and the physical end again. Each step runs in its own error handler, so a
failed step never skips the steps after it. The physical end runs twice
because reconciliation, correction and filing may record an end the first
drive could not see. See openspec/specs/deal-lifecycle/spec.md, "Each deal's
servicing steps run in one kit-owned order".
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Protocol, runtime_checkable

from market_deal_lifecycle.adapters import DisputeAdapter, DisputeBinding
from market_deal_lifecycle.respondent import RespondentAdapter, RespondentCase
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import ListDealsRequest
from market_identity import Signer

from .end import EndService
from .evidence import in_transaction, transaction
from .journal import Classification, EndSession, FinalRequest
from .projection import SellerDeal
from .respondent import RespondentPoller
from .seller import SellerServicing, SellerSession

logger = logging.getLogger(__name__)

#: The term end's source reference: one per deal, recorded once.
TERM_END_SOURCE = "term-end"


class RespondentPort(Protocol):
    """What a domain answers for respondent discovery."""

    def credential_available(self, authority: DisputeAuthority) -> bool:
        """Whether the authority's credential can build a client."""
        ...

    def dispute_adapter(self, binding: DisputeBinding) -> DisputeAdapter:
        """The deal's dispute adapter over its accepted Agreement."""
        ...


@runtime_checkable
class AgreementRespondent(RespondentAdapter, Protocol):
    """A respondent adapter bound to one accepted Agreement by its digest.

    A listed case names the Agreement it was filed under by that digest, so
    discovery resolves a case to a local deal only when they agree.
    """

    agreement_digest: str


#: A domain recovery step, run for each deal after the authorities read.
RecoveryStep = Callable[[SellerDeal], Awaitable[object]]

#: The domain's site-report correction, applying its site-report classifier to
#: each pending site report of one deal inside the caller's transaction.
SiteCorrections = Callable[[EndSession, str, int], None]


class ServicingCycle:
    """A storefront's servicing of its deals, one page per cycle.

    ``loop`` names the page position the cycle keeps in kit-owned state
    (``servicing_page_position``), so a restarted storefront resumes from it.
    ``recovery`` holds the domain's named recovery steps, run in order.
    """

    def __init__(
        self, path: str | Path, *, domain: str, loop: str, seller: SellerServicing, end: EndService,
        respondents: RespondentPort, signer: Signer, clock: Callable[[], int],
        recovery: Sequence[tuple[str, RecoveryStep]] = (),
        resolve_site_corrections: SiteCorrections,
    ):
        self.path = Path(path)
        self.domain = domain
        self.loop = loop
        self.seller = seller
        self.end = end
        self.respondents = respondents
        self.signer = signer
        self.clock = clock
        self.recovery = tuple(recovery)
        self.resolve_site_corrections = resolve_site_corrections

    async def cycle(self, *, limit: int = 100) -> int:
        """Service one page of every registered deal, committed or not; the
        number of deals it held."""
        deals, continuation = await in_transaction(self.path, lambda conn: self._page(conn, limit))
        await self.discover(deals)
        for deal in deals:
            await self.service(deal)
        # Saved once the page is serviced, so a storefront stopped mid-page
        # services that page again rather than skipping its remaining deals,
        # and a page that reached the end starts the next cycle from the first.
        await in_transaction(self.path, lambda conn: conn.execute(
            """INSERT INTO servicing_page_position VALUES (?,?)
               ON CONFLICT(loop) DO UPDATE SET continuation=excluded.continuation""",
            (self.loop, continuation),
        ).rowcount)
        return len(deals)

    def _page(self, conn: sqlite3.Connection, limit: int) -> tuple[list[SellerDeal], str | None]:
        row = conn.execute(
            "SELECT continuation FROM servicing_page_position WHERE loop=?", (self.loop,),
        ).fetchone()
        return SellerSession(conn).page(
            ListDealsRequest(limit=limit, continuation=row[0] if row else None), committed_only=False,
        )

    async def discover(self, deals: Sequence[SellerDeal]) -> None:
        """Run respondent discovery once per dispute authority of the page.

        The respondent listing is scoped by the authority's one credential, so
        one discovery serves every deal under that authority, whichever comes
        first on the page. A deal with no dispute authority, or whose
        authority's credential is unusable, is left out; its credential repair
        already shows it. One authority's failure is logged and every other
        authority still runs.
        """
        authorities: dict[str, SellerDeal] = {}
        for deal in deals:
            if deal.dispute is not None:
                authorities.setdefault(deal.dispute.model_dump_json(), deal)
        for deal in authorities.values():
            authority = deal.dispute
            binding = deal.dispute_binding
            if authority is None or binding is None:
                continue
            try:
                if not self.respondents.credential_available(authority):
                    continue
                adapter = self.respondents.dispute_adapter(binding)
                if not isinstance(adapter, AgreementRespondent):
                    continue
                await RespondentPoller(
                    self.path, authority=authority, read=adapter.respondent,
                    resolve=partial(self._resolve, authority),
                    signer=self.signer, clock=self.clock,
                ).poll()
            except Exception:
                logger.exception(
                    "%s servicing step respondent discovery awaits recovery for authority %s",
                    self.domain, authority.identity,
                )

    def _resolve(self, authority: DisputeAuthority, case: RespondentCase) -> tuple[str, DisputeAdapter] | None:
        """The local deal and dispute adapter a listed case names, or ``None``.

        A case whose Agreement digest differs from the local deal's raises, so
        the poller keeps it as a repair naming the mismatch.
        """
        with transaction(self.path) as conn:
            rows = conn.execute(
                "SELECT deal FROM servicing_seller_deals WHERE json_extract(deal, '$.commitment_ref')=?",
                (case.commitment_ref,),
            ).fetchall()
        for row in rows:
            deal = SellerDeal.model_validate_json(row[0])
            if deal.dispute != authority or deal.dispute_binding is None:
                continue
            adapter = self.respondents.dispute_adapter(deal.dispute_binding)
            if not isinstance(adapter, AgreementRespondent) or adapter.agreement_digest != case.agreement_ref:
                raise ValueError("respondent case differs from accepted Agreement")
            return deal.negotiation_id, adapter
        return None

    async def service(self, deal: SellerDeal) -> None:
        """Run one deal's steps in the kit's order, each isolated."""
        steps: list[tuple[str, Callable[[], Awaitable[object]]]] = [
            ("authorities read", lambda: self.read_authorities(deal)),
            *((name, lambda step=step: step(deal)) for name, step in self.recovery),
            ("physical end", lambda: self.end.drive_physical(deal.negotiation_id)),
            ("local reconciliation", lambda: in_transaction(
                self.path, lambda conn: self.reconcile(EndSession(conn), deal.negotiation_id),
            )),
            ("site-report correction", lambda: in_transaction(
                self.path, lambda conn: self.resolve_site_corrections(
                    EndSession(conn), deal.negotiation_id, self.clock(),
                ),
            )),
            ("filing dispatch", lambda: self.seller.dispatch_filings(deal.negotiation_id)),
            ("physical end", lambda: self.end.drive_physical(deal.negotiation_id)),
        ]
        for name, step in steps:
            try:
                await step()
            except Exception:
                logger.exception(
                    "%s servicing step %s awaits recovery for %s", self.domain, name, deal.negotiation_id,
                )

    async def read_authorities(self, deal: SellerDeal) -> None:
        """Read the payment and dispute authorities of a committed deal.

        The payment authority is read before a missed deadline is admitted, so
        a buyer stop it recorded while the storefront was down is the deal's
        end rather than seller non-delivery; admission waits for that read
        itself, so a failed one delays the deadline to a later cycle. An
        uncommitted deal has no authority record to read. The read dispatches
        no filing: that is the filing step's alone.
        """
        committed = await in_transaction(
            self.path, lambda conn: EndSession(conn).read(deal.negotiation_id).committed_at is not None,
        )
        if committed:
            await self.seller.read(deal.negotiation_id)

    def reconcile(self, session: EndSession, negotiation_id: str) -> None:
        """Admit a missed delivery deadline, then record the term end once due.

        Admission establishes a missed deadline before the term end can turn
        non-delivery into a lawful end. While it holds that deadline for a
        payment observation, the term end waits too: at a deadline capped at
        the term end, it would otherwise be selected in the deadline's place.
        The term end is recorded at the Agreement's end, classified as the term
        end; a payment authority's own stop at the same instant sorts first.
        Admitting at the recorded phase writes nothing unless the deadline is
        recorded, so concurrent readers of the revision are not invalidated.
        """
        record = session.read(negotiation_id)
        if record.committed_at is None:
            return
        now = self.clock()
        admission = session.admit(negotiation_id, record.phase, record.revision, now=now)
        if admission.status == "awaiting_observation":
            return
        if now >= record.term_end and not any(
            request.source_ref == TERM_END_SOURCE for request in session.requests(negotiation_id)
        ):
            session.record_end(FinalRequest(
                negotiation_id=negotiation_id, source_ref=TERM_END_SOURCE, ended_at=record.term_end,
                observed_at=now, actor=record.seller, cause="terms", source="agreement",
                evidence_refs=[record.commitment_ref],
            ), now=now, classification=Classification(kind="terms", evidence_refs=[record.commitment_ref]))
