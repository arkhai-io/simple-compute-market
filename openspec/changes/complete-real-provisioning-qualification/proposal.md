# Complete the qualification of real provisioning

## Why

Real provisioning is qualified by six observations a deployment makes on real hosts
(`docs/development/VALIDATION_RUNBOOK.md`, "Observations the qualification owes").
Three external-topology modules make observations 2, 4, 5 and 6
(`docs/development/TESTING.md`, "The real-provisioning lane"). What is left is of four
kinds.

**The rule for when the observations are owed cannot be met.** The runbook binds every
observation to one frozen candidate and says that any change to source "makes a new
candidate, on which every observation is made again". Source changes with nearly every
merge, so under that rule no release is ever qualified, and the two runs that made
observations 2, 4, 5 and 6 were both on revisions the development branch has since
left. The release procedure already works another way: the deployment validates each
release candidate with its live end-to-end tests (`docs/release-handbook.md`, "The
deployment's part"), and real hosts were exercised for the 0.3.0 and 0.4.0 releases.
Nothing in this repository says when a release owes a real-host run, or which modules
such a run is.

**Two observations have no complete means.**

- Observation 1 owes four refusals at each buyer relay: `grant_missing`,
  `signature_invalid`, `port_mismatch` and `port_outside_range`. The runbook's probe
  ("Prove admission before enabling a pool") sends no grant and shows the first. The
  admission plugin checks a grant's signature before its port
  (`tools/frp-grant-admission/README.md`, "Admission"), so the last two need a validly
  signed grant for a port that was not requested, or one outside the issuer's range.
  The provisioning service signs a grant only for a lease's own port
  (`provisioning/compute/src/compute_provisioning/relays/grants.py`), no relay route
  issues one for a probe, and the plugin's command line serves and checks a
  configuration and nothing else.
- Observation 3 is the two-VM cycle over direct access. `e2e_vm_qualification` already
  runs under either access mode, but it reports its outcome as observation 2 whatever
  the target's mode (`e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_qualification.py`)
  and checks none of observation 3's preconditions. The runbook also keeps every offer
  closed until observation 3 is made, so a deployment that sells only over relays can
  never open.

**Two pieces of coverage run only by hand.**

- The Alkahest real-provisioning modules, `e2e_vm_real_provisioning` and
  `e2e_bare_metal_real_provisioning`, are in no lane, and nothing says when they run.
  They are the only real-host evidence for a deal settled through Alkahest and for the
  stages before fulfillment. `e2e_vm_guest_isolation` subclasses every stage of the VM
  one.
- No workflow runs the bare-metal cleanup native gate, `make
  test-bare-metal-iac-native`. The end-to-end pipeline's `native-ansible-gate` job runs
  `make test-provisioning-iac-native` alone (`.github/workflows/e2e.yml`), so the
  bare-metal working-data helper's native account, filesystem and IPC tests run only
  when someone runs them locally.

**Two things a real host can show are in no list.** The nine guest-isolation
observations are made by a module of their own and are not among what the runbook
owes. And no observation covers a teardown that follows an interrupted create, which
`enforce-delivery-deadlines-at-the-site` makes routine.

## What Changes

- **Qualification becomes a record made for each release candidate, by the
  deployment** (design D1). The runbook's candidate rule is rewritten: a real-host run
  is owed again when a change touches the Ansible layer or how an adapter executes it,
  and not otherwise. A release whose changes touch neither rests on the last qualified
  release's record. `docs/guidance/repository/qualification-evidence.md` states the
  rule.
- **An access-mode observation is owed only where a deployment's pools offer that
  mode** (D3). `e2e_vm_qualification` names its observation by its target's access
  mode and checks the direct-access observation's preconditions before it deals.
- **Observation 1 gains a complete means**, as a runbook procedure or a scenario
  (design Q1).
- **The repository says when the Alkahest real-provisioning modules run**, or retires
  what the qualification modules cover (Q2). No workflow here runs against a real host:
  a real-host run is the deployment's (`docs/guidance/engineering/repository-content.md`,
  "Private dependencies stay out of its tests").
- **The bare-metal cleanup native gate runs in the end-to-end pipeline** (Q7).
- **The list of what a release owes says whether guest isolation and a teardown after
  an interrupted create are in it** (Q3, Q4).
- **Each new scenario or procedure is proven once against a target** before this
  change closes. The change makes no release's qualification record (D1).

No scenario or procedure here needs a GPU (D4), and none files or follows a dispute
(D2).

## Capabilities

### Modified Capabilities

- `test-compatibility`: "Real-provisioning qualification scenarios make the owed
  observations", for the observation named by access mode and its preconditions, and
  for whatever the design's open questions add; "Equivalent physical proof preserves
  lifecycle invariants", its scenario "Direct access is qualified".

`.openspec.yaml` sets `skip_specs` until the design session settles the open
questions; the design names the requirements to be modified.

### New Capabilities

None.

## Non-Goals

- A paid GPU purchase with checked GPU work. `qualify-paid-gpu-purchases` owns it
  (D4).
- A hosted dispute scenario. `switch-on-hosted-per-period-vm` delivered the live
  dispute scenarios, and `qualify-per-period-bare-metal-and-setup-charges` owns the
  observations still unmade (D2).
- Making any release's qualification record. That is the deployment's, at each release
  candidate (D1).
- A workflow in this repository that reaches a real host or a private deployment.
- Opening any offer to general buyers.
- The payer check's reliance on a dedicated account, which waits on the payments
  service publishing a payer-scoped debit listing.
- A relay's admission of each host at login, and emergency rotation of its
  credentials, which are `harden-shared-relays`'.

## Dependencies and Related Changes

- Nothing gates this change.
- `qualify-paid-gpu-purchases`, deferred, owns the paid GPU purchase (D4). It rewrites
  the runbook's GPU-offer sentence; this change leaves that sentence as it finds it.
- `qualify-per-period-bare-metal-and-setup-charges` states the same rule for when a
  real-host run is owed (its design, D3) and promotes it to
  `docs/guidance/repository/qualification-evidence.md`. Whichever of the two lands
  first writes the rule there; the other confirms the text and adds nothing.
- `report-provisioning-failures-to-operators` amends observation 5's notification
  clause. This change rewrites the paragraph above the observations, not observation
  5. Whichever lands second reverifies the section against the other.
- `enforce-delivery-deadlines-at-the-site` hands this change one question: whether the
  owed observations gain a teardown after an interrupted create (its design, Q9; this
  design's Q4).
- `harden-shared-relays` concerns the same buyer relays. Observation 1's procedure
  lives in the runbook's "Prove admission before enabling a pool"; whichever lands
  second reverifies that section against the other.
- `never-strand-the-host-on-passthrough` is blocked in closeout on a rented host with
  out-of-band console access. Nothing here needs that host.
- **Builds on**, all archived: `prove-real-vm-provisioning` and
  `prove-relay-provisioning` (the real-provisioning modules and the relay machinery),
  `admit-relay-proxies-by-grant` (the admission plugin and its reason codes),
  `bound-bare-metal-working-data` (the working-data helper and its native gate),
  `qualify-arkhai-real-provisioning` (the operator-run method),
  `qualify-real-provisioning-by-scenario` (the qualification modules, the
  per-observation outcomes and the target's inputs),
  `shorten-the-end-to-end-pipeline` (the `native-ansible-gate` job), and
  `harden-provisioning-trust-boundaries` (host-key pins on the real modules and
  `e2e_vm_guest_isolation`).

## Impact

`docs/development/VALIDATION_RUNBOOK.md` (the sections on running the
real-provisioning scenarios, preparing buyer relays and qualifying a purchase, with
the owed observations), `docs/guidance/repository/qualification-evidence.md`,
`docs/guidance/repository/ansible-gates.md`, `docs/development/TESTING.md` ("The
real-provisioning lane"), `docs/release-handbook.md` ("The deployment's part"),
`e2e-tests/README.md` ("Real-provisioning qualification"),
`e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_qualification.py` and
`e2e-tests/tests/e2e/roles/helpers/qualification.py`, `.github/workflows/e2e.yml`, and
whatever the design's Q1 and Q2 choose.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag.

- **Behaviour.** No service's behaviour changes under any settled decision. A
  deployment running 0.4.0 provisions, relays and tears down as it does today.
- **Wire and persistence.** Nothing changes. If the design's Q1 chooses an operator
  job, that is a new provisioning action, additive, which a released client never
  calls; the design then states its contract step.
- **Configuration.** No setting is added. A field the real-provisioning target gains
  is optional under target version 2, as `management_unit`, `admission_log` and
  `guest_isolation` are; the target is an operator's ignored local file, not a
  deployed form.
- **Procedure.** The runbook's rule changes what a deployment owes before a release,
  and loosens it: a deployment that qualified under the earlier rule has done more
  than the new one asks.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `docs/guidance/repository/qualification-evidence.md`, for when a real-host run
  is owed; `docs/development/VALIDATION_RUNBOOK.md`, "Observations the qualification
  owes"; `docs/release-handbook.md`, "The deployment's part".
- D2: no permanent destination — the live dispute scenarios are already in
  `docs/development/TESTING.md`, "Live verification", and what is unmade is another
  change's.
- D3: `docs/development/VALIDATION_RUNBOOK.md`, "Observations the qualification
  owes"; `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md`,
  "The real-provisioning lane".
- D4: `docs/guidance/repository/qualification-evidence.md`, for the rule that keeps
  work needing a GPU in changes of its own.
- D5: no permanent destination — where a change sits in the change index, recorded in
  `openspec/changes/README.md`.
- D6: no permanent destination — how the work is grouped into changes.
