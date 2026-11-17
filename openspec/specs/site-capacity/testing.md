---
tags: [repository, testing]
---

# Testing site capacity

Where each layer's tests prove the usable-host rule, which governs this capability's
admission and offered read, each at the lowest level that can
([`test-levels.md`](../../../docs/guidance/engineering/test-levels.md)).

## Host Requirement Enforcement

The usable-host rule — where the pool is backed and its provider needs a host, a
declaration is offered only when it names a host the composition reports taking
new delivery — is rechecked at each layer, and each layer proves its own check. Below the
provisioning service a "disabled" or "unregistered" host is an id a fake
`DeliverableHosts` report leaves out, one case to the layer; that the host
authority leaves both out is proved where it lives.

- `kit/resource-pools` unit tests own the predicates:
  - `pool_needs_host`: no requirement supplied, a declared need, a provider the
    requirement does not name, a value that is not a `bool`;
  - `declaration_has_usable_host`: a host in the report, a host absent from it,
    no host named, an empty report, an unbacked pool, a provider needing no
    host, no requirement, and a requirement with no report.
- `kit/fulfillment` unit tests own the provider declaration, including a
  registry that refuses a provider declaring none.
- `kit/site` library integration tests own admission and the offered read:
  - probe, reserve, and resize refusing a declaration with no usable host, with
    fall-through to one that has one, and matching it again once its host
    returns to the report;
  - the rebind recheck refusing such a destination with the debit and the
    capacity version unchanged;
  - no refusal without a requirement, and named hosts usable with no report;
  - one report read per decision, in the decision's own session, and, on a
    file-backed database, a write from another connection held off for the
    whole decision;
  - the offered read and the snapshot reporting a declaration with no usable
    host not enabled, an unbacked pool's or a pool delivering no mode keeping
    its own `enabled`, the operator's listing keeping the stored `enabled`, and
    the capacity version unchanged.
- `kit/site` unit tests own the projections' input: both are built from the
  offered read, and the capacity-bucket projection's revision and digest
  advance when only offered state changes.
- `kit/fulfillment` library integration tests own placement:
  - exclusion before policy, rebind, cursor, or assignment, on both the
    automatic and the constrained path;
  - a pool-scoped hold whose own backing lost its host re-placed elsewhere, or
    refused with no other candidate;
  - an existing assignment on a disabled host returned unchanged, and refusal
    of an existing assignment that records no host;
  - one report read per scheduling transaction, in its session, and none with
    no requirement.
- Provisioning library integration tests own the host authority's report: a
  disabled host leaves it and returns on enable, an unregistered id is never in
  it, and it reads the caller's own uncommitted disable.
- Provisioning unit tests own composition: refusal of a requirement that
  disagrees with the registered providers; the ledger and the scheduling unit
  of work receiving the host authority as the same report; and a declaration
  handed in not enabled projecting not enabled, with its bare-metal view
  unavailable.
- Provisioning integration tests prove the deployed surface through the typed
  clients:
  - admission and scheduling refusals with the executor boundary asserted
    never reached;
  - a host disabled through the family client making probe and reserve answer
    no capacity and a constrained schedule answer `no_eligible_resource`,
    projecting the declaration not enabled in the resource-pool projection, its
    bare-metal view unavailable, leaving it out of the capacity buckets and the
    snapshot, keeping the operator's listing, and leaving the capacity version
    unchanged, each restored on enable; an unregistered host likewise until it
    is registered; an unbacked pool's declaration unaffected; and an existing
    assignment on a disabled host returned by a retry, its create waiting at
    dispatch until the host is enabled;
  - dispatch to an unregistered host failing before any playbook, even after a
    host definitions document naming the host was submitted and refused.
- End to end, `e2e_bare_metal_publication`'s host stages prove the storefront
  half: disabling the advertised resource's host closes its listing as a
  withdrawn source after one site-projection and one publication cycle, and
  enabling it reopens the same listing id. Every lane registers each host a
  backed declaration names before declaring it, through the shared
  `register_e2e_host` helper.
