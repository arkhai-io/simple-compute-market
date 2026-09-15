"""One capacity-event cycle is callable, and a dry run of it changes nothing.

The feed position used to live in the poller's closure, so a single cycle was
not callable from anywhere else: a scenario that paused the loop could only
wait for it, and waiting on a poller is the sleep this suite forbids. These
tests bind the extracted cycle and the invariant that made the extraction
delicate -- one position per site, shared by the poller and any advance,
because a second cursor would replay events or skip past them.
"""

from __future__ import annotations

import pytest

from market_capacity_publication.capacity_remote import (
    drain_site_events_once,
    preview_site_events,
    reset_site_event_cursors,
    site_event_cursor,
    site_events_poller,
)


class FakeSiteClient:
    """A site authority's event feed, one scripted page per read."""

    base_url = "http://site.invalid"

    def __init__(self, pages: list[tuple[list[dict], int]]) -> None:
        self._pages = list(pages)
        self.reads: list[tuple[int, int | None]] = []

    async def events_after(self, after: int, limit: int | None = None):
        self.reads.append((after, limit))
        if not self._pages:
            return [], after
        return self._pages.pop(0)


class FakeAggregate:
    def __init__(self) -> None:
        self.deltas: list[tuple[str, str, int, str | None]] = []

    async def emit_site_delta(self, site: str, delta) -> None:
        self.deltas.append((site, delta.kind, delta.version, delta.resource_id))


class RecordingReconcile:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1


@pytest.fixture(autouse=True)
def _fresh_cursors():
    reset_site_event_cursors()
    yield
    reset_site_event_cursors()


def _event(version: int, kind: str = "reserved", resource_id: str | None = None):
    payload: dict = {"kind": kind, "version": version}
    if resource_id is not None:
        payload["resource_id"] = resource_id
    return payload


class TestPositioning:
    async def test_the_first_cycle_positions_and_full_reconciles(self):
        """Converge with what happened while down, rather than replaying it."""
        cursor = site_event_cursor("default")
        client = FakeSiteClient([([], 7), ([], 7)])
        reconcile = RecordingReconcile()

        cycle = await drain_site_events_once(
            FakeAggregate(), client, cursor, full_reconcile=reconcile
        )

        assert cycle.positioned is True
        assert reconcile.calls == 1
        assert cycle.applied == ()
        assert cursor.last_applied == 7

    async def test_a_later_cycle_does_not_reposition(self):
        cursor = site_event_cursor("default")
        cursor.last_applied = 7
        reconcile = RecordingReconcile()

        cycle = await drain_site_events_once(
            FakeAggregate(),
            FakeSiteClient([([_event(8)], 8)]),
            cursor,
            full_reconcile=reconcile,
        )

        assert cycle.positioned is False
        assert reconcile.calls == 0


class TestOneCycleAppliesExactlyItsPage:
    async def test_events_are_emitted_in_order_and_move_the_cursor(self):
        cursor = site_event_cursor("default")
        cursor.last_applied = 7
        aggregate = FakeAggregate()

        cycle = await drain_site_events_once(
            aggregate,
            FakeSiteClient([([_event(8, "released", "r1"), _event(9)], 9)]),
            cursor,
            full_reconcile=RecordingReconcile(),
        )

        assert aggregate.deltas == [
            ("default", "released", 8, "r1"),
            ("default", "reserved", 9, None),
        ]
        assert [event["version"] for event in cycle.applied] == [8, 9]
        assert cursor.last_applied == 9
        assert cycle.cursor == 9
        assert cycle.truncated is False

    async def test_a_truncated_page_is_reported_not_drained(self):
        """The caller decides how far to step; the cycle does one page.

        An advance route that drained to the head would collapse several
        state changes into one call, which is the opposite of what stepping
        a held loop is for.
        """
        cursor = site_event_cursor("default")
        cursor.last_applied = 7
        client = FakeSiteClient([([_event(8)], 12)])

        cycle = await drain_site_events_once(
            FakeAggregate(), client, cursor, full_reconcile=RecordingReconcile()
        )

        assert cycle.truncated is True
        assert cycle.cursor == 8
        assert cycle.feed_head == 12
        assert len(client.reads) == 1, "one cycle reads one page"

    async def test_a_backwards_feed_head_resyncs_instead_of_replaying(self):
        cursor = site_event_cursor("default")
        cursor.last_applied = 20
        reconcile = RecordingReconcile()
        aggregate = FakeAggregate()

        cycle = await drain_site_events_once(
            aggregate,
            FakeSiteClient([([_event(3)], 3)]),
            cursor,
            full_reconcile=reconcile,
        )

        assert cycle.resynced is True
        assert reconcile.calls == 1
        assert aggregate.deltas == [], "a reset feed is reconciled, not replayed"
        assert cursor.last_applied == 3

    async def test_a_failing_read_is_reported_rather_than_raised(self):
        """An advance route answers with the failure; a poller keeps its loop."""

        class Unreachable:
            base_url = "http://site.invalid"

            async def events_after(self, after, limit=None):
                raise RuntimeError("401 unsigned response")

        cursor = site_event_cursor("default")
        cursor.last_applied = 7

        cycle = await drain_site_events_once(
            FakeAggregate(),
            Unreachable(),
            cursor,
            full_reconcile=RecordingReconcile(),
        )

        assert cycle.error is not None and "401" in cycle.error
        assert cursor.last_applied == 7, "a failed cycle moves nothing"


class TestTheDryRunChangesNothing:
    async def test_it_names_the_pending_events_without_emitting_them(self):
        cursor = site_event_cursor("default")
        cursor.last_applied = 7
        aggregate = FakeAggregate()
        reconcile = RecordingReconcile()

        preview = await preview_site_events(
            FakeSiteClient([([_event(8, "released", "r1"), _event(9)], 9)]),
            cursor,
        )

        assert [event["version"] for event in preview.pending] == [8, 9]
        assert preview.cursor == 7 and preview.feed_head == 9
        assert cursor.last_applied == 7, "the cursor may not move"
        assert aggregate.deltas == [] and reconcile.calls == 0

    async def test_two_dry_runs_report_the_same_thing(self):
        cursor = site_event_cursor("default")
        cursor.last_applied = 7
        page = ([_event(8)], 8)

        first = await preview_site_events(FakeSiteClient([page]), cursor)
        second = await preview_site_events(FakeSiteClient([page]), cursor)

        assert first.to_dict() == second.to_dict()

    async def test_it_says_when_the_next_cycle_would_position(self):
        """An unpositioned cursor means the next cycle full-reconciles.

        A scenario asserting on its own deal's events needs to know the
        difference: a positioning cycle converges from a snapshot and applies
        none of them.
        """
        preview = await preview_site_events(
            FakeSiteClient([([], 7)]), site_event_cursor("default")
        )

        assert preview.would_position is True
        assert preview.pending == ()
        assert preview.feed_head == 7

    async def test_it_reports_an_unreachable_feed_rather_than_raising(self):
        class Unreachable:
            base_url = "http://site.invalid"

            async def events_after(self, after, limit=None):
                raise RuntimeError("connection refused")

        preview = await preview_site_events(Unreachable(), site_event_cursor("s"))

        assert preview.error is not None
        assert preview.pending == ()


class TestOnePositionPerSite:
    async def test_the_poller_and_an_advance_share_one_cursor(self):
        """The invariant that made this extraction delicate.

        Two cursors for one feed would either replay what the other applied
        or skip past it. The pause is what makes sharing safe: a cycle either
        runs completely or never starts, so an advance under the pause has the
        feed to itself.
        """
        advance_cursor = site_event_cursor("default")
        advance_cursor.last_applied = 7
        aggregate = FakeAggregate()

        await drain_site_events_once(
            aggregate,
            FakeSiteClient([([_event(8)], 8)]),
            advance_cursor,
            full_reconcile=RecordingReconcile(),
        )

        # A poller starting now inherits the advanced position rather than
        # re-reading from 7 and emitting event 8 a second time.
        assert site_event_cursor("default").last_applied == 8
        assert site_event_cursor("other").last_applied is None

    async def test_the_poller_body_is_the_extracted_cycle(self):
        """Held means held: a paused poller runs no cycle at all.

        Binds the loop to the same function the advance route calls, so the
        two cannot drift into different behaviour for the same feed.
        """
        client = FakeSiteClient([([_event(8)], 8)])
        gate_reads = 0

        def paused() -> bool:
            nonlocal gate_reads
            gate_reads += 1
            raise _StopPoller

        with pytest.raises(_StopPoller):
            await site_events_poller(
                FakeAggregate(),
                "default",
                client,
                0.01,
                full_reconcile=RecordingReconcile(),
                paused=paused,
            )

        assert gate_reads == 1
        assert client.reads == [], "the gate is consulted before any request"
        assert site_event_cursor("default").last_applied is None


class _StopPoller(BaseException):
    """Escape hatch: stop the poller's infinite loop from inside its gate."""
