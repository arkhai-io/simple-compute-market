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
refinement; reuse A/B; then, after the external buyer-frontier receipt, B2/S2
and the admitted B4 seller sequence S2, conditional S4, then S3 only if needed
to refine a passing/failing S2/S4 bracket (or as the bounded fallback when S4
is not admissible). The pre-Q0 ref carries every integer B1…B8/S1 shape plus
B2/S2 and B4/S2/S3/S4, so
deterministic refinement never edits the campaign after Q0. Outcomes are
unordered cardinalities over request IDs; no buyer is predesignated to win.
Portable counts do not grant admission, and exhausting the envelope first
produces only a lower bound.

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
prepared action or configuration hash, and monotonic lifecycle timestamps.
Role-specific sections prove the documented preparation appropriate to that
role. A host-operator binds the public instruction, private G1/topology and
baseline authority through the typed privacy-preserving bindings,
KVM/Ansible readiness, teardown plan, and liveness through cleanup. Portable
receipts contain no raw wallets, project/host/GPU identities, private endpoints,
credentials, or executor-local paths.

Buyer steps cover quickstart install/build, wallet/SSH preparation, endpoint
and balance checks, listing discovery, exact request preparation, and successful
guest SSH/resume plus the Git-pinned compiled CUDA vector-add workload. Seller
steps cover install/build,
configuration, wallet/publication preparation, distinct service start, exact
listing publication, and observation liveness. The receipt stores typed step
outcomes and public digests, not their private values.

Scenarios name only logical actor/listing/request slots. Private infrastructure
maps those one-to-one to live seller/listing identities and exposes only the
logical projection and a closed typed binding containing method, field-specific
domain, and one 256-bit value. Its method is either domain-separated
HMAC-SHA-256 under a per-campaign private key or an opaque cryptographically
random surrogate stored with the native proof. Raw hashes of enumerable private
identifiers are invalid. Frozen wrappers recheck the typed binding against the
native private proof immediately before publication or purchase.

A role receipt is accepted only alongside an action/result receipt whose actor
and lifecycle timestamps show liveness through the barrier. The public
validator checks structure and correlation; private infrastructure proves
process identity and supplies the secret-bearing execution context.

An aggregate actor-set receipt binds the exact declared cardinalities,
overlapping lifetimes, invocation timestamps/skew, and controller queue/
throttle observation. This prevents a B8 contract from passing with eight
serial Codex processes.

**Rejected alternative:** one generic readiness receipt with arbitrary
key/value evidence. It cannot make missing role work or an early actor exit
detectable.

### Keep deterministic execution behind an agent-invoked one-shot wrapper

The controller may freeze exact request or publication bytes and the
deterministic driver may perform the low-level operation, but the initiating
agent must invoke a pinned wrapper while its Codex process is still active.
Buyers own purchase; sellers own service start and exact listing publication.
The portable action binds the wrapper path/hash, payload hash, scenario,
logical seller/listing selection, privacy-preserving runtime binding, release,
attempt, expected result schema, and independent-oracle authority. It cannot
bind a result that does not yet exist. The terminal result binds the canonical
action digest and only then computes its own canonical digest.

The wrapper contract is one-shot: it verifies frozen authority immediately
before emission, emits exactly once, and returns a typed result. Changed bytes,
duplicate release, attempt greater than one, wrapper substitution, or early
actor exit fail closed. The private implementation may use a pipe, socket, or
file-backed release channel as long as it preserves those semantics.

**Rejected alternative:** let Codex approve a hash and exit before a controller
thread emits it. That remains useful deterministic-driver evidence but is not
agent-triggered load.

### Evaluate outcomes from an independent durable correlation

The result schema has exact `vm-succeeded`, `capacity-refused`, and `fault`
variants. A normalized public `deal_reference` keeps logical request,
seller/listing, typed runtime binding, negotiation, and escrow digests in the
storefront domain. Success joins that carrier to `capacity_reservation_id` and
then separately to `fulfillment_id`, Settlement Record/Resource state,
`provisioned_resource_id`, the pinned guest exercise, and teardown. Generic
fulfillment does not gain commercial identity. `allocation_id` and
`provisioning_job_id` remain optional diagnostics.

`capacity-refused` is derived from independent per-site capture proving every
eligible attempt in the final escrow-scoped atomic reserve returned routine
`reservation: null`, with zero errors, skips, or missing responses, plus null
durable capacity/fulfillment/output identities, terminal commercial/
failure-policy compensation, and zero active residue. Aggregate null alone is
not scarcity because current aggregation can swallow site errors. The
pre-settlement `capacity_hold_unavailable` event is explicitly nonterminal and
never sufficient. Generic failures, unknown reasons, uncompensated state, and
timeouts are faults. Aggregate validation applies unordered per-request
cardinalities and independently rejects double allocation.

The observation schema carries logical or redacted correlation identifiers.
Private infra retains unredacted provider/host evidence and maps it to these
portable digests.

Every stage result also binds a typed terminal snapshot, teardown,
zero-active-residue proof, and baseline-equivalence result. Reversible
host/cloud/runtime state must exactly return; expected append-only commercial
history, fees, and wallet/accounting deltas are reconciled rather than required
to disappear. No later stage can start from a result that is merely terminal
without both partitions being clean.

**Rejected alternative:** trust the buyer/emitter terminal status. Neither
actor owns aggregate allocation, VM, or GPU truth.

### Model reuse as two baseline-fenced stages

Reuse A and B are distinct stage/scenario identities even though both have B1
counts. A result for B includes a hash reference to A's terminal result and the
intermediate baseline proof. All durable lifecycle identifiers must differ
between the two stages. The public validator proves ordering and correlation;
private infra owns baseline capture and verifies its native evidence.

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
B3/B5/B6/B7 refinement before reuse. After reuse, seller search starts only
with an external buyer-frontier receipt: B2/S2, then admitted B4/S2. A passing
B4/S2 advances to conditional B4/S4; failed S4 is refined with B4/S3. When S4
is inadmissible, an admitted S3 may be the bounded final probe. Failed S2
already gives the adjacent S1/S2 bracket. If the frozen envelope or generator
saturates first, the largest clean result is explicitly a lower bound.

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
