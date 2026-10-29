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

Real VM purchasing is the second target: a GPU-backed guest on an x86-64 host, qualified
on a physical host of its own, in parallel with the bare-metal lane. Today the guest
image is downloaded unpinned and unverified, a host's boot GPU can never be passed
through even when it is the host's only GPU and its operator has prepared it, a GPU
guest's readiness wait is fixed and its autostart unconditional, and VM teardown is
unsafe after a partial create. The real-host bare-metal scenario also cannot drive the
buyer commands as they ship.

The VM target was first a CPU-only ARM64 guest. The owner replaced it on 2026-10-29
(`design.md`, "Scope revision"), so the CPU-only shape and `aarch64` work this proposal
once carried is withdrawn (D7).

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
- **Real-host bare-metal scenario (D14).** `e2e_bare_metal_deal` drives `result`,
  `access`, and `teardown` with `--run-id`, repeats the one idempotent `teardown` until
  `released` within a bound, and fails at once on `teardown_failed`. The harness binds
  a command to its run by `--run-id`. Each SSH attempt is fresh, shares no connection,
  pins the host's key, and counts only an authentication refusal as revocation. Test
  code only; the scenario stays in no lane.
- **VM guest image (D11).** A create from scratch uses one dated release of the x86-64
  cloud image, verified by its pinned SHA-256 before use, and refuses a host of any
  other architecture before any host effect.
- **VM teardown (D9).**
  - Guest rules carry a marker naming the guest, and are removed by that exact marker
    or by the guest's exact address.
  - A teardown with no cleanup record removes what it can attribute to the guest by
    name, reports the guest absent only when nothing remains, and fails on anything it
    cannot attribute.
- **GPU guest prerequisites (D12, D13).** The boot GPU is recognized by its own kernel
  boot flag, since today's detection misses it on real hosts, and stays excluded
  unless a pool's operator opts in; even then it is eligible only while the kernel
  reports it bound for passthrough, never on a possibly stale inventory alone. A
  pool's operator may set the GPU guest's readiness wait and autostart, validated
  before any host effect. Defaults keep today's wait and autostart.
- **CPU-only shapes and `aarch64` guests (D7): withdrawn.** Their slice returned to
  `gpu-optional-compute-shapes`, which has since delivered it on `dev` and is archived.
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
  - the pinned, verified guest image;
  - boot-GPU detection and the operator's opt-in, judged against the live
    passthrough binding;
  - the GPU guest's operator-set readiness wait and autostart.
- `fulfillment`: the `failed` → `teardown_dispatch_pending` edge and the compensating
  teardown operation.

### New Capabilities

None.

## Non-Goals

- A GPU marketplace, shape, or pricing redesign, and any change to GPU selection beyond
  the boot-GPU opt-in.
- Guest or tenant isolation and data sanitization. The live VM lane checks only that
  the GPU returns to the host's driver baseline.
- CPU-only VM shapes and ARM64 guests (D7, withdrawn).
- Guest network or security redesign. The subnet-wide masquerade rule and the root
  password posture of guests are unchanged.
- Marketplace, pricing, or payment redesign. The buyer's refusal of a five-minute
  purchase at some rates is recorded only. No payments kit or service change.
- Unrelated route, publication, and trading-pause defects.
- Everything of `gpu-optional-compute-shapes`, the schema and VM stated-shape slice
  included, and its retirement of the host record's GPU fields. This branch merged it
  from `dev` (`design.md`, "Coordination with `gpu-optional-compute-shapes`").
- Re-running a teardown job whose own retries are exhausted (D6).
- Cross-site accounting of one machine sold by two provisioning services. The live
  lanes run on separate machines; where two lanes share one, they run one at a time,
  under the operational control D10 decides.

**Deferred or externally gated.** None of these is a section of this change:

- live qualification on real hardware, each lane on its own host (`design.md`, "Live
  qualification");
- host package installation, and preparing a host's GPU for passthrough and restoring
  it, which are operator procedures reviewed before physical work;
- test-mode purchases;
- the VM lane's terms and readiness wait (D8, D13);
- where two lanes share a machine, applying the idle-lane pause and proving the drain
  (D10), which are live read-backs.

## Impact

- **Packages:**
  - `provisioning/compute/ansible` (fact reader, connection port, inventory rendering,
    INI format);
  - `domains/bare_metal/provisioning/adapter` (codec, mock output) and its IaC (the
    reclaim role);
  - `domains/vms/provisioning/adapter` (codec, mock output) and its IaC (guest image,
    teardown, the boot-GPU opt-in, readiness wait, and autostart), with the IaC's
    tests;
  - `kit/fulfillment` (transition and compensating operation);
  - `provisioning/compute` (eligibility, release decision and status, teardown port,
    and the lease lifecycle's refusal handling);
  - `provisioning/compute/service` (convergence's teardown-failure write,
    composition, and integration tests);
  - `domains/vms/storefront` (the fulfillment resume reader);
  - `domains/bare_metal/buyer` (test only);
  - `domains/apicredits/storefront` (test only: its settlement coordinator tests wait
    for the coordinator's own task to finish, which the full suite needed; no runtime
    change);
  - `e2e-tests` (test only: five VM scenario modules drop their fixed create output,
    three scenario helpers register their hosts at `ssh` version 2, and the real-host
    bare-metal scenario and the harness's run-id resolver are corrected, with unit
    tests);
  - the host registration requests in `docs/development/VALIDATION_RUNBOOK.md` and
    `tools/issue-discovery`'s local phase configuration, which state `ssh` version 2.
  - Each changed package bumps its minor version once against `dev`, to the next
    minor above `dev`'s own where `dev` has already taken one (`design.md`,
    "Coordination with `gpu-optional-compute-shapes`"). Dependants' floors and locks
    are refreshed where they use the new behaviour.
- **Wire and persistence:**
  - The `ssh` connection envelope moves to version 2, which adds the optional
    `public_port`, and version 2 is the only version served. A submission at version
    1, or stating no version, is refused, and a host stored at version 1 is refused at
    execution until it is updated or imported again at version 2.
  - A compensated fulfillment ends `torn_down` with the failure reason
    `create_compensation`, a value of an existing field.
  - No automatic schema migration.
  - No downgrade to `ssh` version 1 is provided or qualified; retained test hosts
    are moved forward explicitly in the coordinated rollout (`design.md`, D3).
- **Deployment:** none required by the code. Qualifying the lanes needs rebuilt
  buyer environments and images, re-registers each retained host at `ssh` version 2,
  records the buyer route in host records, and sets the VM pool's GPU `extra_vars`.

## Dependencies and Related Changes

- No change gates this one.
- `gpu-optional-compute-shapes` owns all of its scope, and is archived. This change was
  planned to deliver its schema and VM stated-shape slice, and withdrew it
  unimplemented (D7). Neither change depends on the other. This branch merged `dev`
  after it landed, reconciling the INI parser and one VM scenario with it (`design.md`,
  "Coordination with `gpu-optional-compute-shapes`").
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
- [x] Existing subsystem specification: `physical-provisioning`, `fulfillment`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

`design.md`'s promotion record names each destination's heading.

- Fact reading is independent of the callback's display format, and evidence is linked
  to its job. Destination: `openspec/specs/physical-provisioning/spec.md` (delta), and
  its rationale in `openspec/specs/physical-provisioning/architecture.md`.
- Mock output prints what the shipped configuration prints:
  `docs/development/TESTING.md`.
- The tenant-facing port: `openspec/specs/physical-provisioning/spec.md` (delta);
  `docs/development/DEPLOYMENT_AND_CONFIG.md` (host inventory);
  `docs/bare-metal-seller-quickstart.md` ("Define the selected site"); and
  `docs/seller-quickstart.md` ("4. Prepare your KVM hosts"), where a VM guest's port is
  never the host's `public_port`.
- Compensating teardown of a failed dispatched create:
  `openspec/specs/fulfillment/spec.md` and
  `openspec/specs/physical-provisioning/spec.md` (deltas);
  `docs/development/ARCHITECTURE.md` "Release" table; and
  `openspec/specs/fulfillment/architecture.md`.
- An exhausted teardown job is not re-run: the `teardown_failed` requeue sentence in
  `openspec/specs/physical-provisioning/architecture.md` ("Proof-driven release").
- The pinned, verified x86-64 guest image, teardown attribution, the boot-GPU opt-in,
  and the GPU guest's readiness wait and autostart:
  `openspec/specs/physical-provisioning/spec.md` (delta);
  `domains/vms/provisioning/iac/README.md`; and `docs/seller-quickstart.md`.
- The real-host bare-metal scenario's inputs and teardown:
  `docs/bare-metal-seller-quickstart.md` ("Release-qualified deal evidence").
- Live lanes on separate machines in parallel; on a shared machine, sequential lanes,
  the per-listing pause, and the drain conditions:
  `docs/development/VALIDATION_RUNBOOK.md`.
- Roadmap: Goal 1's gap row on the real runner's evidence, and the payment
  qualification boundaries, in `docs/development/ROADMAP.md`.
