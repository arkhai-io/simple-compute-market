"""Conservative seller retention from complete authority and local recovery reads."""

from collections.abc import Callable
from pathlib import Path

from market_deal_lifecycle_contracts.models import Accepted, AuthorityView

from .evidence import RetentionObservation, transaction
from .journal import EndSession


def seller_retention(
    path: str | Path, negotiation_id: str, *, clock: Callable[[], int],
) -> Callable[[list[AuthorityView]], RetentionObservation | None]:
    """Compose on DealWatch; authority adapters supply opaque per-part payouts.

    Unknown payout completion, an open case/extension or unproven physical return
    keeps evidence. Recovery is observed now rather than inferred from an intent.
    """
    def observe(views: list[AuthorityView]) -> RetentionObservation | None:
        if not views or not all(isinstance(view.outcome, Accepted) for view in views):
            return None
        payouts = views[0].payouts
        if payouts is None:
            return None
        with transaction(path) as conn:
            end = EndSession(conn)
            delivery = end.read(negotiation_id)
            selected = end.selected_end(negotiation_id)
            row = conn.execute(
                "SELECT observation FROM servicing_evidence_deals WHERE negotiation_id=?", (negotiation_id,),
            ).fetchone()
            previous = RetentionObservation.model_validate_json(row[0]) if row and row[0] else None
        # A terminal once-part cannot regain held funds. Preserve the first
        # verified completion observation rather than sliding the prune window.
        if previous:
            payouts = {part: previous.payouts.get(part) if previous.payouts.get(part) is not None and at is not None else at
                       for part, at in payouts.items()}
        now = clock()
        cases: dict[str, int | None] = {case.case_ref: None for view in views for case in view.cases}
        for view in views:
            for case in view.cases:
                if case.state == "closed":
                    closes = [event.at for event in view.disputes
                              if event.case_ref == case.case_ref and event.kind == "closed"]
                    cases[case.case_ref] = max(closes) if closes else None
        return RetentionObservation(
            observed_at=now, delivery_ended_at=selected.ended_at if selected else None,
            recovered_at=((previous.recovered_at if previous and previous.recovered_at is not None else now)
                          if delivery.progress == "released" else None),
            payouts=payouts, cases=cases,
            open_extensions=[extension.extension_ref for view in views for extension in view.extensions],
            complete=True,
        )
    return observe
