## Why

A lease committed at the site runs to the end the deal agreed, whatever happens to the
storefront that committed it. For a prepaid deal that is right: the funds are held for
the whole term. For a deal paid per period it is not: the storefront that verifies
funding may die, the payments service may become unreachable, and the lease then runs
to the seller's bound unpaid. Nothing at the site can tell a funded lease from an
abandoned one, because the site — correctly — knows nothing about payment.

This is the site half of the roadmap goal that sells compute by the period until either
party stops ([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)):
a lease the storefront must keep renewing, and a site that decides for itself what an
unrenewed lease does. It is split from
[`converge-ongoing-compute-leases`](../converge-ongoing-compute-leases/) because it is
a `kit/site` change with its own spec deltas and its own integration suite, testable
with no storefront, and existing fixed-term leases behave exactly as they do today.

## What Changes

In `kit/site` and the compute provisioning service that composes it:

- A nullable `renew_by_utc` and a `renewal_phase` on the reservation beside the agreed
  `lease_end_utc`, which keeps its meaning and is still moved only by truncation. A
  lease not renewed by its deadline expires early, exactly as it expires at its end:
  the watchdog's due query reads the earlier of the two. Null for a lease committed
  before this change, which is unchanged.
- Two transitions. **Activation**, once, from phase `provisioning`: replaces the
  deadline with the instant the storefront names, earlier or later, capped by the end
  — a reserved deal activates to its agreed end, a per-period deal to its funded
  horizon. **Renewal**, in phase `active`: only from `leased`, only to a later
  instant, never past `lease_end_utc`; refused from `releasing`. Truncating the end
  truncates the deadline with it.
- **Expiry claims the lease against the deadline and phase it read**: the release
  transition is conditioned on the state *and* on the deadline and phase the due query
  returned, so an activation or renewal that lands between the read and the claim
  makes the claim fail and nothing is written. A deadline that has elapsed but is not
  yet claimed may still be renewed or activated: the deadline is enforced by the
  claim, not by the clock. Admission's overlap check
  keeps reading `lease_end_utc`: the capacity is committed through the agreed end
  whatever the deadline says, or a forward reservation could be admitted into a window
  a running deal then renews into.
- A **provisioning budget**, a Resource Pool policy tag the site reads itself at
  commit: *every* commit records `renew_by_utc = commit + budget` in phase
  `provisioning`, with no flag and no request field — the site classifies no lease.
  A storefront that dies before delivery leaves a lease that expires, reserved or
  per-period alike, and a slow provision has the time the pool's operator gave it
  rather than the running lease's renewal allowance. Provisioning time is non-billable
  by construction and accounted separately: the site stamps the active instant it
  already records at activation, so provisioning time is that instant less the
  commit, readable per lease.
- A **renewal-lapse policy**, a pool policy tag with a site-wide default, for a lease
  whose deadline passed unrenewed: `reclaim` (expire at the deadline; the default, and
  today's expiry), `grace <seconds>` (expire that much later, bounded and reported),
  or `continue` (run to the agreed end; operator-accepted credit risk, under which an
  exhausted buyer may run on while the storefront is unreachable). The site never
  learns why a renewal lapsed.
- The `lease_ended` event `buyer-initiated-compute-termination` adds gains the cause
  `renewal_lapsed`, and the lease view exposes the deadline, its phase, and the lapse
  policy that applied.

## Capabilities

### Modified Capabilities

Expected: `site-capacity` (the field, the transition, the claim rule, overlap),
`physical-provisioning` (the watchdog and the event cause), `resource-pool-management`
(the two policy tags). `.openspec.yaml` sets `skip_specs` until design adds the
deltas.

### New Capabilities

None expected.

## Non-Goals

- Anything that decides *whether* to renew: the storefront continuation, verified
  funding, the payee stop — `converge-ongoing-compute-leases`.
- Extending `lease_end_utc`; a lease pool sharing one deadline across reservations
  (pooled funding, unowned in the goal); the storefront–site liability a `continue`
  policy would attach to (unowned).

## Dependencies and Related Changes

- Depends on `buyer-initiated-compute-termination` for the `lease_ended` event it
  extends with a cause; nothing else.
- `capacity-reservation-lifecycle-hardening` indexes *hold* expiry and prunes terminal
  rows on the same table; the deadline's due query is this change's own, and the two
  coordinate on the migration only.
- `inject-site-pool-authority` touches how the site reads pool facts; the two policy
  tags are read through whatever port it settles.

## Impact

`kit/site`'s models, migration, ledger, router, and client; `kit/site-client`; both compute storefronts' delivery paths, which activate every lease after delivery;
`kit/resource-pools-contracts`' hints; the provisioning service's lease lifecycle and
watchdog; the site's integration suite (two-session renewal-versus-expiry races, a
deadline lapsing under each policy, a prepaid lease untouched). One compute
provisioning migration adds the column; the tags need none. Pipeline evidence is
"existing lanes unchanged" until the convergence change renews a lease end to end,
which closeout records as a stated gap.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Capacity reservation" and "Recovery
  workers"
- [x] Existing subsystem specification: `site-capacity`, `physical-provisioning`,
  `resource-pool-management`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Every lease is armed at commit, activated once after delivery, and kept alive by
  renewal within its agreed end; the site classifies no lease and decides alone what
  an unrenewed one does — `site-capacity` spec and architecture companion;
  `ARCHITECTURE.md`, "Capacity reservation".
- Expiry claims against the deadline it read; the deadline is enforced by the claim —
  `site-capacity` spec.
- Provisioning has its own budget and is accounted apart from billable time —
  `resource-pool-management` spec; `physical-provisioning` spec.
