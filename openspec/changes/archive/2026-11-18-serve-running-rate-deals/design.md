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

What the lanes cannot yet show, once rate deals deliver:

- **An unfiled Agreement's cases.** A dispute authority learns an Agreement from its
  first filing, and until then answers a read `404 invalid_request`, as it answers a
  reader who is no party, so a read discloses neither
  (`tools/mediation-lane-double/src/mediation_lane_double/service.py`, `record`;
  `kit/arkhai-mediation/README.md`). The mediation adapter's ordinary read returns
  that answer as `Rejected` (`kit/arkhai-mediation/src/market_arkhai_mediation/adapter.py`,
  `_read`), so for a deal nobody filed on no dispute view is ever saved: the seller's
  and the buyer's reads carry a rejected outcome
  (`kit/deal-servicing/src/market_deal_servicing/seller.py`, `_observed`;
  `kit/deal-lifecycle-buyer/src/market_deal_lifecycle_buyer/lifecycle.py`, `read`),
  and evidence retention, which needs every view accepted, never runs. The kit's
  in-process fake answers such a read with an empty page instead
  (`kit/arkhai-mediation/src/market_arkhai_mediation/fixtures/authority.py`).
- **A rate part's further reservations.** The payments service keeps a started rate
  part reserved ahead by its own scheduler; the payments kit's engine, which the lane
  double serves, reserves only at `start`, and its reads and commands never top up
  (`kit/arkhai-payments/src/market_arkhai_payments/fixtures/authority.py`, `_refill`,
  `advance`). On the double every rate deal stops `terms` at its first reservation's
  end, whatever the payer's balance.
- **A stopped storefront.** The lane harness runs in a `docker run` container on the
  lane's network, with the buyer, and has no Docker access (`e2e-tests/Makefile`,
  `test-buyer-machine`).

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

1. respondent discovery, a page-level step keyed by dispute authority;
2. per deal, in order: the authorities read, the domain's recovery steps, the
   physical end, local reconciliation, site-report correction, filing dispatch, and
   the physical end again.

Each domain contributes only its steps — its site-report recovery and its site-report
classifier — and a respondent port of two operations each domain already has:
`credential_available(authority)`, whether the authority's credential is usable, and
`dispute_adapter(binding)`, the deal's dispute adapter over its accepted Agreement
(VM's `dispute_adapter`, bare metal's `dispute`). The helper takes the signer and the
clock beside them. The kit groups the page's deals by dispute authority, since the
respondent listing is scoped by the authority's one credential and a payee account
only keyed a poller's cursor, and owns the one `resolve` from a listed case to its
local deal and adapter, replacing the domains' two near copies; a case whose
Agreement digest differs raises, so it lands in the respondent repairs naming the
mismatch. Its failures:

- a deal with no dispute authority, or whose authority's credential is unusable, is
  left out of discovery; the existing credential repair already shows the deal;
- a failed discovery for one authority is logged, naming the domain, the step and the
  authority, and every other authority and every per-deal step still runs;
- a listed case naming no local deal is skipped, and a local deal that cannot be
  resolved is a repair row, as `RespondentPoller` does today.

Keying by authority changes the poller's cursor record, so each authority's listing
restarts from its beginning once after upgrade; answers are idempotent by case, and no
migration is needed.

A physical failure no longer skips reconciliation, correction or filing, which closes
bare metal's defect. The unexplained differences between the two
cycles are unified, following `docs/guidance/repository/family-kits.md`, "Sibling
domains behave alike":

- **The term end.** Both domains record their own term-end final request, classified
  `terms`, once deadline admission allows it, as bare metal does today; VM no longer
  relies on the site's lease expiry for it. For a rate deal it falls at the same
  instant as the payments service's `terms` stop, which sorts first.
- **Respondent discovery.** One poller per dispute authority, built per cycle over
  its durable cursor, replaces VM's cached pollers per authority and account and bare
  metal's per-authority poller taking the first deal's account, which failed the
  whole authority's discovery when that deal named no account (an Alkahest deal).
  `RespondentPoller` holds no state beyond its tables and its constructor's inputs
  (`kit/deal-servicing/src/market_deal_servicing/respondent.py`), so it is built per
  cycle; its cursor record, today derived from the account and the authority, is
  derived from the authority alone.
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
its settlement service's `verified_evidence`, the accepted entry's recovery gate,
which runs its stage's `revalidate` (`revalidate_payment`, `revalidate_alkahest`) and
which its fulfillment's `deliver` already runs before every drive. Each domain keeps
its own serialization, as compute delivery already admits.

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
| `case_unobserved` | the deal names a dispute authority of which no verified read is saved, so no case is verified closed |

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
reading a later storefront. For the same reason the lifecycle read and list stop
omitting their newer fields at their defaults: `ReleasedReadShape`, which existed only
so 0.1.0 clients could read once-only deals, goes from `PaymentEvent`, `AuthorityView`
and `DealSummary`, and `deal-lifecycle`'s "Stop requests are distinct from final
stops, readable by released clients" is removed and added back without the omission
and its 0.1.0 scenario. Spot's released-reads test becomes a test that the client
shipped with the storefront reads once-only, rate, ending and ended deals. The
single-deal `read` gains no `ending`. Neither storefront CLI lists deals today — their
`deals` group holds `preempt` alone — so the codes' text reaches operators through the
typed seller client's list, and this change adds no list command.

Rejected: a free-text reason, which carries one reason and invites matching on
wording; no new field, which makes triage a read per deal; and staging the field's
emission for once-only deals for 0.1.0 clients.

*Settled at round 1's triage (32 F1):* a deal that is not once-only bills through rate
parts, and the payment authority's view of it lists every part, started or not; so
when its last saved view lists no part, or none has been saved, no stop is verified
and it is `ending` with `payment_running`. A once-only deal has no rate part to stop.
Rejected: requiring the latest payment observation to postdate the recorded end, which
guards no window the payments adapter leaves (an unstarted part is already listed
without a stop) and whose instant a backdated end defeats; and a new
`payment_unknown` code, since `payment_running`'s text already says no stop is
verified.

*Settled at round 1's repeat pass (44 F1):* the dispute half follows the same rule. A
deal that names a dispute authority, of which no verified read has been saved — a
view is saved only from an accepted read — has its cases unknown, not empty, so it
is `ending` with a fourth code, `case_unobserved`, until one such read is saved. A
deal whose storefront composed no adapter for its authority's interface therefore
stays `ending` until one is composed; a missing credential still shows repair
required first. The code arrives in `kit/deal-lifecycle-contracts`' unreleased 0.3.0,
so it costs no further version. The authority's first-page `404 invalid_request` is
taken as such a read, showing no case (D16), so a deal nobody filed on is observed —
on the premise, which the published contract cannot check, that the credential
authenticates the Agreement's party; `case_unobserved` remains for an authority that
has not answered or has no adapter composed. Rejected: widening `case_open` to cover an unobserved
authority, which would list `case_open` beside an empty `open_cases` and make its text
untrue; unlike `payment_running`, its text does not already cover the unverified case.

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

*Settled at round 1's triage (32 F2):* a deal is open, and reported, until the seller
list's D7 rule would call it ended, read from its last saved views: a released rate
deal whose part last showed no stop stays reported until the adapter is restored.
Rejected: reporting every such deal with a recorded end until an explicit
financial-completion marker exists, which no record holds, so released once-only
deals would be reported forever.

### D9 — Lane rows set lane time

Every lane row of this change reaches its instants by setting lane time through
`drive-the-storefront-clock-in-lanes`' shared lane-time helper, then steps the loop
that acts and asserts: row 6 reserves the part through the Agreement's end (D17), with
the payer funded one period beyond its first reservation, and sets the funded boundary
the double then reports; row 7 sets the preempt request's time plus the Agreement's
seller notice; row 9 reserves through the Agreement's end and sets it; and row 0 sets
the Agreement's start and its stop. A row setting lane time past its deal's first
reservation reserves first. Lane time is one
frozen instant every party shares, the site included, so a termination is stamped at
the commanded instant and a stop is never in a party's future. Lane presets keep
realistic notice and terms.

The lane round therefore depends on `drive-the-storefront-clock-in-lanes` landing; the
rest of this change does not.

Rejected: waiting for the notice and term-end instants, impossible under frozen lane
time; and mixing waits with set time.

### D10 — The watchdog's delivered-deal cases are lane rows

The four cases spot could not run — the real `buy` with the opt-in from `available`;
access lost with the storefront paused yielding a single buyer stop; a killed command
reading `unmonitored` once its last probe goes stale; the resumed run reading
`monitored` — run in both lanes against a delivered rate deal, the buyer's `buy` run in
the harness's process with its probe and its waits programmed by the harness (D20).
Staleness is reached by setting lane time, which the buyer's probes are stamped with and
its read compares against; the threshold of failed probes is reached by stepping the
watchdog's waits. The storefront is paused for the access-lost case (D18).

Rejected: application-integration tests alone, which cannot show the watchdog's stop
landing at the payments authority from a delivered deal.

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
classifier, from the payments service's record already in its read. The buyer half
(`kit/deal-lifecycle-buyer`) is a kit and cannot import the compute family, so, as the
watch does, it takes the classifier through a slot each compute buyer fills with
`arkhai_compute`'s.

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
at application integration (`docs/guidance/engineering/test-levels.md`): the composed
storefront, read through its typed lifecycle client, with the payments service a fake
behind its client.

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
- **Round 2, the lanes,** two sessions, once `drive-the-storefront-clock-in-lanes` has
  landed:
  1. the mediation adapter's read of an Agreement with no record, and the kit's fake
     answering as the authority does (D16); the payments engine's reservation method,
     the double's reservation control and its typed client (D17); each with its tests;
  2. on that tooling, rows 0, 6, 7 and 9 and the watchdog cases in both lanes against
     both doubles (D9, D10, D20), labelled lane-double evidence (D19).

*Settled at the return from the watchdog cases:* rows 0, 6, 7 and 9 are done; the
watchdog cases (D10, D18, D20) are one session, completing round 2's second; then
round 2's implementation review and validation over all of its work; then closeout.

### D16 — An authority holding no record of the Agreement is read as no case

The mediation adapter's ordinary read takes the authority's first-page
`404 invalid_request` as an accepted read of an empty record — no disputes, no cases —
as its delivery-end filing already does, so the filing's separate flag goes. The watch
saves that view; the seller's list, read and unserviceable report and the buyer's read
carry an accepted dispute outcome; evidence retention runs, still waiting for payouts to
complete. Once a party files, the next read returns the record and the deal is `ending`
again with `case_open` (D7). The kit's in-process fake answers a read of an Agreement it
holds no record of with that `404`, as the authority and the lane double do, so kit and
storefront tests meet it. `kit/arkhai-mediation` is at an unreleased 0.3.0
(`marketplace-v0.3.0` carries 0.2.0), so no deployed form is owed a compatibility path;
the development branch already carries 0.3.0, so the changed contents take one patch
step, 0.3.1 (`docs/guidance/repository/package-versions.md`, "A version changes when its
contents change"). No wire form or stored record changes, and a deployed storefront's
saved rejected observation is replaced by its next read.

This read is not verified. The authority answers the same `404` to a reader who is no
party to the Agreement, and none of the published routes tells a client which account
its token authenticates, so the adapter takes the `404` as no case on a premise the
contract gives no way to check: that the credential authenticates the Agreement's party.
An empty record page is unsigned too, so where that premise holds the read carries the
assurance of any accepted read: transport to the Agreement's pinned authority. Where it
does not, the limit is real: a seller whose mediation credential authenticates another
account sees every unfiled deal, and any case filed against it before its first accepted
read, as no case, so a released, paid deal with a case open can list `ended`. That
misconfiguration also has its filings refused (`filer_not_party`) and its respondent
listing empty, which is where an operator meets it; neither makes the list true.

*Settled at the design review's triage (60 F1):* the mapping stands, its premise and
limit stated rather than called verified. Rejected: requiring the payments view to show
no open extension before `ended`, which corroborates no held case only while a finite
extension lasts and widens D7's rule; keeping the `404` as `case_unobserved`, which
leaves every correctly served unfiled deal `ending`, both reads rejected and retention
stalled, to guard one misconfiguration; and waiting for the contract to give a
verifiable answer, which no answer is expected to provide before this change lands.

Rejected: the same read marking the absence in a new `AuthorityView` field, which no
caller would act on; the seller list telling a `404` from other failures, which makes
the neutral kit interpret one interface's error and leaves both reads rejected and
retention stalled; inferring no case from the seller's own filings and a complete
respondent discovery pass, which needs a per-authority record and a migration for no
more assurance, and leaves the reads rejected; reverting D7's 44 F1 rule, which would
list `ended` a deal whose authority is unreachable or has no adapter composed; and
waiting for the published contract to give a verifiable answer, which it does not.

### D17 — The scenario programs the payments double's further reservation

The double runs nothing of its own: the payments service's scheduler decides when a rate
part is reserved further, and, as `docs/guidance/engineering/test-doubles.md` has a
double take its producer's decisions as answers a scenario programs, the scenario
programs it. The double gains one control:

```http
POST /test/transactions/9c41…e07/reserve
{"through": 1800007200}

200 {"transaction": "9c41…e07", "parts": [{"part": 0, "reserved_through": 1800000360, "periods_added": 1}]}
```

It reserves each running rate part's — started and not stopped — further periods
through the named instant, as far as the part's end and the payer's balance allow — the
arithmetic the engine already applies at `start` — and answers, for each such part, the
instant it is then reserved through, which the signed snapshot reports as its funded
boundary. A transaction with no running rate part — before `start`, once-only, or every
rate part stopped — is refused and nothing changes, so a stage run too early or against
the wrong deal fails where it runs instead of passing with nothing reserved (60 F2):

```http
409 {"code": "no_running_rate_part", "message": "the transaction has no started, unstopped rate part"}
```

The engine gains the public method behind it; `tools/lane-double-controls` gains the route and its typed client method; the
engine's reads, `advance` and its reservation at `start` are unchanged, and funding
running out still shows at the next read once lane time passes the boundary.
`kit/arkhai-payments` is at an unreleased 0.8.1 (`marketplace-v0.3.0` carries 0.6.1),
already one step past the development branch's 0.8.0 on this branch, so this costs no
further version; `tools/lane-double-controls` and `tools/payments-lane-double` each take
one patch step. A reservation is a stage of its own, declared only where
the double runs (`test-doubles.md`, "Shared stages never depend on a double"); against
the payments service its scheduler reserves instead.

Rejected: the double topping up by itself, a scheduler step in the engine run before
every call, which adds internal behaviour the scenario can program; a control reserving
an exact number of periods, refused when the balance falls short, which makes funds
running out the scenario's choice rather than a boundary the ledger computes; rows kept
within the first reservation, against realistic terms and with the double still unlike
its producer; and stepping lane time with a read at each step, since reads never
reserve. *Settled at the design review's triage (60 F2):* the refusal and the per-part
answer. Rejected: an empty answer, `parts: []`, which a lane stage could pass without
reserving anything.

### D18 — The watchdog's storefront is paused, not stopped

For the access-lost case (D10) the scenario pauses the storefront's loops, which holds
every time-based signal it would emit — a term end, a teardown, a filing — so the
watchdog's one payer stop lands at the payments double with nothing from the storefront
between: the transaction's events there are the storefront's `start`, then the payer's
stop. The watchdog's stop is the buyer's ordinary stop and hint, and the storefront acts
on the hint through its API whether or not its loops are paused: it records the payer's
end, with no filing, and in bare metal also carries out the physical end, as the
recurring purchase shows (`Recurring08`). Stepping `deal-servicing` then shows the
teardown begun. A local end-to-end test holds a party's time-based
signals this way; an external-topology test handles time differently. That an
unreachable storefront does not hold the stop back is proven at library integration,
where each compute buyer runs its watchdog against a storefront refusing connections
(`domains/vms/buyer/tests/test_watchdog_rate_stop.py`,
`domains/bare_metal/buyer/tests/test_watchdog_rate_stop.py`).

Rejected: stopping the storefront's container, which the harness, running in a container
of its own with no Docker access, cannot do; giving the harness that access, through the
Docker socket or a socket proxy in each lane, which hands test code control of the lane
host for what a pause shows; splitting the case across two pytest runs with a Compose
stop between, which makes the Makefile a scenario stage; and pointing the buyer's resumed
run at a closed seller address, which proves a misconfigured buyer rather than a quiet
storefront.

### D19 — The Compose lanes are this change's evidence

Every lane row and watchdog case runs in both Compose lanes against both doubles,
labelled lane-double evidence, and closeout runs the end-to-end pipeline over them.
Nothing in this change waits on another topology; a run elsewhere is recorded with its
own label, as further evidence, and gates nothing. The rows use only the lane-time
helper, the doubles' controls and the loop controls, so they carry over to any topology
offering those; the watchdog cases also need both buyers installed in the harness's
process (D20), as `e2e-tests/pyproject.toml` declares.

Rejected: gating a section on a topology no change owns, which gives this change a
prerequisite outside its domain and a second acceptance boundary, and whose wall-time
Helm release cannot reach the doubles' controls or set lane time; and requiring both.

### D20 — The watchdog's buyer runs in the harness's process, its probe and clock programmed

Lane provisioning is mocked, so the endpoint a lane deal discloses reaches no machine,
and the watchdog starts its probes on a monotonic clock (`deal-lifecycle`, "The buyer's
watchdog bounds detection only while it runs"), so neither a probe's answer nor the
threshold of failed probes can be reached through the services' controls or lane time.
The buyer is controlled as a service is: a mock layer the harness programs overrides its
outbound IO and its time. Unlike a service's, that layer is applied in the harness's
process, so nothing test-only ships with the CLI.

Each case runs the shipped `buy`, its resume `buy --from` and the buyer's read in the
harness's process, through the command's own entry (Typer's `CliRunner` in a worker
thread, as `domains/vms/storefront/tests/integration/test_watchdog_buy.py` does); both
buyers are installed in the harness's environment (`e2e-tests/pyproject.toml`). The
harness replaces each buyer CLI's two composition factories, VM's in
`domains/vms/buyer/src/arkhai_vms_buyer/buy_cli.py` and bare metal's in
`domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`:

- `watchdog_probe`: a probe answering as the harness programs it, reachable or not, with
  no network call. It records the endpoint the deal disclosed, so each case checks the
  probe was built for the deal's own access. Each fake matches its domain's signature,
  and in both domains that signature carries the disclosed endpoint: VM's factory takes
  its delivery's connection details, and bare metal's takes the access its callers,
  `buy`'s delivery-and-watch step and its resume, read from the storefront before
  building the probe, where today the factory reads it itself. The harness therefore
  replaces only the probe's outbound connection; the buyer's own read of the access runs
  in the lane.
- `wait_clock`: a `WaitClock` whose `now` is lane time and whose sleep is a gate the
  harness steps one interval at a time, its `monotonic` advancing by each interval
  stepped. It paces every wait `buy` makes, not only the watchdog's: bare metal's commit
  and availability waits already run on it, and VM's commit loop and settlement wait run
  on it too, where today they read the process's monotonic clock and `asyncio.sleep`
  (the settlement wait is given the clock's `sleep` and `monotonic`). A fresh `buy`
  waiting for its deal is parked at the gate while the scenario sets lane time to the
  Agreement's start and steps `delivery-recovery`; the harness then releases the wait,
  the poll sees the deal available, and the same command enters its watchdog. An
  interrupt delivered at the gate is the killed command.

The in-process buyer shares the harness's process, so the harness keeps that shared
state coherent. Its buyer configuration states no `[time]` table, so the `market`
callback installs no source and the buyer reads the harness's installed lane-time source,
as its clock's `now` does. Each watchdog module scopes the buyer's environment (its
`XDG_*`, `HOME` and credential variables) with pytest's `monkeypatch`, undone when the
module ends. A read runs only while `buy` is parked at the gate, so `CliRunner`'s
process-wide stream swaps nest and neither command's output reaches the other's capture.

On one deal the cases run in order: `buy` waiting for delivery at the gate, the deal
delivered and the wait released, the watchdog started from `available` and a passing
probe, the read `monitored`; the interrupt, lane time set past the last probe's staleness bound, the
read `unmonitored`; `buy --from` and a passing probe, the read `monitored`; then, with
the storefront's loops paused (D18), the probe answering unreachable for the threshold
of stepped intervals, one payer stop accepted at the payments double, and `buy` exiting
`stopped`. The reverse order cannot run on one deal: once the stop is journaled, the
read shows `stopped`. The command's process entrypoint is not exercised by these cases;
every other lane scenario runs `market` as a subprocess, and
`e2e-tests/tests/e2e/roles/buyer_cli.py` names the in-process watchdog cases as the
exception and why.

Rejected:

- a mock-provisioning rule disclosing a harness listener, which no rule can do: a rule's
  `result_stdout` is verbatim, both codecs build a direct endpoint's host from the
  registered host's tenant route, bare metal its port too, and VM's yields no evidence
  unless the output names the guest derived from the reservation settle creates;
- a harness-owned loopback listener disclosed through each module's executor-host
  registration (`public_host`, `public_port`), with a bounded real-time wait for the
  probes, which keeps a buyer the harness cannot pause or step;
- the mock and both codecs taking the endpoint from a rule's output, a production change
  for a test fixture that undoes the host registry's ownership of the tenant route;
- caging the buyer process's network, which needs privileges the harness's container
  does not have;
- a mock layer the shipped CLI reads from a file the harness manages, which ships test
  functionality with the CLI and is needed only for a buyer that cannot run in the
  harness's process;
- calling `watch_deal` directly, which each buyer's library-integration test already
  does (`test_watchdog_rate_stop.py`) and which skips the shipped command's opt-in,
  journal and resume;
- a pause-and-step control API in `buy`, against the requirement's "no buyer daemon";
- the watchdog's schedule following lane time under injected time, a change to the
  `deal-lifecycle` requirement and to shipped buyer code;
- network-layer fault injection, such as a service mesh, in this repository's end-to-end
  layer; how infrastructure topologies apply that kind of control is their own guidance,
  decoupled from these tests;
- a new injection point in each CLI: the two factories are already its composition seam,
  and replacing them, as the precedent test does, ships nothing.

*Settled at the design review's triage (75 F1, F2, F3).* Every wait of `buy` runs on the
command's `wait_clock`, VM's commit and settlement waits included, which closes the
campaign index's unowned row "The VM buyer's settlement wait has no clock seam" and makes
the two buyers' waits alike; and bare metal's `watchdog_probe` takes the disclosed
access, as VM's takes its connection details. Both are small changes to shipped buyer
code: neither adds a factory or changes what a buyer sees, and each is proven at the
buyer's own application integration (VM's fresh `buy` waiting for delivery on an injected
clock; bare metal's probe built from the access its caller read) beside the lane. The
in-process buyer's shared-state rules are 75 F3's. Rejected with them: the fresh `buy`
running out of its wait and `buy --from` starting the watchdog, as VM's application test
does, which needs no production change but leaves the lane never showing a fresh `buy`
enter its watchdog; a bounded real-time wait before the watchdog, which `system-tests.md`,
"A scenario is a sequence of state changes", rules out; narrowing bare metal's check to
the probe's run with the access read in a separate assertion, which never runs bare
metal's own read of the access; patching `tcp_reachable` at each CLI's imported name,
which `test-seams.md` rules out beside a seam; and the harness restoring its own time
source after each in-process command, a step to forget that leaves the buyer's file
source installed while `buy` is parked.

## Implementation findings

What implementation found or decided beyond the decisions above, kept here when
`tasks.md`'s notes were shortened at closeout.

### End service, the list and the contracts

- D1's changed answer compares authorization answers by status alone, since a rate
  adapter's evidence reference names each fresh snapshot. An end due by now at the same
  revision is admission's own `refuse`, returned unjournaled, not a held changed answer.
- Stored servicing views and journal rows written before contracts 0.3.0 omit the
  fields that release dumps; they read back at their defaults, and every comparison in
  `kit/deal-servicing` is between parsed models, so none is affected.
- D12's check leaves out the watch's stored observation views (`servicing_watch`,
  `servicing_observations`), which keep the authority's view as read, amounts and
  funded boundary included; D12 admits them as journaled observations.

### Versions taken beyond the plan

- New public API took a minor step even where the package was already bumped on this
  branch (`docs/guidance/engineering/versioning.md`, "One bump per unit of work"):
  `kit/arkhai-payments` 0.9.0, `tools/lane-double-controls` 0.2.0,
  `tools/payments-lane-double` 0.3.0 and `arkhai-core-buyer` 0.8.0. D17's sentence that
  the reservation costs no further version and the tools one patch step each is
  superseded by these.

### Classification and the term end

- The family classifier reads a `PaymentStop` protocol (`cause`, `at`) and returns a
  kind string, since `arkhai_compute`'s allowlist admits only the shape kit; each
  storefront wraps the kind in the kit's `Classification` in its own two-line closure.
  A shared wrapper would need a package both storefronts and the kit admit, so the two
  closures stay. The buyer kit likewise names `"exhaustion"` as a literal, since it
  cannot import the servicing kit's `ClassificationKind`.
- Each storefront registers its term end from the Agreement's start truncated to whole
  seconds, while the payments mandate's part end is `ceil(start + duration)`: for a
  fractional start the payment stop lands a second after the registered term end and
  still classifies `terms`, and which of the two sorts first depends on the fraction.
- The servicing cycle's authorities read records a payment stop before reconciliation
  records the storefront's own term end, so the first physical end commands the
  termination at the payment stop's instant; a termination never restarts.
- The buyer checks rate parts only for funds running out: a once-only part's end is the
  Agreement's end, so its `terms` stop never reads as exhaustion.

### Composition and the startup report

- `PAYMENTS_SERVICING_FIELDS` is stated in each storefront beside its payments
  composition rather than in `kit/arkhai-payments`, which would take that package a
  version and every dependent a relock for one string.
- Every `dataclasses.replace` of the frozen VM composition builds an equal payments
  stage again: the stage holds only its section, client factory and declaration, and a
  frozen composition has no other way to gain its coordinator and lifecycle. A test
  needing the exact stage object reads it after the last replace.
- `VmDealLifecycle` takes `capacity=` and `physical=` so tests pass a world's runtime
  rather than replacing `lifecycle.end.physical` after construction; production passes
  neither and keeps the configured sites' runtime.

### The servicing cycle, the loops and the re-drive

- The cycle's authorities read is `SellerServicing.read`, not `watch`, so only the filing
  step dispatches filings.
- The page position is saved once a page is serviced, `NULL` after the last, so a
  storefront stopped mid-page services that page again rather than skipping its rest.
- A resolved respondent case clears its repair under any record, since repairs held
  under the earlier account-and-authority record have no poller to clear them once the
  listing restarts by authority.
- Every servicing loop in both storefronts runs its first cycle one interval after its
  timer starts, so an operator can hold the loops as the storefront starts; a restarted
  storefront's first re-drive is therefore 30 seconds after start by default.
- Bare metal's re-drive drives through `BareMetalFulfillmentService.redeliver`, so every
  delivery enters through core's fulfillment hook and its identity check
  (`physical-provisioning`). The hook takes the deal's `asyncio.Lock`, which is not
  re-entrant, so the routine's claim only answers whether the lock is free, and
  `deliver`'s gate re-checks the evidence a second time; VM's claim holds its lease
  across re-check and drive. Both re-checks answer `False` with a warning, an
  unreachable chain included; the routine logs only what raises.
- Waits of `buy` still on real time after section 10a: the Alkahest settle's submit
  retries on a propagation-lag refusal (no rate deal settles through Alkahest), and the
  payments kit's approval poll while the service has no snapshot of a transaction it
  just approved, which neither the service nor the lane double answers.

### Storefront test worlds

- VM's recurring world delivers against `tests.delivery_fakes.DeliverySite` as the one
  site of a real `CapacityRuntime`, since the publication harness's `FakeSite` serves
  projections only and has no activation route. Bare metal's needed a fulfillment client
  scheduling the pool member's machine in the world's pool, since delivery refuses a
  resource whose pool or host differs.
- Bare metal's lifecycle row `state` is provisioning's state as last read (it stays
  `dispatch_pending` after a settle-driven delivery), so tests assert availability from
  end service.
- Each world builds fresh fakes, so a restarted storefront meets a site holding no
  reservation and no restart case asserts teardown; VM's `DeliveryProvisioning` has no
  `terminate_lease` and bare metal's `WorldProvisioning` and payments harness no
  `get_lease`, so a cycle logs a harmless physical-end or site-recovery failure there.
- Restarting VM's configured app over a recurring world's database needs the harness's
  seller seed as its credential and the harness's administrator: lifecycle routes refuse
  to sign as another seller, and startup refuses an administrator configuration dropping
  a durable identity.

### The lanes and the payments double

- "No payment hold" in the recurring purchase's clean-up is read as nothing reserved for
  the payer and nothing the stages left running: the same requirement demands the
  started period charged, which the double holds for the payee until its release
  instant, as a once-only purchase's payment stays held until the lane ends.
- A rate part holds two periods reserved once started (`FIRST_RESERVATION_PERIODS`):
  approval reserves one, and the start tops up to its reserve ahead plus the engine's
  60-second slack. A row setting lane time past that boundary declares the reservation
  stage first. Like `_refill`, the reservation covers 60 seconds past `through`, so
  reserving through a stop on a period boundary reserves the next period too, which the
  stop refunds; reserving through the Agreement's end is capped there.
- The double charges nothing for a stop at the start itself, so the recurring purchase
  stops a minute into the first period. No route reads a storefront's classification,
  so the rows assert its consequences: cause, instant, no filing, teardown and the
  buyer's `funding_stop`.
- The rate rows run only against the lane's doubles (D19); `MaximumTerm07` is not split
  from the reservation so it could run against the payments service, which has no lane
  time to set to the Agreement's end.
- A VM scenario's GPU model must be one `core/registry/src/core_registry/filter-spec.yaml`
  admits; the registry refuses to publish any other while the storefront reports the
  listing open.
- A lane's storefront needs the seller's `[[DisputeCredential]]` for the mediation
  double its deals name, or every such deal lists `repair_required`; the bare-metal
  lane's overlay lacked it until section 10.
- The lane harness mounts `e2e-tests/tests` and `src` read-only from the worktree, so a
  stage edited while a lane runs changes the run. The two lanes share host ports, so one
  stack comes down before the other starts; a VM watchdog run needs a fresh stack, its
  resource listed once per stack.

### The in-process buyer

- pytest points `sys.stdout` at its own capture for each stage and around each live-log
  record, so a background command's output after its stage ends is unreliable: stages
  read its exit status and run log, and a foreground command runs with logging held.
- A `WaitClock`'s `sleep` is awaited on event loops the command makes for itself (VM's
  `run_sync` threads, bare metal's `run_sync`, the watchdog's `asyncio.run`), so the
  harness's gate is a thread condition, not an `asyncio` primitive, and work on the
  harness's loop goes through `run_coroutine_threadsafe`. `buy` builds one clock per
  command, so the replaced factory may return the same gated clock each call.
- The watchdog probes once on entering, before its first sleep, so a release yields the
  second probe and a threshold of two takes two releases after the probe fails.

### Test-before evidence

- `scripts/change-workflow run test-before` runs a test file as `HEAD` holds it and
  without the packages' environments, so it showed nothing for this change's sections:
  their new tests fail at the base by the code — the refusal, API or route they assert
  is absent there — not by a run.

## Open Questions

- The published mediation contract gives no verifiable answer for an Agreement the
  authority holds no record of, nor a way to check which account a credential
  authenticates, so D16 reads an unsigned `404` as no case on an unchecked premise.
  Revisit D16's mapping if the contract comes to offer either.

## Design promotion record

The six capability specifications are written by the archive from the change's deltas;
the rest was promoted at closeout.

| Accepted decision | Permanent location |
|---|---|
| D1 — a changed authorization answer at an unchanged revision is pending; the refusal removed | `openspec/specs/deal-lifecycle/spec.md#requirement-delivery-authorization-delegates-payment-interpretation` and `openspec/specs/compute-delivery/spec.md#requirement-protected-delivery-steps-are-authorized-and-admitted` (by the archive; `compute-delivery/spec.md`'s "Delivery is driven one deal at a time and reports where it stands" loses the `rate_servicing_unavailable` reason by hand); `openspec/specs/deal-lifecycle/architecture.md#one-end-instant-transactional-admission` ("A changed authorization answer holds a phase back", "The deadline barrier") and `#current-limits`; `openspec/specs/compute-delivery/architecture.md#commit-and-hold-adoption`; `docs/development/ARCHITECTURE.md#settlement-servicing`; `openspec/specs/settlement-servicing/architecture.md#charge-first-payment-settlement` and `#current-limits`; `openspec/specs/settlement-servicing/configuration.md#seller-servicing-budget-diagnostics`; `openspec/specs/settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover`; `openspec/specs/storefront-publication/architecture.md#the-servicing-declaration-and-its-three-doors` |
| D2, D3 — one compute-family stop classifier; `terms` split by the Agreement's end | `openspec/specs/deal-lifecycle/spec.md#requirement-cause-classification-is-owned-by-end-service` (by the archive); `openspec/specs/deal-lifecycle/architecture.md#one-end-instant-transactional-admission` ("One compute-family classifier for every payment stop"); `docs/development/ARCHITECTURE.md#settlement-servicing` |
| D4, D6 — the kit's servicing step order, respondent port, unified term end and paging; the kit-owned page position | `openspec/specs/deal-lifecycle/spec.md#requirement-each-deals-servicing-steps-run-in-one-kit-owned-order` (by the archive); `openspec/specs/deal-lifecycle/architecture.md#package-and-counterpart-boundaries` ("The kit owns each deal's servicing order"), `#current-limits` and `#buyer-surrender-and-cases`; `openspec/specs/vm-storefront-fulfillment/architecture.md#delivery-end-and-post-release-history`; `openspec/specs/settlement-servicing/architecture.md#current-limits` |
| D5 — one four-loop layout and one delivery re-drive | `openspec/specs/compute-delivery/spec.md#requirement-unfinished-deliveries-are-re-driven-by-one-routine` and `openspec/specs/market-composition/spec.md#requirement-both-compute-storefronts-run-one-loop-layout` (by the archive); `openspec/specs/compute-delivery/architecture.md#dispatch-and-recovery`, `#the-agreement-window-and-the-future-start-wait` and `#domain-compositions`; `openspec/specs/physical-provisioning/architecture.md#bare-metal-storefront-pull-boundary`; `openspec/specs/vm-storefront-fulfillment/architecture.md#evidence-and-delivery-ownership`; `openspec/specs/market-composition/architecture.md#storefront-composition-kit`; `docs/development/ARCHITECTURE.md#operator-lifecycle-controls`; `openspec/specs/storefront-publication/configuration.md#durations-are-positive-seconds` and `#the-settlement-servicing-interval`; `docs/development/TESTING.md#the-canonical-compute-deal` (the VM lane's `delivery-recovery` step) |
| D7 — *ended* is physical and financial; the `ending` codes; the read and list carry every field | `openspec/specs/deal-lifecycle/spec.md#requirement-the-seller-half-lists-deals` and `#requirement-stop-requests-are-distinct-from-final-stops` (by the archive); `openspec/specs/deal-lifecycle/architecture.md#one-end-instant-transactional-admission` ("When a deal is ended") and `#seller-notice-and-administrator-interruption`; `kit/deal-servicing/README.md` and `kit/deal-lifecycle-client/README.md`, written with the code |
| D8 — a storefront that cannot service its deals starts and reports them | `openspec/specs/market-composition/spec.md#requirement-a-storefront-reports-deals-its-configuration-cannot-service` (by the archive); `openspec/specs/market-composition/architecture.md#settlement-runtime-composition`; `openspec/specs/storefront-publication/architecture.md#the-servicing-declaration-and-its-three-doors`; `openspec/specs/settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover` |
| D9, D10 — lane rows set lane time; the watchdog's delivered-deal cases are lane rows | `openspec/specs/test-compatibility/spec.md#requirement-rate-deals-are-qualified-in-both-compute-lanes-on-lane-time`, `#requirement-a-recurring-purchase-is-delivered-end-to-end-in-each-compute-lane` and `#requirement-the-buyers-watchdog-is-qualified-against-a-delivered-deal` (by the archive); `docs/development/TESTING.md#the-canonical-compute-deal`; `openspec/specs/test-compatibility/architecture.md#the-in-lane-payments-double`, `#ordinary-arkhai-purchase-evidence` and `#the-in-lane-mediation-double`; `docs/development/ROADMAP.md`, Goal 8 |
| D11 — the VM composition builds its own payments seller stage | `openspec/specs/market-composition/spec.md#requirement-each-compute-composition-builds-its-payments-seller-stage` (by the archive); `openspec/specs/market-composition/architecture.md#settlement-runtime-composition`; `openspec/specs/storefront-publication/architecture.md#the-servicing-declaration-and-its-three-doors` |
| D12 — the servicing loop may journal observations, never balances | `openspec/specs/settlement-servicing/spec.md#requirement-payment-settlement-is-retryable-and-idempotent` (by the archive) |
| D13 — what the buyer is shown | `openspec/specs/buyer-orchestration/spec.md#requirement-the-buyer-is-shown-the-penaltys-collectible-bound-and-why-a-funding-stop-is-final` (by the archive); `openspec/specs/buyer-orchestration/architecture.md#compute-terms-before-approval` and `#the-buyers-watchdog` |
| D14 — the buyer requirement reworded; restart recovery proven | `openspec/specs/buyer-orchestration/spec.md#requirement-the-buyer-refuses-seller-ends-that-keep-the-started-period` (by the archive); `openspec/specs/test-compatibility/architecture.md#lifecycle-contract-evidence` |
| D15 — implementation cadence | No permanent destination: it ordered this change's own work |
| D16 — an authority holding no record of the Agreement is read as no case | `openspec/specs/deal-lifecycle/spec.md#requirement-the-seller-half-lists-deals` (by the archive); `openspec/specs/deal-lifecycle/architecture.md#one-end-instant-transactional-admission` ("When a deal is ended"), `#buyer-surrender-and-cases` and `#current-limits`; `openspec/specs/settlement-servicing/architecture.md#charge-first-payment-settlement` and `#current-limits`; `kit/arkhai-mediation/README.md`, written with the code |
| D17 — the scenario programs the payments double's further reservation | `openspec/specs/test-compatibility/spec.md#requirement-lane-double-controls-are-typed-deterministic-steps` (by the archive); `openspec/specs/test-compatibility/architecture.md#the-in-lane-payments-double` and `#lane-time-and-the-doubles-controls`; `docs/development/TESTING.md#private-service-dependencies`; `kit/arkhai-payments/README.md`, `tools/payments-lane-double/README.md` and `tools/lane-double-controls/README.md`, written with the code |
| D18, D19 — the watchdog's storefront paused; the Compose lanes as evidence | `openspec/specs/test-compatibility/spec.md#requirement-the-buyers-watchdog-is-qualified-against-a-delivered-deal` and `#requirement-rate-mechanics-qualification-consumes-the-shared-lane-contract` (by the archive); `docs/development/TESTING.md#the-canonical-compute-deal` |
| D20 — the watchdog's buyer runs in the harness's process, its probe and clock programmed | `openspec/specs/test-compatibility/spec.md#requirement-the-buyers-watchdog-is-qualified-against-a-delivered-deal` (by the archive); `docs/development/TESTING.md#the-canonical-compute-deal` and `#lane-time`; `openspec/specs/test-compatibility/architecture.md#lane-time-and-the-doubles-controls`; `openspec/specs/buyer-orchestration/architecture.md#the-buyers-watchdog` and `#the-buyers-time`; `e2e-tests/README.md` and `e2e-tests/tests/e2e/roles/buyer_cli.py`'s module note, written with the code |
| The owner's principle: a change taking on another change's work names the move | `docs/guidance/workflow/changes.md#defects-found-during-a-change` |
| The owner's principle: a released client is not owed compatibility with a later storefront | `docs/guidance/repository/package-versions.md#compatibility-is-owed-to-what-a-release-has-shipped` |
| The owner's principle: a producer's scheduled actions are answers a scenario programs | `docs/guidance/engineering/test-doubles.md#a-double-mirrors-its-producer` |
| The owner's principle: a local end-to-end test holds a party's time-based signals by pausing it | `docs/guidance/repository/deterministic-tests.md#pause-the-loop-then-advance-it-explicitly` |
| The owner's principle: a CLI under a system test is controlled as a service is, its mock layer in the harness's process | `docs/guidance/engineering/system-tests.md#a-system-test-reaches-services-only-through-their-interfaces` |
| Roadmap currency | `docs/development/ROADMAP.md`, Goal 8: the open-gap row removed; the current state absorbs rate delivery and servicing in both storefronts, classification, *ended* and *ending*, the shared servicing order and loop layout, the buyer's display and the lane qualification; the respondent/term-end difference dropped |
| Campaign index currency | `openspec/changes/README.md`: this change's row, linked to its archive directory; the unowned rows "`VmSettlementComposition` builds no payments seller stage" and "The VM buyer's settlement wait has no clock seam" removed; the Goal 8 prose's refusal wording made current |
