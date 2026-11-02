import pytest
from market_deal_lifecycle_contracts.models import Accepted, AuthorityView, DisputeEvent, Rejected, Unknown

from market_deal_servicing.evidence import transaction
from market_deal_servicing.watch import WatchSession


@pytest.mark.parametrize("failure", [Unknown(reason="authority down"), Rejected(reason="bad signature")])
@pytest.mark.parametrize("record", ["payment", "dispute"])
async def test_current_read_failure_keeps_records_but_not_cached_success(rig, failure, record):
    api = rig["service"]()
    adapter = rig[record]
    adapter.read.return_value = AuthorityView(outcome=failure)
    assert (await api.read("deal")).authority.outcome == failure
    adapter.read.return_value = AuthorityView(outcome=Accepted())
    assert isinstance((await api.read("deal")).authority.outcome, Accepted)
    adapter.read.return_value = AuthorityView(outcome=failure)
    assert (await rig["service"]().read("deal")).authority.outcome == failure
    adapter.read.return_value = AuthorityView(outcome=Accepted())
    assert isinstance((await api.read("deal")).authority.outcome, Accepted)


@pytest.mark.parametrize("sequences", [[], [1]])
async def test_full_dispute_replay_enforces_durable_floor_after_restart(rig, sequences):
    def view(sequences):
        return AuthorityView(outcome=Accepted(), disputes=[DisputeEvent(
            negotiation_id="deal", commitment_ref="commitment", case_ref="case",
            kind="closed", actor="authority", at=120 + seq, sequence=seq, record_ref=f"record-{seq}",
        ) for seq in sequences])

    rig["dispute"].read.return_value = view([1, 2])
    await rig["service"]().read("deal")
    rig["dispute"].read.return_value = view(sequences)
    read = await rig["service"]().read("deal")
    assert isinstance(read.authority.outcome, Rejected)
    assert "regress" in read.authority.outcome.reason
    assert [event.sequence for event in read.authority.disputes] == [1, 2]
    watch = rig["watch"]()
    with transaction(rig["path"]) as conn:
        assert WatchSession(conn).cursor("deal", watch.dispute_record) == 2
