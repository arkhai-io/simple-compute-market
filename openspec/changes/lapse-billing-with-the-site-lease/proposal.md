## Why

A per-period compute deal is kept honest after commitment by actions at the
authorities: the buyer's own stop at the payment authority, a seller's self-filed
exceptional end, a case over held money (`agreed-evidence-and-early-termination`).
Two things that model does not provide are worth having on their own terms:

- **A bound on billing that needs nobody to notice.** When the resource is lost
  while the seller's storefront is down, the buyer is charged until its own stop
  lands, and the money is returned only if the seller recovers within the dispute
  window or a person rules a case. A storefront that vouches for billing only as far
  ahead as it has verified the lease is alive turns that into a bound the payment
  authority enforces by itself: billing lapses when the vouch does.
- **A site's protection from a storefront that is not its own business.** The
  activation deadline (`renewable-compute-lease-deadlines`) expires a lease whose
  storefront dies before delivery; an active lease runs to its agreed end whatever
  happens to the storefront. A site operator who is not the storefront operator has
  no way to bound its exposure to a storefront that has gone.

Both were designed under the roadmap goal that sells compute by the period
([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops))
and set aside there, because the goal's guarantees rest on the authorities alone and
because reclaiming a working lease without lapsing its billing costs the buyer a
VM and the seller a self-penalty for a crash. Kept together they cost neither: the
lease and the billing lapse at the same instant. This change preserves that design
for the day either need is real.

## What Changes

- **A billing horizon on a rate part**, advanced only by the payee: a `vouch` the
  storefront sends each cycle to the earliest of now plus the option's reserve-ahead,
  the funded-through time and the agreed end; periods begin only inside it; when it
  lapses unadvanced, the payment authority stops the part itself with cause `terms`,
  settled to the lapsed instant. This is a payments-service capability the published
  contract lacks, and this change's design states it as the one requirement it makes
  of the service.
- **A renewable site deadline on an active lease**, beside the agreed end and after
  the activation deadline: the storefront renews it to the same instant it vouched
  for in the same cycle; renewal moves it later only, never past the agreed end, and
  is refused once release is claimed; expiry claims against the deadline and phase it
  read, so an elapsed but unclaimed deadline may still be renewed.
- **A per-pool lapse policy** the site applies alone when a deadline passes
  unrenewed — `reclaim` (expire at the deadline), bounded `grace` (expire later, the
  duration visible), or `continue` (serve to the agreed end as operator-accepted
  risk) — with a site-wide default; the site never learns why a renewal lapsed, and
  the lease view and the `lease_ended` event carry the deadline, its phase, the
  policy and the cause `renewal_lapsed`.
- **The continuation's vouch-and-renew step** in the rate servicing loop, recording
  each instant before the call, so a dead storefront's billing and lease lapse
  together within one cycle, and the buyer's worst case for an unobserved end is the
  option's reserve-ahead.

## Capabilities

### Modified Capabilities

Expected: `settlement-servicing` (the horizon and the vouch), `site-capacity` (the
deadline, the renew transition, the claim rule), `physical-provisioning` (the
watchdog and the lapse cause), `resource-pool-management` (the lapse policy tag),
`deal-lifecycle` (the vouch-and-renew step). `.openspec.yaml` sets `skip_specs`
until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Replacing any guarantee Goal 8 gives through the authorities; the horizon and
  the renewal bound the honest-crash case and the separate-operator case on top of
  them.
- Deciding whether to renew: the storefront renews only on verified funding and a
  verified lease.
- Pooled funding or a lease pool sharing one deadline across reservations.

## Dependencies and Related Changes

- Depends on `renewable-compute-lease-deadlines` (the deadline column and the
  activation phase this change's renewal follows) and `converge-ongoing-compute-leases`
  (the loop the vouch-and-renew step joins).
- Externally, the horizon is a payments-service capability; the design states the
  requirement and the vector it would verify against.
- Revisit triggers: a site operator who is not the storefront operator; or buyers
  who need a billing bound that does not depend on their own attention.

## Impact

`kit/arkhai-payments` (the vouch operation and its verification), `kit/site`'s
models, migration, ledger and client, the provisioning service's lease lifecycle
and watchdog, `kit/resource-pools-contracts`' hints, `kit/deal-servicing`'s loop,
and the site's integration suite.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Capacity reservation" and "Recovery
  workers"
- [x] Existing subsystem specification: `settlement-servicing`, `site-capacity`,
  `physical-provisioning`, `resource-pool-management`, `deal-lifecycle`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Billing and the lease lapse together when the storefront stops vouching;
  nothing accrues that the storefront did not vouch for while alive —
  `settlement-servicing` and `deal-lifecycle` specs.
- What an unrenewed lease does is the site operator's policy, applied with no
  knowledge of payment — `site-capacity` spec and architecture companion.
