# Design — contact payload retention

## Context

The mechanism's PII posture was designed carefully and is mostly implemented. Options
and listings carry prose terms and a channel descriptor only, because a public,
scrapable registry carrying contact details would be a spam directory; payloads
persist only for deals whose introduction has been started; and both payloads persist
atomically at start, so "available to both parties" is a well-defined terminal
condition. The end of that lifecycle is the part left as a requirement without an
implementation.

What exists, read against the code:

- **The deletion primitive removes the row.** `delete_introduction(conn,
  obligation_ref)` in `kit/contact-exchange/src/market_contact_exchange/migrations.py`
  runs `DELETE FROM contact_introductions`. It is exported and unit-tested for
  returning `True` then `False` across a repeat, and has no production caller.
- **The route service reads a missing row as "never started".**
  `IntroductionRouteService.read` answers 409 "introduction has not been started" when
  `load` returns nothing. `start` checks for an existing row only to decide whether to
  deliver, then persists. After a row delete, a buyer's repeat start with a fresh
  request id therefore persists a new contact pair and delivers to the seller again.
- **Re-delivery reads the same table.** The bare-metal `redeliver-introduction`
  command loads the stored record and refuses only when none exists.
- **`created_at` exists and is never read.** It is set by SQLite at first persist,
  which is the reveal.
- **Only bare metal composes the mechanism.** `market_contact_exchange` is imported by
  the bare-metal storefront and buyer and nowhere else; VM has no introductions table.
- **The seller's configuration is typed and kit-owned.** `ContactSettlementConfig`
  holds `contact_payload` and `profiles` under the `[Settlement.contact]` root,
  tagged with the seller role, and generates role templates and schema fragments.
- **Bare metal has no loop pause.** It starts its negotiation watchdog and
  settlement-servicing worker with no predicate and steps only publication.
  `kit-owned-storefront-loop-lifecycle` supplies the controller every storefront will
  register its loops with.
- **No end-to-end scenario reaches an introduction**, and the bare-metal lane does not
  configure contact exchange.
- **The authenticated replay store keeps response bodies.** `core_storefront`'s
  `auth_replay_reservations.response_body` records the body of every authenticated
  first-dispatch response so an exact retry can be answered identically. Reveal
  responses carry the counterparty's contact, so each reveal leaves a copy there. The
  table records no operation or resource, and nothing prunes it.

## Goals / Non-Goals

**Goals.** Make the existing retention requirement executable and safe: a deletion no
party can undo, a window a party can read before committing contact data and again at
reveal, and a deal that stays intact when its payloads go.

**Non-Goals.** No aliasing, no change to what is persisted at start, no registry or
listing-shape change, no VM composition.

## Decisions

### Placement: kit first

A compute-family storefront serving several domains, as the provisioning service
already serves several, is the long-term direction. Anything this change adds that is
not truly bare-metal-only therefore lands in `kit/contact-exchange`:

- redaction, the tombstone column, the triggers, and the select-expired query;
- the `retention_seconds` configuration field;
- the one deletion operation, the sweep cycle, and the sweep loop runner;
- a framework-free retention admin service — delete one introduction, run one sweep,
  preview the next sweep — following the precedent `kit/pool-overrides` set, which
  each storefront binds into its own router behind its own administrator
  authentication;
- the disclosure model, and the route service's behaviour after deletion.

Bare metal keeps only wiring: its persistence wrappers, embedding the disclosure
object in its readiness response, binding the admin service into its router,
registering the sweep loop with the kit loop controller, and refusing re-delivery
through the kit's projection.

The sweep loop runner takes a `paused` gate and an injected wait rather than importing
the loop controller, because `kit/storefront` depends on Alkahest and the mechanism
kit's boundary test forbids that dependency.

### Ordering: retention on bare metal now; VM inherits it

Reversing the dependency — composing VM first and adding retention once over both
domains — was considered and rejected. Almost all of retention is kit work, which is
where `compose-contact-exchange-across-compute` already places its promoted glue, so
doing retention first causes no later move. What VM then adds is wiring: registering
the sweep loop, binding the admin service, and embedding the disclosure. That
composition change owns it, alongside composing the mechanism.

Reversing would also ship VM holding contact data with no deletion path, against that
change's own recorded gate, and would put the larger change, whose system evidence
depends on the VM lane, at the head of Goal 7's critical path.

So that a later composing domain cannot omit retention, the specification requires it
of every storefront that composes the mechanism.

### Deletion redacts in place and leaves a tombstone

Deleting the row is what makes deletion unsafe: the row's existence is the only
record that the introduction was revealed, so removing it erases the fact as well as
the payloads, and the next start reveals again.

The row is therefore kept. Redaction sets an additive `payloads_deleted_at` column and
empties both contact columns in one statement, so a concurrent read sees either the
whole introduction or the tombstone and never a partial record. The agreed
`introduction_package` is kept: it is a copy of the accepted plan's service terms,
which persist in the negotiation thread regardless, so removing it here would remove
nothing.

Alternatives rejected:

- **A separate tombstone table** keeps two tables that must agree and adds a read to
  every reveal.
- **Inferring deletion from obligation state** (collected but no row) fails when
  `persist` succeeded and `complete` did not: the obligation is not collected, the row
  is gone, and a later start reveals again.

The existing primitive is replaced rather than joined by a second implementation. It
has no production caller, so it is renamed to say what it now does:
`delete_introduction_payloads`. It returns `True` when it redacts and `False` for an
already-redacted or absent row.

### The active part of the table is append-only, enforced by triggers

A row is inserted once at reveal and changed at most once, by redaction. Triggers make
that mechanical, as the storefront's listing-binding triggers already do for backing
and closure reasons:

- an update is refused unless it is the one-way redaction: `payloads_deleted_at` goes
  from null to a value, both contacts become empty, and nothing else changes;
- deleting a row whose payloads have not been deleted is refused.

Removing a payload can then only go through redaction, which leaves the tombstone.
Deleting a tombstone stays permitted, because that is how state growth will
eventually be managed.

**Tombstone removal is anticipated and unowned.** A tombstone may be removed only once
its deal can no longer be revealed again — that is, once the accepted negotiation
thread that `prepare` resolves is itself gone. Removing one earlier reopens the
re-reveal this decision closes. No change owns that cleanup.

### What every surface does after deletion

- **Read** answers 410 with the stable code `introduction_payloads_deleted` and the
  time of deletion. It never returns a partial introduction.
- **Start** still drives the obligation to collected, which is idempotent and lets a
  deal whose earlier completion failed converge, then answers the same 410. It
  persists nothing and delivers nothing.
- **The projection** used by read, start, and re-delivery refuses a redacted record,
  so no surface can emit an empty contact as though it were a reveal.
- **Re-delivery** refuses a deleted introduction and delivers nothing.
- **The buyer** reports the deleted outcome as its own result rather than as a
  generic failure.

### Retention is an aggregate policy over the storefront's dataset

The window is a property of the storefront's data holdings, not a term of any deal.
Nothing in the settlement plan, the obligation, or `service_terms` carries it; it is
not negotiated or agreed. The storefront pays for the storage and carries the
liability for holding the data, so the storefront sets the policy, and parties
exercise choice by selecting a storefront whose retention they accept — which is why
the window must be discoverable.

**Rejected: recording the window on each row at reveal and enforcing the recorded
value.** An operator who shortens the policy — for cost, an incident, or a legal
instruction — would find it does not apply to the data they most want gone, and the
operator can delete any row directly regardless, so a per-row pin protects nothing.

The window is read from the running configuration at each sweep and each disclosure.
A change takes effect when the storefront restarts with it and applies to every
existing row. Setting a finite window is consent to delete existing rows past it;
setting `indefinite` stops deletion.

### The window is mechanism configuration with a 30-day default

`retention_seconds` joins `ContactSettlementConfig`, tagged with the seller role, as a
positive integer or the literal `"indefinite"`, defaulting to `2592000` (30 days).
Zero is refused, so a typo cannot delete introductions moments after they are
revealed.

The mechanism's typed configuration already holds the seller's contact payload, so
the policy governing that payload sits beside it, and VM inherits the setting through
the same `[Settlement.contact]` root with no per-domain parsing. A literal sentinel
rather than a null is needed because TOML, which VM's configuration uses, has no null.
Generated templates and schema fragments regenerate with the field.

30 days is an unremarkable retention period for transactional contact data. Nothing
is released, so no deployment holds historical payloads a first sweep would delete.

### A row is eligible when its reveal is older than the window

An introduction is eligible for deletion when `now ≥ created_at + window`.
`created_at` is set at first persist, which is the reveal.

### Both invocation paths, one operation

The sweep runs unattended on a configurable interval, and an operator can delete one
introduction on request. Neither substitutes for the other: a policy honoured only
when an operator remembers is the hand-written-SQL status quo, and an unattended sweep
cannot serve an out-of-schedule request for one party.

Both call `delete_introduction_payloads`. The sweep cycle selects eligible rows and
redacts each, returning a count; the loop runner repeats that cycle. The admin
service's single deletion calls the operation directly, its sweep step calls the same
cycle the timer calls, as `ARCHITECTURE.md`'s operator lifecycle rule requires, and
its preview reports what the next cycle would delete without deleting it. A
partially failed sweep converges on retry because redacting an already-redacted row
returns `False` rather than raising.

The sweep loop registers with the kit loop controller, so the lifecycle pause holds
it and its step and preview are reachable while held.

### Disclosure: one machine-readable object, before commitment and at reveal

Disclosure at reveal alone is too late to inform a choice: the buyer's contact
payload accompanies the start request, so a party reading the policy in the reveal
learns it just after the point they could have declined.

The kit defines one disclosure object:

```json
{"window_seconds": 2592000, "basis": "current_policy", "scope": "introduction_record"}
```

`window_seconds` is `null` for `indefinite`. `basis` says the value is current
storefront policy rather than a commitment: the operator may change the window or
delete a row directly at any time. `scope` says it governs the storefront's
introduction record — not copies each side's delivery sinks or the buyer's own tooling
already hold, and not responses the storefront recorded for exact retry (see "The
authenticated replay store is out of scope"). Enumerated values carry both statements
without prose that could drift between storefronts.

The object appears:

- on the storefront's public readiness projection, which bare metal serves at
  `/health` and `/api/v1/system/health`, nested so operator tooling parsing the
  readiness shape is unaffected and later disclosures have one place to land;
- in the reveal projection both parties read.

Both read the same running configuration, so they agree. It is present only when the
mechanism is enabled. `/api/v1/system/status` is not usable: it is admin-gated, and a
buyer cannot read it. An exact-retry replay before deletion returns the response
recorded at first dispatch, including the disclosure as it then stood; that is
accepted, and so, until the replay store is bounded, is a replay after deletion.

**Rejected: publishing the window into the registry** on the settlement option's
published parameters. It would put a storefront-scoped value on every listing to serve
a minority use case.

**Rejected for now: publisher-level registry metadata.** That is the right scope — the
registry's `Publisher` row already holds one storefront-scoped attribute — and where a
filterable storefront-policy facility should eventually live, but it needs a
publish-payload field, indexer handling, a read surface, and a capability that is not
this one. The readiness projection is the minimal step toward it.

### Deletion preserves the obligation record

The settled obligation record is the deal's durable identity: `obligation_ref` is the
universal deal-settlement identity that cross-mechanism status and tooling correlate
by. Removing it to remove contact data would erase the deal rather than its payloads.
Redaction touches only `contact_introductions`; the introduction remains a settled
deal with a terminal state that no longer carries anyone's contact details.

### Obligation servicing does not depend on the payloads

Nothing after the reveal re-reads the payloads to service the obligation: completion
runs within start, and the only other readers are read and re-delivery. The window
therefore has no functional floor; it is purely policy.

### The first introduction scenario runs on the bare-metal lane

No end-to-end scenario reaches an introduction today, so this change adds one. The
lane configures contact exchange with a short window. The scenario reveals an
introduction and checks both disclosures; deletes one introduction through the admin
path and observes the deleted outcome on read, start, and re-delivery; and expires
another by polling the retention preview until it reports the introduction, then
stepping the sweep. Polling the preview synchronizes on an observable transition
rather than a blind sleep. `unbacked-bare-metal-listings` can build its own
introduction evidence on this scenario.

### The authenticated replay store is out of scope

Every reveal response, carrying the counterparty's contact, is also recorded in
`core_storefront`'s `auth_replay_reservations.response_body` so that an exact retry is
answered identically, and is kept indefinitely. Redaction does not reach it: the table
records no operation or resource, so its rows cannot be attributed to an introduction.

The rows cannot simply be pruned after a freshness horizon either. Replay identity
deliberately excludes the timestamp and proof so that a caller can re-sign the same
request after a restart, which is how buyer run recovery resumes, so a row remains
consultable — and remains the evidence for refusing a changed reuse of its request id
— for as long as a caller may recover.

Attributing replay rows, recording a contact-free body for introduction operations, or
linking reveal responses to their introductions would each solve the subset of rows
this mechanism produces. How long recorded outcomes are kept and what they may hold is
a question about every authenticated response in every storefront, and the replay
stores of other authorities are about to retain outcomes as well
(`retain-authenticated-request-outcomes`). It deserves one cohesive answer rather than
a mechanism-specific exception, so this change does not attempt it and records it as
unowned work.

The consequence is stated rather than hidden. The retention window governs the
introduction record. The disclosure's `scope` says exactly that, so it makes no claim
about the replay store; an exact retry of a request answered before deletion may still
return the response recorded at the time, contact included, until the replay store is
bounded.

### Aliasing is adjacent and out of scope

A per-storefront alias needs no code — the seller's payload is configuration. A
per-deal alias needs the payload to become a resolver, the same hook per-origin
resolution in `compose-contact-exchange-across-compute` adds. Neither is retention.

### Planning decisions

Settled while planning, from the code each touches.

- **The sweep interval is mechanism configuration too.** `retention_sweep_interval_seconds`
  joins `retention_seconds` in `ContactSettlementConfig`, seller role, a positive
  integer defaulting to `3600`, so VM inherits it with the window.
- **Operator deletion has one route and one client method.** `DELETE
  /api/v1/admin/introductions/{obligation_ref}/payloads`, signed as
  `admin_delete_introduction_payloads` over the obligation reference, answering the
  reference, whether this call redacted, and the deletion time. The canonical
  `StorefrontClient` gains the method in both its async and sync forms, as the parity
  rule requires. Sweep step and preview use the lifecycle routes under the route name
  `introduction-retention`; the step answers the deleted count and the preview the
  eligible references.
- **The buyer recognises the deleted outcome from a typed error.** An authenticated
  non-success answer reaches the buyer today as an untyped `RuntimeError` carrying only
  text. `core_buyer` gains an error type carrying the verified status and body, still a
  `RuntimeError`, so existing callers are unaffected. The introduction transport maps
  410 `introduction_payloads_deleted` to its own error, and the bare-metal buyer's
  `start-introduction` and `introduction` commands print it as an outcome with
  `revealed: false` and the deletion time.
- **Readiness nests the object under `disclosures.introduction_retention`.** The
  `disclosures` key is where later storefront-configuration disclosures land.
- **The triggers state the redaction exactly.** An update is permitted only when
  `payloads_deleted_at` goes from null to a value, both contact columns become `{}`, and
  every other column is unchanged; a delete only when `payloads_deleted_at` is set.
  Eligibility compares `created_at` against `now − window` rendered in the column's own
  UTC second-precision text form, so the comparison is a string comparison SQLite can
  index.
- **The scenario offers introduction through a pool override.** Enabling contact
  exchange in the lane's settlement configuration adds no option to any listing, because
  options come from clauses. The scenario declares its own pool and sets a bare-metal
  pool override whose clauses are a single introduction option, so the existing
  publication and deal scenarios' listings and assertions are untouched.

### Implementation decisions

Settled while implementing, where the code differed from what planning assumed.

- **The sweep gates on entry.** Planning described the runner as "wait, then gate".
  `market-composition` requires a loop to read its gate when it starts, because a
  loop that sleeps first is invisible to a pause for its whole first interval. The
  runner therefore follows the watchdog's shape: gate on entry, sweep once due — the
  first sweep one interval after start, like the storefront's other loops — and wait
  through the controller. An operator wanting a sweep sooner steps it.
- **Operator deletion reports the tombstone's time.** `delete_one` answers whether
  this call redacted and when the payloads were deleted, by this call or an earlier
  one, and None when the deal never revealed an introduction. Converging rather than
  failing is the spec's requirement; reporting which case occurred is what lets an
  operator answer a request without a second query. The service takes the record
  loader to do it.
- **A redaction racing a start answers the deleted outcome.** The start reads the
  record before persisting; if the sweep redacts between that read and the persist,
  persistence refuses with a typed error and the start completes the obligation and
  answers 410, rather than a 409 conflict.
- **The canonical client reads the disclosure as a typed field.** `HealthResponse`
  gains `disclosures`, so a buyer and the end-to-end scenario read the window without
  digging in `extra`. The administrator status is built from the same readiness and
  carries it too; that is a superset, not a second disclosure surface.
- **The scenario reveals through the production buyer transport.** The e2e image
  installs no bare-metal buyer plugin. Negotiating through the canonical
  `StorefrontClient` and revealing through `IntroductionTransport` keeps the
  no-raw-calls rule and the cross-service contract without adding an e2e
  dependency; the `market bare-metal` commands' handling of the deleted outcome is
  proven by the buyer's own tests.
- **The deleted outcome's code is a wire constant on both sides.** `core_buyer`
  cannot import the mechanism kit, so it names `introduction_payloads_deleted` itself,
  as it names every other route it calls.

## Risks / Trade-offs

- **[A party is told one window and the policy changes]** → Accepted, and why the
  disclosure states current policy. The operator owns the data; no wording binds them.
- **[Disclosure is read as covering copies held elsewhere]** → Why `scope` is stated
  explicitly and names only the introduction record.
- **[Recorded replay responses outlive the window]** → Accepted for this change and
  recorded as unowned work: the replay store needs one bound for every authenticated
  response, not an exception for this mechanism.
- **[The window is discoverable per storefront, not filterable]** → Accepted for this
  version; publisher metadata is the eventual answer.
- **[Tombstones accumulate]** → One small row per revealed introduction. Removal is
  anticipated with its precondition stated above.
- **[A trigger blocks a legitimate repair]** → An operator with database access can
  drop and recreate a trigger; the triggers exist to stop code paths, not the
  database owner.

## Open questions

None.

## Migration Plan

1. Land `kit-owned-storefront-loop-lifecycle`.
2. Replace the primitive with redaction, add the tombstone column and triggers, and
   change every surface's post-deletion behaviour.
3. Add the configuration field, the sweep, the admin service, and the disclosure
   object in the kit.
4. Compose them into bare metal and add the end-to-end scenario.

The tombstone column and triggers are additive. Nothing is released, so there is no
historical payload set for a first sweep to act on and no deployment whose behaviour
changes on upgrade.
