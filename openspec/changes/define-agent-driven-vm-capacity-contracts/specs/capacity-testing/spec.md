## Purpose

Define portable, privacy-safe contracts for agent-driven VM capacity
qualification and measurement, including scenario authority, substantive role
evidence, frozen actions, independent oracles, and immutable findings.

## ADDED Requirements

### Requirement: Pinned portable scenario authority
Every capacity scenario used by a current run MUST resolve through its known
repository-relative capacity-scenario path at one exact SCM commit. The
validator MUST reject absolute or escaping paths, symlinks, non-regular files,
untracked paths, worktree bytes that differ from that commit, schema-invalid
content, and a declared canonical digest that does not match the scenario.
Canonical scenario SHA-256 MUST be calculated from a deterministic,
formatting-independent JSON representation. The canonical byte algorithm MUST
encode the parsed JSON value as UTF-8 with object keys recursively sorted,
compact separators, `ensure_ascii=false`, non-finite numbers rejected, and
exactly one trailing newline before SHA-256 is calculated.

#### Scenario: Exact tracked scenario is accepted
- **WHEN** a caller selects a tracked regular scenario under the public capacity-scenario root and its worktree bytes, schema version, and canonical digest match the pinned SCM commit
- **THEN** validation returns that exact scenario identity and canonical digest

#### Scenario: Hidden or path-level drift is rejected
- **WHEN** a selected scenario is absolute, escapes the scenario root, is a symlink, is untracked, or has bytes that differ from the pinned SCM commit even when ordinary status output hides the difference
- **THEN** validation fails before the scenario can authorize a request

#### Scenario: Formatting does not change scenario identity
- **WHEN** two schema-equivalent scenario documents differ only in insignificant JSON formatting or key order
- **THEN** they produce the same canonical scenario SHA-256

#### Scenario: Non-canonical numeric value is rejected
- **WHEN** a scenario contains NaN, positive infinity, or negative infinity
- **THEN** canonicalization fails rather than producing an implementation-dependent digest

### Requirement: VM-only real-provisioning scope
Current capacity scenarios MUST use schema version 2 and MUST describe only VM
deals provisioned through real KVM and Ansible with whole-device GPU
passthrough. Every request-bearing scenario MUST declare one GPU per successful
VM and a retry budget of zero. A frozen scenario MUST contain no unresolved
placeholder. Historical schema-v1 evidence MAY remain verifiable only through
the historical SCM commit that defined it; a current schema-v2 validator MUST
NOT treat a schema-v1 scenario as current campaign authority.

#### Scenario: Current VM scenario is valid
- **WHEN** a schema-v2 scenario declares VM, real KVM/Ansible provisioning, whole-device passthrough, one GPU per successful VM, zero retries, and no placeholder
- **THEN** the scenario is eligible for further topology and profile validation

#### Scenario: Non-VM or simulated provisioning is rejected
- **WHEN** a current scenario declares a non-VM deal, mock or simulated provisioning, non-passthrough GPU assignment, a positive retry budget, or an unresolved placeholder
- **THEN** validation fails before any role action is prepared

#### Scenario: Historical evidence remains ref-scoped
- **WHEN** a schema-v1 artifact is verified against the exact historical SCM commit that defined schema v1
- **THEN** it may be read as historical evidence but cannot authorize a schema-v2 qualification or measured run

### Requirement: Scenario shapes are mode-neutral
A scenario document MUST describe only the portable VM topology, actor/load
counts, frozen requests, and expected terminal outcomes. It MUST NOT declare
whether it is mock, reference, qualification, or measured evidence and MUST NOT
self-authorize admission. A versioned profile-stage record MUST bind one pinned
scenario identity and digest to one ordered stage identity, admission context,
exact `execution_boundary`, and exact `actor_trigger`; the result record MUST
repeat that binding. `execution_boundary` MUST be exactly one of `readiness`,
`mock`, `real-reference`, `real-qualification`, or `real-measured`.
`actor_trigger` MUST be exactly one of `none`, `controller-driven`, or
`agent-triggered`. The mock, deterministic-reference, qualification, and
measured paths MAY reuse the same B1/S1/G1 scenario bytes without conflating
their evidence.

A `mock` stage bound to a real-KVM/Ansible scenario means that agents rehearse
the frozen actions against the mock boundary in preparation for that target
shape. Its result MUST NOT claim that the scenario's declared real
provisioning, GPU, fulfillment, or cleanup oracle ran.

#### Scenario: One shape is reused without relabeling
- **WHEN** mock preparation, the deterministic reference, and Q0 each use the same pinned B1/S1/G1 scenario
- **THEN** their profile-stage and result records carry `mock`/`agent-triggered`, `real-reference`/`controller-driven`, and `real-measured`/`agent-triggered`, respectively, while the scenario identity and digest remain unchanged

#### Scenario: Scenario attempts to grant admission
- **WHEN** a scenario document contains an evidence class, qualification status, measured status, or private admission decision
- **THEN** scenario validation fails because that authority belongs to the profile-stage and private gate

#### Scenario: Mock result claims the real oracle
- **WHEN** a `mock` result claims a durable real fulfillment, KVM/Ansible provisioning, guest GPU exercise, or system-capacity frontier
- **THEN** result validation rejects the claim

### Requirement: Exact one-GPU qualification profile
Before the agent-driven qualification rows, the profile MUST run
`b1-s1-g1-reference`, one deterministic real B1/S1/H1/O1 lifecycle, as a
product/environment reference and MUST exclude it from agent-capacity evidence.
The deterministic controller that releases and drives this reference is
orchestration, not a counted role; O1 remains a distinct independent-observer
actor whose receipt and observation sources cannot be authored, released, or
accepted by that controller.

The private no-request observer stage MUST use the exact identity
`observer-probe`, precede `b1-s1-g1-reference`, and bind public scenario identity
and digest to null because it emits no market request. Its profile-stage record
MUST bind `execution_boundary=readiness` and `actor_trigger=none`.
`b1-s1-g1-reference` MUST bind `execution_boundary=real-reference` and
`actor_trigger=controller-driven`. The public one-GPU
qualification profile MUST then contain, in order, the stage identities
`b1-s1-g1-qualification`, `b2-s1-g1-qualification`,
`serialized-reuse-a-qualification`, `serialized-reuse-b-qualification`, and
`b2-s2-g1-qualification`. Those stages MUST bind the mode-neutral scenario
shapes `b1-s1-g1`, `b2-s1-g1`, `serialized-reuse-a`,
`serialized-reuse-b`, and `b2-s2-g1`, respectively. Every stage MUST carry the
`real-qualification` execution boundary, `agent-triggered` actor authority, and
retry-zero authority. Public validation MUST distinguish listing count from
independently assignable GPU count and MUST reject every G2 scenario until a
separate reviewed contract proves two independently assignable whole GPUs.

The exact role/load matrix MUST be:

| Profile stage | Scenario | O | B | S | H | L | R | G | Expected terminal result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `b1-s1-g1-qualification` | `b1-s1-g1` | 1 | 1 | 1 | 1 | 1 | 1 | 1 | one success |
| `b2-s1-g1-qualification` | `b2-s1-g1` | 1 | 2 | 1 | 1 | 1 | 2 | 1 | one success and one independently proven capacity refusal |
| `serialized-reuse-a-qualification` | `serialized-reuse-a` | 1 | 1 | 1 | 1 | 1 | 1 | 1 | first successful lifecycle |
| `serialized-reuse-b-qualification` | `serialized-reuse-b` | 1 | 1 | 1 | 1 | 1 | 1 | 1 | second success after complete teardown and baseline equivalence |
| `b2-s2-g1-qualification` | `b2-s2-g1` | 1 | 2 | 2 | 1 | 2 | 2 | 1 | one total success and one independently proven capacity refusal |

`O`, `B`, `S`, and `H` are independent-observer, buyer, seller, and
host-operator roles. The deterministic controller is non-counted orchestration.
`L`, `R`, and `G` are selected listings, requests, and independently assignable
whole GPUs.

#### Scenario: Deterministic reference precedes agent evidence
- **WHEN** the applicable one-GPU qualification begins
- **THEN** `observer-probe` completes without a request and `b1-s1-g1-reference` then completes one real B1/S1/H1/O1 lifecycle as `real-reference`/`controller-driven`, with its non-counted controller separated from O1, rather than as agent-capacity evidence

#### Scenario: Complete one-GPU profile is accepted
- **WHEN** the five required profile stages bind the five exact scenario shapes once with the exact O/B/S/H/L/R/G counts and expected outcomes in the required order, buyer rows precede seller scaling, every stage is `real-qualification`/`agent-triggered` and retry-zero, and verified physical capacity is one GPU
- **THEN** the public profile is eligible for private qualification assembly

#### Scenario: Observer remains a no-request probe
- **WHEN** the private `observer-probe` stage declares zero requests
- **THEN** it selects no public scenario, binds scenario identity and digest to null, and cannot be substituted by a controller readiness receipt

#### Scenario: Listing count does not expand physical capacity
- **WHEN** a scenario declares multiple truthful VM listings but the verified topology has one independently assignable GPU
- **THEN** the maximum expected simultaneous successful whole-GPU VM count remains one

#### Scenario: Unqualified G2 is rejected
- **WHEN** any current profile or scenario expects two simultaneous whole-GPU VM successes without separate two-GPU authority
- **THEN** validation fails even if two or more listings are present

### Requirement: Measured one-GPU progression is separately identified
The public one-GPU measured registry MUST bind mode-neutral shapes to the
following required `real-measured`/`agent-triggered`, retry-zero profile stages
in this order:

| Profile stage | Scenario | O | B | S | H | L | R | G | Unordered expected cardinality |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `q0-b1-s1-g1-measured` | `b1-s1-g1` | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 success |
| `b2-s1-g1-measured` | `b2-s1-g1` | 1 | 2 | 1 | 1 | 1 | 2 | 1 | 1 success + 1 capacity refusal |
| `b4-s1-g1-measured` | `b4-s1-g1` | 1 | 4 | 1 | 1 | 1 | 4 | 1 | 1 success + 3 capacity refusals |
| `b8-s1-g1-measured` | `b8-s1-g1` | 1 | 8 | 1 | 1 | 1 | 8 | 1 | 1 success + 7 capacity refusals |
| `serialized-reuse-a-measured` | `serialized-reuse-a` | 1 | 1 | 1 | 1 | 1 | 1 | 1 | first success |
| `serialized-reuse-b-measured` | `serialized-reuse-b` | 1 | 1 | 1 | 1 | 1 | 1 | 1 | second success after baseline equivalence |
| `b2-s2-g1-measured` | `b2-s2-g1` | 1 | 2 | 2 | 1 | 2 | 2 | 1 | 1 success + 1 capacity refusal |
| `b4-s2-g1-measured` | `b4-s2-g1` | 1 | 4 | 2 | 1 | 2 | 4 | 1 | 1 success + 3 capacity refusals |
| `b4-s4-g1-measured` | `b4-s4-g1` | 1 | 4 | 4 | 1 | 4 | 4 | 1 | 1 success + 3 capacity refusals |

S4/B4 MUST be inadmissible unless four distinct seller identities and service
instances are available. B4 seller stages MUST be skipped unless the external
buyer-frontier receipt proves B4 is inside the applicable buyer correctness
and load-generator frontiers. Public measured scenario shapes MUST NOT by
themselves grant pre-Q0 admission.

Before Q0, the pinned public ref MUST contain the complete bounded refinement
envelope: every integer buyer shape `b1-s1-g1` through `b8-s1-g1`, both
serialized-reuse shapes, `b2-s2-g1`, and `b4-s2-g1`, `b4-s3-g1`, and
`b4-s4-g1`. The registry MUST name optional profile stages
`b3-s1-g1-measured`, `b5-s1-g1-measured`,
`b6-s1-g1-measured`, `b7-s1-g1-measured`, and
`b4-s3-g1-measured` with the same exact O/H/G counts, B/S/L/R counts encoded
by their names, and unordered `1 success + (B-1) capacity refusals`.

The measured execution order MUST be:

1. `q0-b1-s1-g1-measured`, then `b2-s1-g1-measured`,
   `b4-s1-g1-measured`, and `b8-s1-g1-measured`;
2. immediately after those four buyer observations and before reuse, only the
   B3/B5/B6/B7 stages selected by deterministic integer bisection, in the
   deterministic selection order, until the first passing/first failing bracket
   is adjacent, retaining the results immediately below, at, and above the
   candidate boundary;
3. `serialized-reuse-a-measured` and then
   `serialized-reuse-b-measured`;
4. after an external buyer-frontier receipt, `b2-s2-g1-measured`, followed—only
   when B4 is inside both the buyer correctness and load-generator
   frontiers—by `b4-s2-g1-measured`; if B4/S2 passes and four-seller admission
   exists, run `b4-s4-g1-measured`, then run `b4-s3-g1-measured` only when S4
   fails and S3 is needed to make the passing/failing seller bracket adjacent.
   If S4 is not admissible but three-seller admission exists, S3 MAY run after
   S2 as the final bounded probe, and the result MUST remain a lower bound when
   it passes. If S2 fails, S1/S2 is already adjacent and neither S3 nor S4 runs.

Neither the registry nor scenario bytes may change after Q0 begins. If B8
passes, or an earlier generator limit prevents a product failure, B8 or the last
clean shape is only a lower bound.

Expected concurrent outcomes are unordered cardinality constraints over the
declared request IDs. No scenario may predesignate which buyer wins. Every
observed outcome MUST still correlate to exactly one request ID.

#### Scenario: Initial buyer progression is valid
- **WHEN** a measured G1 profile declares the exact B1, B2, B4, and B8 stages with one request per buyer, one unordered expected success, independently proven capacity refusal for the other requests, and retry zero
- **THEN** its portable counts are valid while private admission and resource authority remain independently required

#### Scenario: Seller progression follows buyer completion
- **WHEN** a measured seller row declares S2/B2 or S2/B4 after the buyer frontier receipt and binds distinct seller/listing choices to one globally fenced G1 authority
- **THEN** the row may be assembled by private infrastructure

#### Scenario: Four-seller row is conditional
- **WHEN** S4/B4 is selected without four distinct seller identities and service instances
- **THEN** public topology validation rejects the row

#### Scenario: Measured scenario cannot self-authorize Q0
- **WHEN** a valid measured scenario is presented without the external qualification and pre-Q0 authority required by the private runner
- **THEN** the public validator confirms only scenario semantics and makes no admission claim

#### Scenario: Boundary refinement uses frozen shapes
- **WHEN** the initial B1, B2, B4, and B8 search brackets a boundary
- **THEN** deterministic integer bisection selects only pre-Q0 pinned shapes and preserves the observations immediately below, at, and above that boundary

### Requirement: Seller topology safety
Seller count MUST represent distinct seller identities and distinct service
instances, not multiple listings from one seller. A scenario's seller
distribution MUST contain exactly one positive listing count per seller and
MUST sum to the total listing count. In a one-GPU multi-seller row, every
seller MUST bind one shared, globally fenced physical-capacity authority;
disjoint seller views that can independently allocate the same GPU MUST fail
validation. Every request MUST select one declared seller and one declared
listing.

#### Scenario: Safe two-seller one-GPU row is accepted
- **WHEN** two distinct sellers each expose one selected VM listing, both bind the same globally fenced one-GPU authority, and each request targets an exact declared seller/listing pair
- **THEN** the row may expect one total success and one independently proven capacity-refusal outcome

#### Scenario: Duplicate or partitioned seller authority is rejected
- **WHEN** seller identities or service identities repeat, seller distribution does not match listing count, a request targets an unselected listing, or two one-GPU sellers use independent allocation views
- **THEN** validation fails before publication or request release

### Requirement: Logical slots bind privately to live identities
Public scenarios MUST use only logical actor, seller, listing, and request slots.
Private infrastructure MUST create an owner-only one-to-one binding from every
declared logical seller/listing slot to the distinct runtime identities
published by the seller agents. The portable profile/action/result chain MUST
bind the sanitized logical projection and typed `runtime_binding`, but MUST
NOT contain live listing, wallet, account, host, project, endpoint, or GPU
identifiers. Immediately before a buyer action, the private wrapper MUST
resolve its logical selection through the unchanged binding and fail closed on
a missing, duplicate, stale, or changed live identity.

#### Scenario: Runtime listings bind one-to-one
- **WHEN** every seller publishes its declared listing and private orchestration maps each logical seller/listing slot to one distinct live pair
- **THEN** the sanitized logical projection and typed `runtime_binding` may authorize frozen buyer selections without exposing the live IDs

#### Scenario: Runtime binding drifts before release
- **WHEN** a listing disappears, a live ID maps to two logical slots, or the typed `runtime_binding` changes after action freeze
- **THEN** the buyer wrapper fails before purchase and no replacement listing is selected

### Requirement: Substantive portable role receipts
The public contract MUST define versioned buyer, seller, host-operator, and
independent-observer receipt variants. O1 MUST always mean the
independent-observer actor, never the deterministic controller. The controller
MAY coordinate barriers and deterministic reference emission, but MUST NOT
author observer evidence, control the observer's source credentials, or accept
its own observations as oracle authority. Every substantive receipt MUST bind
the exact SCM commit, the role's pinned quickstart or instruction path and
content digest, exact scenario/profile-stage identity and digest, a non-secret
isolated identity fingerprint, the canonical digest of its closed
role-specific plan, ordered lifecycle timestamps, and proof that the actor
remained alive through its declared release or observation barrier. The
complete role plan MUST name the action IDs it will own and the canonical
digest of each action's exact prepared intent. That intent MUST cover the
logical selection, portable VM/KVM/Ansible terms, service or listing binding,
private concrete-payload binding, pinned wrapper, expected oracle, and
actor-invocation capability while excluding release/policy fields. A
pre-release concurrency policy MUST freeze every complete role-plan digest and
prepared-action digest. Each frozen action MUST then reproduce the prepared
intent and bind the complete role-plan digest plus the release/policy; each
action result MUST bind the frozen-action digest, and the terminal receipt MUST
bind the ordered result digests. This directed artifact graph MUST NOT contain
a digest cycle.
Every real-stage role receipt, including host-operator and observer receipts
that own no market action, MUST bind the exact common `release_id` and
concurrency-policy ID/digest. A standalone observer probe or capture-only mock
MUST instead bind its exact non-campaign release with null policy authority.
This run authority prevents an otherwise valid cleanup or observation receipt
from being replayed into another wave.
Portable receipts MUST
exclude credentials, wallet addresses and secrets, executor-local paths,
project and host identities, private endpoints, listing identifiers, and GPU
identifiers. Logical public listing slots remain allowed; live listing IDs do
not. Readiness-only processes, duplicate role identities, early exits,
or controller-generated role receipts MUST NOT satisfy substantive-role
requirements.

A buyer receipt MUST prove the pinned quickstart's install/build path, isolated
wallet and SSH preparation, endpoint and balance checks, listing discovery,
and exact request preparation for every request. Only after an independently
successful real lifecycle MUST it also prove buyer-owned guest SSH/resume plus
the declared GPU and CUDA exercise; an expected capacity-refused buyer MUST
omit those success-only steps rather than claim them. A seller receipt MUST
prove the pinned quickstart's install/build/configuration path, isolated wallet
and publication preparation, distinct service start, exact truthful listing
publication, and liveness through observation. Private values remain outside
the receipt; the public receipt binds their non-secret action/configuration
digests and typed step outcomes.

A host-operator receipt MUST bind the pinned public host-operator instruction,
typed `topology_authority_binding`, admitted G1 fence, typed
`reversible_baseline_binding`, KVM/Ansible readiness, host-side observation
plan, teardown plan, typed `baseline_equivalence_binding`, and liveness from
admission through cleanup. It
MUST NOT expose the private host, project, interface, PCI, IOMMU, GPU, or
credential identity. An observer receipt MUST bind its pinned observation
instruction, independent-source plan, release/terminal observations, and
typed `native_evidence_bindings` without copying private evidence.

The successful buyer MUST bind the pinned public workload paths
`tools/issue-discovery/workloads/cuda/run-vector-add.sh` and
`tools/issue-discovery/workloads/cuda/vector_add.cu` and their Git blob
digests. Passing requires buyer-owned resume and SSH, exactly one guest-visible
GPU, successful compilation with the pinned wrapper, device execution of the
fixed vector-add workload, the exact public success marker and checksum, and
correlation of that guest session to the request's `fulfillment_id`. Device
visibility or `nvidia-smi` alone MUST NOT satisfy the GPU exercise. Public
receipts retain only typed outcomes and content/result digests.

For a concurrent stage, the aggregate role evidence MUST contain exactly the
declared number of distinct role identities, MUST prove every declared actor
process overlapped the release window, MUST prove request/publication
invocations fell within the declared emission-skew bound, and MUST report no
local actor queue or controller throttling. The skew bound MUST be frozen by a
pre-release concurrency-policy digest. Cross-process overlap and skew MUST use
independently captured monotonic offsets relative to one common release plus a
typed native clock-evidence binding; a post-hoc wall-clock bound or
integer-truncated duration is invalid. A serially executed actor set MUST NOT
satisfy a concurrent stage. Every action's invocation and terminal offsets
MUST fall inside its owning actor's independently observed lifetime.

#### Scenario: Substantive buyer receipt is accepted
- **WHEN** a buyer receipt proves pinned-instruction inspection, isolated preparation, listing discovery, exact frozen-request preparation, and liveness through release at the exact SCM commit
- **THEN** it may contribute to agent-driven evidence

#### Scenario: Substantive seller receipt is accepted
- **WHEN** a seller receipt proves pinned-instruction inspection, isolated build and configuration, exact mock or live publication preparation appropriate to the run mode, distinct service identity, and liveness through its observation boundary
- **THEN** it may contribute to the profile stage's exact execution-boundary and actor-trigger combination

#### Scenario: Substantive host operator is accepted
- **WHEN** one host-operator agent proves the pinned instruction, typed private G1/topology and baseline bindings, KVM/Ansible readiness, observation and teardown plans, liveness through cleanup, and final baseline equivalence
- **THEN** it satisfies H1 without exposing private host or GPU identity

#### Scenario: Readiness probe cannot impersonate a role
- **WHEN** a process merely approves a hash, never performs the documented role preparation, exits before the barrier, duplicates another actor identity, or has its receipt synthesized by the controller
- **THEN** the receipt is rejected as substantive buyer, seller, host-operator, or observer evidence

#### Scenario: Declared actors overlap
- **WHEN** a concurrent stage declares multiple buyers or sellers
- **THEN** the aggregate receipts prove exact distinct cardinality, overlapping actor lifetimes, bounded invocation skew, and absence of local queuing or throttling

#### Scenario: Buyer verifies the successful guest
- **WHEN** a buyer's real VM request succeeds
- **THEN** its substantive receipt correlates buyer-owned SSH/resume, one visible guest GPU, and the pinned compiled vector-add success marker/checksum to the successful `fulfillment_id` without exposing private SSH, host, or GPU identity

### Requirement: Agent-triggered frozen actions
A controller MAY independently validate and freeze exact request bytes, and a
deterministic driver MAY execute those bytes behind a pinned wrapper, but a run
MUST be labeled agent-triggered only when the initiating buyer process remains
alive through release and invokes that wrapper itself. The action contract MUST
bind the exact SCM commit, scenario identity and digest, selected logical
seller/listing, typed service/listing `runtime_binding`, a private
`concrete_payload_binding`, closed sanitized portable VM/KVM/Ansible intent and
its exact canonical payload digest, pinned wrapper identity and digest, actor
identity and actor-invocation capability, prepared-action digest, release
identity, attempt number, and the expected result schema version and a closed
independent-oracle-authority artifact's canonical digest. That authority MUST
bind the exact profile stage, result schema, execution boundary/trigger,
observer plan for a real path, and whether real oracle evidence is allowed. A
real oracle's exact observer-plan digest MUST be frozen exactly once among the
same concurrency policy's role-plan authorities. The frozen
action MUST NOT bind a future result digest. A terminal result receipt MUST bind
the canonical frozen-action digest and MUST compute its own canonical digest
only after terminal observation. Changed authority,
request, configuration, selection, wrapper, or bytes; an unauthorized retry;
duplicate release; or actor exit before invocation MUST fail closed.
The physical one-shot wrapper's fixed action kind MUST NOT be caller
overridable, and the terminal result paired with a role MUST bind that exact
supplied frozen-action digest and release rather than merely reuse its action
ID.

Service start and seller/listing publication MUST use distinct logical
selections. Private infrastructure MUST allocate one typed service binding per
seller service and one typed listing binding per logical seller/listing pair.
An opaque listing binding MAY be allocated before publication, but publication
MUST atomically seal its owner-only proof to exactly one minted live listing;
the buyer wrapper MUST later resolve that unchanged binding. A service binding
MUST NOT be substituted for a listing binding.

A successful result MUST record attempt one and one release claim. A rejected
unauthorized-retry result MUST preserve the attempted value greater than one
and zero emissions; a rejected duplicate release MUST preserve more than one
claims and zero emissions.

A substantive seller MUST likewise remain alive and invoke its frozen service
start and exact listing-publication actions through pinned one-shot wrappers.
During mock preparation those actions target only the mock boundary; during
real qualification they target the admitted live boundary. Controller-owned
seller service start or publication after the seller exits MUST NOT count as a
substantive seller action.

The public actor-invocation capability is a portable correlation referent, not
proof that a Codex process owns it. Private infrastructure MUST issue and
authenticate that capability against the still-live Codex process/session and
the release channel immediately before every real invocation. A public mock
capture MUST explicitly record `portable-binding-only` and
`private_actor_ownership_verified: false`; it proves artifact composition and
zero live effects, not private process authenticity.

#### Scenario: Buyer triggers one frozen request
- **WHEN** a live buyer receives one release for its unchanged frozen request and invokes the pinned wrapper exactly once
- **THEN** the resulting action receipt records attempt one and can be correlated with the buyer's substantive role receipt

#### Scenario: Controller emission after actor exit is classified accurately
- **WHEN** an actor approves a request digest and exits before another process emits the request
- **THEN** the result records `actor_trigger=controller-driven` with the boundary actually exercised and MUST NOT claim `agent-triggered`

#### Scenario: Mutation or retry is rejected
- **WHEN** the request bytes, scenario authority, selected seller/listing, wrapper digest, or attempt count differs from the frozen action
- **THEN** the wrapper returns a typed failure without emitting a replacement request

#### Scenario: Seller owns service start and publication
- **WHEN** a substantive seller reaches release with unchanged frozen configuration and listing bytes
- **THEN** the live seller process invokes the pinned service-start and publication wrappers itself and remains alive through observation

#### Scenario: Capture-only composition stays outside the campaign registry
- **WHEN** buyer and seller agents rehearse the pinned B1/S1/G1 actions through `tools/issue-discovery/config/capacity/profile-stages/b1-s1-g1-mock.json`
- **THEN** the artifact proves only `mock`/`agent-triggered` portable action/capability composition with an empty live-resource ledger, explicitly denies private actor-ownership verification, and cannot enter the exact qualification/measured registry or claim a real oracle

#### Scenario: Interrupted mock result materialization is recovered
- **WHEN** the capture-only sink durably installs the owner-only claim/payload/first-result record for either an emission or typed pre-emission rejection but result-file materialization is interrupted
- **THEN** a repeated invocation for that exact output validates and recovers those exact first-terminal bytes without creating a second emission or reinterpreting the payload; a corrupt record or mismatched existing output fails hard

#### Scenario: Rejected first invocation consumes the release
- **WHEN** the first invocation fails a frozen authority, payload, selection, runtime-binding, wrapper, retry, or liveness check
- **THEN** its typed zero-emission result is the atomically recorded first terminal result, and a later corrected invocation under the same action/release cannot emit as a new attempt one

### Requirement: Independent VM-capacity oracle
Capacity outcomes MUST be evaluated from independent observations rather than
an actor's or emitter's success claim. Each result MUST have exactly one
`outcome_kind`: `vm-succeeded`, `capacity-refused`, or `fault`.

The public `deal_reference` carrier MUST be a closed object containing
`request_id`, logical seller/listing slots, the typed `runtime_binding`,
and nullable non-secret digests of the storefront negotiation and escrow
references. A successful outcome requires both commercial digests and
independent joins from that storefront-owned carrier to
`capacity_reservation_id`, then separately to durable `fulfillment_id`,
Settlement Record state and selected Settlement Resource,
`provisioned_resource_id`, the pinned guest GPU exercise, and torn-down state.
The generic fulfillment record MUST NOT be required to contain commercial
agreement identity. `fulfillment_id` is the durable fulfillment identity.
`allocation_id` and `provisioning_job_id` MAY appear as diagnostics but MUST
NOT be required as universal identities. Public buyer evidence MUST NOT require
physical `resource_id` or `vm_host`.

`capacity-refused` is a harness oracle outcome, not a product terminal-status
alias. It MUST require an independent per-site observation proving that every
eligible-site attempt in the final escrow-scoped atomic capacity reservation
call for the exact deal reference returned the current routine
`reservation: null` response. The observation MUST enumerate the complete
eligible-site set and prove zero site errors, skipped sites, missing responses,
or non-routine responses. An aggregate `reservation: null` or `None` result
alone MUST NOT establish scarcity because the current aggregator can also
produce it after swallowed site errors. The oracle MUST also prove that no
`capacity_reservation_id`,
Settlement Resource, `fulfillment_id`, provisioned output, VM, or GPU
assignment was created, and that storefront deal/escrow/failure-policy state
converged to its declared terminal or compensated state with no active claim,
lock, or run-owned funds. Its durable capacity/fulfillment identifiers MUST
therefore be null.

The current `capacity_hold_unavailable` stage event is only a nonterminal,
best-effort pre-settlement signal: it MAY support the observation trail but
MUST NEVER establish `capacity-refused`. Generic provisioning errors, policy
denials, unknown reasons, uncompensated or nonterminal commercial state,
missing atomic-refusal proof, and timeouts MUST be `fault`. On a one-GPU
topology, any observation of more than one simultaneous successful whole-GPU
VM MUST fail correctness regardless of expected counts.

#### Scenario: Successful lifecycle is correlated
- **WHEN** independent evidence joins one request through `deal_reference`, `capacity_reservation_id`, `fulfillment_id`, Settlement Record state, `provisioned_resource_id`, VM/GPU exercise, and teardown with the selected seller/listing
- **THEN** the oracle counts one `vm-succeeded` whole-GPU lifecycle

#### Scenario: Atomic capacity refusal is counted
- **WHEN** independent evidence enumerates every eligible site, proves that every attempt returned routine `reservation: null` with zero errors/skips/missing responses, and proves null durable capacity/fulfillment identities, no physical output, terminal compensation, and no active residue for the exact deal reference
- **THEN** the oracle counts one `capacity-refused` outcome

#### Scenario: Aggregate null after a site error is a fault
- **WHEN** the aggregate reserve result is null but any eligible site errored, was skipped, lacked an observed response, or returned something other than routine `reservation: null`
- **THEN** the oracle records `fault` rather than capacity scarcity

#### Scenario: Soft-hold event is not a terminal refusal
- **WHEN** `capacity_hold_unavailable` is observed but the later escrow-scoped atomic reserve and terminal compensation are not independently established
- **THEN** the oracle does not count a capacity refusal

#### Scenario: Timeout is a fault
- **WHEN** a request times out, returns only a generic failure, remains uncompensated, or lacks independent atomic-refusal and zero-active-residue proof
- **THEN** the oracle records `fault`

#### Scenario: One-GPU double allocation fails
- **WHEN** independent observation finds two simultaneous successful VM lifecycles assigned to the one verified GPU authority
- **THEN** correctness fails even if all actor receipts report success

### Requirement: Serialized teardown and reuse
Serialized reuse A and B MUST be separate ordered integer-count B1 stages. Reuse
A MUST reach terminal teardown and an independently verified intermediate
baseline before reuse B may emit. Reuse B MUST create a distinct request,
`deal_reference`, `capacity_reservation_id`, `fulfillment_id`, Settlement
Record, `provisioned_resource_id`, VM, and teardown lifecycle and MUST restore
the same baseline again. Serialized reuse MUST NOT be reported as concurrent
fulfillment capacity.

#### Scenario: Ordered reuse succeeds
- **WHEN** reuse A completes one correlated VM/GPU lifecycle, restores the required baseline, and reuse B then completes a distinct lifecycle and restores that baseline again
- **THEN** the profile proves release and safe serial reuse

#### Scenario: Reuse B is fenced by cleanup
- **WHEN** reuse A lacks terminal teardown, baseline equivalence, or an empty active-resource observation
- **THEN** reuse B cannot release its request

### Requirement: Every stage restores its declared baseline
Every request-bearing stage MUST durably record its complete terminal
per-request correlations, aggregate independent observation, teardown result,
zero-active-residue result, and baseline-equivalence comparison.

The baseline model MUST partition:

- reversible state, whose native digest must return exactly to the declared
  stage baseline, including active capacity reservations/leases, Settlement
  Resources, fulfillment/provider jobs, VMs, disks, networks, Ansible
  processes, GPU assignment, and the stage's intended listing/service set; and
- append-only or accounting state, whose expected deal, Settlement, request,
  escrow/claim, transaction-fee, wallet-balance, and terminal history deltas
  must be completely enumerated, reconciled, and contain no active lock or
  unexplained value.

Baseline equivalence means exact reversible-state equality plus only the
allowlisted reconciled immutable/accounting deltas. It does not require
append-only history or wallet balances to equal their pre-stage bytes. Missing
or unexplained state in either partition MUST fail the stage. The next stage
MUST NOT start before the prior stage is teardown-verified and
baseline-equivalent. Public artifacts MUST bind privacy-preserving private proof
values rather than expose private resource identifiers.

#### Scenario: Clean stage can advance
- **WHEN** every request has a terminal correlation, teardown completes, reversible state returns exactly, every immutable/accounting delta is expected and reconciled, and no undeclared active residue or lock remains
- **THEN** the stage may pass and the next ordered stage may prepare

#### Scenario: Residue prevents advancement
- **WHEN** any governed market, settlement, request, funds, job, VM, Ansible/process, or GPU state is missing, active outside the declared reversible baseline, or an unexplained immutable/accounting delta
- **THEN** the stage fails clean-state verification and the next stage remains fenced

### Requirement: Private authority bindings resist identifier enumeration
Every public value that binds a private runtime identity map, concrete action
payload, actor-invocation capability, topology, host baseline, or
native-evidence set MUST use one closed
`privacy_preserving_binding` object containing exactly:

- `method`: exactly `hmac-sha256-v1` or `opaque-random-v1`;
- `domain`: the exact field-specific value
  `scm.capacity.runtime-binding.v1`,
  `scm.capacity.topology-authority.v1`,
  `scm.capacity.reversible-baseline.v1`,
  `scm.capacity.baseline-equivalence.v1`, or
  `scm.capacity.native-evidence.v1`,
  `scm.capacity.actor-invocation.v1`, or
  `scm.capacity.concrete-payload.v1`, as applicable; and
- `value`: exactly 64 lowercase hexadecimal characters.

For `hmac-sha256-v1`, `value` MUST be HMAC-SHA-256 under a per-campaign private
random key over the domain string, one zero byte, and the canonical native proof
bytes. For `opaque-random-v1`, `value` MUST be 256 bits sampled from a
cryptographically secure private random source and stored beside the owner-only
native proof. The private executor MUST verify the typed value, method, and
domain against that proof at every authority boundary. For a concrete-payload
binding, that proof is the exact secret-bearing native action payload. For an
actor-invocation binding, private infrastructure MUST additionally prove that
the still-live Codex process/session owns the capability and authenticated
release channel; the public carrier alone does not authenticate ownership. The
key, random source value, and native identifiers MUST remain private.

The portable schema fields MUST be named `runtime_binding`,
`concrete_payload_binding`, `actor_invocation_capability_binding`,
`topology_authority_binding`, `reversible_baseline_binding`,
`baseline_equivalence_binding`, and `native_evidence_bindings` rather than
calling either representation a digest. Raw unkeyed SHA-256 or another
deterministic public hash of private enumerable listing, wallet, project, host,
endpoint, PCI/GPU, topology, baseline, or evidence identifiers MUST be
rejected. Ordinary digests of public Git-tracked content remain unaffected.

#### Scenario: Keyed private binding is accepted
- **WHEN** a public runtime, topology, baseline, or native-evidence field contains the exact typed binding method, applicable domain, and 256-bit value and private infrastructure verifies it against the owner-only proof
- **THEN** the value may correlate portable artifacts without exposing enumerable private identity

#### Scenario: Raw private-identifier digest is rejected
- **WHEN** a public authority value is a raw deterministic hash of private enumerable identifiers, omits its method, or uses the wrong field domain
- **THEN** validation fails before role release or result publication

### Requirement: Evidence classes and capacity frontiers
Every profile-stage and result record MUST carry the exact orthogonal
`execution_boundary` and `actor_trigger` enums defined by the mode-neutral
scenario requirement. Scenario documents MUST carry neither field. Only
`real-qualification`/`agent-triggered` and
`real-measured`/`agent-triggered` results may be agent-capacity evidence.
`mock` proves preparation only; `real-reference`/`controller-driven` remains a
product/environment control. Buyer count MUST be reported as offered demand,
not as capacity.

Measured results MUST report these frontiers separately:

- the request-processing frontier is the greatest offered-concurrency shape in
  which every request reaches its expected `outcome_kind` within the
  declared request-processing SLO without local generator saturation;
- the simultaneous-fulfillment frontier is the greatest independently observed
  count of concurrently active successful whole-GPU fulfillments;
- the provisioning frontier reports queue wait separately from Ansible service
  time and identifies the greatest admitted shape meeting both declared
  provisioning SLOs;
- the correctness frontier is the greatest shape whose complete correlations,
  expected outcomes, cleanup, and baseline equivalence all pass; and
- the load-generator frontier is the greatest shape for which declared actors
  overlap, remain live, meet emission skew, and show no local queue or
  controller throttle.

Buyer search MUST begin with B1, B2, B4, and B8 against S1/G1. A boundary
refinement MUST select frozen shapes immediately below, at, and above the
candidate integer boundary and MUST change only the dimension being measured.
Seller scaling MUST not begin without an external receipt for the completed
buyer frontier. If the frozen envelope or load-generator frontier ends before
an SCM boundary is exceeded, the result MUST be reported only as a validated
lower bound.

#### Scenario: Mock path is classified as preparation
- **WHEN** substantive agents complete publication and purchase through mock provisioning with clean teardown
- **THEN** the result is `execution_boundary=mock` and `actor_trigger=agent-triggered`, and no real provisioning or system-capacity claim is permitted

#### Scenario: Measured result reports distinct frontiers
- **WHEN** an admitted measured wave completes
- **THEN** its result separates offered buyers from request-processing, simultaneous fulfillment, provisioning queue wait, Ansible service time, correctness, and load-generator observations

#### Scenario: Boundary refinement changes one dimension
- **WHEN** buyer or seller scaling brackets a possible frontier within the frozen envelope
- **THEN** the below/at/above refinement shapes hold every non-target dimension constant

#### Scenario: Seller scaling lacks buyer receipt
- **WHEN** a seller-scaling stage is selected without an external receipt identifying the completed buyer frontier
- **THEN** the profile-stage validation rejects the selection

#### Scenario: Generator saturation limits the claim
- **WHEN** the actor or load-generator layer saturates before SCM fails
- **THEN** the report states the largest validated lower bound and does not claim the unobserved SCM limit

### Requirement: Sanitized immutable capacity findings
A current capacity finding MUST use schema version 2 and bind its canonical
scenario ID and SHA-256, profile-stage ID and SHA-256, result ID and SHA-256,
destination, classification, frontier, structured durable lifecycle
correlation, observed outcome, and filing readiness. `finding_id` MUST be the
immutable identity of this one observed occurrence. SCM MUST derive and
validate the stable defect fingerprint from normalized defect semantics; a
producer-supplied fingerprint MUST NOT be authoritative. Finding ID, run,
branch, and timestamp metadata MUST NOT change defect identity.

The stable fingerprint input MUST contain only destination, classification,
canonical scenario ID/hash, affected frontier, normalized failure code and
signature, expected outcome kind, actual fault category, and normalized
lifecycle phase. It MUST exclude `finding_id`, profile-stage/result IDs and
hashes, run/stage/ref/epoch/time authority, evidence paths/hashes, and concrete
per-request commercial, reservation, fulfillment, or provisioned-resource
correlations. Those excluded values remain immutable occurrence evidence.

The `observed` authority MUST contain bounded `run_id` and `stage_id`, exact
`working_branch`, `working_ref`, `upstream_branch`, `upstream_ref`, nullable
`inbound_merge_ref`, reconciliation-epoch ID, and observation timestamp. A
finding for SCM MUST map working authority to
`feat/issue-discovery-harness` and upstream authority to `dev`; a finding for
internal infrastructure MUST map working authority to
`tools/agent-orchestration-scratch` and upstream authority to `main`. All refs
MUST be exact 40-character commits and the working ref MUST contain the pinned
upstream ref, directly or through the recorded inbound merge.

Classification MUST be exactly one of `public-product`, `public-harness`,
`private-orchestration`, or `environment-provider`. An expected, independently
proven `capacity-refused` outcome is a result, never a finding; a missing
terminal compensation or cleanup proof is instead an actionable fault. A
finding MUST NOT become `ready_to_file` until its stage has complete teardown,
zero-active-residue proof, and baseline equivalence. In this campaign,
`public-product` and `public-harness` target SCM;
`private-orchestration` and `environment-provider` target internal
infrastructure. Any additional destination requires a reviewed contract.

Public findings MUST reject credentials, wallet or account identities, cloud
project or host identities, GPU identifiers, private endpoints, absolute or
escaping evidence paths, and evidence references whose bytes do not match their
declared digest. Every evidence reference MUST be an object containing exactly
one repository- or run-relative `path` and its lowercase `sha256`.

#### Scenario: Finding v2 is accepted
- **WHEN** a sanitized finding binds exact scenario/profile/result and branch authority, immutable finding occurrence, durable VM correlation, cleanup-complete evidence hashes, a valid destination, and a fingerprint reproduced by SCM
- **THEN** it may enter the branch-scoped finding lifecycle

#### Scenario: New occurrence keeps defect identity
- **WHEN** the same normalized defect occurs in another run or at another working-branch commit
- **THEN** SCM derives the same stable defect fingerprint while preserving a new immutable `finding_id` and occurrence authority separately

#### Scenario: Expected capacity refusal is not fileable
- **WHEN** a request produces the expected independently proven `capacity-refused` result with terminal compensation and complete cleanup
- **THEN** it remains capacity evidence and cannot be represented as a finding

#### Scenario: Cleanup-incomplete occurrence is not ready
- **WHEN** an actionable defect is observed but teardown, zero-active-residue, or baseline equivalence is incomplete
- **THEN** the immutable finding may be retained for reconciliation but `ready_to_file` is false

#### Scenario: Sensitive or mutable evidence is rejected
- **WHEN** a finding contains a forbidden private identifier, an unsafe evidence path, a missing digest, or evidence bytes that no longer match the digest
- **THEN** validation fails before issue-packet rendering
