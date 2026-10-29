## Why

A controlled real purchase of a whole bare-metal host, settled through
`arkhai.payments.v1` in test mode, got as far as granting the buyer's access on the
host. It still delivered nothing the buyer could use, and its cleanup needed an operator.
Each failure was replayed against this branch's base (`design.md`, "Context"):

- The real grant's printed result is lost. The packaged Ansible configuration prints
  results as YAML, while the fact reader looks only for JSON. Every mock prints JSON,
  so no lane exercised the real form.
- The delivered endpoint is the provisioner's management route, not the buyer's.
- A create that failed after it was dispatched cannot be torn down: its lease waits for
  an operator, and its capacity is held, even though the host carries effects the
  domain's own teardown removes.
- Nothing proves that what a bare-metal `buy` writes to its run log, `access` can read.
  The producer was corrected before this change, and this change qualifies the fix.
- The buyer's refusal of the signed receipt came from a stale build. The current
  payments kit verifies the captured receipt, so this needs no code, only a rebuilt
  environment.

Real VM purchasing is the second target, as a truthful CPU-only ARM64 guest. Today no VM
shape without a GPU can be stated, the guest recipe is amd64-only, and VM teardown is
unsafe after a partial create.

## What Changes

`design.md` records each decision; the labels below are its.

- **Fact reading (D1, D2).** One reader in `compute_provisioning_ansible` reads a
  role's printed fact in the JSON `var:` form, or from the `msg:` literal blocks the role
  prints. It reads each block alone, ignores any block that is not a JSON document
  naming the action the domain expects, and takes the last that is. With none, the
  fact is absent and delivery fails closed. Both compute codecs use it.
  - A bare-metal grant yields evidence only from a fact naming the job's action, host,
    tenant account, and machine, and reporting success.
  - A VM create yields evidence only from a fact naming `create` and the job's guest,
    and reporting success.
  - Mock output prints the form the shipped configuration prints, rendered for the
    job. The VM pipeline scenarios drop their fixed create output, which names a
    guest that is not the job's, and use that default.
  - Fixtures are synthetic.
- **Tenant endpoint (D3).** An `ssh` connection may state a tenant-facing
  `public_port`, falling back to its `ssh_port`, as `public_host` falls back to
  `ssh_host`. A bare-metal grant's delivery endpoint is built from the host record's
  tenant-facing address and port. The port belongs to a new version, `ssh` version 2,
  which becomes the only version served. A host stored at version 1 runs nothing until
  it is updated or imported again at version 2. An update restates the stored public
  fields, `key_path` included where present, and keeps a protected key it does not
  replace.
- **Compensating teardown (D4).** A failed create that was dispatched is torn down
  through its domain's ordinary teardown when its provider can prepare that teardown
  from durable state:
  - The fulfillment kit gains `failed` → `teardown_dispatch_pending`, taken only by a
    new compensating-teardown operation. That operation records the failure reason
    `create_compensation`, which convergence keeps through a teardown failure. A
    compensated fulfillment ends `torn_down` carrying it.
  - One compute-owned eligibility predicate is shared by the release decision, the
    release status, and the teardown port, which judges from current state. A lease
    released on termination, expiry, or retry-release begins compensation, including
    one released while its create was in flight.
  - A compensation the provider cannot prepare leaves the lease `release_failed`,
    with capacity held.
  - Capacity returns only at `torn_down`.
  - A bare-metal reclaim succeeds, reporting the account absent, when its grant never
    created the account.
- **Run-log qualification (D5).** A bare-metal buyer test records a real run log from
  `buy` and recovers it as `access`, `result`, and `teardown` do.
- **CPU-only VM shapes (D7).** The compute capability schema requires no family.
  - A VM shape stated by a pool hint or storefront override may omit `gpu`, and is
    published, claimed, and provisioned without a GPU.
  - The VM listing models, compute discriminator, reconciler, lease encoding, and
    administrator reservation response stop assuming a GPU.
  - A shape with no GPU model is priced from the flat tiers alone.
  - Default generation is unchanged.
- **VM guest recipe and teardown (D7, D9).**
  - An `aarch64` host gets a pinned, checksum-verified `aarch64` cloud image on the
    `virt` machine under UEFI.
  - Guest rules carry a marker naming the guest, and are removed by that exact marker
    or by the guest's exact address.
  - A teardown with no cleanup record removes what it can attribute to the guest by
    name, reports the guest absent only when nothing remains, and fails on anything it
    cannot attribute.
- **Payments.** No code change. Environments are rebuilt from the wheelhouse.

## Capabilities

### Modified Capabilities

- `physical-provisioning`:
  - fact reading and evidence linkage;
  - the tenant-facing port;
  - release of a failed dispatched create;
  - relay ports held with capacity;
  - bare-metal reclaim of an absent account;
  - VM teardown attribution;
  - guest architecture.
- `fulfillment`: the `failed` → `teardown_dispatch_pending` edge and the compensating
  teardown operation.
- `market-composition`: the compute capability schema requires no family.
- `storefront-publication`: VM stated shapes without GPUs, and declarations without
  GPUs as members for stated shapes.

### New Capabilities

None.

## Non-Goals

- GPU passthrough, and guest or tenant isolation and sanitization.
- Guest network or security redesign. The subnet-wide masquerade rule and the root
  password posture of guests are unchanged.
- Marketplace, pricing, or payment redesign. The buyer's refusal of a five-minute
  purchase at some rates is recorded only. No payments kit or service change.
- Unrelated route, publication, and trading-pause defects.
- Retiring host GPU fields; the VM default generator for pools without GPUs; bare-metal
  shapes without GPUs; the resource type of a declaration without GPUs; and registry
  filter treatment of GPU-less listings. All of these remain
  `gpu-optional-compute-shapes`'s.
- Re-running a teardown job whose own retries are exhausted (D6).
- Cross-site accounting of one machine sold by two provisioning services. The lanes
  run one at a time, under the operational control D10 decides.

**Deferred or externally gated.** None of these is a section of this change:

- live qualification on real hardware;
- host package installation;
- test-mode purchases;
- the VM lane's terms (D8);
- applying the idle-lane pause and proving the drain (D10), which are live read-backs.

## Impact

- **Packages:**
  - `provisioning/compute/ansible` (fact reader, connection port, inventory rendering,
    INI format);
  - `domains/bare_metal/provisioning/adapter` (codec, mock output, reclaim role);
  - `domains/vms/provisioning/adapter` (codec, mock output) and its IaC (guest recipe,
    teardown);
  - `kit/fulfillment` (transition and compensating operation);
  - `provisioning/compute` (eligibility, release decision and status, teardown port,
    and the lease lifecycle's refusal handling);
  - `provisioning/compute/service` (convergence's teardown-failure write,
    composition, and integration tests);
  - `domains/compute`, `domains/vms/domain`, `domains/vms/listings`,
    `domains/vms/storefront`, and `domains/vms/settlement` (CPU-only shapes, the
    administrator reservation response, and the fulfillment resume reader);
  - `core/storefront-client` (the optional `gpu_count` of the reservation response);
  - `domains/bare_metal/buyer` (test only);
  - `e2e-tests` (five VM scenario modules drop their fixed create output, and three
    scenario helpers register their hosts at `ssh` version 2; test only);
  - the host registration requests in `docs/development/VALIDATION_RUNBOOK.md` and
    `tools/issue-discovery`'s local phase configuration, which state `ssh` version 2.
  - Each changed package bumps its minor version. Dependants' pins and locks are
    refreshed.
- **Wire and persistence:**
  - The `ssh` connection envelope moves to version 2, which adds the optional
    `public_port`, and version 2 is the only version served. A submission at version
    1, or stating no version, is refused, and a host stored at version 1 is refused at
    execution until it is updated or imported again at version 2.
  - A compensated fulfillment ends `torn_down` with the failure reason
    `create_compensation`, a value of an existing field.
  - The VM administrator reservation response's `gpu_count` becomes optional.
  - VM listings may omit GPU fields.
  - No automatic schema migration.
  - No downgrade to `ssh` version 1 is provided or qualified; retained test hosts
    are moved forward explicitly in the coordinated rollout (`design.md`, D3).
- **Deployment:** none required by the code. Qualifying the lanes needs rebuilt
  buyer environments and images, re-registers each retained host at `ssh` version 2,
  and records the buyer route in host records.

## Dependencies and Related Changes

- No change gates this one.
- `gpu-optional-compute-shapes` keeps its remaining scope. This change delivers its
  schema and VM stated-shape slice. That change's index row names this one in
  `Depends on`, gating its planning.
- `resolve-compute-family-findings` plans edits to files this change also edits:
  `lease_lifecycle.py`, `fulfillment_convergence.py`, the VM storefront's
  `admin_controller.py`, and the VM codec tests, which it moves. The edits touch
  different functions. Its terminal-state sets are not changed by this change, since
  the convergence set holds site reservation states, not fulfillment states. This
  change is implemented on its pinned base, and whichever lands second reconciles the
  overlap when it merges `dev` (`design.md`, "Coordination with
  `resolve-compute-family-findings`").
- `relay-vm-access-without-a-dashboard`: relay ports return with capacity on every
  terminal outcome, which compensation preserves.
- `version-accepted-artifacts`: the create result's shape is unchanged.
- `bare-metal-and-credits-domain-stacks`: this change adds only a run-log test to the
  bare-metal buyer.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning`, `fulfillment`,
      `market-composition`, `storefront-publication`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Fact reading is independent of the callback's display format, and evidence is linked
  to its job. Destination: `openspec/specs/physical-provisioning/spec.md` (delta), and
  its rationale in `openspec/specs/physical-provisioning/architecture.md`.
- Mock output prints what the shipped configuration prints:
  `docs/development/TESTING.md`.
- The tenant-facing port: `openspec/specs/physical-provisioning/spec.md` (delta) and
  `docs/development/DEPLOYMENT_AND_CONFIG.md` (host inventory).
- Compensating teardown of a failed dispatched create:
  `openspec/specs/fulfillment/spec.md` and
  `openspec/specs/physical-provisioning/spec.md` (deltas);
  `docs/development/ARCHITECTURE.md` "Release" table; and
  `openspec/specs/fulfillment/architecture.md`.
- An exhausted teardown job is not re-run: the `teardown_failed` requeue sentence in
  `openspec/specs/physical-provisioning/architecture.md` ("Proof-driven release").
- CPU-only VM shapes and their flat-tier pricing:
  `openspec/specs/market-composition/spec.md` and
  `openspec/specs/storefront-publication/spec.md` (deltas);
  `openspec/specs/storefront-publication/architecture.md`; the shape-constraints
  bullet of `docs/development/DEPLOYMENT_AND_CONFIG.md`; and
  `docs/development/ROADMAP.md` Goal 2.
- The VM guest's architecture, teardown attribution, and host prerequisites:
  `openspec/specs/physical-provisioning/spec.md` (delta);
  `domains/vms/provisioning/iac/README.md`; and `docs/seller-quickstart.md`.
- Sequential lanes on one machine, the per-listing pause, and the drain conditions:
  `docs/development/VALIDATION_RUNBOOK.md`.
- Roadmap: Goal 1's gap row on the real runner's evidence, and a Goal 2 note, in
  `docs/development/ROADMAP.md`.
