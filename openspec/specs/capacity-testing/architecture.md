# Capacity Testing Architecture

The [normative contract](spec.md) defines the portable authority for
agent-driven VM capacity qualification, measurement, and finding handoff. This
document explains the models behind that contract: how public policy remains
separate from private execution, how roles and outcomes form an auditable
evidence graph, and where the current security and capacity claims stop.

## Role in the testing system

Capacity testing is a portable contract layer, not a second marketplace or
provisioning implementation. It describes the shapes to exercise, the actors
that own each action, the independent evidence required to interpret an
outcome, and the sanitized occurrence format used when an experiment exposes a
defect.

```text
public pinned contract
  scenario + profile + schemas + instructions + workload
                         |
                         v
private campaign authority
  live identities + credentials + topology + baselines + admission
                         |
                         v
executor and substantive agents
  frozen actions + native evidence + teardown
                         |
                         v
public sanitized result and owner-only finding handoff
```

The separation lets the same public bytes be reviewed, pinned, and invoked by
different developers without publishing cloud projects, hosts, wallets,
endpoints, listing IDs, GPU identities, credentials, or executor-local paths.
The public repository defines what evidence means. Private infrastructure
decides whether a particular live environment is authorized and supplies the
secrets and native proof needed to run it.

## Public and private ownership

| Concern | Public SCM harness | Private infrastructure or executor |
| --- | --- | --- |
| Test intent | Scenario shapes, role counts, request mapping, expected unordered cardinalities | Selection of an authorized campaign and live resource bindings |
| Reproducibility | Exact SCM commit, canonical/raw digests, schemas, quickstarts, role instructions, workload | Pinned checkout, authenticated toolchain, process isolation |
| Market identities | Logical buyer, seller, listing, and request slots | Wallets, accounts, services, live listing IDs |
| Physical topology | Declared independently assignable GPU count and portable KVM/Ansible intent | Project, host, network, PCI/IOMMU/GPU identity, global allocation fence |
| Execution | Frozen action and result contracts, CLI/runner seams | Agent processes, release barrier, one-shot live wrappers, credentials |
| Observation | Portable receipt and oracle schemas | Independent source credentials, native timestamps and lifecycle evidence |
| Safety | Cleanup and baseline-equivalence predicates | Spend bounds, cancellation, teardown, residue inspection, emergency stop |
| Findings | Validation, stable defect fingerprinting, immutable local packet | Sanitization inputs and separately authorized issue/PR publication |

Neither side can substitute for the other. A valid public scenario does not
authorize a live run, while an operator's assertion about a private run does
not satisfy the portable oracle.

## Scenario and topology model

Scenario documents are mode-neutral shapes. They express counts and
relationships—observer, buyer, seller, host operator, selected listings,
requests, and independently assignable whole GPUs—without deciding whether the
shape is a mock rehearsal, deterministic reference, qualification, or measured
wave. Profile-stage records add the orthogonal `execution_boundary` and
`actor_trigger` classifications.

```text
scenario shape: O / B / S / H / L / R / G
                         +
profile stage: execution boundary / actor trigger / expected cardinality
                         +
private bindings: live actors / listings / topology / baseline
                         =
one admissible execution
```

The current physical authority is G1: one independently assignable,
whole-device GPU. Listing count is intentionally distinct from physical
capacity. Several truthful VM listings can compete for G1, but they do not
create a second GPU. Multi-seller rows therefore bind all selected sellers to
one private, globally fenced G1 allocation view.

Qualification establishes that the product, environment, agents, oracle, and
cleanup path can execute the bounded profile. It starts with an observer probe
and a controller-driven real reference, then exercises agent-triggered B1/S1,
B2/S1, serialized reuse A/B, and B2/S2 rows. Qualification results do not claim
a capacity frontier.

Measurement keeps the same shape authority but searches for distinct limits:

1. Buyer load progresses through B1, B2, B4, and B8 against S1/G1.
2. A bracketed buyer boundary is refined only with the pre-pinned
   B3/B5/B6/B7 shapes selected by deterministic integer bisection.
3. A closed buyer-frontier receipt hash-binds the complete ordered buyer
   evidence.
4. Serialized reuse A and B prove teardown and physical reuse while carrying
   that frontier lineage.
5. Seller load progresses through admitted S2, S4, and conditionally S3 shapes
   without changing the G1 physical authority.

The search envelope is frozen before Q0. Results at the end of the envelope or
at a load-generator limit are reported as lower bounds, not inferred product
limits.

## Actor and action model

The controller coordinates; it is not a counted marketplace or observation
role. Counted actors are substantive processes:

- buyers follow the pinned buyer quickstart, prepare isolated identities,
  discover listings, own requests, and verify a successful guest;
- sellers follow the pinned seller quickstart, prepare isolated identities,
  start distinct services, and own truthful listing publication;
- the host operator proves topology, KVM/Ansible readiness, observation,
  teardown, and final baseline equivalence;
- the independent observer uses separately controlled evidence sources and
  seals request outcomes and cleanup bytes.

An actor receipt proves more than readiness. It binds the exact commit and
instruction digest, the actor's closed plan, ordered lifecycle timestamps,
prepared actions, common release authority, and liveness through its required
barrier. Concurrent rows also prove overlapping actor lifetimes, bounded
emission skew, and absence of local queueing or controller throttling.

Action authority forms an acyclic digest graph:

```text
role plan
  -> prepared intent
  -> pre-release concurrency policy
  -> frozen action
  -> one-shot wrapper result
  -> terminal role receipt
```

For an agent-triggered live action, the initiating actor process owns the
one-shot invocation. A controller-created receipt or controller-driven market
action cannot be relabeled as agent evidence. The wrapper admits exactly one
frozen payload and durably records its first terminal result, including typed
pre-emission rejection. This prevents retries or orchestration from silently
changing the experiment.

The public mock stage exercises the portable actor/action composition through a
capture boundary. It proves that role plans, frozen actions, and one-shot
capture results compose with an empty live-resource ledger. It does not prove
that a substantive private agent prepared or emitted them, and it provides no
evidence of real provisioning or private actor ownership.

## Outcome and oracle model

Expected concurrent outcomes are unordered cardinalities over exact request
IDs. A G1 B4 wave, for example, expects one independently proven success and
three independently proven capacity refusals; it does not predetermine which
buyer wins.

The independent oracle joins each request across commercial and physical
state: deal reference, reservation, fulfillment, settlement, provisioned
resource, VM lifecycle, guest workload, compensation, teardown, and cleanup.
A successful lifecycle includes buyer-owned SSH/resume, exactly one
guest-visible GPU, and successful execution of the pinned compiled CUDA
vector-add workload. Device visibility alone is insufficient.

Outcomes fall into three semantic groups:

- `vm-succeeded`: one complete, correlated whole-GPU VM lifecycle;
- `capacity-refused`: a terminal, compensated refusal independently proven
  to be capacity-related;
- typed fault: timeout, provisioning, correlation, cleanup, generator, or
  other closed failure category.

Expected refusal is useful capacity evidence, not a defect. Unknown,
uncompensated, incomplete, or cleanup-failing behavior remains a fault. Two
overlapping successful whole-GPU lifecycles on G1 produce a deterministic
double-allocation witness.

The frozen evaluation policy produces five separate observations:

| Frontier | Question answered |
| --- | --- |
| Request processing | Did every request reach its expected terminal outcome within policy? |
| Simultaneous fulfillment | How many independently observed whole-GPU VM lifecycles overlapped? |
| Provisioning | Which shape met both queue-wait and Ansible-service SLOs? |
| Correctness | Which shape had complete correlation, expected outcomes, cleanup, and baseline equivalence? |
| Load generator | Which shape had valid actor overlap/skew/liveness without local saturation? |

Agent provenance and frontier eligibility are separate. A valid agent wave can
produce negative evidence when its action is rejected or its generator
saturates. Such a result remains auditable but is censored from product-frontier
promotion.

## Cleanup, reuse, and progression

Every stage has a declared reversible baseline. Cleanup covers market,
settlement, provisioning, VM, network, disk, Ansible/process, GPU assignment,
claim, and lock state. The observer seals the exact cleanup object, and the
host operator proves baseline equivalence from private native evidence.

Serialized reuse is an explicit capacity assertion rather than incidental
cleanup:

```text
buyer results -> buyer-frontier receipt
              -> reuse A success and clean baseline
              -> reuse B success and clean baseline
              -> seller stage 1 -> seller stage 2 -> optional refinement
```

Each arrow carries both hash lineage and a strictly later campaign-clock
boundary. An unclean stage cannot authorize reuse or later seller scaling.
Logical slots may be reused, but their commercial, reservation, fulfillment,
provisioned-resource, VM, and teardown identities remain distinct.

## Evidence and finding model

Portable results retain typed public facts and digests. Sanitized finding
evidence approved for export is admitted from one explicit root only through
canonical relative paths, raw-byte hashing, safe file types, and privacy
checks. Private native evidence stays outside public artifacts. Typed random
bindings let a public artifact refer to private topology, baseline, and native
evidence without exposing an enumerable live identifier.

A capacity finding is one immutable occurrence derived from one fully
validated result. The harness recomputes every durable correlation and any
double-allocation witness before accepting the occurrence. It then derives a
stable defect fingerprint only from normalized defect semantics. Run IDs,
timestamps, concrete resource correlations, prose, evidence paths, cleanup
facts, and commit drift remain occurrence evidence and do not fragment the
defect identity.

```text
validated result + exact evidence bytes
              -> immutable occurrence (finding_id)
              -> normalized defect fingerprint
              -> owner-only marker-free candidate packet
              -> separately authorized publication
```

Filing readiness is cleanup-gated. An actionable occurrence can be preserved
when cleanup is incomplete, but it is not ready to file. Reaching a frontier,
ending a bounded search, or observing an expected capacity refusal does not
create a finding.

The local capacity path detects and packages; it does not mutate GitHub.
Issue/PR creation and lifecycle markers belong to the separately authorized
guarded-publication capability.

## Owner-only handoff and threat boundary

Finding state uses an owner-only root: directories are mode 0700 and files are
mode 0600, non-symlink, current-user-owned, regular, and single-link where
required. Ingest and packet replay use both a root lock and a finding lock,
reauthenticate path components around access, and use create-once or
exchange-based publication with directory fsync.

Create-once publication uses a temporary inode followed by a hard-link to an
absent destination. Deterministic replacement uses Linux
`renameat2(RENAME_EXCHANGE)`, verifies the exchanged identities and bytes,
and can exchange back on mismatch. Recovery removes only precisely recognized,
authenticated temporary state; ambiguous state remains untouched and fails
closed.

This boundary protects against malformed inputs, symlink/path traversal,
unsafe ownership or modes, accidental replay, ordinary concurrent writers, and
crash windows under the compliant-writer model. It does not claim protection
against a malicious process running as the same effective user that bypasses
both advisory locks and substitutes a pathname during the final
`linkat`, `unlinkat`, or `renameat2` syscall window. Executors requiring
that stronger boundary need OS-level isolation beyond this handoff contract.

## Executor compatibility

Portable commands and artifacts are repository-relative and pinned to one Git
commit. The contract therefore does not depend on Codex running on a
developer's laptop. The same entrypoints can be invoked by:

- a local Codex session controlling local or remote resources;
- an authenticated cloud worker;
- a private CI runner; or
- a Tekton pipeline that supplies the same pinned checkout and inputs.

Executor portability does not move private concerns into this repository. The
execution envelope still owns process-level authentication, secrets, live
identity bindings, project selection, spend limits, cancellation, native
evidence capture, and guaranteed teardown. A cloud or Tekton integration is
compatible when it invokes the Git-pinned public interface and emits the same
validated artifacts; it does not need a second capacity-testing semantics
layer.

## Current limits

- Capacity authority is G1. No G2 or multi-GPU capacity claim is admitted.
- Live scenarios are VM-only and use real KVM/Ansible provisioning,
  whole-device GPU passthrough, one GPU per successful VM, and zero retries.
- The executable public path is preparatory. It validates contracts, composes
  capture-only mock actions, evaluates supplied evidence, and creates
  owner-only local handoff state; it does not fund wallets, create listings,
  purchase deals, provision or destroy VMs, access a GPU, create cloud
  resources, perform live cleanup, or mutate GitHub.
- Mock evidence proves portable preparation and composition only. It is not
  system-capacity evidence.
- Public binding values are privacy-safe references, not proof of a private
  topology, baseline, identity, or native evidence source.
- The owner-only file protocol assumes compliant writers and Linux filesystem
  primitives; it does not defend the same-user syscall-interposition case
  described above.
- A private local, cloud, or Tekton campaign envelope is not provided by this
  capability. Such an envelope must pin and honor this contract.
- Capacity-v2 finding packets remain local and marker-free until a separately
  authorized publication path accepts them.
- Schema-v1 finding and publication behavior remains a separate compatibility
  path and does not establish current capacity authority.

## Related contracts

- [Testing and compatibility](../test-compatibility/spec.md)
- [Site capacity](../site-capacity/spec.md)
- [Fulfillment](../fulfillment/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Compute provisioning contract](../compute-provisioning-contract/spec.md)
- [Repository architecture](../../../docs/development/ARCHITECTURE.md)
