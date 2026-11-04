"""Account-wide discovery filters foreign ownership and fairly retries local repairs."""

from market_deal_lifecycle.respondent import RespondentPage
from test_respondent import respondent


async def test_foreign_cases_do_not_become_local_repairs_or_retry_after_restart(respondent):
    env = respondent
    base = (await env["adapter"].respondent()).cases[0]
    foreign = base.model_copy(update={"case_ref": "a-foreign", "commitment_ref": "another-storefront"})
    local = base
    calls, pages = [], [RespondentPage(cases=[foreign, local], next_after="after", has_more=False)]
    ready = [False]

    async def read(after, limit):
        return pages.pop() if pages else RespondentPage(cases=[], next_after=after, has_more=False)

    def resolve(case):
        calls.append(case.case_ref)
        if case == foreign:
            return None
        if not ready[0]:
            return None
        return "deal", env["adapter"]

    poller = env["poller"](resolve)
    poller.read = read
    assert (await poller.poll())["skipped"] == 2
    repairs = await poller.repairs()
    assert [r["case"].case_ref for r in repairs] == [local.case_ref]
    ready[0] = True
    reopened = env["poller"](resolve)
    reopened.read = read
    assert (await reopened.poll())["answered"] == 1
    assert await reopened.repairs() == []
    assert calls.count(foreign.case_ref) == 1 and calls.count(local.case_ref) == 2


async def test_local_repair_retries_rotate_in_arrival_order(respondent):
    env = respondent
    cases = list(reversed((await env["adapter"].respondent()).cases))
    pages = [RespondentPage(cases=cases, next_after="after", has_more=False)]
    attempts = []

    async def read(after, limit):
        return pages.pop() if pages else RespondentPage(cases=[], next_after=after, has_more=False)

    def resolve(case):
        attempts.append(case.case_ref)
        raise ValueError("local Agreement is temporarily unavailable")

    poller = env["poller"](resolve)
    poller.read = read
    await poller.poll()
    assert (await poller.repairs(1))[0]["case"] == cases[0]
    reopened = env["poller"](resolve)
    reopened.read = read
    await reopened.poll(limit=1)
    assert attempts[-1] == cases[0].case_ref
    assert (await reopened.repairs(1))[0]["case"] == cases[1]
