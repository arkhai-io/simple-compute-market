## Context

See `proposal.md` for motivation. The branch reconciles current `dev` with a
portable issue-discovery layer, but that layer predates the durable
fulfillment/capacity cutover and the final campaign boundary:

- scenario schema v1 equates successful capacity with listing count;
- two current files encode G2 without verified two-GPU authority;
- no portable role or frozen-action receipt proves what an agent did or whether
  it remained alive through release;
- success/scarcity expectations are integer assertions without a durable,
  independent correlation model;
- finding v1 trusts a producer-supplied fingerprint and lacks upstream,
  reconciliation, evidence-hash, and durable-fulfillment authority.

The public repository can define and validate portable semantics, but cannot
authenticate private Codex credentials, wallets, cloud projects, hosts, GPUs,
or a distributed campaign generation. Private infrastructure owns those
authorities and consumes the public contracts at one exact SCM commit.

## Goals / Non-Goals

**Goals:**

- Make one public schema family authoritative for portable scenario, role,
  frozen-action, oracle-result, evidence-class, and finding semantics.
- Make "agent-driven" mechanically distinguishable from readiness probes and
  controller-only emission.
- Align result correlation with current durable VM fulfillment without exposing
  physical placement to buyers.
- Make scenario and finding identity reproducible from exact committed bytes
  and normalized public semantics.
- Preserve a clean executor seam so the same contracts can later be used by a
  cloud or Tekton runner without changing their meaning.

**Non-Goals:**

- GitHub mutation, issue occurrence reconciliation, and draft-PR opening; those
  have a separate change and credential boundary.
- Private execution envelopes, credentials, wallets, topology, generation
  fencing, cost limits, unredacted evidence, watchdogs, or cleanup execution.
- Running real qualification or measured workloads as part of this public
  implementation.
- Restoring obsolete direct provisioning clients or physical-placement fields.

## Decisions

### Use a clean schema-v2 authority boundary

Scenario, role/action/result, and finding contracts use explicit version 2
schemas with closed object shapes. Current commands accept v2 for new campaign
authority. Historical v1 artifacts remain verifiable only by checking out their
pinned historical SCM commit and using the code/schema that commit contained.

This avoids a mixed validator whose optional fields would allow a v1 artifact
to look like v2 authority. The compatibility cost is acceptable because these
are pre-release campaign artifacts rather than marketplace wire or persistence
records.

**Rejected alternative:** incrementally add optional v2 fields to the v1
schema. That cannot fail closed when authority, evidence hashes, or substantive
role proof is absent.

### Resolve scenario authority through Git, not the ambient filesystem

The public tool exposes a pinned-path validation operation that accepts the
repository root, exact 40-character commit, and known repository-relative
scenario path. It verifies:

1. the root is the expected SCM worktree and the commit exists;
2. the path is under the capacity-scenario root, tracked as a regular file at
   that commit, and not a symlink;
3. worktree bytes equal the blob at the commit even if an index flag hides
   drift;
4. schema and semantic validation pass; and
5. the canonical JSON digest is reproduced.

Canonical bytes are JSON encoded as UTF-8 with recursively sorted object keys,
compact separators, `ensure_ascii=false`, non-finite numbers rejected, and one
trailing newline. The same helper is used for every portable artifact identity
so Python implementation details cannot create different authority.

Plain in-memory validation remains useful for unit tests but cannot itself
grant pinned scenario authority.

**Rejected alternative:** accept any operator-supplied local JSON path and
record its digest. A digest proves bytes, not that those bytes are the reviewed
scenario at the pinned public ref.

### Separate market choices from physical capacity

Schema v2 has distinct logical fields for listing topology and independently
assignable whole-GPU capacity. `listing_count` and seller distribution describe
market choices; `independently_assignable_gpus` bounds expected simultaneous
success. Semantic validation uses the latter for success counts.

Scenario shapes do not carry evidence or admission state. A separate
profile-stage registry binds a pinned shape to an ordered stage, the exact
`execution_boundary` enum, and the orthogonal `actor_trigger` enum, and the
result repeats that binding. This lets mock preparation, deterministic
reference, and Q0 reuse identical B1/S1/G1 scenario bytes without allowing one
result to impersonate another. A mock binding rehearses actions against a
real-target scenario and cannot satisfy its real-provisioning oracle.

Qualification uses a versioned, exact G1 profile-stage sequence. The
deterministic controller is non-counted orchestration and cannot supply the O1
independent-observer receipt or oracle sources:

1. `observer-probe`, with no request or public scenario and exact
   `readiness`/`none` authority;
2. `b1-s1-g1-reference`, deterministic B1/S1/H1/O1, excluded from agent
   evidence;
3. B1/S1/H1/O1/L1/R1/G1;
4. B2/S1/H1/O1/L1/R2/G1;
5. serialized reuse A with B1 counts;
6. serialized reuse B with B1 counts after baseline equivalence;
7. B2/S2/H1/O1/L2/R2/G1.

The private observer probe has no request scenario. G2 files are removed from
the current registry and remain only in history. A later G2 series requires a
new reviewed contract rather than a runtime inventory branch that silently
admits it.

Measured stages use `real-measured`/`agent-triggered` in an exact dynamic order:
Q0 B1 and buyer B2/B4/B8; immediately selected B3/B5/B6/B7 adjacent buyer
refinement; an independently derived buyer-frontier receipt; reuse A, which
binds that receipt, then reuse B, which binds both reuse A and the same receipt;
and finally B2/S2 and the admitted B4 seller sequence S2, conditional S4, then
S3 only if needed to refine a passing/failing S2/S4 bracket (or as the bounded
fallback when S4 is not admissible). Every seller result binds the buyer
receipt, the clean reuse-B baseline, and the immediately preceding seller
result. The pre-Q0 ref carries every integer B1…B8/S1 shape plus B2/S2 and
B4/S2/S3/S4, so deterministic refinement never edits the campaign after Q0.
Outcomes are unordered cardinalities over request IDs; no buyer is
predesignated to win. Portable counts do not grant admission, and exhausting
the envelope first produces only a lower bound.

**Rejected alternative:** infer GPU capacity from the number of listings. A
seller can publish multiple truthful market choices backed by one globally
fenced GPU, so listing count is not a physical-capacity claim.

### Represent roles and actions with discriminated receipts

Add closed public schemas for:

- role plans and receipts with `buyer`, `seller`, `host-operator`, and
  `observer` variants;
- frozen request actions and one-shot results;
- independent capacity observations/results.

Common role fields bind contract version, role/actor logical identity,
non-secret isolated-identity fingerprint, exact SCM ref, instruction path/hash,
exact scenario/profile-stage identity and digest, prepared action or
configuration hash, and ordered lifecycle timestamps. The prepared-authority
hash is the canonical SHA-256 of the closed nested role-specific plan, so it
has one reproducible, acyclic referent rather than being an opaque producer
assertion. The complete role-plan artifact names every action ID the role will
own and the digest of that action's exact prepared intent. The prepared intent
includes the logical selection, portable VM/KVM/Ansible terms, service or
listing binding, private concrete-payload binding, pinned wrapper, expected
oracle, and actor-invocation capability, but excludes release/policy fields so
the graph remains acyclic. A real pre-release concurrency policy freezes every
complete role-plan digest and every prepared-action digest. Frozen actions then
bind the complete role plan, the same prepared intent, and the release/policy;
action results bind the frozen-action digest, and the terminal role receipt
binds the ordered result digests.
Every real role receipt also binds the common release and concurrency-policy
ID/digest, including the actionless host and observer roles; a standalone
observer probe or mock receipt binds its exact non-campaign release and null
policy. This prevents valid cleanup or observation evidence from being replayed
across waves.

For a seller-bearing stage, the sole H1 plan and every seller plan carry the
same typed `topology_authority_binding`. The concurrency-policy validator
compares those exact values before release and fails closed if any seller
consults a disjoint authority. Because the policy freezes every complete plan
hash and each frozen seller action binds that plan hash plus the policy, seller
actions inherit the shared topology fence without adding a cyclic
future-result reference. Each terminal seller receipt repeats its plan's
binding, and the capacity result independently repeats the sole H1 binding.
This is the public opaque proof that all one-GPU sellers consult one globally
fenced view; private infrastructure retains the host, GPU, allocator, and
fence identities.

Role-specific sections prove the documented preparation appropriate to that
role. A host-operator binds the public instruction, private G1/topology and
baseline authority through the typed privacy-preserving bindings,
KVM/Ansible readiness, teardown plan, and liveness through cleanup. Portable
receipts contain no raw wallets, project/host/GPU identities, private endpoints,
credentials, or executor-local paths.

Buyer steps separate preparation required for every request from
success-contingent guest verification. Every buyer proves quickstart
install/build, wallet/SSH preparation, endpoint and balance checks, listing
discovery, and exact request preparation. Only a buyer whose independent
outcome is `vm-succeeded` additionally proves guest SSH/resume and the
Git-pinned compiled CUDA vector-add workload; an expected capacity-refused
buyer records no fabricated guest step. Seller steps cover install/build,
configuration, wallet/publication preparation, distinct service start, exact
listing publication, and observation liveness. The receipt stores typed step
outcomes and public digests, not their private values.

Scenarios name only logical actor/listing/request slots. Private infrastructure
maps those one-to-one to live seller/listing identities and exposes only the
logical projection and a closed typed binding containing method, field-specific
domain, and one 256-bit value. Its method is either domain-separated
HMAC-SHA-256 under a per-campaign private key or an opaque cryptographically
random surrogate stored with the native proof. The private executor allocates
distinct service bindings and one distinct listing binding per logical
seller/listing pair. A listing's opaque binding may be allocated before
publication; the seller publication atomically seals its owner-only proof to
the one minted live listing, and every buyer later resolves that unchanged
binding. Raw hashes of enumerable private identifiers are invalid. Frozen
wrappers recheck the applicable typed binding against the native private proof
immediately before service start, publication, or purchase.

A role receipt is accepted only alongside an action/result receipt whose actor
and lifecycle timestamps show liveness through the barrier. The public
validator checks structure and correlation; private infrastructure proves
process identity and supplies the secret-bearing execution context.

An aggregate actor-set receipt binds the exact declared cardinalities,
overlapping lifetimes, a pre-release concurrency-policy digest, independently
observed monotonic offsets relative to the common release, a typed native clock
evidence binding, and controller queue/throttle observation. Skew is calculated
without integer truncation from those common-clock offsets and cannot be chosen
after the wave. Every action interval must also remain inside its owning
actor's independently observed lifetime. This prevents wall-clock
disagreement, post-exit actions, or eight serial Codex processes from
satisfying a B8 contract.

A failed actor invocation, rejected one-shot action, local queue, controller
throttle, overlap failure, or skew failure is still a valid negative
observation when its structure, authority, and independent timing are intact.
The validator retains that receipt as agent provenance and records why the load
generator failed; it does not promote the row into a capacity frontier. This
distinguishes evidence that the agent-driven experiment ran and found a fault
from evidence that the generator successfully applied the intended load.

**Rejected alternative:** one generic readiness receipt with arbitrary
key/value evidence. It cannot make missing role work or an early actor exit
detectable.

### Keep deterministic execution behind an agent-invoked one-shot wrapper

The controller may freeze exact request or publication bytes and the
deterministic driver may perform the low-level operation, but the initiating
agent must invoke a pinned wrapper while its Codex process is still active.
Buyers own purchase; sellers own service start and exact listing publication.
The portable action binds the wrapper path/hash, sanitized portable-payload
hash, scenario, logical seller/listing selection, privacy-preserving
service/listing and private concrete-payload bindings, actor-invocation
capability, prepared-action digest, release, attempt, expected result schema,
and an independent-oracle-authority artifact.
That closed authority artifact binds the exact stage, result schema, observer
plan when real evidence is allowed, and whether the boundary is capture-only;
its canonical digest is the action field's exact referent. For a real action,
that observer-plan digest must occur exactly once in the same frozen policy's
role-plan authority set. It cannot bind a result that does not yet exist. The
terminal result binds the canonical action digest and release, and only then
computes its own canonical digest.

The wrapper contract is one-shot: it verifies frozen authority immediately
before emission, emits exactly once, and returns a typed result. Changed bytes,
duplicate release, attempt greater than one, wrapper substitution, or early
actor exit fail closed. The wrapper-fixed action kind is a single-use argument
that a caller cannot override. A rejected unauthorized-retry receipt records the
attempted value greater than one while a successful emission is always attempt
one; a duplicate-release receipt likewise records more than one claim and zero
emissions. The private implementation may use a pipe, socket, or file-backed
release channel as long as it preserves those semantics. The public
capture-only sink atomically installs one owner-only record containing the
claim, canonical logical payload, and first terminal result—emitted or
rejected—before it materializes the requested result file. A pre-emission
rejection consumes that one-shot release, so corrected inputs cannot be
resubmitted as a new attempt one. If result materialization is interrupted,
the next invocation recovers that same first result; it cannot reinterpret the
durable record as a new emission. Recovery accepts only the
exact closed canonical record for an emitted, live, attempt-one, single-claim
result or a schema-valid typed first rejection and requires any existing output
to match those bytes; corruption or a conflicting output fails hard.

The typed public actor-invocation capability is only a portable correlation
referent. SCM cannot authenticate that a Codex process actually owns it.
Private infrastructure must issue and verify the capability against the live
Codex process/session and authenticated release channel. A public mock capture
therefore records `portable-binding-only` and
`private_actor_ownership_verified: false`; it proves contract composition and
zero live effects, not private process authenticity.

Capture-only composition uses the separately tracked
`tools/issue-discovery/config/capacity/profile-stages/b1-s1-g1-mock.json`
stage. It is not a member of the exact qualification/measured registry and
therefore cannot authorize a campaign row. It reuses the pinned B1/S1/G1
scenario only to prove seller-owned service/publication and buyer-owned request
actions through the mock adapter, with an empty live-resource ledger,
`execution_boundary=mock`, and no real oracle or capacity claim.

**Rejected alternative:** let Codex approve a hash and exit before a controller
thread emits it. That remains useful deterministic-driver evidence but is not
agent-triggered load.

### Freeze outcome evaluation before Q0

A closed evaluation-policy artifact is frozen before Q0 and binds the exact SCM
ref, both the canonical and raw digests of the pinned profile registry, a typed
common-clock evidence binding, request-processing, provisioning-queue, Ansible
service, and terminal-observation limits, plus the exact definitions of all
five capacity frontiers. The terminal-observation timeout cannot be shorter
than the request-processing SLO.

Every reference, qualification, and measured result binds the same validated
policy by ID and canonical digest. The policy timestamp must precede the
stage's independently observed release. This makes a timeout, a frontier
classification, and a pass/fail decision reproducible instead of allowing
thresholds or frontier meanings to be selected after seeing Q0.

An individual public command proves equality to its supplied policy. Private
campaign assembly must present one policy ID/hash across reference,
qualification, and measurement. A second closed reference policy freezes
strictly after that policy and before controller release, binding the exact
reference stage/scenario, evaluation policy, release, clock, non-counted
controller, O1/H1 plan IDs/hashes, and per-request invocation schedule. The
reference result binds its exact O1/H1 receipt IDs/hashes.

**Rejected alternative:** store thresholds only in private runner flags or add
them to the result after execution. Neither creates reviewed, immutable
pre-Q0 authority, and both make two validators capable of classifying the same
observations differently.

### Evaluate outcomes from an independent durable correlation

The result schema has closed, discriminated `vm-succeeded`,
`capacity-refused`, and `fault` variants. A normalized public
`deal_reference` keeps logical request, seller/listing, typed runtime binding,
negotiation, and escrow digests in the storefront domain. Success joins that
carrier to `capacity_reservation_id` and then separately to `fulfillment_id`,
the Settlement Record keyed by the reservation and its typed selected
Settlement Resource proof, `provisioned_resource_id`, the real KVM/Ansible
whole-device passthrough observation, the Git-pinned compiled CUDA guest
exercise, and teardown. Generic fulfillment does not gain commercial
identity, and there is no invented buyer-visible Settlement Resource ID.
`allocation_id` and `provisioning_job_id` remain optional diagnostics.

`capacity-refused` is derived from independent per-site capture proving every
eligible attempt in the final escrow-scoped atomic reserve returned routine
`reservation: null`, with zero errors, skips, or missing responses, plus null
durable capacity/fulfillment/output identities, terminal commercial/
failure-policy compensation, and zero active residue. Aggregate null alone is
not scarcity because current aggregation can swallow site errors. The
pre-settlement `capacity_hold_unavailable` event is explicitly nonterminal and
never sufficient. Generic failures, unknown reasons, uncompensated state, and
timeouts are faults. Aggregate validation applies unordered per-request
cardinalities. A double allocation is retained as the independently derived
`double-allocation` fault on the stage assessment while preserving the exact
per-request observations; it fails correctness and remains eligible for issue
discovery rather than making the evidence disappear as an invalid document.

Every final or partial atomic observation first proves exact deal, clock,
request-interval, eligible-site-set, distinct site-binding, and unique-attempt
authority. Routine-null, reservation-created, error, and missing/skipped
attempts have closed mutually consistent field combinations; no variant may
hide a created reservation. Elapsed time equal to the terminal timeout has
reached the deadline: `elapsed >= timeout` is a timeout fault.

Every request carries invocation and terminal offsets. The aggregate
independent observation repeats those offsets for every exact request under one
typed common clock, and each request binds the exact native evidence used by
its matching aggregate timing and O1 observation.
O1's terminal receipt seals the canonical hash of every exact request outcome
and of the complete cleanup object. The aggregate observation time must fall
inside both the stage and O1 receipt lifecycles. O1 and H1 cannot complete
before the cleanup they seal or attest, and the next-stage fence is the later
of their completed evidence timestamps.

The deterministic `real-reference` path has no agent actor set. Its non-counted
controller binds a reference execution proof, frozen reference policy,
release, common clock, and independently captured per-request timing, while
exactly one actionless O1 and one actionless H1 bind that reference policy and
release. O1 remains the independent author of request-outcome and cleanup
seals; the controller cannot supply either receipt or become O1.

The observation schema carries logical or redacted correlation identifiers.
Private infra retains unredacted provider/host evidence and maps it to these
portable bindings.

Every stage result also binds a typed terminal snapshot, teardown,
zero-active-residue proof, and baseline-equivalence result. Reversible
host/cloud/runtime state is an exact nine-component partition: capacity
reservations/leases, Settlement Resources, fulfillment/provider jobs, VMs,
disks, networks, Ansible processes, GPU assignments, and the intended
listing/service set. Append-only/accounting state is an exact six-category
partition: deal, Settlement, request, and escrow/claim history, transaction
fees, and wallet accounting. Each category binds expected and observed native
evidence and must be reconciled without an active lock or unexplained value.
No later stage can start from a result that is merely terminal without both
partitions, all residue counters, H1, and O1 cleanup sealing being clean.

**Rejected alternative:** trust the buyer/emitter terminal status. Neither
actor owns aggregate allocation, VM, or GPU truth.

### Model reuse as two baseline-fenced stages

Reuse A and B are distinct stage/scenario identities even though both have B1
counts and may reuse logical `request-1`. Measured reuse A binds the completed
buyer frontier; qualification reuse carries null frontier authority. Reuse B
starts after A's `progression_ready_at`, binds A's result/baseline, and
preserves that frontier authority. B uses a distinct result ID, deal,
negotiation/escrow references, reservation, fulfillment, and provisioned
resource. Reuse requires correct success, teardown,
and baseline equivalence, but does not require either request to meet the
request-processing SLO: safe physical release and reuse is independent of
latency. The public validator proves ordering and correlation; private infra
owns baseline capture and verifies its native evidence.

**Rejected alternative:** one scenario with a fractional or repeated count.
That hides the cleanup barrier and cannot prove that a released GPU was safely
reused.

### Report independent frontiers instead of one capacity number

The measured result has separate request-processing, simultaneous-fulfillment,
provisioning, correctness, and load-generator frontiers. Request processing is
about all offered requests reaching expected outcome kinds inside its SLO;
fulfillment is independently observed concurrent successful VM/GPU state;
provisioning splits queue wait from Ansible service time; correctness requires
the full oracle plus cleanup; and load generation requires live overlapping
actors with bounded skew and no local queue.

Buyer search starts B1/B2/B4/B8 and immediately runs any selected adjacent
B3/B5/B6/B7 refinement. Selection uses request processing plus provisioning
plus correctness, while load-generator failure censors the product observation
rather than being interpreted as SCM failure. The resulting typed
buyer-frontier receipt binds the exact ordered result IDs/hashes, stage
observations, retained counts, five separately derived frontiers, and whether
the product boundary is exact, a lower bound, or has no clean shape. It also
binds the one exact `topology_authority_binding` shared by every bound
B1/B2/B4/B8 and selected refinement result.

Only after that receipt may reuse A run, followed by reuse B. Seller search
then starts at B2/S2 using the clean reuse-B result as its baseline. Each seller
result binds the buyer-frontier receipt, reuse-B result, H1-derived topology cardinality,
and the immediately prior seller result by ID/hash, and starts strictly after
that predecessor's `progression_ready_at`. Reuse-B H1 pre-freezes and attests
seller/service admission without referring to the future reuse-B result; reuse
B binds the H1 receipt and seals the derived admission, and downstream seller
results bind reuse B. Callers cannot inflate the admission. An admitted B4/S2 follows; a passing B4/S2 advances
to conditional B4/S4, and failed S4 is refined with B4/S3. When S4 is
inadmissible, an admitted S3 may be the bounded final probe. Failed S2 already
gives the adjacent S1/S2 bracket. If the frozen envelope or generator saturates
first, the largest clean result is explicitly a lower bound.

Measured reuse A must equal the buyer-frontier topology authority, and reuse B
must preserve A's value. Qualification reuse has null frontier authority but
still preserves topology A→B. Every measured seller result must equal the
frontier and reuse-B topology and the immediately prior seller result's
topology. The campaign is therefore one topology-fenced chain, not a sequence
of individually plausible rows from different physical-capacity views.

**Rejected alternative:** call the greatest buyer count "capacity." Offered
demand can exceed fulfillment, processing, provisioning, or generator
capacity, and collapsing them would hide which system actually saturated.

### Make SCM own normalized finding identity

Finding v2 removes producer authority over `fingerprint`. The producer supplies
sanitized defect semantics: destination, classification, frontier, canonical
scenario identity/hash, expected outcome, actual fault category, normalized
lifecycle phase, failure code, and stable normalized signature. SCM normalizes
those fields, calculates the stable fingerprint, and verifies any rendered
packet/action repeats it. `finding_id` is separately the immutable identity of
one occurrence.

Occurrence authority—bounded run/stage IDs, exact working and upstream branch
and SHA, nullable inbound merge ref, reconciliation epoch, observation time,
profile/result identities and hashes, concrete lifecycle correlations, and
repository/run-relative `{path, sha256}` evidence objects—is retained but
excluded from stable defect identity. SCM findings bind
`feat/issue-discovery-harness` to `dev`; private findings bind
`tools/agent-orchestration-scratch` to `main`. This preserves cross-run and
cross-SHA deduplication without collapsing different scenario or destination
semantics.

Classification distinguishes public product, public harness, private
orchestration, and environment/provider faults. Expected independently proven
`capacity-refused` is a result, never a finding; missing compensation or
cleanup is a fault. No finding is ready to file until teardown, zero-active
residue, and baseline equivalence are complete; environment/provider evidence
remains separately dispositioned rather than mislabeled as product or harness
code.

Evidence references are closed repository/run-relative `{path, sha256}`
objects. Public redaction and deny rules run before ingestion and again before
rendering.

**Rejected alternative:** accept a producer-supplied fingerprint and merely
check its syntax. That permits accidental or malicious collision and makes
deduplication policy private rather than portable.

### Keep publication mutation in a separate capability

This change ends at validated findings and portable proposal/action inputs. It
does not call GitHub. The follow-on `guard-issue-fix-publication` change owns
issue occurrence idempotency, partial-mutation reconciliation, and draft-PR
actions. Private infra remains the credentialed mutation authority in both
cases.

This separation allows role/scenario/oracle contracts to be implemented and
qualified without granting or testing GitHub write authority.

### Promote accepted behavior before archive

Normative behavior is promoted to a new permanent `capacity-testing` capability
and the existing `test-compatibility` capability. Durable rationale goes to
their architecture companions, the public/private test-authority split goes to
repository architecture, and the capability index links them. Operational
issue-discovery docs change only after implementation.

## Risks / Trade-offs

- **[Schema-v2 breadth can produce a large first implementation]** → Land
  scenario, roles/actions, oracle, and finding behavior in independently
  validated commits under this one coherent capability; do not couple GitHub
  mutation.
- **[Portable receipts could accidentally carry private identity]** → Use
  closed schemas, explicit non-secret fingerprints, denylisted field names and
  values, and negative redaction fixtures.
- **[Git path checks can differ across platforms]** → Specify Git object/type
  semantics, not Unix inode behavior alone, and test symlink, tracked-mode,
  hidden-index-drift, and path traversal cases in temporary repositories.
- **[An allowlist may misclassify a new capacity terminal reason]** → Treat
  unknown reasons as faults; extend the public allowlist only through reviewed
  contract changes.
- **[Deterministic IDs could leak private values through hashing]** → Hash only
  normalized public logical identities or salted private-to-public mappings;
  never publish an unsalted digest of a small sensitive identifier space.
- **[Removing G2 files reduces apparent coverage]** → Record them as
  unqualified historical artifacts and require fresh two-GPU authority before
  introducing a replacement profile.
- **[Current dev has unrelated strict OpenSpec failures]** → Validate each new
  change independently and record the inherited global failures; do not modify
  unrelated active changes inside this campaign.

## Migration Plan

1. Add and strictly validate the two active delta specs and this design.
2. Implement schema-v2 scenario authority and replace the current scenario
   registry with the exact G1 qualification and measured scenario set.
3. Add role/action/result schemas and validators, then switch private
   preparation to consume them only after the public commit is pushed.
4. Add durable oracle and finding-v2 behavior; keep v1 artifacts readable only
   from historical refs.
5. Promote permanent specs and architecture, update operational docs, run the
   complete package and cross-repository contract suites, synchronize, and
   archive this change.

Rollback before private consumption is a revert of the bounded public commits.
After a private contract pins v2, rollback requires abandoning that run epoch
and pinning a new exact public/private SHA pair; no adapter converts v2 live
authority back to v1.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Pinned scenario authority and schema-v2 VM/GPU semantics | `openspec/specs/capacity-testing/spec.md` — scenario authority and VM-only scope |
| Listing topology is distinct from independently assignable physical capacity | `openspec/specs/capacity-testing/architecture.md` — scenario and topology model |
| Exact one-GPU qualification and measured evidence profiles | `openspec/specs/capacity-testing/spec.md` — profile stages and execution/trigger evidence authority |
| Substantive role receipts and agent-triggered one-shot actions | `openspec/specs/capacity-testing/spec.md` and `architecture.md` — actor/action model |
| Independent durable VM outcome correlation and reuse | `openspec/specs/capacity-testing/spec.md` and `architecture.md` — oracle and lifecycle model |
| SCM-owned defect fingerprint and immutable sanitized finding evidence | `openspec/specs/capacity-testing/spec.md` — findings |
| Evidence labels match exercised boundaries | `openspec/specs/test-compatibility/spec.md` and `architecture.md` |
| Public/private capacity-test authority split | `docs/development/ARCHITECTURE.md#testing-strategy` |
| Capability ownership and navigation | `openspec/specs/README.md` |
