# Design — compute lease activation at the site

## Context

`kit/site` owns the capacity reservation and the agreed lease window. Its commit is
idempotent, truncation only moves the end earlier, admission accounts the full
agreed window, and `list_lease_due` selects leased rows by `lease_end_utc`. A lease
is `leased` from commit until release; the site records nothing about whether the
resource behind it was ever provisioned.

`unify-compute-delivery-path` orders every compute delivery as commit, dispatch,
activation, billing start, access — activation being the point at which the resource
is provisioned and the lease runs in earnest — and needs the site to record that
transition once, idempotently, by reservation identity, in both domains and on every
recovery path. `renewable-compute-lease-deadlines` then gives an unactivated lease a
deadline, written at commit from the pool's policy and the deal's accepted term, and
expires the lease that never reaches activation. The deadline needs the pool-authority
port; the transition needs nothing, so the transition is this change and lands first.

## Goals / Non-Goals

**Goals:** a phase on the lease that records activation; one conditional,
idempotent activation transition; the typed contract and client every compute
caller activates through; legacy leases unchanged.

**Non-goals:** the deadline and everything that reads or writes it, renewal,
extension, payment or refund operations, and delivery-caller wiring.

## Decisions

### D1. An activation phase beside the agreed end, and one transition into it

Two nullable columns join the lease row: `renewal_phase` and `renew_by_utc`. The
names do not imply an active renewal operation; they are the columns the deadline
change and, later, any renewal design write, created once here so that the schema
changes once. `lease_end_utc` keeps meaning the agreed end and moves only through
truncation. Migration leaves both null on every existing row; an existing active
lease must not become awaiting activation during upgrade.

- **The phase.** `renewal_phase` is `awaiting_activation`, `active` or null. This
  change writes only `active`. The deadline change writes `awaiting_activation` and
  `renew_by_utc` at commit; a lease committed without a deadline, or before the
  deadline change lands, has a null phase and a null due instant.
- **Activation** is one conditional transition from `leased`, in phase
  `awaiting_activation` or null, to phase `active`. It sets the lease's due instant
  to the reservation's current `lease_end_utc`: with a deadline in place, that
  replaces the provisional deadline, earlier or later, with the agreed end; with none,
  it records the phase and changes no instant. **Every deal activates to that end**,
  reserved, on-demand, spot and Alkahest alike; the request names the reservation and
  carries no payment fact and no target time.
- **Retry and refusal.** Activation retried in `active` returns the current lease
  unchanged. From `releasing`, terminal, failed-release or operator-owned states it is
  refused without a write: activation cannot resurrect a lease, and an expiry that
  claimed the row first wins. A truncation before activation, or between a lost
  acknowledgement and its retry, is adopted: the retry returns the shorter current end
  and the original active instant, and no call extends the lease toward its original
  commit end. Activation never changes the reservation's end.
- **Admission** is untouched: it accounts the full agreed window before and after
  activation.

The phase is not a reservation state. `awaiting_activation` avoids reviving the
retired `provisioning` state. Fulfillment's active instant remains the site fact
recorded when the resource becomes usable; activation does not move it on retry.
Whether a late activation means the deal was delivered is not the site's question:
the lifecycle judges delivery by the storefront's durable `available` record against
the accepted deadline (`openspec/changes/agreed-evidence-and-early-termination/design.md`,
D8), and the site's phase is a capacity fact.

### D2. Typed activation and inspection through the shared contract

The site's typed authority, HTTP models, router and client gain activation by
reservation identity and lease inspection carrying `renewal_phase`, `renew_by_utc`
and the existing active instant, all nullable where the lease predates them. The
shared compute contract and client expose the same, offering-mode neutral: a VM or
bare-metal caller activates without importing a VM-specific model and receives the
site's recorded lease through every client layer. Requests carry no billing kind, no
funded-through time and no deadline value. The existing authenticated service
boundary and exact response verification apply; a response signed by a principal
other than the independently configured site authority is refused rather than taken
as activation.

A null-phase lease means only that no deadline was written: every lease that predates
the migration, every lease committed while `activation_deadlines_enabled` is off (the
site's shipped setting) and every lease in a pool enforcing no deadline. Read, it shows
its nulls; activated on a site that exposes the operation, it becomes `active` like any
other, with its due instant left at the agreed end and its activation recorded — the
ordinary case for all new work until the deadline change is switched on, not an edge
case about old rows. The no-op is reserved for a site that exposes no activation
operation at all: there a caller holding a verified legacy lease view treats the lease
as already active without a write, and any other phase or an unverified view is
repair-required. Those caller rules are `unify-compute-delivery-path`'s to apply; this
change makes them expressible.

## Rejected alternatives

- Reusing the retired `provisioning` reservation state as the phase — the phase is
  orthogonal to reservation state and must not revive a state the lifecycle removed.
- A caller-supplied activation instant or target deadline — the site's active instant
  is the site's fact, and a target deadline is the deadline change's to compute.
- Shipping the columns with the deadline change — unify needs the phase and the
  transition before the deadline exists; adding the columns here changes the schema
  once and leaves the deadline change writing into them.
- Activation as a payment-aware transition — the site knows no payment mechanism;
  billing start follows activation in unify and is end service's intent.

## Implementation cadence and gates

One site-focused round with no external gate: schema and migration, the ledger
transition, the typed authority and clients. Migration order is coordinated with
`capacity-reservation-lifecycle-hardening`, whose hold-expiry index shares the table;
that is coordination, not a behaviour dependency. `unify-compute-delivery-path`
consumes the transition and wires every caller; `renewable-compute-lease-deadlines`
consumes the columns and the phase.

## Open questions

None.

## Permanent documentation destinations

| Accepted decision | Destination |
|---|---|
| D1 phase, transition, retry and refusal | `openspec/specs/site-capacity/spec.md` and `openspec/specs/site-capacity/architecture.md`; capacity reservation in `docs/development/ARCHITECTURE.md` |
| D2 typed activation and inspection | `openspec/specs/compute-provisioning-contract/spec.md` |

## Design promotion record

No promotion yet: this is the design, not implemented architecture. The table above
is the record to complete at closeout, with the campaign-index row update named
beside it.
