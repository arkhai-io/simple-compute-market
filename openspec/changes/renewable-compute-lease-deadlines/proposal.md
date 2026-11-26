# Compute lease delivery deadlines

## Why

A storefront can stop between committing capacity at a site and delivering it. The site
then holds that capacity until the deal's agreed end, because no site enforces a
delivery deadline:

- Commit records a lease's window and nothing else, and the lease watchdog's due read
  selects a lease only by its end (`kit/site/src/market_site/ledger.py`, `commit` and
  `list_lease_due`).
- The storefront alone enforces the deadline a deal accepted. Its servicing journal
  records non-delivery at the earlier of the term end and the deadline, and for a deal
  that is not once-only it does so only after a payment read made at or after the
  deadline (`kit/deal-servicing/src/market_deal_servicing/journal.py`; `deal-lifecycle`'s
  "Non-delivery is established at the delivery deadline" and "Delivery authorization
  delegates payment interpretation"). A storefront that is down, whose loops are held,
  whose database is lost, or that cannot read the payment authority enforces nothing.
- The remedy marketplace 0.4.0 ships is manual. The operator handbook's "Leases the
  storefront has not delivered" has an operator find active leases with no
  `activated_at_utc` and end them at the site.

On-demand and spot VM are a supported configuration in 0.4.0, and such a deal's agreed
end is the seller's maximum horizon, which may be days or years away. A storefront lost
before delivery pins capacity for all of it.

The term the buyer reads already exists. A compute option publishes
`lifecycle.delivery_deadline_seconds`: the value the composition's
`delivery_deadline_for_pool` port gives for the pool, else the one the seller's payments
clause configures (`storefront-publication`'s "A compute option's delivery deadline is
its pool's, else its clause's"). Neither compute composition supplies the port, so every
published deadline is the clause's, and nothing ties it to what a site would enforce.

## What Changes

- **The site records an activation deadline at commit.** Where the reservation's pool
  resolves a delivery deadline, the first commit records the later of the deal's
  commitment instant and the lease start, plus the deal's accepted
  `delivery_deadline_seconds`, or plus the pool's value where the commit carries none.
  A commit asking for more than the pool resolves is refused. A pool that resolves none
  records none. Existing leases have none and behave as before.
- **An unactivated lease is due at its deadline.** A lease with a deadline and no
  recorded activation is due at the earlier of the deadline and its agreed end. Expiry
  claims the lease as its due read saw it, so an activation that arrives first defeats a
  stale claim and a claim that arrives first is not undone.
- **A pool states its delivery deadline.** The pool's `delivery_deadline_seconds` tag
  has three states: a number of seconds; nothing, which resolves the provider's declared
  default; or none, which enforces no deadline. Enforcement varies by pool. No service
  setting turns it on or off.
- **Providers declare a default.** The VM and bare-metal providers declare one; the
  API-credits provider declares none, so a quota hold gets no deadline by the same rule.
- **The storefront supplies the deal's facts with the commit.** The one compute delivery
  path sends the deal's accepted deadline and commitment instant.
- **Both compute compositions publish the pool's value.** `delivery_deadline_for_pool`
  returns the pool's resolved deadline. The clause-configured deadline is kept: it is
  published where the pool gives none, and publication reports a clause value that a
  pool's different value replaced.
- **An activation lapse is reported.** The signed `lease_ended` report carries a cause
  for it, the deadline claimed and a phase naming that deadline. It is evidence of an
  intended end, not of completed teardown or of anything owed.
- **Both lease views show the deadline**, beside `activated_at_utc`.
- **The operator handbook** gains the upgrade step for a site whose storefronts still
  run 0.4.0, and its "Leases the storefront has not delivered" is rewritten for a pool
  that enforces a deadline and kept for one that states none.

What the design leaves open is in its "Open Questions".

## Capabilities

### Modified Capabilities

- `site-capacity`: the activation deadline, the commit's refusal, the due instant and
  the expiry claim. Its "Resource-pool projection metadata" changes too if the design
  settles that the resolved deadline is projected.
- `resource-pool-management`: the tag's three states, provider defaults and the resolved
  value.
- `physical-provisioning`: the watchdog releasing a lease at its deadline, and the lapse
  report.
- `compute-delivery`: the commit carrying the accepted deadline and commitment instant.
- `compute-provisioning-contract`: the lease view's deadline.
- `storefront-publication`: the report of a clause value a pool's value replaced.

### New Capabilities

None.

## Non-Goals

- Renewing a deadline on an active lease, a policy for a lapsed one, and any end of
  delivery calculated from what a deal has funded: `lapse-billing-with-the-site-lease`
  (design D4).
- Retiring the clause-configured deadline (D7).
- A service-level or site-wide setting for enforcement, and a way for a committer to
  opt a lease out (D3).
- A buyer's guarantee. The site's deadline is the seller's capacity safeguard; the
  buyer's deadline is judged by the dispute authority (D1).
- A refund triggered by a site event. End service classifies a failed delivery and the
  seller files `delivery_end`; the site's report is evidence.
- The activation instant and transition, which `activate-compute-leases-at-the-site`
  landed.

## Dependencies and Related Changes

- **`inject-site-pool-authority` gates implementation.** The site ledger reads pool rows
  directly today; that change replaces the read with pool facts its composition injects,
  read in the caller's session. This change needs one more fact through it: the pool's
  resolved delivery deadline, readable in the commit's own transaction, resolved by the
  pool authority from the pool's tag and the provider defaults the composition supplies.
  The port's names, its typing and how a missing fact fails follow that change's
  recorded design.
- **Builds on**, all archived: `activate-compute-leases-at-the-site` (the activation
  instant), `agreed-evidence-and-early-termination` (the `lease_ended` report with its
  claimed deadline and phase), `unify-compute-delivery-path` (one commit step, the
  refused-commit classification and the activation-lapse hand-off),
  `negotiate-open-ended-compute-terms` (the term, the port and the precedence),
  `drive-the-storefront-clock-in-lanes` (the site deciding by its process's time source)
  and `serve-running-rate-deals` (end service's deadline rule).
- `converge-ongoing-compute-leases` gives this change its late-anchor row (that
  change's design, D5). The form in which this change proves it is open in the design.
- `lapse-billing-with-the-site-lease` depends on this change and holds what D4 names.
- `activate-per-period-compute-servicing` depends on this change.
- `capacity-reservation-lifecycle-hardening` indexes hold expiry on the same table. The
  two coordinate migration order; neither depends on the other's behaviour.

## Impact

`kit/site` (schema, ledger, commit request, reservation view), `kit/site-client`,
`kit/capacity-publication`, `kit/resource-pools-contracts` and `kit/resource-pools` (the
tag, its validation, the resolved value), the VM and bare-metal provisioning adapters
(their declarations), `provisioning/compute` (the lease lifecycle, the lease view, the
service's composition), `domains/compute/delivery` (the commit), `domains/compute` (the
classification of a site's end), both compute storefronts' settlement compositions,
`kit/settlement-runtime` (the publication report), `docs/operator-handbook.md` and
`docs/development/DEPLOYMENT_AND_CONFIG.md`.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag, which carries
every form below as it stands on the development branch.

- **Persistence.** One nullable column is appended to the shared site schema, which the
  provisioning service and the API-credits service both apply. A lease a 0.4.0 site
  committed has none and is due only at its end.
- **The commit request.** Two optional fields. A 0.4.0 site ignores them and enforces
  nothing, as today. A 0.4.0 storefront sends neither, and the site then applies the
  pool's value (D1).
- **The pool tag.** A pool written under 0.4.0 states nothing, so on upgrade it resolves
  its provider's default for new commits. A 0.4.0 storefront published its clause's
  deadline, and a shorter pool value would reclaim its lease early. The handbook's
  upgrade step is to upgrade storefronts first, or to state none, or a value at least
  the clause's, on the pools they sell until they are upgraded (D3).
- **The `lease_ended` report.** Its version is unchanged; the cause and the phase are
  open strings. A 0.4.0 storefront leaves a phase it does not know unclassified.
- **The lease view.** One optional field on the compute contract's current major.
- **Configuration.** The payments clause's `delivery_deadline_seconds` is unchanged, and
  no setting is added.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`: "Site authority", "Resource pools" and
  "Recovery workers".
- [x] Existing subsystem specification: the capabilities above.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/site-capacity/spec.md` and its companion, in a section for the
  deadline; `docs/development/ARCHITECTURE.md`, "Site authority".
- D2: `openspec/specs/site-capacity/spec.md` and its companion;
  `docs/development/ARCHITECTURE.md`, "Recovery workers".
- D3: `openspec/specs/resource-pool-management/spec.md` and its companion;
  `docs/development/ARCHITECTURE.md`, "Resource pools";
  `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/operator-handbook.md`, "Pool
  definitions", "Leases the storefront has not delivered" and the upgrade steps.
- D4: no permanent destination — a boundary between two changes.
- D5: `openspec/specs/physical-provisioning/spec.md` and its companion, "Lease-end report
  delivery"; `openspec/specs/compute-provisioning-contract/spec.md`.
- D6: `openspec/specs/compute-delivery/spec.md` and its companion;
  `openspec/specs/storefront-publication/architecture.md`.
- D7: `openspec/specs/storefront-publication/spec.md` and its companion, for the report
  of a replaced clause value; `openspec/specs/settlement-configuration/configuration.md`
  and `docs/seller-quickstart.md`, which go on describing the clause deadline as what is
  published where a pool gives none.
