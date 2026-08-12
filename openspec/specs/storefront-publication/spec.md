# Storefront Publication Specification

## Purpose

Define seller storefront ownership, listing publication/reconciliation, and domain-runtime composition.

## Requirements

### Requirement: Seller protocol surface
A storefront MUST expose authenticated listing, negotiation, settlement, identity, health, and operator control surfaces while keeping domain-specific behavior behind injected adapters.

#### Scenario: Buyer settles accepted terms
- **WHEN** the buyer submits a settlement request for an accepted negotiation
- **THEN** the storefront verifies the agreed terms and settlement evidence before scheduling fulfillment

### Requirement: Operator-visible acceptance state
The storefront MUST expose enough operator state to distinguish global negotiation pause from listing state and an empty resource projection from an inventory import failure.

#### Scenario: Storefront is globally paused
- **WHEN** a buyer starts a negotiation while global pause is active
- **THEN** the storefront rejects it with HTTP 503 and a global-pause reason until an authenticated operator resumes the process

#### Scenario: Storefront has no imported resources
- **WHEN** the active storefront database contains no resource rows
- **THEN** system status reports `resource_count` as zero and new negotiations cannot match inventory

### Requirement: Registry publication ownership
A storefront MUST publish, update, close, and reconcile its listings against one or more configured registries using its publisher identity.

#### Scenario: Derived capacity disappears
- **WHEN** authoritative capacity no longer supports a derived listing
- **THEN** reconciliation closes that listing in configured registries without treating stale local state as authority

### Requirement: Commercial mapping identity
A storefront's derived-listing mapping (`derived_compute_listings`, `derived_bare_metal_listings`) is the commercial-mapping table between an authoritative physical or capacity identity and a published listing; it MUST NOT be duplicated as a separate schema. Pricing, settlement terms, and seller policy MUST continue to live on the generic `listings` table, addressed by `listing_id` — the mapping row carries no commercial fields of its own. Each mapping row's derivation key MUST include the owning `site_id`, since a pool or resource identifier is only unique within one site, never globally. A derivation key MUST be collision-resistant by construction against any values its constituent fields (`site_id`, `pool_id`, `resource_id`) may take — these are operator-chosen strings with no character restrictions, so a naive delimiter-joined encoding is not sufficient.

#### Scenario: Two sites name a pool identically
- **WHEN** two different sites each have a pool sharing the same operator-chosen `pool_id`
- **THEN** their derived-listing mapping rows have distinct derivation keys and neither row's mapping is silently overwritten by the other's

#### Scenario: An operator-chosen identifier contains a delimiter character
- **WHEN** a `site_id`, `pool_id`, or `resource_id` value contains a character that would otherwise separate fields in a naively joined key
- **THEN** the resulting derivation key remains distinct from any other combination of values that could produce the same joined string

#### Scenario: Two specific-resource candidates share a pool
- **WHEN** a multi-member pool publishes more than one `specific_resource` candidate, each naming a different physical resource
- **THEN** each candidate's derivation key is resource-keyed and distinct, and recording one candidate's mapping does not overwrite another's

### Requirement: Site-pinned claim routing
A capacity claim for a listing with a known site mapping MUST be routed to exactly that site, with no fallback to a different site on refusal or error — this applies to every listing with a site mapping, whether the underlying capacity is fungible (pool-derived) or pinned to a specific physical resource, never only to resource-pinned listings. A listing with no recorded site mapping MAY be routed by placement policy across configured sites.

#### Scenario: A mapped listing's site would lose to placement policy
- **WHEN** a listing is mapped to one site but placement policy would otherwise prefer a different configured site with more available capacity
- **THEN** the claim is routed only to the listing's mapped site, regardless of what placement policy would have chosen for an unmapped claim

#### Scenario: A mapped site refuses or errors
- **WHEN** a listing's mapped site refuses the claim or the request to that site fails
- **THEN** the claim is not retried against a different configured site

### Requirement: Domain-owned publication and hold hints
A storefront domain MAY interpret a projected pool's `listing_mode`, `max_reservation_hold_seconds`, `region`, `sla`, and `pricing` policy tags. Each domain MUST own its accepted `listing_mode` values and structural default; an absent or unrecognized value MUST fall back to that default with an operator-visible explanation rather than failing projection ingestion or blocking publication. A cooperating storefront MUST treat a valid `max_reservation_hold_seconds` as an advisory upper bound on its own requested reservation-hold TTL — it MUST NOT change what the site ledger itself enforces, and an unresolvable or invalid preference MUST leave the caller's requested TTL unchanged rather than block hold placement.

A `fungible` pool's publishable capacity range is bounded by what a single member can currently satisfy, never by a sum across members, and MUST be sourced from grouped `site_capacity_buckets` data when it is available; a `specific_resource` pool publishes one independently identified, independently reservable listing candidate per currently enabled member, regardless of member count. No listing/hold hint's projected value may be persisted into storefront-local storage — a consumer reads it live from the current projection each time it is needed.

`region` has no storefront-side override — a storefront overriding where hardware physically sits would misrepresent a fact, not adjust a policy. `sla` and `pricing` (per resource family and, within a family, per model) each resolve through a three-tier precedence, highest to lowest: a storefront-specific override on a specific pool; the pool's own declared hint; the storefront's own configured default. `sla`'s middle tier is additionally gated behind a storefront-wide trust setting — a storefront MAY decline to consult a pool's declared SLA at all, independent of whether any specific pool has an override, since publishing a site's self-reported SLA claim is a trust decision distinct from a per-pool pricing override.

#### Scenario: Listing mode is absent or invalid
- **WHEN** a projected pool omits `listing_mode` or supplies a value unsupported by the selected domain
- **THEN** publication uses the domain's structural default and exposes an operator-visible explanation without failing projection ingestion

#### Scenario: A fungible pool's members have unequal availability
- **WHEN** a fungible pool's members currently have different available capacity
- **THEN** the storefront publishes candidate slice sizes no larger than the largest currently available single member, not a sum across members

#### Scenario: A specific-resource pool has more than one member
- **WHEN** a pool resolves to `specific_resource` and has multiple currently enabled members
- **THEN** the storefront derives one listing candidate per member rather than one pooled candidate

#### Scenario: Hold preference is shorter than storefront policy
- **WHEN** a valid positive `max_reservation_hold_seconds` is lower than the storefront's configured acceptance-hold TTL
- **THEN** the storefront requests no more than the projected preference while live site admission remains authoritative

#### Scenario: A storefront declines to trust a pool's declared SLA
- **WHEN** a storefront has not enabled its SLA trust setting
- **THEN** publication resolves SLA from a per-pool storefront override or the storefront's own default, never from the pool's own declared hint, regardless of whether that pool has one

#### Scenario: A per-pool storefront override sets only one pricing field
- **WHEN** a storefront's per-pool override sets `min_price` but not `token`
- **THEN** the unset field resolves independently through the pool hint and configured default, rather than the whole override being ignored or the whole pool falling back to defaults

### Requirement: Domain publication capability
A domain that supports seller publication MUST provide its publication source and listing interpretation through the domain contract while registry fan-out remains schema-opaque core orchestration.

#### Scenario: Domain publication plugin is selected
- **WHEN** an operator selects a registered domain source
- **THEN** the core runner invokes it through the publication-source contract and publishes its opaque payloads

#### Scenario: Domain capacity changes
- **WHEN** a domain publication source observes a change in its authoritative inventory or quota
- **THEN** it produces domain listings through its contract and the shared runner publishes or reconciles their opaque payloads

### Requirement: Domain runtime composition
The shared storefront role MUST consume the selected market-domain contract for listing, message, agreed-terms, materialization, receipt, and result codecs plus the lifecycle hooks declared by that domain. A concrete storefront composition MUST supply its implementations explicitly, and generic storefront services MUST NOT import or branch on concrete domains.

#### Scenario: Current storefront composition selects a domain
- **WHEN** a VM or API-credit storefront is assembled
- **THEN** its composition root supplies a validated domain contract used by every shared storefront service that interprets domain behavior

#### Scenario: Domain validation fails
- **WHEN** a domain codec or hook rejects a payload
- **THEN** the storefront surfaces the domain validation failure without coercing it through a different domain or a generic fallback

### Requirement: Trusted provisioning-site identity
A storefront MUST bind each provisioning connection to an operator-configured `site_id`. It MUST derive routing and ownership from that trusted binding rather than accepting a counterparty-provided site identity.

#### Scenario: Provisioner reports a conflicting site identity
- **WHEN** a configured provisioning connection reports a `site_id` different from the storefront binding
- **THEN** the storefront retains the configured identity and rejects or ignores the conflicting assertion

### Requirement: Storefronts cache independent site projections
Individual-resource publication consumes `site_resource_pools`, which carries the physical inventory facts required to create a listing for a specific resource. Capacity-oriented publication consumes vertically grouped `site_capacity_buckets`. Grouped capacity is advisory publication input only and is never an allocation target; authoritative reservation admission remains host-granular inside the provisioning site authority.

A storefront SHALL load the resource-pool and capacity-bucket projections at startup, poll their independent revision-and-digest identities, and replace each cached generation atomically. Refresh failure SHALL retain the last complete generation and mark it stale rather than representing an empty projection. Topology-sensitive authoritative errors MAY trigger one coalesced drift check but SHALL NOT automatically retry a state-changing request.

A storefront implementation MAY additionally support deriving publishable listing candidates from local, non-projection tables as a compatibility or staged-rollout path. Once that implementation's projection-backed candidate derivation has parity with its local-table path, the projection path SHALL be the default; a local-table path, if one still exists, is an explicit opt-in for rollback rather than the default behavior.

#### Scenario: One projection refresh fails
- **WHEN** a storefront cannot refresh one site projection after previously loading a complete generation
- **THEN** it retains that generation as stale without replacing the other independently versioned projection

#### Scenario: Projection-backed derivation has reached parity
- **WHEN** a storefront's projection-backed listing-candidate derivation has parity with any local-table path it retains
- **THEN** the projection path is that storefront's default, with the local-table path available only as an explicit, non-default rollback option

### Requirement: A paused storefront performs no timer-driven work

A storefront MUST expose its trading pause and its lifecycle pause as independent
controls. Refusing new negotiations and halting timer-driven work are different
requests: a storefront that stops accepting deals is still expected to finish those
it has accepted, and a storefront whose loops are idle is still expected to trade.
Neither control MAY imply the other.

The lifecycle pause MUST hold every timer-driven loop the storefront runs idle, so
that a storefront with its loops paused changes no state on its own. A loop MUST observe the pause at a cycle boundary: a cycle either runs
to completion or does not begin, and a paused loop MUST NOT be interrupted part-way
through one. Loops MUST NOT be torn down to achieve this, so loop-local position and
progress survive a pause and resuming continues from where the loop stopped rather
than re-converging from an initial state.

A storefront MUST report each loop's current state, and that report MUST distinguish
a loop held idle by the pause, a loop whose cycle began before the pause was requested
and has not yet returned to its gate, and a loop that has ended on its own. Reporting
only whether the pause flag is set does not satisfy this: the flag records what was
requested, and the per-loop state records what is true, which only the loop itself can
establish by reaching its gate.

Pausing MUST wait for loops to reach their gates before reporting, and that wait MUST
be bounded. A loop's gate is at the end of its interval, and intervals may be tens of
seconds, so an unbounded wait would make an operator control unresponsive. A loop that
has not reached its gate inside the window MUST be reported as still stopping rather
than as stopped, and that MUST NOT be an error: a cycle in flight is a normal state to
report, and failing the request would replace an accurate answer with none.

#### Scenario: Pausing holds every loop idle

- **WHEN** an operator pauses a storefront and every loop reaches its gate
- **THEN** no timer loop performs further work until it is resumed, and the response
  reports each loop as paused

#### Scenario: A cycle already running when the pause is requested

- **WHEN** a loop is part-way through a cycle at the moment a pause is requested
- **THEN** that cycle runs to completion, the loop is reported as still stopping
  rather than stopped, and the pause request itself succeeds

#### Scenario: A paused loop retains its position

- **WHEN** a storefront is paused while a loop holds a position in a feed or sweep
- **THEN** that position is unchanged on resume and the loop continues from it,
  rather than restarting from an initial position

#### Scenario: A loop that ends on its own is distinguishable

- **WHEN** a timer loop exits unexpectedly and the storefront is then paused
- **THEN** that loop is reported as exited rather than as paused, so an operator can
  tell a halted loop from a failed one

### Requirement: Lifecycle cycles are operator-invocable while paused

A storefront MUST expose, for each timer loop whose work a caller may need to drive
deliberately, a control that runs one cycle on demand. Such a control MUST invoke the
same operation the loop itself invokes and MUST NOT implement an alternate
transition. Where a loop's work has no separately callable unit, the control MUST
invoke the nearest production handler covering that work and the difference MUST be
recorded at the control.

These controls MUST remain available while the storefront is paused, since operating
on a paused storefront is their purpose.

#### Scenario: A cycle runs while paused

- **WHEN** a caller invokes a lifecycle cycle control on a paused storefront
- **THEN** the underlying operation runs once and its result is returned, and the
  storefront remains paused

#### Scenario: A control does not diverge from its loop

- **WHEN** a lifecycle cycle control runs
- **THEN** the state transitions it produces are those the timer-driven loop would
  produce, so behaviour observed through the control is behaviour production
  exhibits

### Requirement: Lifecycle control coverage is per storefront

Operator lifecycle controls belong to the storefront implementing them and are not
implied for every storefront in the system. A storefront that runs timer loops
without exposing these controls cannot be paused or advanced, and callers MUST NOT
assume otherwise from the presence of the controls elsewhere.

Currently the VM storefront implements pause-and-advance. The API-credits storefront
runs equivalent timer loops — capacity-event polling, projection refresh, claims
sweeping, and fulfillment resumption — and exposes no control over them; its
background work continues regardless of its pause state. This is a current
limitation rather than a deliberate difference in behaviour between the two.

#### Scenario: A storefront without lifecycle controls

- **WHEN** a caller pauses a storefront that does not implement lifecycle controls
- **THEN** new negotiations are refused but timer-driven work continues, and no cycle
  control is available to drive that work deliberately

### Requirement: A loop's reported state is established by the loop

A storefront MUST derive each loop's reported state from evidence the loop itself
produces, not from the existence of the task running it. A loop that has been scheduled
but has not yet reached its gate MUST be reported as starting, distinctly from a loop
that is cycling: the first cannot yet observe a pause, and reporting the two alike lets a
caller pause a storefront whose loops have not begun and receive an answer that cannot be
true.

Reading the pause flag and acknowledging the gate MUST NOT be separately available to a
loop. A loop that consults the pause without acknowledging is indistinguishable, from
outside the process, from one that never reaches a gate at all, and the pause control
cannot then report what is true of it.

#### Scenario: A scheduled loop that has not yet cycled

- **WHEN** a storefront reports loop state before a loop has reached its gate for the
  first time
- **THEN** that loop is reported as starting rather than as running

#### Scenario: Every loop acknowledges

- **WHEN** an operator pauses a storefront whose loops are all cycling
- **THEN** every loop reaches its gate within the bounded wait and is reported paused,
  with none left reported as still stopping

#### Scenario: One worker cannot acknowledge for another

- **WHEN** a storefront runs several workers of the same kind, one per configured
  authority, and one of them is still mid-cycle while another sits at its gate
- **THEN** the pause reports the one still working as not yet stopped, because each
  worker acknowledges only for itself

### Requirement: Readiness, liveness, and diagnosis are separate surfaces

A storefront MUST distinguish whether its process is worth keeping from whether it can be
relied on. Liveness MUST fail only for a condition no further running can resolve. A loop
that has ended on its own is such a condition while no supervisor restarts one, because
replacing the process is then the only recovery available.

Readiness MUST fail while any timer loop has not yet begun cycling, since a storefront
whose loops have not started will not perform the background work a caller relies on, and
MUST report that condition distinctly from a fault.

A storefront held at its lifecycle pause MUST remain ready. The pause is operator-requested,
the storefront continues to serve and to trade, and treating it as unreadiness would make
an operator control indistinguishable from a failure.

Diagnostic status MUST remain available regardless of either, and MUST report per-loop
state, since a caller consults it precisely when one of the other two is failing.

#### Scenario: A storefront whose loops have not started

- **WHEN** a caller probes readiness before every loop has begun cycling
- **THEN** readiness fails and reports the condition as starting rather than as a fault,
  while liveness continues to succeed

#### Scenario: A storefront with a dead loop

- **WHEN** a timer loop has ended on its own and no supervisor will restart it
- **THEN** both liveness and readiness fail, so the process is replaced rather than left
  serving with background work silently stopped

#### Scenario: A paused storefront is ready

- **WHEN** a caller probes readiness while the lifecycle pause is held
- **THEN** readiness succeeds, and diagnostic status reports each loop as paused

### Requirement: A bounded operator query reports its own truncation

An operator-facing query that caps the rows it returns MUST allow a caller to tell a
complete result from a capped one. Returning a row count alone does not satisfy this: a
caller receiving exactly the cap cannot distinguish the two, and a caller reasoning about
a complete history will silently reason about part of one.

#### Scenario: A query that reaches its cap

- **WHEN** a caller requests more rows than the surface will return and the available rows
  reach that cap
- **THEN** the response reports that it was truncated, in addition to the rows returned

## Evidence

- Projection-backed candidate derivation defaults on once at parity with a retained local-table path: `domains/vms/storefront/tests/unit/test_config_loader.py::test_settings_toml_provides_baseline_defaults` and `test_use_site_projection_for_listings_can_still_be_disabled_explicitly`.
- Generic publication source, runner, and plugin discovery: `core/storefront/tests/unit/test_publication_sources.py`, `test_publication_runner.py`, and `test_publication_plugins.py`.
- Registry fan-out and publication persistence: `core/storefront/tests/unit/test_registry_publication.py` and `domains/vms/storefront/tests/unit/test_publications_wiring.py`.
- Domain-runtime bundle and VM wiring: `core/storefront/tests/unit/test_domain_runtime.py` and `domains/vms/storefront/tests/unit/test_domain_runtime_wiring.py`.
- Global pause state: `domains/vms/storefront/tests/unit/test_order_pause_state.py` and `tests/integration/test_admin_api.py`.
- Loop pause, per-loop gate acknowledgement including one registered loop per configured capacity site, and the `starting`/`running`/`pausing`/`paused` state machine: `domains/vms/storefront/tests/unit/test_lifecycle_registry.py` and `test_loop_gate_wiring.py`. The second is the one that proves each production loop acknowledges under its registered name; the first drives a synthetic loop and proves only the mechanism.
- Readiness, liveness, and diagnosis as separate surfaces, including that a paused storefront stays ready and an ended loop fails both probes: `domains/vms/storefront/tests/integration/test_readiness_and_liveness.py`. Probe wiring: `helm/charts/storefront/templates/deployment.yaml` and the VM compose healthchecks.
- Operator lifecycle advance producing the transitions its loop produces, in both directions: `domains/vms/storefront/tests/integration/test_admin_api.py::TestCapacityAdvanceMovesListings`.
- Bounded stage-event queries reporting their own truncation: `core/storefront/tests/unit/test_stage_event_pagination.py`.
- Resource-count diagnosis: `domains/vms/storefront/src/market_storefront/services/system_service.py` and `e2e-tests/tests/smoke/test_storefront_smoke.py`.
- Site-scoped derivation keys and collision resistance (VM and bare-metal): `domains/vms/storefront/tests/unit/test_reconciler.py`, `domains/bare_metal/tests/test_publication.py`, and `domains/bare_metal/tests/test_storefront_publication.py`.
- Site-pinned claim routing, including the collision case placement policy would otherwise choose wrongly: `core/storefront/tests/unit/test_aggregation.py`. Mapped-listing routing reached through the real admin, negotiation-hold, and settlement/fulfillment entry points: `domains/vms/storefront/tests/integration/test_admin_api.py`, `domains/vms/storefront/tests/unit/test_two_phase_reserve.py`, and `domains/vms/storefront/tests/unit/test_settlement_jobs.py`.
- Domain-owned listing-mode resolution, bucket-sourced fungible candidates, multi-member specific-resource derivation, the resource-keyed derivation-key collision fix, and the live (never persisted) hold-preference cap: `domains/vms/storefront/tests/unit/test_reconciler.py`, `domains/vms/storefront/tests/unit/test_listing_mode.py`, `domains/vms/storefront/tests/unit/test_sync_negotiation_hold_cap.py`, and `domains/vms/storefront/tests/unit/test_remote_capacity_client.py`. VM is currently the only domain with a `listing_mode` resolver wired to a real publication consumer; another domain adds its own resolver and evidence line here once it gains a concrete consumer.
- Region/SLA hint resolution (including SLA's storefront-wide trust gate) and the three-tier pricing precedence (including independent per-field resolution across tiers): `domains/vms/storefront/tests/unit/test_pool_descriptors.py`, `domains/vms/storefront/tests/unit/test_pricing_resolution.py`, `domains/vms/storefront/tests/unit/test_reconciler.py`, and `domains/vms/storefront/tests/unit/test_cli_publish_helpers.py::TestPoolHintResolutionSettings`.

Replacing the domain-owned storefront executables remains proposed work rather than baseline behavior. Bare metal currently supplies domain codecs and publication semantics but not a complete runnable storefront composition.
