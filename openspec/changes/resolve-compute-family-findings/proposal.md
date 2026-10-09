## Why

Moving provisioning execution into the compute family kit, composing bare metal
onto the kit negotiation runtime, and running a bare-metal deal in the pipeline
surfaced defects and dead surfaces that were outside that work's scope. Each is
small; together they are the compute family's known debt, and none has another
owner. `bare-metal-mock-provisioned-deal` recorded them as it found them; its
design (archived) holds the context for each.

The substantive gaps it found — host-secret protection, failure classification,
guest network isolation, disabled-host admission, a relay lane, the
administrator stance, lease start policy, and pricing an escrow that names no
contract — are open roadmap gaps rather than part of this change.

## What Changes

Typed and single-sourced route contracts:

- `kit/site` serves a router of its own rather than contributing its routes as
  data the composition root binds; the site's server and client state their
  contracts twice; the family contracts carry path templates; VM's pool-override
  route is a literal path.
- Bare metal's mock-rule routes, and the system worker controls' responses, are
  untyped bodies.

Dead or senderless surfaces — remove each, or give it its caller:

- `ReservationState.provisioning`, which nothing sets: `commit` moves a reservation
  from `reserved` past it.
- The site ledger's `find_active_lease_by_vm_target`, which nothing calls (its
  docstring names a retired VM removal route), with its match on a reservation's
  `executor_target`, and the `vm_target` key the ledger's reservation payload still
  emits.
- The VM storefront's fulfillment-failed callback and admin usage-started event,
  which have no production sender (and usage-started's unrecorded `host_id`), and
  its uncalled `terminate_vm_lease`.
- The VM storefront wheel's shipped `[provisioning] mode`, which nothing reads, and
  the validation runbook's Helm override of it.

Behaviour that answers wrongly:

- The provisioning service's authentication middleware raises on an authenticated
  request matching no route contract, so it answers 500 rather than 404 or 405.
- VM's operator `create_vm` route checks no guest name against the rules
  provisioning's own names satisfy, so a name whose login exceeds 32 characters
  fails at `useradd`.
- A restarted bare-metal storefront whose site reports a different delivery for an
  active lease answers the buyer's status read with an unhandled 500.
- The bare-metal storefront's begin reads a scheduled resource's nested
  `bare_metal_publication.physical_host_id`, a shape the site treats as legacy.
- The policy kit's refusal of an unknown middleware name points a bare-metal
  operator at the VM policy package.
- The bare-metal settlement servicing worker has no event callback, so a failing
  servicing step retries with no stage event or log line; only the administrator's
  settlement wait wakes servicing when a lease becomes active, where
  `BareMetalFulfillmentService.status` recording the transition should; and that
  wait fails on a site error rather than polling through it.
- The bare-metal Compose wrapper and Helm chart forward no seller negotiation
  chain, so only the lane's overlay sets one.
- An interrupted contact-exchange reveal is finished only by the buyer retrying,
  though the servicing worker could finish it from the persisted introduction.
- A seller's EVM address and wallet key are separate inputs nothing checks against
  each other; the Alkahest address book is named both by the settlement section and
  by each chain.
- The fulfillment convergence sweep logs its counts as structured fields the
  end-to-end lanes' plain-text log format does not print.

Placement and test reliability:

- The relay administration, port allocator, port lease, pool-configuration, and VM
  codec suites test VM-owned behaviour from the provisioning service's suite.
- The provisioning integration harness shares one in-memory SQLite connection
  across sessions, so a dispatched job can end the transaction the authentication
  middleware is committing; production uses a connection per session.
- The site ledger keys reservation idempotency and release-by-escrow on the escrow,
  which hosted deals lack, while jobs correlate on the capacity reservation.
- Bare metal's listing recheck and publication read each site's projection live,
  where VM reads the projections its storefront holds; API credits'
  `credit_quota_guard` could move onto the kit's listing-source verdict.

State: **proposed; design not started.** Design decides, per item, fix or record
as accepted.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None expected; `.openspec.yaml` sets `skip_specs`. Design adds a delta and clears
it for any item that changes a normative requirement (the 500, for instance).

## Non-Goals

- The roadmap's substantive gaps listed under Why.
- Should anything come to act on a reservation's recorded executor target, a
  deliberate operation to resolve a reservation whose recorded target differs from
  its fulfillment's is needed with it; nothing does today.

## Dependencies and Related Changes

- Follows `bare-metal-mock-provisioned-deal` (archived), which recorded each item.
- The VM storefront items coordinate with `remove-dead-storefront-physical-surfaces`
  and `pools-9-retire-local-physical-authority`; the listing-source items with
  `kit-owned-listing-and-fulfillment-lifecycles`.

## Impact

`provisioning/compute/`, `kit/site`, `kit/policy`, `domains/vms/`, and
`domains/bare_metal/`; the bare-metal Helm chart and Compose wrapper.
