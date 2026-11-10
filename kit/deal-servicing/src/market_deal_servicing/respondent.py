"""Answer discovery with journal-before-I/O and append-before-cursor progress."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from market_deal_lifecycle.adapters import DisputeAdapter
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle.respondent import RespondentAdapter, RespondentCase, RespondentPage
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import Accepted, EvidenceItem, LifecycleCommand, Rejected
from market_identity import Signer, canonical_json

from .evidence import EvidenceSession, in_transaction, transaction
from .journal import Classification, EndSession, atomic, stable_ref
from .seller import SellerSession


class RespondentPoller:
    """One bounded cycle per accepted authority/account, under the loop controller.

    Resolve only exact accepted Agreements at this authority, using payee
    credentials. Discovery owns counterparty answers; watches never preempt
    concurrence with plain appends. Unknown writes retry after listing omission.
    """

    def __init__(
        self, path: str | Path, *, authority: DisputeAuthority, account: str,
        read: Callable[[str, int], Awaitable[RespondentPage]],
        resolve: Callable[[RespondentCase], tuple[str, DisputeAdapter] | None],
        signer: Signer, clock: Callable[[], int],
    ):
        self.path = Path(path)
        self.authority = authority
        self.read = read
        self.resolve = resolve
        self.signer = signer
        self.clock = clock
        self.record = stable_ref(account, "respondent", canonical_json(authority.identity).decode())

    async def _database(self, operation):
        # Its tables are the storefront chain's (market_deal_servicing.schema):
        # a poll issues no DDL.
        return await in_transaction(self.path, operation)

    async def repairs(self, limit: int = 100) -> list[dict]:
        """Unresolved cases stay visible and retry independently of the listing page."""
        return await self._database(lambda conn: [
            {"case": RespondentCase.model_validate_json(row[0]), "reason": row[1]}
            for row in conn.execute(
                "SELECT case_json,reason FROM servicing_respondent_repairs WHERE record=? ORDER BY rowid LIMIT ?",
                (self.record, limit),
            ).fetchall()
        ])

    def prepare(self, negotiation_id: str, adapter: DisputeAdapter, case: RespondentCase):
        if not isinstance(adapter, RespondentAdapter) or adapter.binding.authority != self.authority:
            raise ValueError("respondent adapter does not bind the accepted authority")
        with transaction(self.path) as conn, atomic(conn):
            deal = SellerSession(conn).read(negotiation_id)
            if deal.dispute != self.authority or deal.commitment_ref != case.commitment_ref:
                raise ValueError("respondent case differs from the registered deal")
            end = EndSession(conn)
            key = stable_ref(negotiation_id, "append", case.case_ref)
            previous = end.intent(stable_ref(negotiation_id, "append", key))
            if previous is not None:
                return previous
            record = end.read(negotiation_id)
            intent = case.intent
            delivered = record.available_at is not None and (
                intent is not None and record.available_at <= intent.ended_at
            )
            matching = False
            selected = end.selected_end(negotiation_id)
            if intent is not None and intent.delivered == delivered:
                if intent.cause == "payer":
                    for request in end.requests(negotiation_id):
                        row = conn.execute(
                            "SELECT classification FROM servicing_final_requests WHERE negotiation_id=? AND source_ref=?",
                            (negotiation_id, request.source_ref),
                        ).fetchone()
                        classification = Classification.model_validate_json(row[0]) if row and row[0] else None
                        if (request == selected and request.ended_at == intent.ended_at and request.actor == deal.buyer
                                and classification is not None
                                and classification.kind in {"buyer_surrender", "entitled_stop"}):
                            matching = True
                            break
                else:
                    matching = any(
                        journal.kind == "filing" and journal.payload.get("payload") == intent.model_dump(mode="json")
                        for journal in end.intents(negotiation_id)
                    )
            items = list(EvidenceSession(conn).read(negotiation_id).items)
            if not matching:
                body = canonical_json({
                    "case": case.model_dump(mode="json"), "available_at": record.available_at,
                    "ends": [request.model_dump(mode="json") for request in end.requests(negotiation_id)],
                    "position": "The requested end facts do not match durable available/end records.",
                })
                contest = EvidenceItem(
                    evidence_id="respondent-contest:" + case.case_ref, kind="respondent_contest",
                    classification="seller_assertion", recorded_at=self.clock(),
                    body=base64.b64encode(body),
                )
                EvidenceSession(conn).put(negotiation_id, contest)
                items.append(contest)
            payload = adapter.build_answer(case, matching=matching, items=items, signer=self.signer)
            if isinstance(payload, Rejected):
                raise ValueError(payload.reason)
            command = LifecycleCommand(
                negotiation_id=negotiation_id, kind="append", operation_key=key, payload=payload,
            )
            return end.journal(
                negotiation_id, "append", key, command.model_dump(mode="json"), not_before=case.filed_at,
            )

    async def poll(self, limit: int = 100) -> dict[str, int | str]:
        row = await self._database(lambda conn: conn.execute(
            "SELECT cursor,page FROM servicing_respondent WHERE record=?", (self.record,),
        ).fetchone())
        cursor, stored = row if row else ("", None)
        page = RespondentPage.model_validate_json(stored) if stored else await self.read(cursor, limit)
        await in_transaction(self.path, lambda conn: conn.execute(
            "INSERT INTO servicing_respondent VALUES (?,?,?) ON CONFLICT(record) DO UPDATE SET page=excluded.page",
            (self.record, cursor, page.model_dump_json()),
        ).rowcount)
        repairs = await self.repairs(limit)
        cases = {case.case_ref: case for case in page.cases}
        for repair in repairs[:limit]:
            cases.setdefault(repair["case"].case_ref, repair["case"])
        answered = skipped = 0
        for case in cases.values():
            try:
                resolved = await asyncio.to_thread(self.resolve, case)
                if resolved is None:
                    local = await self._database(lambda conn: conn.execute(
                        """SELECT 1 FROM servicing_seller_deals
                           WHERE json_extract(deal, '$.commitment_ref')=? LIMIT 1""",
                        (case.commitment_ref,),
                    ).fetchone())
                    if local is None:
                        # Account discovery spans storefronts. Only a locally
                        # registered commitment can owe a repair on this worker.
                        await in_transaction(self.path, lambda conn: conn.execute(
                            "DELETE FROM servicing_respondent_repairs WHERE record=? AND case_ref=?",
                            (self.record, case.case_ref),
                        ).rowcount)
                        skipped += 1
                        continue
                    raise ValueError("accepted local Agreement is temporarily unavailable")
                negotiation_id, adapter = resolved
                intent = await asyncio.to_thread(self.prepare, negotiation_id, adapter, case)
            except (KeyError, ValueError) as exc:
                reason = str(exc)
                await in_transaction(self.path, lambda conn: conn.execute(
                    "INSERT OR REPLACE INTO servicing_respondent_repairs VALUES (?,?,?,?,?)",
                    (self.record, case.case_ref, case.commitment_ref, case.model_dump_json(), reason),
                ).rowcount)
                skipped += 1
                continue
            await in_transaction(self.path, lambda conn: conn.execute(
                "DELETE FROM servicing_respondent_repairs WHERE record=? AND case_ref=?",
                (self.record, case.case_ref),
            ).rowcount)
            if intent.state == "pending":
                command = LifecycleCommand.model_validate(intent.payload)
                await in_transaction(self.path, lambda conn: EndSession(conn).acknowledge(
                    intent.intent_ref, {"attempted": True}, state="pending",
                ))
                outcome = await adapter.submit(
                    command, None, OperationKeys(negotiation_id, command.operation_key),
                )
                state: Literal["done", "pending", "skipped"] = "done" if isinstance(outcome, Accepted) else "pending"
                if isinstance(outcome, Rejected):
                    view = await adapter.read()
                    if isinstance(view.outcome, Accepted) and any(
                        item.case_ref == case.case_ref and item.state == "closed" for item in view.cases
                    ):
                        state = "skipped"
                await in_transaction(self.path, lambda conn: EndSession(conn).acknowledge(
                    intent.intent_ref, outcome.model_dump(mode="json"), state=state,
                ))
                if state == "pending":
                    return {"answered": answered, "cursor": cursor,
                            "pending": len(cases) - answered - skipped, "skipped": skipped}
            answered += 1
        await in_transaction(self.path, lambda conn: conn.execute(
            "UPDATE servicing_respondent SET cursor=?,page=NULL WHERE record=?", (page.next_after, self.record),
        ).rowcount)
        return {"answered": answered, "cursor": page.next_after, "pending": 0, "skipped": skipped}
