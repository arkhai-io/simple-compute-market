from unittest.mock import AsyncMock, Mock

from market_deal_lifecycle.adapters import InterfaceRequest
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, CaseRecord, DisputeEvent, LifecycleCommand, ListDealsRequest,
    OpenExtension, Unknown,
)
from market_deal_servicing import EndSession, PhysicalResult
from market_deal_servicing.evidence import transaction
from market_deal_servicing.watch import WatchSession


async def test_ruling_applies_once_before_and_after_application_with_authority_actor(rig):
    rig["physical"].apply_end.return_value = PhysicalResult(done=True, progress="released")
    for sequence, applied in ((1, False), (2, True)):
        rig["dispute"].read.return_value = AuthorityView(outcome=Accepted(), disputes=[
            DisputeEvent(
                negotiation_id="deal", commitment_ref="commitment", case_ref="case", kind="ruled",
                actor="opaque-dispute-account", at=150, sequence=seq, record_ref=f"record-{seq}",
                outcome=[{"effect_id": "one-effect", "kind": "delivery_end", "at": 140,
                          "applied": applied if seq == sequence else False}],
            ) for seq in range(1, sequence + 1)
        ])
        watch = rig["watch"]()
        watch.actor = lambda _: rig["seller"].identity
        await watch.poll()
        await rig["end"].drive_physical("deal")
    assert rig["physical"].apply_end.await_count == 1
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        assert len(end.requests("deal")) == 1
        selected = end.view("deal").recorded_end
        assert selected.actor == rig["authority_signer"].identity
        assert selected.actor != rig["seller"].identity
        assert selected.source == "record-1" and selected.cause == "ruling"


class AppendAuthority:
    def __init__(self):
        self.view = AuthorityView(outcome=Accepted())
        self.read = AsyncMock(side_effect=lambda: self.view)
        self.submit = AsyncMock(side_effect=[Unknown(reason="lost append"), Accepted()])
        self.build_append = Mock(side_effect=lambda case, items: {"case_ref": case, "items": []})


async def test_journal_before_cursor_and_restart_replays_append_even_after_close(rig):
    adapter = AppendAuthority()
    filed = DisputeEvent(
        negotiation_id="deal", commitment_ref="commitment", case_ref="case", kind="filed",
        actor="buyer-account", at=140, sequence=1, record_ref="filed",
    )
    adapter.view = AuthorityView(outcome=Accepted(), disputes=[filed])
    watch = rig["watch"](dispute=adapter)
    await watch.poll()
    with transaction(rig["path"]) as conn:
        assert WatchSession(conn).cursor("deal", watch.dispute_record) == 1
        intent = next(item for item in EndSession(conn).intents("deal") if item.kind == "append")
        assert intent.state == "pending"
    adapter.view = AuthorityView(outcome=Accepted(), disputes=[filed], cases=[
        CaseRecord(case_ref="case", state="closed", record_ref="closed"),
    ])
    await rig["watch"](dispute=adapter).poll()
    assert adapter.submit.await_count == 2
    first, second = adapter.submit.await_args_list
    assert first.args[0] == second.args[0] and first.args[2] == second.args[2]
    # Cases entirely closed during downtime never send a new append.
    other = filed.model_copy(update={"case_ref": "closed-case", "sequence": 2, "record_ref": "filed-2"})
    adapter.view = AuthorityView(outcome=Accepted(), disputes=[filed, other], cases=[
        CaseRecord(case_ref="closed-case", state="closed", record_ref="closed-2"),
    ])
    await rig["watch"](dispute=adapter).poll()
    assert adapter.submit.await_count == 2


async def test_independent_authority_sequences_and_overlapping_extensions(rig):
    extensions = [
        OpenExtension(part="0", extension_ref="a", case_ref="case-a", until=None),
        OpenExtension(part="0", extension_ref="b", case_ref="case-b", until=300),
    ]
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), extensions=extensions)
    rig["dispute"].read.return_value = AuthorityView(outcome=Accepted(), disputes=[DisputeEvent(
        negotiation_id="deal", commitment_ref="commitment", case_ref="case-a", kind="closed",
        actor="authority", at=150, sequence=50, record_ref="record-50",
    )])
    api = rig["service"]()
    assert (await api.read("deal")).authority.extensions == extensions
    watch = rig["watch"]()
    with transaction(rig["path"]) as conn:
        session = WatchSession(conn)
        assert session.cursor("deal", watch.dispute_record) == 50
        assert session.cursor("deal", watch.payment_record) == -1
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), extensions=extensions[1:])
    assert (await api.read("deal")).authority.extensions == extensions[1:]


async def test_seller_pages_pinned_authority_repair_and_operator_end_filing(rig):
    api = rig["service"]()
    assert (await api.list()).deals[0].state == "running"
    assert (await api.list(ListDealsRequest(continuation="deal"))).deals == []
    rig["credentials"][0] = False
    assert (await api.list()).deals[0].state == "repair_required"
    assert "credential" in (await api.read("deal")).authority.outcome.reason
    rig["credentials"][0] = True
    adapter = rig["dispute"]
    adapter.supported_commands = {"delivery_end"}
    adapter.supported_intents = {"delivery_end"}
    adapter.build_request = Mock(return_value=InterfaceRequest(interface=rig["authority"].interface, payload={}))
    adapter.validate_request = Mock(return_value=None)
    adapter.submit.side_effect = [Unknown(reason="lost filing"), Accepted()]
    command = LifecycleCommand(negotiation_id="deal", kind="delivery_end", operation_key="operator")
    outcome = await api.submit(command, actor=rig["seller"].identity, reason="maintenance")
    assert isinstance(outcome, Unknown)
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        assert end.selected_end("deal").administrator_reason == "maintenance"
        assert len([item for item in end.intents("deal") if item.kind == "filing"]) == 1
    # No payment stop or reverse, and a filing never waits for a ruling to end delivery.
    rig["payment"].submit.assert_not_called()
    assert (await rig["service"]().submit(command, actor=rig["seller"].identity, reason="maintenance")).status == "accepted"
    assert adapter.submit.await_args_list[0].args[0] == adapter.submit.await_args_list[1].args[0]
    assert (await api.read("deal")).delivery.recorded_end is not None
    assert (await api.list()).deals[0].state == "ending"
