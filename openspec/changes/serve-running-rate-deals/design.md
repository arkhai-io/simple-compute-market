# Design: serve-running-rate-deals

## Context

Goal 8's MVP is three changes: `drive-the-storefront-clock-in-lanes` and this one
in parallel, then `switch-on-hosted-per-period-vm`. Together they let a buyer take
an on-demand or spot deal paid per period from a prepaid Arkhai payments balance,
under the shipped presets, with Arkhai operators handling disputes by hand. This
change makes both compute storefronts deliver and service those deals, and
qualifies them in both lanes against the payments and mediation doubles.

What already runs for any deal, rate deals included:

- **Delivery and billing start.** Each domain's `accepted_deal` resolves the deal's
  payment adapter through its payment table
  (`domains/vms/storefront/src/market_storefront/delivery_ports.py`,
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/delivery_ports.py`);
  the payments seller stage builds one adapter serving once and rate parts
  (`kit/arkhai-payments/src/market_arkhai_payments/seller.py`, `payment_adapter`);
  the shared delivery path asks it to authorize commit, dispatch, start and
  disclose and starts billing through end service
  (`domains/compute/delivery/src/compute_delivery/path.py`).
- **Stops and teardown.** The payment watch records each rate part's verified final
  stop as a final request (`kit/deal-servicing/src/market_deal_servicing/watch.py`);
  `record_end` schedules a termination or truncation
  (`kit/deal-servicing/src/market_deal_servicing/journal.py`); both servicing cycles
  drive it through `drive_physical`.
- **The physical fact.** End service's delivery record carries `progress`,
  `released` once the site proves release, which the seller list already reads
  (`kit/deal-servicing/src/market_deal_servicing/seller.py`).
- **Withdrawal.** Only materialization checks the servicing declaration; servicing
  re-derives an accepted deal from its stored mandate without it
  (`kit/arkhai-payments/src/market_arkhai_payments/agreement.py`).

What stops a rate deal, and what goes wrong once nothing does:

- End service refuses to commit any deal that is not once-only
  (`kit/deal-servicing/src/market_deal_servicing/end.py`, `_unserviceable`; spot
  D12–D14). No released storefront ever made that refusal: the newest release tag,
  `marketplace-v0.3.0`, carries neither the servicing declaration nor the refusal.
- End service journals one authorization answer per phase and revision, and
  refuses a different answer for a completed one. A once-only adapter's answer
  depends only on stored evidence; the rate adapter reads a fresh signed snapshot
  every time (`kit/arkhai-payments/src/market_arkhai_payments/rate_parts.py`,
  `authorize`), so its answer changes while the revision stands still.
- No composition passes the watch a stop classifier, so every payment final stop,
  once-only deals' included, is recorded with its classification pending. An
  unclassified earlier end cannot discharge a later seller failure's filing, and a
  site's teardown report finds no classified command to adopt.
- The seller list calls a deal *ended* on physical release alone, while a rate part
  may still bill.
- The two storefronts' servicing cycles order their steps differently for no stated
  reason, and bare metal's runs its physical end, local reconciliation, site
  corrections and filing dispatch in one error handler, so a physical failure skips
  the rest for that deal (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py`,
  `cycle`).

`converge-ongoing-compute-leases` designs the full servicing of running rate deals.
This change takes the slice an MVP deal needs, because the payment authority, not
the storefront, records every stop an MVP deal can end on, and it takes from
convergence the work its decisions below name.

## Decisions

### D1 — A changed authorization answer at an unchanged revision is pending

End service's commit refusal goes, in both domains at once. Authorization keeps its
journal of one answer per phase and revision: the first `allow` or `refuse`
journaled for a phase at a revision stands. When the adapter later answers that
phase differently at the same revision, end service returns `pending` — "the
payment authority's answer changed at this revision; awaiting its observation" —
and journals nothing. The delivery path already treats `pending` as "drive again
later".

The three ways an answer changes at an unchanged revision:

- `allow` then `pending`: a later drive asks a phase again while the payments
  service is slow or unreachable, or returns a snapshot older than the freshness
  window. It is routine for a deal waiting for its Agreement start, whose commit is
  asked again on every drive until dispatch is recorded. Spot's deadline barrier,
  which turns an `allow` into `pending`, is this case.
- `allow` then `refuse`: the payments service already shows a stop, an end or
  exhausted funding the watch has not yet recorded. The next servicing cycle records
  it, the revision moves, and admission answers `ended`.
- `refuse` then `allow`: only the removed refusal produced it. Under
  `docs/guidance/engineering/versioning.md`, "Compatibility is owed to what has
  been deployed", read against `marketplace-v0.3.0`, a deal refused before this
  change is owed no recovery path; one would wait until its deadline.

A changed answer can only hold a phase back, never advance one, as financial
evidence may only narrow delivery admission. Teardown follows the end the watch
records, never an authorization.

Rejected: leaving it, which raises "completed intent cannot change" on every drive
through an ordinary payments outage and every buyer-stop race; journaling only
`allow` as completed, which fixes only the moot case and weakens a definitive
refusal; one journal entry per distinct answer, which grows with every reason text
and changes the operation identity the path reports; and moving the revision on a
changed answer, which invalidates in-flight drives and churns on every slow read.

### D2 — One stop classifier in the compute family, for every payment stop

`arkhai_compute.end_classification` gains `classify_payment_stop(event, *,
entitlements, term_end)`, beside `payment_actor`, which already interprets the
payments service's `"terms"` actor, and the site-report classifier. Both
storefronts' watch factories pass it through the watch's existing
`classify_payment_end` slot, bound to the deal's accepted entitlements and the
Agreement's end:

| Cause | Classification |
|---|---|
| `payer` | `entitled_stop` when the deal entitles the payer, else pending |
| `payee` | `entitled_stop` when the deal entitles the payee, else pending |
| `authority` | `ruling` |
| `terms` | `terms` or `exhaustion` (D3) |
| anything else | pending |

It covers every payment stop, once-only deals' included: a once-only deal's term
end or dispute-account stop is pending today, which in bare metal lets a site
withdrawal after the term end still file a self-penalty, since the unclassified
payment stop sorts before bare metal's own term-end record. When the watch reads a
stop it recorded earlier with a pending classification and the classifier now
classifies it, it resolves the slot through end service's existing correction
resolution; deployed once-only deals' pending stops are resolved that way.

The cause the adapter reports is not changed: the watch refuses a re-read that
changes a recorded end, and `marketplace-v0.3.0` records `terms`.

Rejected: classifying in `kit/deal-servicing` itself, which makes the neutral kit
interpret a payment mechanism's vocabulary; and a classification method on the
payment adapter interface, an interface change for every adapter for a concept the
spec gives end service. Revisit if a second payment mechanism with stops enters the
roadmap.

### D3 — Funds running out is a `terms` stop before the Agreement's end

The payments service records funds running out and the term end with one cause,
`terms`. The rate part's end in the mandate is the Agreement's start plus its
duration (`kit/arkhai-payments/src/market_arkhai_payments/mandates.py`), whole
seconds, which end service records as the deal's term end. A `terms` stop effective
at or after the Agreement's end is the term end; one effective before it is
exhaustion. If the payments service ever distinguishes the two in its signed cause,
the classifier reads that first.

Rejected: comparing with the part's own end in the payments record, equivalent but
not carried by the stop the classifier receives.

### D4 — The kit owns each deal's servicing step order, and the two cycles are unified

A `kit/deal-servicing` helper runs one page of deals in a fixed order, each step in
its own error handler, logged with the domain, step and deal:

1. respondent discovery, a page-level step keyed by dispute authority and payee
   account;
2. per deal, in order: the authorities read, the domain's recovery steps, the
   physical end, local reconciliation, site-report correction, filing dispatch, and
   the physical end again.

Each domain contributes only its steps: its site-report recovery and its site-report
classifier. A physical failure no longer skips reconciliation, correction or filing,
which closes bare metal's defect. The unexplained differences between the two
cycles are unified, following `docs/guidance/repository/family-kits.md`, "Sibling
domains behave alike":

- **The term end.** Both domains record their own term-end final request, classified
  `terms`, once deadline admission allows it, as bare metal does today; VM no longer
  relies on the site's lease expiry for it. For a rate deal it falls at the same
  instant as the payments service's `terms` stop, which sorts first.
- **Respondent discovery.** One poller per (authority, payee account), built per
  cycle over its durable cursor, replaces VM's cached pollers and bare metal's
  per-authority poller taking the first deal's account. Planning confirms the poller
  holds no state beyond its tables, and caches it if it does.
- **The authorities read and paging.** Every registered deal is paged, so an
  uncommitted surrender still gets its physical end; the payments service and
  mediation are read for committed deals only; filings are sent only in the filing
  step.

Convergence's D3 builds its single kit loop on this helper, and listed respondent
recovery as a composition-supplied step; the respondent unification is this change's,
named in its proposal and in convergence's row Notes.

Rejected: splitting bare metal's error handler alone, which leaves the cycles'
differences to convergence; and keeping bare metal's term-end record as its own
contributed step with the difference recorded.

### D5 — One loop layout and one delivery re-drive in both storefronts

Both storefronts run the same four loops, each one job, under the same names:

| Loop | Job |
|---|---|
| `deal-servicing` | the D4 helper's cycle |
| `delivery-recovery` | re-drive unfinished deliveries |
| `payment-reconciliation` | advance accepted payment deals the buyer has not settled |
| `settlement-servicing` | the settlement worker only |

VM's `fulfillment-resume` splits into `delivery-recovery` and
`payment-reconciliation`, and its `settlement-servicing` no longer runs the servicing
cycle; bare metal's `delivery-recovery` becomes the re-drive alone. New interval
keys for `deal-servicing` and `delivery-recovery` default to the interval each job
runs at today, and keys a release accepted keep their meaning
(`docs/guidance/repository/package-versions.md`). The lane stages that pause and
step these loops by name are renamed with them.

The re-drive is one routine in `domains/compute/delivery` over three ports each
domain fills:

```python
async def recover_deliveries(path, domain, *, limit):
    for nid in await domain.unfinished_deliveries(limit=limit):
        async with domain.claim(nid) as claimed:          # VM: database lease; bare metal: its lock
            if claimed and await domain.revalidate(nid):  # the settlement stage re-checks evidence
                await path.drive(nid)
```

VM supplies its incomplete-deliveries query, its claim lease and its settlement
stage's evidence re-check; bare metal supplies its lifecycle-row query, its lock and
a re-check through its settlement stage, which it lacks today. Each domain keeps its
own serialization, as compute delivery already admits. If bare metal's re-check
cannot be made through its settlement stage without new authority reads, the routine
still unifies the listing and the claim, and that re-check is recorded as the
remaining difference with its reason.

Rejected: the same layout with each domain's re-drive unchanged, which leaves the
listing and re-check different; putting the re-drive inside the kit servicing cycle,
which joins delivery and servicing under one pause control the lane scenarios hold
apart; and splitting this work into its own change.

### D6 — The servicing page position is kit-owned

The D4 helper keeps its page position in a kit-owned table in
`market_deal_servicing.schema`, one row per loop, created by an ordinary migration
appended to each storefront chain, as spot's `servicing_payment_observations` was.
VM's position stops living in memory; bare metal's `bare_metal_lifecycle_cursor` is
dropped in the same migration, losing only a rotation position.

Rejected: a VM table copying bare metal's, two tables for one kit concept.

### D7 — *Ended* is physical and financial, and the list says why a deal is ending

In the seller's list a deal with a recorded end is `ended` only when its resource is
proven released, every payment part has a verified stop or end at the payments
service, and no case is open at the dispute authority; otherwise it is `ending`. A
case filed after a deal ended returns it to `ending`.

`DealSummary` gains `ending`, a closed list of codes, present while the deal is
ending:

| Code | Meaning |
|---|---|
| `release_pending` | the resource is not yet proven released |
| `payment_running` | a payment part has no verified stop or end |
| `case_open` | a case is open at the dispute authority |

```json
{"negotiation_id": "n-123", "commitment_ref": "tx-abc", "domain": "vms",
 "mechanism": "arkhai.payments.v1", "entitlements": {"payer": {"notice_seconds": 0}},
 "state": "ending", "ending": ["payment_running"], "deadline": 1763301600,
 "parts": [{"part": "0", "started_at": 1763290800, "final_stop": null,
            "evidence_ref": "tx-abc:snapshot:7:1763301590"}],
 "has_open_extension": false, "open_cases": []}
```

`kit/deal-lifecycle-contracts` carries each code's text, so every CLI renders the same
words and a new code arrives with its text. It takes a version marking the change
incompatible for older readers: the seller client and both storefront CLIs in the
same release read every deal shape, and a client released earlier is not owed
reading a later storefront. For the same reason the models this change touches stop
omitting their newer fields at their defaults (`ReleasedReadShape`), which existed
only so 0.1.0 clients could read once-only deals; spot's released-reads test becomes a
test that the client shipped with the storefront reads once-only, rate, ending and
ended deals. The single-deal `read` keeps its shape.

Rejected: a free-text reason, which carries one reason and invites matching on
wording; no new field, which makes triage a read per deal; and staging the field's
emission for once-only deals for 0.1.0 clients.

### D8 — A storefront that cannot service its deals starts and reports them

With the refusal gone, what services a payment deal, once-only or rate, is the
payments seller stage, built whenever the storefront's payments section has its
servicing fields. A storefront whose configuration builds no stage while it holds
open deals of that mechanism starts, shows each such deal repair required in its
list, naming the missing section, and reports them at startup in its log and its
readiness report, as "With no authorities, no hosted options" reports at startup and
a missing dispute credential shows a deal for repair. Withdrawing a treatment from the
servicing declaration withdraws new offers and acceptances only, as already built.

Rejected: refusing to start, which takes the storefront's other business down for one
mechanism's configuration mistake; and refusing only for rate deals, which treats one
missing stage differently by deal kind.

### D9 — Lane rows set lane time

Every lane row of this change reaches its instants by setting lane time through
`drive-the-storefront-clock-in-lanes`' shared lane-time helper, then steps the loop
that acts and asserts: row 6 sets the instant the balance cannot reserve the next
period, row 7 the preempt request's time plus the Agreement's seller notice, row 9 the
Agreement's end, and row 0 the Agreement's start and its stop. Lane time is one
frozen instant every party shares, the site included, so a termination is stamped at
the commanded instant and a stop is never in a party's future. Lane presets keep
realistic notice and terms.

The lane round therefore depends on `drive-the-storefront-clock-in-lanes` landing; the
rest of this change does not.

Rejected: waiting for the notice and term-end instants, impossible under frozen lane
time; and mixing waits with set time.

### D10 — The watchdog's delivered-deal cases are lane rows

The four cases spot could not run — the real `buy` with the opt-in from `available`;
access lost with the storefront stopped yielding a single buyer stop; a killed
command reading `unmonitored` once its last probe goes stale; the resumed run reading
`monitored` — run in both lanes on the lane-time helper: the buyer reads lane time from
its lane-time file, so staleness is reached by setting time. Planning confirms how a
lane discloses an endpoint the watchdog's TCP probe can reach and the harness can
close, adding a harness-controlled listener if it cannot, and how a Compose lane stops
the storefront.

Rejected: application-integration tests alone, which cannot see the stopped
storefront.

### D11 — The VM composition builds its own payments seller stage

`VmSettlementComposition` builds its payments seller stage over the servicing
declaration in `__post_init__`, as bare metal's composition does; the builder function
and the VM storefront's `tests/recurring_world.py` stop building their own. The
campaign index's unowned row recording the gap closes.

### D12 — The servicing loop may journal observations, never balances

`settlement-servicing`'s "Payment settlement is retryable and idempotent" keeps domain
progress domain-owned, never a local ledger or a payment-servicing daemon. With the
servicing cycle a kit loop (D4), the requirement states that a neutral lifecycle loop
may journal the authorities' observations and the effects of its injected adapters,
never balances or amounts owed.

### D13 — What the buyer is shown

The pre-approval disclosure states that an on-demand option's premature-stop penalty is
collectible only from the seller's earnings still held: under today's holds, what the
deal has earned so far, nothing in the first period without a setup charge.
`offer-a-seller-chosen-payout-hold` later states the collectibility rule. After a
funding stop the buyer's delivery and read output and the watchdog's exit say the deal
stopped because its balance could not reserve the next period, that a top-up cannot
revive it, and that a new deal is needed. The buyer tells exhaustion apart with D2's
classifier, from the payments service's record already in its read.

Rejected: asking the storefront, which makes the seller the buyer's source for a fact
the payments service records.

### D14 — A stale buyer requirement reworded, and restart recovery proven

`buyer-orchestration`'s "The buyer refuses seller ends that keep the started period"
and its scenario "A buyer accepts charged seller stops" name the per-term waivers,
`--allow-charged-preemption` and `--allow-charged-term-end`, as "Each default refusal
has its own waiver" states, instead of a buyer configuring the treatments it accepts.

Restart recovery is built already: both cycles rebuild from the database and the
authorities' records. Each domain proves it by restarting the composed storefront over
the same database with a running rate deal, an ending deal and a pending seller stop,
at application integration, which planning confirms against
`docs/guidance/engineering/test-levels.md`.

### D15 — Implementation cadence

Two rounds, then closeout.

- **Round 1, end service, classification, the list and the loops,** four sessions:
  1. `kit/deal-servicing` and `kit/deal-lifecycle-contracts`: the refusal removed
     and a changed answer pending (D1); the `ending` codes with their text, the
     contract version and the omissions removed, the seller client and both CLIs
     (D7); the journal allowance (D12);
  2. the stop classifier and both watch factories, with pending stops resolved (D2,
     D3); the startup report (D8); the VM stage (D11); the buyer's display (D13); the
     buyer requirement's rewording (D14);
  3. the kit helper with respondent discovery, the authorities read and paging and
     the term end unified (D4); the page position table and its migrations (D6);
     both cycles on the helper;
  4. the re-drive routine and the loop layout with its interval keys and the renamed
     lane stages (D5); the restart tests (D14).
- **Round 2, the lanes,** one session, once `drive-the-storefront-clock-in-lanes` has
  landed: rows 0, 6, 7 and 9 and the watchdog cases in both lanes against both doubles
  (D9, D10), labelled lane-double evidence.

## Open Questions

None.
