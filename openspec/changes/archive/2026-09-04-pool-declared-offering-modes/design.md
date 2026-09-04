# Design: Pool-declared offering modes

## Context

Capacity previously recorded `executor_kind` but could manufacture `vm` from a matched resource's attributes at reservation or supersede time. Release event dispatch also substituted `vm` when a durable reservation had no executor identity. Resource Pools described placement and publication hints but did not authorize which offering modes their provider configuration could deliver.

That combination let resource attributes decide a commercial delivery mode and let old rows continue through a VM executor without evidence. It also conflated provider capability with the independent cross-mode accounting rule that prevents shareable and exclusive use of one Physical Resource.

## Decisions

### One authoritative set per Resource Pool

`policy_tags.deliverable_modes` is a JSON list with set semantics. The resource-pool kit validates only uniqueness and non-empty strings; domains own the vocabulary. Absence and an empty list both authorize no offering mode. Existing projection, precedence, YAML reconciliation, and administration paths remain the only configuration channel.

The declaration belongs to the pool, not each host. A pool selects and configures the provider, playbook, and requirement delegate that can deliver an offering. Host attributes describe capacity and matching facts; allowing them to grant delivery authority would let inventory widen policy accidentally.

### Explicit requested executor identity

Every capacity claim supplies `executor_kind`. The site authority persists that request on the Capacity Reservation before returning a hold. It never derives the identity from the matched resource, `vm_host`, allocation shape, settlement resource, deal event, or dispatcher registration. Later executor parameters are assertions against the recorded identity, not a path for assigning one after reservation.

### The same predicate at three independent boundaries

`pool_delivers_offering_mode(policy_tags, requested_mode)` is the one capability predicate. Reservation checks it before capacity is held. Scheduling re-reads the selected pool before assignment. Provisioning re-reads it before accepting or dispatching provider work. Each check remains necessary because an accepted hold may outlive a declaration change and each boundary can be called independently during recovery.

Capability and physical conflict remain separate. A pool may authorize both VM and bare-metal delivery while the ledger still rejects an exclusive host claim when a shareable slice is live, or the inverse. Passing one check never implies passing the other.

### Deterministic upgrade policy

The schema migration derives every existing pool's exact set from durable provider configuration. An Ansible pool receives `vm` only when it has a non-empty playbook and the `vm_management_v1` requirement delegate; an unproved pool receives an empty set. The system-owned `default` pool is included, and each result is logged at INFO.

For legacy reservations and jobs, only durable evidence may establish executor identity: recorded scheduling requirements, provider/job inputs, deal market, executor references, and unambiguous backing-resource facts. All debit rows are considered together. Exactly one proved identity is backfilled into the reservation, settlement requirements, and linked job. Missing or conflicting evidence moves held reservations to `unmanaged`, active settlement work to `failed`, and active jobs to `failed`, with the stable `legacy_executor_identity_quarantined` reason. Terminal rows keep their terminal state but record the quarantine. A job linked to a quarantined reservation cannot dispatch even if its own parameters look usable.

## Consequences

Operators must declare a mode before a pool delivers it. Narrowing takes effect immediately for new reservations and for later scheduling or provisioning of existing holds. Recovery no longer gains a compatibility executor; quarantined legacy rows require explicit operator reconciliation. The resource-pool, site, fulfillment, and domain package directions remain unchanged because all layers import the shared predicate from the resource-pool kit.