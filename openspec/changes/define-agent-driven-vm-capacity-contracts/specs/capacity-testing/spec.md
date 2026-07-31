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

### Requirement: Pinned profile authority is consumable across repositories
SCM MUST expose CLI and runner operations that resolve the exact public profile
registry and any registered or standalone profile stage through the same
Git-pinned validators used internally. A successful operation MUST return one
closed deterministic JSON object containing the exact validated registry or
stage semantic object, its canonical digest, the exact pinned SCM ref and
repository-relative path, every applicable registry canonical and raw-byte
digest, and the resolved validated scenario semantic object and authority or
null. Validation operations MUST require the caller's expected canonical
digest; profile-registry validation MUST also require its expected raw-byte
digest. Profile-stage validation MUST additionally require both expected
registry digests for a registry-backed stage and MUST reject either registry
digest for a standalone stage. This interface MUST NOT require private
orchestration to import SCM Python modules, reread unvalidated worktree bytes,
or reproduce public profile policy.

#### Scenario: Private orchestration resolves one registered stage
- **WHEN** a caller supplies the exact SCM ref and expected stage, registry-canonical, and registry-raw digests for a registered profile stage
- **THEN** the operation returns the validated stage and resolved scenario semantics with the matching pinned authority in one deterministic JSON object

#### Scenario: Standalone mock remains outside registry authority
- **WHEN** a caller resolves the standalone mock stage without registry digests
- **THEN** the operation returns its validated stage and scenario semantics with null registry path and digests

#### Scenario: Cross-repository authority mismatch fails closed
- **WHEN** the expected profile, stage, registry-raw, or registry-canonical digest differs from the pinned public authority, or registry digests are omitted or supplied for the wrong stage class
- **THEN** validation fails instead of returning a semantic projection

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

A capacity result MUST be emitted only for `real-reference`,
`real-qualification`, or `real-measured`. Readiness/probe observations and
mock captures are evidence artifacts, not capacity results, and MUST NOT use a
capacity-result schema or enter any capacity frontier. A controller process
that exits after release invalidates its row rather than converting the row
into a readiness, mock, or partial capacity result.

#### Scenario: One shape is reused without relabeling
- **WHEN** mock preparation, the deterministic reference, and Q0 each use the same pinned B1/S1/G1 scenario
- **THEN** their profile-stage records carry `mock`/`agent-triggered`, `real-reference`/`controller-driven`, and `real-measured`/`agent-triggered`, respectively; only the two real executions emit capacity results, while the scenario identity and digest remain unchanged

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
3. an external buyer-frontier receipt, derived from and hash-binding those
   exact ordered buyer results, before any reuse stage begins;
4. `serialized-reuse-a-measured`, which binds that buyer-frontier receipt, and
   then `serialized-reuse-b-measured`, which binds reuse A and preserves the
   exact buyer-frontier lineage;
5. `b2-s2-g1-measured`, which binds the clean reuse-B baseline and the same
   buyer-frontier receipt, followed—only
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

Every measured seller result MUST bind the buyer-frontier receipt ID/hash, the
clean reuse-B result ID/hash, the admitted distinct-seller and distinct-service
cardinalities, and the immediately preceding seller result ID/hash (null only
for B2/S2). Seller admission MUST be derived by H1 from independently observed,
simultaneously live seller processes and truthful distinct published services;
declared counts alone are not authority. Its start MUST be strictly after
reuse B's `progression_ready_at` or the preceding seller result's
`progression_ready_at`, respectively. Thus the portable lineage is exactly
buyer frontier → reuse A → reuse B → seller stage, then seller result by seller
result, with both hash and temporal fencing.

Expected concurrent outcomes are unordered cardinality constraints over the
declared request IDs. No scenario may predesignate which buyer wins. Every
observed outcome MUST still correlate to exactly one request ID.

#### Scenario: Initial buyer progression is valid
- **WHEN** a measured G1 profile declares the exact B1, B2, B4, and B8 stages with one request per buyer, one unordered expected success, independently proven capacity refusal for the other requests, and retry zero
- **THEN** its portable counts are valid while private admission and resource authority remain independently required

#### Scenario: Seller progression follows buyer completion
- **WHEN** a measured seller row declares S2/B2 or S2/B4 after the hash-bound buyer frontier and clean reuse-B baseline, binds its exact prior seller result, and binds distinct seller/listing choices to one globally fenced G1 authority
- **THEN** the row may be assembled by private infrastructure only as the next temporally admitted seller stage

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
validation. Every seller plan MUST carry the exact same typed
`topology_authority_binding` as the stage's sole H1 plan. The pre-release
concurrency policy MUST reject any missing or unequal seller binding before
release. Each frozen seller action MUST inherit that authority through its
exact seller-plan hash and concurrency-policy authority, each terminal seller
receipt MUST repeat the same binding as its plan, and the capacity result's
topology authority MUST equal H1's. This opaque public binding proves that all
one-GPU sellers consult one globally fenced view without exposing the private
host, GPU, allocator, or fence identity. Every request MUST select one declared
seller and one declared listing.

#### Scenario: Safe two-seller one-GPU row is accepted
- **WHEN** two distinct sellers each expose one selected VM listing, both bind the same globally fenced one-GPU authority, and each request targets an exact declared seller/listing pair
- **THEN** the row may expect one total success and one independently proven capacity-refusal outcome

#### Scenario: Duplicate or partitioned seller authority is rejected
- **WHEN** seller identities or service identities repeat, seller distribution does not match listing count, a request targets an unselected listing, or two one-GPU sellers use independent allocation views
- **THEN** validation fails before publication or request release

#### Scenario: Seller plan diverges from H1 topology authority
- **WHEN** any seller plan omits or changes the sole H1 plan's typed `topology_authority_binding`
- **THEN** concurrency-policy validation rejects the stage before release, so no frozen seller action can inherit or exercise the disjoint authority

#### Scenario: Seller receipt or result changes topology authority
- **WHEN** a terminal seller receipt differs from its exact plan binding or the capacity result differs from the sole H1 receipt binding
- **THEN** role/result validation fails and the row cannot contribute qualification, measurement, or a frontier

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

Only reuse B's H1 evidence may authorize seller scaling. The H1 plan MUST
pre-freeze the eligible distinct-seller/service identities and cardinalities
with typed native-evidence bindings, and the H1 receipt MUST exactly repeat and
attest that plan without referring to the not-yet-created reuse-B result. The
reuse-B result MUST bind that exact H1 receipt, derive and seal the admission
predicate, and bind the buyer-frontier/reuse-A lineage and baseline equivalence.
Downstream seller results MUST bind the exact reuse-B result and its sealed
frontier/admission authority. No H1 artifact may bind a future result ID/hash.

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

An otherwise authoritative actor set whose one-shot action is rejected, or
whose independently observed overlap, skew, local-queue, or
controller-throttle predicate fails, MUST remain valid negative observation
evidence. Its role/action provenance and failure reasons MUST be retained, but
`load_generator_passed` and `eligible_for_capacity_frontier` MUST be false.
Structural, identity, authority, correlation, or timing fabrication remains
invalid rather than becoming a negative observation.

For every real request-bearing result, O1's terminal receipt MUST enumerate
each exact request ID once and seal the canonical SHA-256 of that request's
complete outcome bytes. The same receipt MUST seal the canonical SHA-256 of
the complete stage-cleanup object and bind the native evidence used for each
seal. Recomputing an outcome or cleanup object outside O1, even from equivalent
facts, MUST NOT substitute for these exact byte seals.

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

#### Scenario: Generator failure remains a negative observation
- **WHEN** authoritative agent receipts prove that a frozen action was rejected or independently observe failed overlap/skew or local queue/throttle
- **THEN** the row retains agent provenance and the exact failure reason but is censored from capacity-frontier promotion

#### Scenario: Independent observer seals exact result bytes
- **WHEN** O1 completes a real request-bearing stage
- **THEN** its terminal receipt binds each request ID to the canonical hash of its exact outcome object and separately binds the exact cleanup-object hash

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
- **THEN** the controller-driven observation is retained as accurately labeled negative evidence, but the attempted agent row is invalid and no qualification/measured capacity result may claim `agent-triggered`

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

### Requirement: Outcome evaluation policy is frozen before Q0
Before Q0, the campaign MUST freeze one closed evaluation-policy artifact
containing the exact SCM ref; the pinned profile-registry path plus canonical
and raw SHA-256 values; a typed common-clock evidence binding; positive-integer
request-processing, provisioning-queue, Ansible-service, and
terminal-observation limits; and these exact five frontier-definition values:

- request processing:
  `all-expected-terminal-within-slo-without-generator-saturation`;
- simultaneous fulfillment:
  `maximum-independent-overlapping-whole-gpu-vms`;
- provisioning: `greatest-shape-meeting-queue-and-ansible-slos`;
- correctness:
  `greatest-shape-with-complete-oracle-cleanup-and-baseline`; and
- load generator:
  `greatest-shape-with-overlap-skew-liveness-and-no-local-queue`.

The terminal-observation timeout MUST NOT be shorter than the
request-processing SLO. Every real-reference, real-qualification, and
real-measured result MUST bind that validated policy's ID and canonical digest,
and its independently observed release MUST be later than the policy's
`frozen_at`. Profile-registry or policy bytes MUST NOT drift after Q0.
For every request, `elapsed = terminal_offset - invocation_offset`;
`elapsed >= terminal_observation_timeout` is a `timeout` fault, while a
non-timeout terminal MUST satisfy `elapsed < terminal_observation_timeout`.
The same frozen policy MUST govern the private campaign executor and every
individual public command; private orchestration MAY add secrets and native
proofs but MUST NOT alter thresholds, ordering, outcome semantics, or frontier
rules.

#### Scenario: Pre-Q0 policy is accepted
- **WHEN** one policy was frozen before release, binds the exact canonical and raw profile-registry bytes, common clock, SLOs, timeout, and five fixed definitions
- **THEN** the same policy ID/hash may govern reference, qualification, and measured result evaluation

#### Scenario: Post-observation threshold is rejected
- **WHEN** a result binds a different policy, the registry digest drifts, the policy was not frozen before release, or the terminal timeout is shorter than the request-processing SLO
- **THEN** outcome evaluation fails rather than selecting thresholds after observing the wave

### Requirement: Independent VM-capacity oracle
Capacity outcomes MUST be evaluated from independent observations rather than
an actor's or emitter's success claim. Each result MUST have exactly one
closed, discriminated `outcome_kind`: `vm-succeeded`, `capacity-refused`, or
`fault`; fields belonging to another variant MUST be rejected.

The public `deal_reference` carrier MUST be a closed object containing
`request_id`, logical seller/listing slots, the typed `runtime_binding`,
and nullable non-secret digests of the storefront negotiation and escrow
references. A successful outcome requires both commercial digests and
independent joins from that storefront-owned carrier to
`capacity_reservation_id`, then separately to durable `fulfillment_id`,
the Settlement Record keyed by `capacity_reservation_id`, its typed private
selected-Settlement-Resource binding, `provisioned_resource_id`, real
KVM/Ansible provisioning with whole-device GPU passthrough, the Git-pinned
compiled CUDA guest exercise, and torn-down state.
The generic fulfillment record MUST NOT be required to contain commercial
agreement identity. `fulfillment_id` is the durable fulfillment identity.
`allocation_id` and `provisioning_job_id` MAY appear as diagnostics but MUST
NOT be required as universal identities. Public buyer evidence MUST NOT require
physical `resource_id` or `vm_host`, and the harness MUST NOT invent a
buyer-visible Settlement Resource ID.

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
missing atomic-refusal proof, and timeouts MUST be `fault`. A fault MUST use
exactly one of `generic-failure`, `provisioning-error`, `policy-denial`,
`unknown-reason`, `uncompensated`, `atomic-refusal-incomplete`, `timeout`,
`missing-durable-correlation`, `cleanup-incomplete`, or `generator-failure`;
its typed observation MUST identify the lifecycle phase and timeout state, and
an atomic-refusal-incomplete fault MUST preserve the partial site observation.
A complete routine atomic refusal with terminal compensation and clean request
teardown MUST NOT be mislabeled as a fault. On a one-GPU
topology, any observation of more than one simultaneous successful whole-GPU
VM MUST preserve the exact request outcomes, add the derived stage fault
`double-allocation`, and fail correctness regardless of expected counts. The
artifact remains valid negative issue-discovery evidence rather than being
discarded by schema or correlation validation.

Each request outcome MUST carry invocation and terminal monotonic offsets. The
aggregate independent observation MUST cover every exact request once, repeat
those exact offsets, bind a native timing-evidence value also present on that
request, and use the same typed common-clock authority as the actor set or
reference policy. For an agent-driven row, invocation MUST equal the exact
frozen buyer action's independently observed invocation, the market terminal
MUST not precede the one-shot wrapper terminal, and both MUST remain inside the
owning buyer's observed lifetime. Aggregate observation time MUST fall inside
both the stage lifecycle and O1's receipt lifecycle.

O1's receipt MUST seal the canonical hash of every exact request outcome and
the complete cleanup object. A `real-reference` result MUST instead have no
agent actor set and MUST bind a non-counted controller's reference execution,
reference policy, release, common clock, and per-request timing. It MUST still
include exactly one independent actionless O1 receipt and one actionless H1
receipt bound to that reference policy and release; the controller MUST NOT
author either role receipt or O1's outcome/cleanup seals.

The typed reference policy MUST be created after the campaign evaluation
policy is frozen and before reference release. It MUST bind the exact H1 and O1
plans (including H1's teardown plan), release authority, campaign clock, and
request schedule. The reference result MUST separately bind the controller's
execution proof and the exact H1 and O1 receipt IDs/hashes that attest those
plans. Substitution of any plan, receipt, release, clock, or schedule
invalidates the reference.

The per-site atomic-reservation observation MUST treat the exact deal-reference
hash as base authority and MUST prove that invocation and terminal offsets are
ordered, inside the request interval, and on the campaign clock; that the
typed eligible-site-set binding verifies; that eligible slots are nonempty and
unique; that attempt slots are unique and exactly cover the eligible set for a
complete observation; and that typed site bindings are distinct. Each attempt
MUST satisfy exactly one row of this truth table:

- `routine-reservation-null`: `reservation=null`, `error=null`, `observed=true`,
  `skipped=false`;
- `reservation-created`: nonempty `reservation`, `error=null`,
  `observed=true`, `skipped=false`;
- `error`: `reservation=null`, nonempty `error`, `observed=true`,
  `skipped=false`;
- `missing`: `reservation=null`, `error=null`, and either attempted-no-response
  (`observed=true`, `skipped=false`) or skipped
  (`observed=false`, `skipped=true`); or
- `non-routine`: `reservation=null`, nonempty diagnostic `error`,
  `observed=true`, `skipped=false`.

No response kind may hide a reservation, and `skipped=true` is valid only for
`missing`. A complete capacity refusal
MUST be the final escrow-scoped call, cover the eligible set exactly once, use
only `routine-reservation-null` rows, and have null aggregate reservation. A partial
observation remains base-valid negative evidence but MUST be classified
`fault/atomic-refusal-incomplete`; a complete clean routine refusal MUST NOT.

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

#### Scenario: Timeout equality is terminal
- **WHEN** request elapsed time equals the frozen terminal-observation timeout
- **THEN** the oracle records `fault/timeout`, because only elapsed time strictly below the timeout may be non-timeout

#### Scenario: Partial atomic observation is retained
- **WHEN** the atomic observation has valid base authority and truthful attempt rows but does not cover the eligible set exactly once
- **THEN** the oracle preserves it as `fault/atomic-refusal-incomplete` and does not call it capacity scarcity

#### Scenario: One-GPU double allocation fails
- **WHEN** independent observation finds two simultaneous successful VM lifecycles assigned to the one verified GPU authority
- **THEN** the validator preserves both request observations, derives `double-allocation`, fails correctness, and retains the result as fault evidence even if all actor receipts report success

#### Scenario: Independent timing cannot be replayed
- **WHEN** a request changes its offsets, uses an unrelated timing binding, falls outside its buyer lifetime, or disagrees with the reference policy timing
- **THEN** result validation fails before the request can contribute to any SLO or frontier

#### Scenario: Deterministic reference preserves independent O1 and H1
- **WHEN** the non-counted controller completes a real-reference B1 lifecycle under a frozen reference policy
- **THEN** exact actionless O1 and H1 receipts bind that policy/release, O1 seals the request and cleanup bytes, and neither role is attributed to the controller

### Requirement: Serialized teardown and reuse
Serialized reuse A and B MUST be separate ordered integer-count B1 stages.
Reuse A MUST begin strictly after, and bind the ID/hash of, the completed
buyer-frontier receipt. It MUST reach one correct successful lifecycle,
terminal teardown, and an independently verified intermediate baseline before
reuse B may emit. Reuse B MUST begin strictly after reuse A's
`progression_ready_at`, bind the exact reuse-A result ID/hash, cleanup
completion and baseline-equivalence binding, and preserve the same
buyer-frontier authority, evaluation policy, and topology authority. For
measured reuse, A MUST match the buyer-frontier receipt's topology; for
qualification reuse, the frontier authority is null but B MUST still match A's
topology.

The two stages intentionally repeat the same frozen logical request slot
`request-1`; the repeated slot proves reuse and is not itself a durable product
identity. Their `deal_reference` hashes, negotiation references, escrow
references, `capacity_reservation_id` values, `fulfillment_id` values,
Settlement Records, `provisioned_resource_id` values, VM lifecycles, and
teardown lifecycles MUST each be distinct. Reuse B MUST restore the same
reversible baseline again.

Reuse correctness MUST depend on successful durable correlation, teardown,
zero residue, and baseline equivalence, not on the request-processing SLO.
A clean, correct A/B pair that misses that latency SLO still proves safe
physical release and reuse. Serialized reuse MUST NOT be reported as concurrent
fulfillment capacity.

#### Scenario: Ordered reuse succeeds
- **WHEN** reuse A and B repeat logical slot `request-1` while proving distinct commercial, reservation, fulfillment, Settlement, provisioned-resource, VM, and teardown identities and each restores the required baseline
- **THEN** the profile proves release and safe serial reuse

#### Scenario: Reuse B is fenced by cleanup
- **WHEN** reuse A lacks terminal teardown, baseline equivalence, or an empty active-resource observation
- **THEN** reuse B cannot release its request

#### Scenario: Reuse remains valid across an SLO miss
- **WHEN** reuse A and B each prove a correct durable success, complete teardown, zero residue, and the same restored baseline but exceed the request-processing SLO
- **THEN** request-processing fails while serialized-reuse validation still proves safe physical release and reuse

### Requirement: Every stage restores its declared baseline
Every request-bearing stage MUST durably record its complete terminal
per-request correlations, aggregate independent observation, teardown result,
zero-active-residue result, and baseline-equivalence comparison.

The baseline model MUST partition:

- exactly nine reversible components, each with exact equality and typed native
  evidence: `capacity-reservations-and-leases`, `settlement-resources`,
  `fulfillment-provider-jobs`, `vms`, `disks`, `networks`,
  `ansible-processes`, `gpu-assignments`, and `listing-service-set`; and
- exactly six append-only/accounting delta categories, each with expected and
  observed native bindings, reconciliation status, no active lock, and no
  unexplained value: `deal-history`, `settlement-history`, `request-history`,
  `escrow-claim-history`, `transaction-fees`, and `wallet-accounting`.

Baseline equivalence means exact reversible-state equality plus only the
allowlisted reconciled immutable/accounting deltas. It does not require
append-only history or wallet balances to equal their pre-stage bytes. Missing
or duplicated categories, false equality/reconciliation, any nonzero active
reservation, Settlement Resource, provider job, VM, disk, network, Ansible
process, GPU assignment, claim, or lock residue, or unexplained state in either
partition MUST fail the stage. `ready_for_next_stage` MUST equal this derived
clean-state predicate rather than be trusted as a producer assertion. H1's
cleanup/baseline observation and O1's exact cleanup-object hash seal MUST agree
with the result. Neither H1 nor O1 may complete before the cleanup it attests.
Each result MUST derive
`progression_ready_at = max(H1 receipt completed_at,
O1 receipt completed_at)` on the common campaign clock; neither receipt may
complete before actual cleanup completion. Every following buyer, reuse, or
seller stage MUST start strictly after that value. Public artifacts MUST bind privacy-preserving private proof values
rather than expose private resource identifiers.

#### Scenario: Clean stage can advance
- **WHEN** every request has a terminal correlation, teardown completes, reversible state returns exactly, every immutable/accounting delta is expected and reconciled, and no undeclared active residue or lock remains
- **THEN** the stage may pass and the next ordered stage may prepare

#### Scenario: Residue prevents advancement
- **WHEN** any governed market, settlement, request, funds, job, VM, Ansible/process, or GPU state is missing, active outside the declared reversible baseline, or an unexplained immutable/accounting delta
- **THEN** the stage fails clean-state verification and the next stage remains fenced

#### Scenario: Producer clean flag cannot override a partition
- **WHEN** `ready_for_next_stage` is true but one required reversible/accounting category is omitted, duplicated, unreconciled, non-equal, or not sealed by O1
- **THEN** the validator derives cleanup failure and refuses to advance

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
not as capacity. `agent_capacity_evidence` records the provenance of a valid
qualification/measured agent observation even when that observation discovers
a product or generator failure. `eligible_for_capacity_frontier` MUST be true
only for a `real-measured` row whose load generator passed; these two booleans
MUST NOT be conflated.

A `real-qualification` result MUST set every derived frontier and
buyer-frontier-receipt reference to null: qualification proves readiness but
does not measure a boundary. Every `real-measured` result MUST carry all five
derived frontier observations, even when their classification is
`not-observed`, and MUST bind the frozen campaign clock used for ordering and
SLO arithmetic.

Measured results MUST report these frontiers separately:

- the request-processing predicate is every request reaching its expected
  `outcome_kind` inside both the request-processing SLO and terminal timeout;
  generator failure censors the shape from frontier promotion rather than
  becoming an SCM request-processing failure;
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

Buyer search MUST begin in the exact order B1, B2, B4, and B8 against S1/G1.
The product progression predicate MUST be request processing plus provisioning
plus correctness, with load-generator failure treated as censoring. If that
predicate brackets a product boundary, refinement MUST select only the frozen
B3/B5/B6/B7 shapes required by deterministic integer bisection, in its exact
selection order, until the passing/failing bracket is adjacent. It MUST retain
the applicable observations immediately below, at, and above the candidate
boundary and MUST change only buyer count.

A closed buyer-frontier receipt MUST bind the exact SCM ref, pinned
profile-registry canonical/raw digests, evaluation-policy ID/hash, ordered
result IDs/hashes, exact initial and refinement stage IDs, retained counts,
per-stage predicate observations, all five independently derived frontiers,
the one exact typed `topology_authority_binding` shared by every bound
B1/B2/B4/B8 and refinement result, the selection predicate, and a completion
time strictly after every bound
result's `progression_ready_at` on the frozen campaign clock. Result IDs,
stage IDs, retained counts, and ordered result entries MUST be unique, and the
receipt MUST include every selected stage exactly once. Each shape frontier MUST be classified `exact-bound`,
`lower-bound`, or `not-observed`; the overall progression MUST be
`exact-bound`, `lower-bound`, or `no-clean-shape`. A shape exact bound MUST use
`observed-failure`, a lower bound MUST use `frozen-envelope-ended` or
`load-generator-ended-first`, and `not-observed` MUST use `no-passing-shape`.
Overall `exact-bound` and `no-clean-shape` use a null lower-bound reason;
overall `lower-bound` uses one of the two lower-bound reasons.

No result with unclean final state may authorize this receipt or reuse. Reuse A
MUST start strictly after and hash-bind the receipt, and measured reuse A's
topology authority MUST equal the receipt's. Reuse B MUST preserve both reuse
A's topology authority and, when measured, its frontier authority.
Qualification reuse has null frontier authority but MUST still preserve
topology from A to B. Seller scaling MUST then bind the same receipt and clean
reuse-B result. Every seller result MUST match the frontier, reuse-B, and
immediately prior seller result topology authorities and additionally bind H1-derived admitted distinct
seller/service counts and immediately prior seller result, and MUST begin
strictly after that predecessor's `progression_ready_at` on the campaign clock.
All seller result and predecessor IDs MUST be unique, and the seller sequence
MUST contain each admitted selected stage exactly once. If the frozen envelope or
load-generator frontier ends before an SCM boundary is exceeded, the result
MUST be reported only as a validated lower bound.

#### Scenario: Mock path is classified as preparation
- **WHEN** substantive agents complete publication and purchase through mock provisioning with clean teardown
- **THEN** the mock capture is classified `execution_boundary=mock` and `actor_trigger=agent-triggered`, no capacity result is emitted, and no real provisioning or system-capacity claim is permitted

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

#### Scenario: Agent provenance does not imply frontier eligibility
- **WHEN** an authoritative measured agent row observes a generator rejection, queue, throttle, overlap failure, or skew failure
- **THEN** it remains agent-originated negative evidence while `eligible_for_capacity_frontier` is false and the product frontier is censored

#### Scenario: Buyer frontier precedes reuse and seller scaling
- **WHEN** the exact B1/B2/B4/B8 and selected refinement results finish cleanly
- **THEN** one typed receipt hash-binds those observations and their shared topology before reuse A, the topology/frontier authority propagates through measured reuse B, and every seller result transitively matches the same topology, receipt, reuse-B baseline, and immediate predecessor

#### Scenario: Qualification reuse changes topology
- **WHEN** qualification reuse B binds a topology authority different from qualification reuse A
- **THEN** reuse validation fails even though both stages correctly carry null buyer-frontier authority

### Requirement: Finding occurrences bind one validated VM result
A current capacity finding MUST use schema version 2. `finding_id` MUST be the
immutable identity of one observed occurrence. The producer schema MUST NOT
contain `fingerprint`; SCM derives defect identity only after the occurrence
validates.

The closed top-level object MUST contain exactly `schema_version`,
`finding_id`, `destination_repo`, `classification`, `frontier`, `scenario_id`,
`scenario_sha256`, `profile_stage_id`, `profile_stage_sha256`, `result_id`,
`result_sha256`, `scm_contract_ref`, `defect_semantics`, `summary`, `expected`,
`actual`, `observed_outcome`, `durable_correlations`, `observed_authority`,
`evidence`, and `filing_readiness`.

Validation MUST consume an already fully validated capacity-result context and
the exact result artifact. The finding's `scenario_id`/`scenario_sha256`,
`profile_stage_id`/`profile_stage_sha256`, and
`result_id`/`result_sha256`, plus `scm_contract_ref`, MUST equal that context.
Schema-only result validation or a result with merely equivalent prose MUST
NOT grant finding authority.

Validation MUST load the finding schema blob from the exact
`scm_contract_ref`, which MUST equal the validated result's SCM ref and identify
a commit in the result's exact SCM repository. An ambient or uncommitted
schema file MUST NOT grant finding authority.

`observed_outcome` MUST contain exactly unique `request_ids`, one result
`outcome_kind`, and a normalized `diagnostic_code` ID or null.
`durable_correlations` MUST contain one entry per selected request in the same
deterministic order. Each entry MUST contain exactly `request_id`,
`outcome_kind`, `deal_reference_sha256`, nullable
`capacity_reservation_id`, nullable `fulfillment_id`, nullable
`settlement_record_sha256`, nullable `provisioned_resource_id`, nullable
`allocation_id`, nullable `provisioning_job_id`,
`commercial_resolution_sha256`, and `request_cleanup_sha256`. Every object
hash MUST be recomputed over that exact closed subobject in the result and
every nullable identity MUST repeat the result exactly. The producer MUST NOT
add, omit, reorder, or rewrite a correlation.

A `double-allocation` occurrence MUST recompute the deterministic witness from
the validated successful half-open active intervals: visit unique interval
start offsets in ascending order, select the first offset with more than one
active G1 VM, and bind every request active at that offset in lexicographic
request ID order. A producer-selected witness or a derived result fault without
this reproducible witness MUST fail.

#### Scenario: Finding v2 binds the exact result
- **WHEN** a sanitized occurrence repeats exact scenario/profile/result authority and exact affected-request correlation from one fully validated result
- **THEN** the finding is eligible for fingerprint derivation

#### Scenario: Plausible but unbound correlation is rejected
- **WHEN** a finding changes an identity or subobject hash, omits a null field, adds or reorders a request, or points to a different result with similar output
- **THEN** validation fails before fingerprinting or ingest

#### Scenario: Double allocation comes from the independent oracle
- **WHEN** the validated result independently derives a half-open overlap witness above the one-GPU authority
- **THEN** a `double-allocation` finding binds that exact witness rather than an actor-reported capacity claim

### Requirement: SCM derives stable defect identity
SCM MUST form one closed normalized fingerprint object containing exactly
`destination_repo`, `classification`, `scenario_id`, `scenario_sha256`,
`frontier`, `failure_code`, `stable_signature`, `expected_outcome_kind`,
`actual_fault_category`, and `lifecycle_phase`. SCM MUST hash the exact byte
domain prefix `scm.capacity.finding-fingerprint.v1\0` followed by the existing
canonical JSON bytes for that object, where `\0` is one terminal NUL byte and
not two printable characters. The externally visible fingerprint MUST be
`capacity-` followed by the full lowercase 64-hex SHA-256.

`failure_code` MUST already be a lowercase normalized code matching the closed
schema. `stable_signature` MUST already equal its Unicode NFKC, Unicode
case-folded, trimmed, Unicode-whitespace-collapsed form. SCM MUST recompute
that form and reject a mismatch before canonicalizing the fingerprint object.
SCM MUST NOT apply that normalization to human occurrence prose.

SCM MUST exclude `finding_id`, `scm_contract_ref`, profile-stage and result
IDs/hashes, `observed_outcome` request/diagnostic facts, every
`observed_authority` run/stage/ref/epoch/time field, evidence paths and
raw-byte hashes, concrete durable correlations, human summary/expected/actual
prose, cleanup, readiness, and lifecycle facts from the fingerprint preimage.
Those values remain immutable occurrence evidence.

#### Scenario: New occurrence keeps defect identity
- **WHEN** the same normalized defect occurs in another run, result, profile stage, or working-branch commit
- **THEN** SCM derives the same stable defect fingerprint while preserving a new immutable `finding_id` and occurrence authority

#### Scenario: Defect semantics change identity
- **WHEN** destination, classification, scenario identity, frontier, normalized failure code/signature, expected kind, actual fault category, or lifecycle phase changes
- **THEN** SCM derives a different stable fingerprint

#### Scenario: Producer supplies a fingerprint
- **WHEN** a finding input contains a producer-selected fingerprint even if its syntax or value appears correct
- **THEN** the closed schema rejects it

### Requirement: Finding eligibility is closed and cleanup-gated
Classification MUST be exactly one of `public-product`, `public-harness`,
`private-orchestration`, or `environment-provider`. Actual fault category MUST
be exactly one of the ten request categories `generic-failure`,
`provisioning-error`, `policy-denial`, `unknown-reason`, `uncompensated`,
`atomic-refusal-incomplete`, `timeout`, `missing-durable-correlation`,
`cleanup-incomplete`, and `generator-failure`, or the stage-derived categories
`double-allocation` and `unexpected-outcome`.

`expected_outcome_kind` MUST be exactly `vm-succeeded` or
`capacity-refused`; a frozen scenario cannot expect a fault.
`lifecycle_phase` MUST be exactly one result phase:
`pre-emission`, `negotiation`, `escrow`, `reservation`, `settlement`,
`provisioning`, `guest-verification`, `teardown`, `cleanup`, or
`load-generation`.

The affected `frontier` MUST be exactly `request-processing`,
`simultaneous-fulfillment`, `provisioning`, `correctness`, `load-generator`, or
`cleanup`. For a request-fault finding, `failure_code`,
`lifecycle_phase`, `observed_outcome.outcome_kind`, and
`observed_outcome.diagnostic_code` MUST exactly equal the selected result
fault.

`unexpected-outcome` MUST identify an independently valid terminal
`vm-succeeded` or `capacity-refused` kind whose observed cardinality exceeds
its frozen scenario cardinality. Its `request_ids` and durable correlations
MUST include every result request of that surplus kind in lexicographic request
ID order; they MUST NOT select an arbitrary surplus-sized subset because only
the aggregate proves `observed[kind] > expected[kind]`. Typed request faults
MUST retain their exact failure category. Independently derived
`double-allocation` MUST take precedence over `unexpected-outcome` for
overlapping surplus successes.

Double allocation MUST use frontier `simultaneous-fulfillment`, failure code
`double-allocation`, phase `provisioning`, successful observed kind, and null
diagnostic. An unexpected success MUST use expected kind
`capacity-refused`, failure code `unexpected-vm-succeeded`, phase
`guest-verification`, and null diagnostic. An unexpected refusal MUST use
expected kind `vm-succeeded`, failure code `unexpected-capacity-refused`, phase
`reservation`, and null diagnostic.

An expected, independently proven `capacity-refused` outcome MUST remain a
result and MUST NOT be represented as a finding. A bounded frontier stop,
lower-bound conclusion, or no-clean-frontier conclusion MUST NOT be represented
as its own finding; an actual underlying normalized fault MAY be represented
separately.

`filing_readiness` MUST be a closed derived proof with exactly
`terminal_correlations_complete`, `teardown_complete`,
`zero_active_residue`, `baseline_equivalent`, and `ready_to_file`. A finding
MUST NOT set `ready_to_file` until the other result-derived proof fields, exact
O1 cleanup/lifecycle sealing, and complete result progression permit it. An
occurrence whose cleanup is incomplete MAY be retained, but
`ready_to_file` MUST remain false.

#### Scenario: Expected capacity refusal is not fileable
- **WHEN** a request produces the expected independently proven `capacity-refused` result with terminal compensation and complete cleanup
- **THEN** it remains capacity evidence and cannot be represented as a finding

#### Scenario: Unexpected complete refusal is a normalized fault
- **WHEN** independently valid and fully compensated `capacity-refused` outcomes exceed the frozen refusal count
- **THEN** one `unexpected-outcome` occurrence binds every refusal request in lexicographic order rather than misclassifying the refusals themselves as invalid

#### Scenario: Overlapping surplus successes use the correctness fault
- **WHEN** successful outcomes exceed the frozen success count and the independent oracle also derives `double-allocation`
- **THEN** the occurrence uses the deterministic double-allocation witness instead of an `unexpected-outcome` success set

#### Scenario: Frontier completion is not a meta-defect
- **WHEN** a validated result stops at an exact frontier, a lower bound, or no clean shape without a new underlying fault observation
- **THEN** the harness emits no frontier-stop finding

#### Scenario: Cleanup-incomplete occurrence is not ready
- **WHEN** an actionable defect is observed but teardown, zero-active residue or locks, O1 sealing, or baseline equivalence is incomplete
- **THEN** the immutable occurrence may be retained but `ready_to_file` is false

### Requirement: Evidence uses one explicit root and raw-byte authority
Every evidence reference MUST be a closed object containing exactly one
canonical relative `path` and its lowercase `sha256`. That digest MUST be over
the file's raw bytes and MUST remain distinct from canonical JSON digests for
results, findings, payloads, and candidates.

Validation MUST receive exactly one explicit evidence root and MUST resolve
every evidence path below only that root. Ingest MUST use the explicit run
directory as its evidence root. The finding MUST NOT store the absolute root,
and the validator MUST NOT guess or fall back among a repository root, run
directory, process current directory, or any second root.

Every evidence path MUST begin with exact `evidence/` and contain at least one
component after it; the bare path `evidence` MUST fail. That subtree MUST be
immutable input and the harness MUST NOT write there. Harness-managed
manifests, ledgers, per-finding sources/indexes/bodies, candidates, locks, and
lifecycle outputs MUST remain outside it.

The explicit root MUST itself be a non-symlink directory. The validator MUST
reject absolute, empty, escaping, non-canonical-POSIX, duplicate, symlinked,
missing, non-regular, non-UTF-8, or mutated evidence; any artifact larger than
1 MiB (1,048,576 bytes); more than 4 MiB (4,194,304 bytes) across one finding;
and any raw-byte digest mismatch. Public sanitization MUST be rejection rather
than byte replacement: secret-bearing fields, credentials, wallet/account
values, cloud project, host, GPU or private-endpoint identities, values matched
by the pinned portable redaction policy, and unresolved placeholders in the
finding or evidence MUST fail before canonical hashing, ingest, or payload
rendering.

Privacy validation MUST be representation-aware. It MUST recursively inspect
every structured finding JSON key and string and MUST inspect raw UTF-8
evidence and rendered occurrence text in all of these representations:

- the exact source text;
- decoded JSON/YAML scalar spellings, including quoted escapes, aliases, and
  recoverable YAML fragments;
- the CommonMark-visible projection after repeated HTML-character-reference
  and Markdown punctuation-backslash-escape decoding; and
- the Unicode NFKC and combining-mark-stripped NFKD projections of each
  preceding representation.

Semantic scalar and CommonMark decoders MUST be composed to a fixed point under
closed visited-set, depth, projection-count, and byte-work limits. Exceeding a
limit MUST fail closed rather than accepting an additional uninspected layer.
Unicode Default_Ignorable code points, category `Cf` format and bidirectional
controls MUST be rejected outright. Privacy matching MUST also inspect the
corresponding `Cf`-stripped NFKC projection so an invisible control cannot
split a sensitive token. Unicode category `Cc` controls other than tab,
newline, and carriage return MUST be rejected. These projections MUST be used
only for rejection; validation MUST NOT normalize, decode, redact, or otherwise
replace the authoritative finding, evidence, or rendered bytes.

The case-insensitive unresolved-sentinel vocabulary MUST be exactly
whole-token `TODO`, `TBD`, `FIXME`, `XXX`, `CHANGEME`, `CHANGE_ME`,
`REPLACEME`, `REPLACE_ME`, and any `YOUR_*`; `<placeholder...>`, `{{...}}`,
and `${...}` forms; plus `example-`/`example_` followed by `id`, `sha`, `hash`,
`ref`, or `value`. The validator MUST apply it recursively to keys and string
values and to raw UTF-8 evidence and body text.

The configured redaction rules MUST be loaded from the exact pinned
`scm_contract_ref` and applied as reject-if-transform to finding, evidence, and
rendered occurrence bytes. Before building an index or payload from a validated
finding, the harness MUST re-read every evidence file and reverify its path,
raw-byte digest, mutation identity, and redaction rejection.

Public SCM MUST NOT claim a runtime exact-value denylist for bare private
projects, hosts, accounts, or endpoints. Private infrastructure MUST apply that
denylist and reject or sanitize before public validation/export. If its adapter
passes a known exact private value that does not match a portable public rule,
that is a `private-orchestration` defect; values matching portable public
field, pattern, or sentinel rules still fail public validation.

#### Scenario: Evidence validates below the one root
- **WHEN** every canonical relative evidence path identifies one unchanged regular file below the explicit evidence root and every raw-byte digest matches
- **THEN** the evidence may contribute occurrence authority without exposing the local root

#### Scenario: A second implicit root would make a path succeed
- **WHEN** an evidence path is absent below the explicit root but exists below the repository, current directory, or another caller-known root
- **THEN** validation fails rather than guessing a source

#### Scenario: Harness output cannot become finding evidence
- **WHEN** an evidence path names a manifest, ledger, source, index, body, candidate, lock, lifecycle output, or any path outside exact `evidence/`
- **THEN** validation fails before ingest can mutate the cited bytes

#### Scenario: Sensitive or mutable evidence is rejected
- **WHEN** a finding or referenced evidence contains a forbidden private value, uses a symlink or unsafe path, is not regular, changes during validation, or no longer matches its raw-byte digest
- **THEN** validation fails without producing sanitized replacement bytes

#### Scenario: Encoded private data cannot evade validation
- **WHEN** a private field or value is hidden by composed JSON/YAML scalar escapes, a YAML alias or fragment, nested CommonMark HTML entities or backslash escapes, a compatibility or combining-mark spelling, or a Unicode default-ignorable/`Cf` control
- **THEN** validation rejects the exact source bytes before hashing, ingest, or rendering rather than decoding or redacting them into a public artifact

### Requirement: Destination authority follows the reconciled first parent
Destination aliases MUST be exactly `simple-compute-market` and
`compute-market-internal-infra`, resolving respectively to
`arkhai-io/simple-compute-market` and
`arkhai-io/compute-market-internal-infra`. `public-product` and
`public-harness` MUST map only to SCM working branch
`feat/issue-discovery-harness` and upstream `dev`.
`private-orchestration` and `environment-provider` MUST map only to internal
infrastructure working branch `tools/agent-orchestration-scratch` and upstream
`main`.

The closed `observed_authority` object MUST contain exactly `run_id`,
`stage_id`, `working_branch`, `working_ref`, `upstream_branch`, `upstream_ref`,
nullable `inbound_merge_ref`, `reconciliation_epoch_id`, and `observed_at`.
Commit values MUST be exact lowercase 40-character SHAs. With a null inbound
merge, the exact upstream commit MUST occur on the working commit's
first-parent chain. With a non-null inbound merge, the merge MUST occur on the
working commit's first-parent chain, MUST have exactly two parents, and MUST
have the exact upstream commit as its second parent. General reachability or
ancestry through an unrecorded side parent MUST NOT satisfy the contract.

`observed_at` MUST be an exact UTC timestamp no earlier than the validated
result's `progression_ready_at`. For an SCM-destination finding, the working
ref's first-parent chain MUST additionally contain `scm_contract_ref`. A
private-destination finding MUST carry the same public contract ref but MUST
NOT claim cross-repository ancestry.

Every authority-bearing Git read MUST use an ambient-`GIT_*`-free local
environment, disable replacement objects, reject any nonempty graft namespace
or replace ref, and derive ancestry and parent order from raw commit-object
headers rather than a replace/graft-aware revision walker. Local history
overlays MUST fail closed before schema, redaction-policy, ancestry, or merge
authority is accepted.

#### Scenario: Direct first-parent authority is accepted
- **WHEN** the inbound merge is null and the exact upstream commit occurs on the exact working commit's first-parent chain
- **THEN** the destination authority may validate

#### Scenario: Recorded inbound merge is accepted
- **WHEN** the exact recorded two-parent merge occurs on the working first-parent chain and its second parent is the exact upstream commit
- **THEN** the destination authority proves upstream-into-working reconciliation

#### Scenario: Incidental ancestry is rejected
- **WHEN** the upstream or merge is only generally reachable, the merge has the wrong parent count or second parent, or branch/classification/destination mapping drifts
- **THEN** validation fails without treating incidental ancestry as reconciliation authority

#### Scenario: Local Git history rewriting cannot forge authority
- **WHEN** a replace ref, nonempty graft file, ambient Git object override, or rewritten revision walk would substitute a schema, policy, parent, or first-parent chain
- **THEN** validation fails rather than accepting locally rewritten Git authority

### Requirement: Local finding handoff cannot mutate GitHub
Ingest and packet replay MUST authenticate the explicit run root as one
current-user-owned, mode-0700 non-symlink directory and MUST hold its exact
open descriptor across the complete private-artifact critical section. They
MUST acquire exclusive locks on both that root-directory descriptor and the
persistent `.capacity-finding-ingest.lock` descriptor. The persistent lock
MUST retain one current-user-owned, non-symlink regular-file, single-link,
mode-0600 identity before and after the critical section. Every private path
operation MUST be descriptor-relative to the held root, and MUST reauthenticate
the root, every traversed ancestor, and the relevant destination against its
held device/inode, owner, type, link, and mode authority around each path
operation or publication. The root and persistent lock MUST be reauthenticated
before lock release. A replaced run-root pathname MUST be treated as a
different authority and MUST make the operation holding the prior inode fail
closed rather than redirecting its reads or writes.

These guarantees cover crash recovery, non-malicious filesystem drift, and
concurrent harness writers that honor both advisory locks. A mismatch observed
before a pathname mutation MUST prevent that mutation, and any mismatch
observed afterward MUST prevent the operation from reporting success. A process
running as the same effective user can bypass advisory locks and substitute a
leaf name inside a `linkat`, `unlinkat`, or `renameat2` syscall window. Because
those operations cannot be conditioned on a previously opened inode, adversarial
same-user interposition is outside this owner-only handoff boundary; the harness
does not claim that no intermediate filesystem mutation occurred in that case.

Under that held authority, ingest MUST create mode-0700 private directories and
mode-0600 create-once source, derived-index, and occurrence-body files keyed
by `finding_id`, and MUST NOT overwrite them. It MUST also preserve the
mode-0600 deterministic append-only `capacity-findings.jsonl` and
`capacity-finding-index.jsonl` ledgers. The same ID with the same canonical
source/index/body bytes MUST be an idempotent no-op; the same ID with changed
bytes MUST fail; the same derived fingerprint with a new ID MUST remain a
distinct occurrence.

`finding_sha256` MUST be SHA-256 over the source finding's canonical JSON
bytes, not the stable fingerprint or the input file's incidental whitespace.

Under that lock, ingest MUST semantically preserve unrelated fields in an
existing `manifest.json` and atomically maintain its capacity-finding
projection. If absent, the manifest MUST begin with schema version 2 and the
occurrence's `run_id`. Its `capacity_finding_authority` MUST contain exactly
`run_id`, `working_branch`, `working_ref`, `upstream_branch`, `upstream_ref`,
`inbound_merge_ref`, and `reconciliation_epoch_id`. Every occurrence ingested
into that run directory MUST have the same projection. Any existing direct
manifest `working_branch`, `working_ref` or `observed_ref`, `upstream_branch`,
`upstream_ref`, `inbound_merge_ref`, and `reconciliation_epoch_id` MUST agree
with their corresponding projected field.

The manifest's `capacity_findings` entries MUST be deterministically ordered by
`finding_id`. The entry produced for one occurrence MUST contain exactly
`finding_id`, `finding_sha256`, `fingerprint`, `destination_repo`,
`classification`, `scenario_id`, `scenario_sha256`, `profile_stage_id`,
`profile_stage_sha256`, `result_id`, `result_sha256`, `stage_id`, and
`observed_at`. The same occurrence projection MUST be a no-op and a changed
projection under the same ID MUST fail.
Only an absent projection key is a recoverable crash prefix. An explicitly
present null, non-object `capacity_finding_authority`, or non-array
`capacity_findings` value MUST be treated as malformed existing state and MUST
NOT be replaced.

Ingest MUST maintain `issue-lifecycle.jsonl` as a separate canonical,
append-only, mode-0600 ledger. This capability MAY append exactly one event per
occurrence, containing exactly `schema_version: 2`,
`candidate_kind: capacity-finding-v2`, `finding_id`, `finding_sha256`,
`fingerprint`, `state: detected`, `recorded_at`, `destination_repo`,
`classification`, `frontier`, `scenario_id`, `scenario_sha256`,
`profile_stage_id`, `profile_stage_sha256`, `result_id`, `result_sha256`,
`scm_contract_ref`, `observed_authority`, and `filing_readiness`.
`recorded_at` MUST equal the occurrence's `observed_authority.observed_at`; all
other values MUST be exact projections of the validated occurrence and derived
index. Reingest MUST treat one identical detected event as a no-op, reject a
duplicate or changed detected event, and reject any same-ID lifecycle suffix
that lacks its detected prefix. It MUST NOT append or claim a later
publication lifecycle state.

Every private directory MUST be a non-symlink directory owned by the effective
user with mode 0700. Every lock, source, index, body, manifest, and
ledger—including the lifecycle ledger—MUST be a non-symlink regular file owned
by the effective user, have link count one, and have mode 0600. Existing state
that violates any owner/type/link/mode invariant MUST fail closed. Atomic
create-once or replacement publication MUST make the new file durable and
fsync its containing directory before success. Newly created objects MUST
reach those exact modes regardless of the invoking process's umask; this MUST
NOT authorize repairing an unsafe pre-existing object.

Every create-once and replacement write MUST use a uniquely named mode-0600
temporary peer opened below the authenticated parent descriptor. The writer
MUST fsync the complete temporary file before publication. Create-once
publication MUST hard-link the temporary inode to the absent destination,
authenticate that exact destination inode and content, remove the temporary
under the supported concurrency boundary, and fsync the directory. Replacement
publication requires Linux `renameat2(RENAME_EXCHANGE)` support. It MUST
authenticate the expected destination immediately before atomically exchanging
it with the fsynced temporary, verify both exchanged identities and the
installed content, exchange back and fail on mismatch, then remove the
exchanged old destination and fsync the directory. No publication may report
success unless the final destination still matches the held temporary after
directory fsync.

While holding both locks and the run-root authority, ingest MUST recover
interrupted writer temporaries before read-only preflight and before another
write. Recovery MAY unlink only a temporary matching the harness's exact
managed name whose inode is a current-user-owned regular mode-0600 file with
link count one, or with link count two only when the other name is the exact
same-inode destination from the create-once post-link crash window. Recovery
MUST authenticate the pathname and held descriptor again immediately before
unlink and MUST fsync every directory it changes. Under the supported
compliant-writer model, this removes only the authenticated managed peer. A
symlink, wrong owner/type/mode/link count, unmatched destination, or otherwise
ambiguous temporary observed before unlink MUST remain untouched and fail
closed; an inconsistency observed afterward MUST prevent success. A shaped peer
whose destination is not one of the exact managed root names or the closed
per-finding JSON/body filename grammar MUST remain untouched.

If a crash leaves a valid durable prefix, the next identical ingest MUST verify
every existing create-once file and ledger line and append/create only the
missing exact source/index ledger, manifest projection, or detected-event
suffix. A mismatch MUST fail rather than be overwritten or silently repaired.

The generated human occurrence payload MUST be marker-free UTF-8 normalized to
exactly one trailing newline and MUST bind SHA-256 over those exact bytes. Its
create-once owner-only filename MUST be keyed by `finding_id`, not by the
stable fingerprint. A capacity-v2 candidate MUST identify itself as
`capacity-finding-v2`, bind the finding ID and canonical finding SHA-256,
SCM-derived fingerprint, exact destination/branch authority, payload path and
SHA-256, and `guard-issue-fix-publication` as the required publication
capability. Readiness MAY be carried as derived local state, but MUST NOT claim
a filed, updated, reopened, fixed, verified, or closed lifecycle state.
Agent-controlled `summary`, `defect_semantics.stable_signature`, `expected`,
and `actual` prose MUST appear only beneath fixed harness headings as
four-space-indented literal CommonMark blocks. The renderer MUST NOT interpret
those strings as headings, lists, links, HTML, fenced-block delimiters, or any
other active Markdown syntax, and MUST apply the same representation-aware
privacy rejection to the completed payload bytes before accepting their
digest.

Before emitting or regenerating any capacity-v2 candidate, packet replay MUST
hold the same validated lock and reauthenticate the explicit non-symlink run
root, source/index/body artifacts and ledgers, manifest projection, immutable
evidence, and one exact detected lifecycle prefix for every persisted index.
The exact file and directory identities, metadata, and bytes used for final
candidate derivation MUST form one replay snapshot that remains unchanged
through the final pre-output boundary. Any missing, duplicate, changed, unsafe,
or non-canonical component MUST fail before the candidate directory or file is
created.

Issue surfaces MUST select legacy or finding-v2 handling once while holding the
run-root descriptor lock. The persistent lock file by itself MUST NOT select
finding v2, because it may be durable residue from a preflight failure before
any occurrence state was published. A v2 index or per-finding artifact
directory MUST select finding v2 and MUST require the already-existing
authenticated persistent lock; replay MUST NOT create a missing lock. A
marker-free mode-0700 legacy run MUST publish any regenerated candidate
directory/file at mode 0700/0600 while holding that root lock. In a selected v2
run, a non-capacity failed-phase candidate MAY retain legacy behavior, but its
body read MUST use the held private authority. A selector matching any durable
v2 finding ID or fingerprint MUST be rejected by legacy mutation methods from
the canonical index before packet regeneration or output writes.

Legacy issue creation, including its `force` and dry-run paths, MUST reject a
capacity-v2 candidate before constructing or executing `gh`. Legacy lifecycle
transition and fix-proposal surfaces MUST reject it before any file write,
subprocess, or external access. Legacy non-capacity candidates retain their
existing behavior.

The separate `guard-issue-fix-publication` capability exclusively owns
`scm.finding-publication.scope.v1`,
`scm.finding-publication.occurrence.v1`, and
`scm.finding-publication.fix-pr.v1` markers, final rendered-body digest,
paginated GitHub reconciliation, mutation journals, credentialed issue/PR
actions, and verified post-mutation lifecycle facts. This capability MUST NOT
precompute, imitate, or claim any of those authorities.

#### Scenario: Immutable ingest is idempotent
- **WHEN** identical canonical finding bytes with an existing `finding_id` are ingested again
- **THEN** no second occurrence or lifecycle fact is appended

#### Scenario: Crash-prefix recovery preserves exact bytes
- **WHEN** ingest resumes after only a valid create-once file, source/index ledger prefix, manifest projection, or detected-event prefix became durable
- **THEN** it verifies all existing authority and bytes, writes only the missing exact suffix under the lock, and refuses any mismatch

#### Scenario: Writer temporary crash windows are authenticated
- **WHEN** a prior writer stopped before publication or after linking a create-once destination but before removing its temporary name
- **THEN** under the compliant-writer model the next locked ingest removes and directory-fsyncs only the authenticated one-link temporary or exact same-inode two-link peer, while any unsafe or ambiguous state observed before unlink remains untouched and fails closed

#### Scenario: Run-root or lock identity cannot be swapped
- **WHEN** the run-root pathname, an ancestor, a leaf destination, or the persistent lock pathname changes while ingest or packet replay holds its descriptors
- **THEN** root or ancestor replacement cannot redirect descriptor-rooted operations, every observable leaf drift is rejected before success, writers honoring the locks remain serialized, and a replacement root is rejected as different authority

#### Scenario: Same-user syscall interposition is outside the handoff boundary
- **WHEN** a same-effective-user process bypasses both advisory locks and substitutes a leaf inside a `linkat`, `unlinkat`, or `renameat2` syscall window
- **THEN** any detected mismatch prevents success, but the harness does not claim zero intermediate mutation because the pathname syscall cannot be conditioned on the previously held inode

#### Scenario: Run-manifest authority cannot drift
- **WHEN** a new occurrence's run, branch, ref, inbound-merge, or reconciliation-epoch authority conflicts with the run manifest's direct or projected authority
- **THEN** ingest fails without overwriting the manifest or appending source, index, or lifecycle history for the conflicting occurrence

#### Scenario: Detected lifecycle is separate and idempotent
- **WHEN** an identical occurrence is reingested after its exact detected event exists in `issue-lifecycle.jsonl`
- **THEN** no lifecycle line is added, while a duplicate, changed, or suffix-without-detection history fails closed

#### Scenario: Same defect is a new occurrence
- **WHEN** a different `finding_id` has the same SCM-derived fingerprint and valid distinct occurrence evidence
- **THEN** ingest retains it separately rather than collapsing occurrence identity

#### Scenario: Local packet remains marker-free
- **WHEN** a validated occurrence produces its human payload and capacity-v2 candidate
- **THEN** the payload SHA is exact but no publication, occurrence, fix-PR, final-body, issue, or PR marker is minted

#### Scenario: Agent prose remains literal
- **WHEN** summary, stable-signature, expected, or actual prose contains text that would otherwise be parsed as a CommonMark heading, list, link, HTML block, or fenced-block delimiter
- **THEN** the payload represents the text only inside an indented literal block beneath a fixed harness heading

#### Scenario: Packet replay requires detected lifecycle authority
- **WHEN** the lifecycle ledger is missing, unsafe, non-canonical, duplicated, or no longer exactly projects every persisted finding index
- **THEN** packet replay fails before creating or replacing candidate output

#### Scenario: Legacy mutation rejects capacity v2
- **WHEN** create with or without force/dry-run, lifecycle transition, or fix proposal receives a capacity-v2 candidate
- **THEN** it fails before a `gh` command, subprocess, external access, or mutation while non-capacity legacy behavior remains unchanged

### Requirement: Public contract preparation has no live side effects
The executable scope of this change MUST remain preparatory. Pinned validation,
capture-only mock composition, finding ingest, packet generation/replay,
strict validation, and documentation promotion MUST NOT fund or use wallets,
start a live buyer or seller action, publish a listing, emit a purchase,
provision or destroy a VM, access KVM/Ansible/GPU resources, create cloud
resources, execute cleanup against live state, or mutate GitHub. Mock
composition MUST retain an empty live-resource ledger. The portable schemas MAY
describe later real qualification and measured evidence, but only separately
authorized private campaign infrastructure MAY perform those effects after it
pins the pushed public contract.

#### Scenario: Preparatory validation cannot become a live run
- **WHEN** an operator validates, hashes, ingests, renders, or replays a capacity artifact while preparing this contract
- **THEN** the command may read pinned/local artifacts and write owner-only local handoff state but performs no market, cloud, host, GPU, wallet, GitHub, or live cleanup action

#### Scenario: Capture-only composition remains resource-empty
- **WHEN** the public mock composition path rehearses portable buyer and seller actions
- **THEN** it targets only the capture boundary, retains an empty live-resource ledger, and grants no authority for a live qualification or measured campaign
