# Qualify paid GPU purchases

## Why

The validation runbook keeps every GPU offer closed to general buyers until "a paid
purchase ..., with checked GPU work, has passed for each GPU offer"
(`docs/development/VALIDATION_RUNBOOK.md`, "Observations the qualification owes").
Nothing in this repository can make that purchase, and nothing says what it is.

- **No scenario buys a GPU.** The real-provisioning target states a host's vCPUs,
  memory and disk and no GPU, and allows one host per domain
  (`e2e-tests/src/e2e_harness/real_provisioning_target.py`). The qualification modules
  deal GPU-less shapes, and the VM one fails if a GPU reaches a guest
  (`e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_qualification.py`). The runbook's
  bare-metal cycle says GPU work "is not part of this observation".
- **"Checked GPU work" is defined nowhere.** The runbook and
  `docs/guidance/repository/qualification-evidence.md` require a paid buyer's journey
  for any claim about GPU work, and neither says what work is run or what is checked.
- **The evidence that exists is an operator's.** Both GPU offers of an earlier
  deployment were bought through the shipped buyer with a signed TEST payment and
  checked GPU computation, by a procedure run outside this repository. The roadmap
  records them as accepted live observations and not as qualification evidence.
- **No GPU host is available to a qualification deployment today.**

Host preparation's GPU path is `never-strand-the-host-on-passthrough`'s, which is
blocked in closeout on a rented host with out-of-band console access. Its last live
task has a guest receive a bound card.

## What Changes

- A paid GPU purchase scenario exists for each GPU offer, in both compute domains: a
  GPU guest on a VM host, and a whole bare-metal machine with its GPUs. Each buys
  through the shipped buyer in `arkhai.payments.v1`, runs checked GPU work on what was
  delivered, and ends by the lease's ordinary teardown.
- "Checked GPU work" is defined: what a buyer runs on the delivered machine, and what
  the scenario requires of its result.
- The real-provisioning target can state a host's GPUs and name a GPU host beside a
  host that has none.
- The payment is a signed TEST payment, as
  `docs/guidance/repository/qualification-evidence.md` requires of every physical
  qualification. No real-money purchase is made.
- The runbook's sentence keeping GPU offers closed is restated against the rule for
  when a real-host run is owed, which `complete-real-provisioning-qualification` writes
  (its design, D1).

### Decided by the owner

- **D1: a change of its own.** Anything, anywhere in the repository, that requires
  GPUs is isolated to changes that focus on GPU-specific concerns, and is not mixed
  into broader features that can be validated on machines without GPUs. The paid GPU
  purchase is therefore not part of `complete-real-provisioning-qualification`, whose
  every piece is satisfied on machines without a GPU (its design, D4).
- **D2: deferred.** No work starts until a GPU host is available to a qualification
  deployment.
- **D3: listed with the lesser goal "Reach hosts and VMs that have no inbound
  route"**, beside `complete-real-provisioning-qualification` and their archived
  predecessors. Qualification is a property of each release, so no roadmap goal waits
  for it.

### Open for design, not decided here

- **What checked GPU work is.** What is run, for how long, and what is compared: the
  devices the guest or machine lists against the Agreement's GPU model and count, a
  computation whose result is checked, or both.
- **The target's GPU capacity and host count.** Whether a GPU host is a second host of
  its domain in one target, or a target of its own; which fields state its GPU model
  and count; and what a target that names no GPU host makes the scenario do.
- **Which stages have a lane twin.** An external-topology scenario extends a locally
  verifiable one. The purchase has a twin in each lane; GPU work has none, since mock
  provisioning's endpoint reaches no machine.
- **Sharing a host with `never-strand-the-host-on-passthrough`.** Its live
  verification prepares a GPU host and ends with a guest receiving a card. Whether one
  rented host serves both, and in which order.
- **When a GPU purchase is owed again.** The rule for a real-host run turns on changes
  to the Ansible layer or to how an adapter executes it. Which paths are the GPU path's
  is this change's to say.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `test-compatibility`: the paid GPU purchase scenarios and the target's GPU inputs.

### New Capabilities

None.

## Non-Goals

- Making host preparation safe for GPU passthrough.
  `never-strand-the-host-on-passthrough` owns that.
- How a listing states or a buyer negotiates a GPU, which is the roadmap's Goal 2. This
  change buys what a listing already offers.
- Opening any GPU offer to general buyers. That follows the evidence.
- A real-money purchase.
- Any observation that a machine without a GPU can make.
  `complete-real-provisioning-qualification` owns those.

## Impact

- Provisionally: `e2e-tests` (new scenarios, the target model and its committed
  example), `docs/development/VALIDATION_RUNBOOK.md`,
  `docs/guidance/repository/qualification-evidence.md` and
  `docs/development/TESTING.md`.
- No service's behaviour, wire, persistence or configuration is expected to change.
  Compatibility is owed to the newest release tag when the design is held; nothing
  proposed here alters a form `marketplace-v0.4.0` carries.

## Dependencies and Related Changes

- None gates this change. Its activation condition is hardware, stated in the change
  index.
- `complete-real-provisioning-qualification` writes the rule for when a real-host run
  is owed and shares the qualification modules' helpers. It leaves the runbook's
  GPU-offer sentence to this change.
- `never-strand-the-host-on-passthrough` is blocked in closeout on a rented host with
  out-of-band console access. A GPU purchase needs a host that change's preparation
  has not stranded.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: the `test-compatibility`
specification and its architecture companion, `docs/development/VALIDATION_RUNBOOK.md`,
`docs/guidance/repository/qualification-evidence.md` and `docs/development/TESTING.md`.
