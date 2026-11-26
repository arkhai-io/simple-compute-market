# Complete the qualification of real provisioning

## Why

Real provisioning has been shown to work, but not all of it has been qualified,
and some of the evidence for it isn't repeated anywhere. Goal 1 of
`docs/development/ROADMAP.md` lists five gaps in that evidence:

- **Two of the six owed observations haven't been made.**
  `VALIDATION_RUNBOOK.md`'s "Observations the qualification owes" asks for six on a
  frozen, reviewed candidate. The qualification scenarios have made observations 2,
  4, 5 and 6, twice. Two are still missing:
  - observation 1, negative relay admission on each buyer relay, using section 28's
    probe;
  - observation 3, the two-VM cycle over direct access, which needs an
    operator-routable test path that a relay-only deployment lacks.

  The offers stay closed to general buyers until all six have passed.
- **No GPU offer has had a paid purchase with checked GPU work.** Every GPU offer
  stays closed to general buyers. The qualification scenarios check no GPU.
- **The real-provisioning modules can drift unnoticed.** `e2e_vm_real_provisioning`
  and `e2e_bare_metal_real_provisioning` have run against a target twice, the
  second time at `ef7c77345` after the relay drain. No lane runs them. The
  qualification scenarios share only their stages from fulfillment onwards.
- **The bare-metal cleanup native gate runs only by hand.** No workflow runs `make
  test-bare-metal-iac-native`, so the working-data helper's native account,
  filesystem, and IPC tests run only when someone runs them locally. The gate needs
  a container with `SYS_ADMIN` and AppArmor unconfined, which has never run on a
  hosted runner.
- **A hosted deployment has no dispute authority that answers.** Payment purchases
  on a real-provisioning deployment pin an authority identity no service answers.
  So the buyer's delivery-end filing, case holds, and rulings are exercised only in
  the lanes, against the mediation double.

They're grouped because they are one body of evidence, made on one frozen
candidate under one procedure, and an operator runs them together.

## What Changes

- **Observations 1 and 3 become scenarios, or a procedure an operator runs on the
  candidate.** Observation 1 runs section 28's admission probe against each buyer
  relay. Observation 3 runs on a deployment with an operator-routable test path,
  and the qualification records where it was made.
- **A paid GPU purchase scenario exists for each GPU offer.** It buys the offer
  through the shipped buyer, runs checked GPU work on the delivered machine, and
  tears it down.
- **The real-provisioning modules run on a schedule or at a trigger.** They run
  whenever relay delivery changes, or regularly, against a development cluster, and
  their results are recorded where qualification reads them. If the qualification
  scenarios cover what they check, they're retired instead.
- **The native gate runs in a workflow.** It runs on a runner that grants what it
  needs, or the gate's needs are reduced until a hosted runner can run it.
- **A hosted scenario exercises a dispute.** Once a hosted deployment has a dispute
  authority it controls, a scenario files a delivery end and follows the case to a
  ruling.

### Decided by the owner

- **D1: one change for qualification and coverage.** Goal 1's unowned gaps are
  grouped by theme. This change takes the missing observations, GPU purchases, the
  real-provisioning modules, the native gate, and the hosted dispute.

### Open for design, not decided here

- **Scenario or operator procedure, per observation.** Which of observations 1 and
  3 become scenarios, and what a deployment without a routable path records.
- **GPU hardware.** Which GPU offers exist to qualify, what hardware is available,
  and whether the purchase needs a real-money payment or TEST payments suffice.
- **Retire or schedule the modules.** Whether the qualification scenarios' stages
  can cover what the real-provisioning modules check, so one of the two retires.
- **The native gate's runner.** A self-hosted runner, a hosted runner with the
  needed privileges, or a narrower gate.
- **The hosted dispute authority.** Whether the deployment runs one of its own or
  the payments service's hosted mediation answers. How its identity is kept from
  the lanes' fixture identities, which are inert outside development topologies
  by construction.
- **Sections that wait.** The GPU purchase waits on hardware, observation 3 on a
  routable path, and the hosted dispute on an authority. Design decides whether
  those sections are planned now and blocked, or split into later changes.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `test-compatibility`: the qualification scenarios, the real-provisioning modules'
  place, and the hosted dispute scenario.
- `market-change-workflow` or the CI workflows' owner: the native gate's workflow.

### New Capabilities

None.

## Non-Goals

- The payer check's reliance on a dedicated account. That waits on the payments
  service publishing a payer-scoped debit listing, outside this repository.
- Opening any offer to general buyers. That follows the evidence. It isn't part of
  this change.

## Impact

- `e2e-tests` (the qualification scenarios, the real-provisioning modules, and new
  scenarios).
- `VALIDATION_RUNBOOK.md` (sections 25, 28 and 29, and the owed observations).
- `.github/workflows/` (the native gate, and any scheduled real-provisioning run).
- `docs/development/TESTING.md` ("The real-provisioning lane").

## Dependencies and Related Changes

- None.
- `never-strand-the-host-on-passthrough` is blocked in closeout on a rented host
  with out-of-band console access. A GPU purchase scenario prepares a GPU host, so
  design checks whether the two can share that host.
- `qualify-per-period-bare-metal-and-setup-charges` makes its live observations
  against a hosted dispute authority on mock provisioning, and waits on no real host.
  Design checks whether the hosted dispute scenario is shared.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: the
`test-compatibility` specification and architecture companion,
`docs/development/TESTING.md`, `VALIDATION_RUNBOOK.md`, and
`docs/development/ROADMAP.md`'s Goal 1 current state.
