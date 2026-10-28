## Why

Once a deal can be per-period
([`negotiate-open-ended-compute-terms`](../negotiate-open-ended-compute-terms/)) and
its mandate a `rate` part the kit can start, stop, and prove
([`settle-ongoing-compute-through-arkhai-payments`](../settle-ongoing-compute-through-arkhai-payments/)),
nothing yet keeps such a deal honest while it runs. No storefront watches a transaction
after delivery starts: VM's `VmPaymentsCoordinator` spawns provisioning and then nothing,
bare metal's and credits' reconciliation passes skip delivered deals, so a buyer whose
funds run out, or who stops the transaction, keeps the VM or host until the lease the
seller committed ends. And the site has nothing to catch a storefront that dies: a lease
committed to the seller's bound runs to it, paid or not.

This is the integration point of the roadmap goal that sells compute by the period until
either party stops ([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)):
the site-side lease machinery that lets a storefront keep a lease alive only while it
can prove funding, and the storefront-side continuation that does so, in both compute
domains.

## What Changes

At the site (`kit/site`, served by the compute provisioning service):

- A nullable `renew_by_utc` on the reservation: a lease not renewed by it expires
  early, exactly as it expires at `lease_end_utc`. Set at commit, moved later by a new
  **renew** transition — only from `leased`, only later, never past `lease_end_utc` —
  and truncated with the end. Null for a prepaid deal, which behaves as today. The
  watchdog expires a lease at the earlier of the two; admission's overlap check keeps
  reading `lease_end_utc`, since the capacity is committed through the agreed end
  whatever the renewal deadline says.
- A **renewal-lapse policy**, per pool as a policy tag with a site-wide default, for a
  lease whose `renew_by_utc` passed unrenewed: `reclaim` (expire at the deadline, the
  default and today's behaviour), `grace <seconds>` (expire that much later), or
  `continue` (run to the agreed end; the site holds the storefront accountable outside
  the codebase). The site never learns why a renewal lapsed.
- The lease-ended report `buyer-initiated-compute-termination` added is sent for
  expiry at `renew_by_utc` and at `lease_end_utc` alike, with its cause.

In the storefront, built once in the payments mechanism kit with each compute domain
contributing only its delivery and teardown hooks, as the rest of the payments
integration is:

- A **continuation** for every delivered per-period deal, a storefront lifecycle loop
  on the kit loop controller: it issues `start` when delivery is verified, polls the
  signed snapshot within the option's `reserve_ahead`, renews the lease to the verified
  `fundedThrough` on each snapshot, terminates the lease at once — through the
  terminate route, never truncation — on a verified stop or exhaustion, and recomputes
  everything from the snapshot on restart. It renews only on verified funding, so an
  unreachable payments service leaves the lease to the site's lapse policy.
- The storefront issues the **payee stop at a lease's end** — the site's lease-ended
  report, expiry at the seller's bound included — so billing ends with the lease, and
  backdates it where the service permits when it learns of the end late.
- The reconciliation pass that converges approved-but-unsettled deals also stops and
  reverses a per-period transaction whose delivery failed, returning its reserved
  first batch.
- The buyer's cancel issues the **payer stop first**, directly at the payments service,
  then calls the end-deal route; the payer stop is authoritative whatever the storefront
  does, and the continuation discovers a stop the buyer never reported.
- An **operator stop command** over the storefront's stored state — the mandate and
  transaction ID in `negotiation_threads.settlement_data`, the operator's credential —
  that works with the storefront process down, so the seller of record can always end
  billing.
- The stop intent gains the causes `funding_ended`, `deadline`, and `site_withdrawal`,
  with their financial convergence.
- End-to-end: on-demand VM and bare-metal deals in the pipeline against the in-lane
  double — continued funding does not end a lease merely because a polling interval or
  period passed; buyer cancel stops billing and returns capacity; exhaustion ends the
  lease within the funded horizon; a storefront restart resumes the continuation; the
  seller's bound ends both lease and billing; a crash between delivery and `start`
  re-issues nothing twice.

## Capabilities

### Modified Capabilities

Expected: `site-capacity` (renewal, the lapse policy, overlap), `physical-provisioning`
(the watchdog, the report's causes), `settlement-servicing` (the continuation, the
stops), `vm-storefront-fulfillment`, `market-composition` (the loop),
`buyer-orchestration` (payer stop first), `test-compatibility`. `.openspec.yaml` sets
`skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Seller preemption: [`publish-and-preempt-spot-compute`](../publish-and-preempt-spot-compute/).
- Pooled funding — one balance behind several leases, all ending when it lapses — and
  the lease pool that would renew them at once; unowned, recorded in the goal.
- A storefront–site liability ledger (what the storefront owes the site, with penalties
  for failing to relay a stop); unowned, recorded in the goal. The `continue` lapse
  policy is where it would attach.
- Push delivery of payment events; polling within `reserve_ahead` is the correctness
  path and a push would only make teardown prompter.
- Extending a lease past its agreed end.

## Dependencies and Related Changes

- Depends on `buyer-initiated-compute-termination` (the stop intent, the end-deal
  route, the lease-ended report), `negotiate-open-ended-compute-terms` (per-period
  deals exist), and `settle-ongoing-compute-through-arkhai-payments` (rate parts,
  verified snapshots, `start`/`stop`, the double).
- `capacity-reservation-lifecycle-hardening` touches the reservation ledger's expiry
  scan; the renewal deadline joins whatever index it adds.
- `replace-polling-with-authenticated-push` plans a transactional outbox for site
  events; the lease-ended report rides it when it lands.
- `redesign-storefront-stage-events` decides the event vocabulary the continuation
  emits into.

## Impact

`kit/site`'s ledger, models, migration, router, and client; the provisioning service's
lease lifecycle and watchdog; `kit/arkhai-payments`' seller stage; both compute
storefronts' payment coordinators, settlement compositions, loop registrations, and
operator CLIs; `core/buyer`'s and both buyers' settle paths; the compute deal stages and
new per-period scenarios in both lanes. One compute provisioning migration adds the
column and the policy tag.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Capacity reservation", "Release",
  "Recovery workers", and "Settlement servicing"
- [x] Existing subsystem specification: `site-capacity`, `physical-provisioning`,
  `settlement-servicing`, `vm-storefront-fulfillment`, `market-composition`,
  `buyer-orchestration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A lease is kept alive by renewal, which the storefront makes only on verified
  funding, and the site decides what an unrenewed lease does — `site-capacity` spec and
  architecture companion; `ARCHITECTURE.md`, "Capacity reservation" and "Recovery
  workers".
- Stopping payment first is always safe for the buyer, reclaiming first is always safe
  for the seller's hardware, and the storefront reconciles whichever came first —
  `ARCHITECTURE.md`, "Deciding which party is authoritative"; `settlement-servicing`
  architecture companion.
- The continuation's cadence plus teardown fits inside `reserve_ahead` —
  `settlement-configuration` spec.
- The seller's stop lever works with the storefront process down — `settlement-servicing`
  spec.
