"""The family's re-drive over a domain's recovery ports, driving the real path.

The deal is the rig's, committed and waiting for its Agreement start, over the
rig's SQLite and its end service; the recovery port is a double that lists,
claims and re-checks as a domain's would, recording each call.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from compute_delivery import OutcomeKind, recover_deliveries


class RecoveryPort:
    """A domain's recovery ports: its listing, its serialization and its re-check."""

    def __init__(self, unfinished: list[str]) -> None:
        self.unfinished = unfinished
        #: Deals another worker holds.
        self.held: set[str] = set()
        #: What the re-check answers, by deal; unnamed deals re-check.
        self.answers: dict[str, bool | Exception] = {}
        self.limits: list[int] = []
        self.calls: list[tuple[str, str]] = []

    async def unfinished_deliveries(self, *, limit):
        self.limits.append(limit)
        return list(self.unfinished)[:limit]

    @asynccontextmanager
    async def claim(self, negotiation_id):
        claimed = negotiation_id not in self.held
        self.calls.append(("claim", negotiation_id))
        try:
            yield claimed
        finally:
            self.calls.append(("release", negotiation_id))

    async def revalidate(self, negotiation_id):
        self.calls.append(("revalidate", negotiation_id))
        answer = self.answers.get(negotiation_id, True)
        if isinstance(answer, Exception):
            raise answer
        return answer


class RecordingPath:
    """The real path, its drives recorded in the order the routine made them."""

    def __init__(self, delivery, calls) -> None:
        self.delivery = delivery
        self.calls = calls
        self.outcomes = []

    async def drive(self, negotiation_id):
        self.calls.append(("drive", negotiation_id))
        outcome = await self.delivery.drive(negotiation_id)
        self.outcomes.append(outcome)
        return outcome


async def _waiting(rig):
    """The rig's deal committed before its start, as settlement leaves it."""
    rig.clock[0] = rig.start - 600
    assert (await rig.drive()).kind is OutcomeKind.WAITING
    rig.clock[0] = rig.start


async def test_a_claimed_re_checked_deal_is_driven_at_its_start(rig):
    await _waiting(rig)
    port = RecoveryPort(["deal"])
    path = RecordingPath(rig.delivery, port.calls)

    assert await recover_deliveries(path, port, limit=7) == 1

    assert port.limits == [7]
    assert port.calls == [("claim", "deal"), ("revalidate", "deal"), ("drive", "deal"), ("release", "deal")]
    assert [outcome.kind for outcome in path.outcomes] == [OutcomeKind.CONVERGED]
    assert len(rig.fulfillment.begins) == 1
    assert rig.progress.row(rig.path, "deal")["step"] == "activated"


async def test_a_deal_another_worker_holds_is_not_driven(rig):
    await _waiting(rig)
    port = RecoveryPort(["deal"])
    port.held.add("deal")
    path = RecordingPath(rig.delivery, port.calls)

    assert await recover_deliveries(path, port, limit=7) == 0

    assert port.calls == [("claim", "deal"), ("release", "deal")]
    assert rig.fulfillment.begins == []
    assert rig.progress.row(rig.path, "deal")["step"] == "commit"


async def test_a_deal_whose_evidence_does_not_re_check_is_not_driven(rig):
    await _waiting(rig)
    port = RecoveryPort(["deal"])
    port.answers["deal"] = False
    path = RecordingPath(rig.delivery, port.calls)

    assert await recover_deliveries(path, port, limit=7) == 0

    assert port.calls == [("claim", "deal"), ("revalidate", "deal"), ("release", "deal")]
    assert rig.fulfillment.begins == []
    assert rig.progress.row(rig.path, "deal")["step"] == "commit"


async def test_one_deal_failing_its_re_check_leaves_the_next_recovered(rig, caplog):
    await _waiting(rig)
    port = RecoveryPort(["unreadable", "deal"])
    port.answers["unreadable"] = RuntimeError("authority unreachable")
    path = RecordingPath(rig.delivery, port.calls)

    with caplog.at_level(logging.ERROR, logger="compute_delivery.recovery"):
        assert await recover_deliveries(path, port, limit=7) == 1

    assert port.calls == [
        ("claim", "unreadable"), ("revalidate", "unreadable"), ("release", "unreadable"),
        ("claim", "deal"), ("revalidate", "deal"), ("drive", "deal"), ("release", "deal"),
    ]
    assert [
        record.getMessage() for record in caplog.records if record.name == "compute_delivery.recovery"
    ] == ["[DELIVERY_RECOVERY] unreadable was not re-driven"]
    assert len(rig.fulfillment.begins) == 1
