# Proposal

## Why

Real-provisioning offers stay closed to general buyers until the observations the
qualification owes pass on a frozen, reviewed candidate
(`docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes`).
`docs/development/ROADMAP.md` Goal 1 records none made that way.

`qualify-arkhai-real-provisioning` made them as an operator-run procedure, driving the
shipped buyer and typed operator APIs from orchestration kept outside this repository.
Those results are not qualification, because they were not bound to a frozen candidate.
The procedure also cannot be rerun from this repository: its steps, its correlation and
the half of its pass criteria that no helper asserts live with whoever ran it.

Today's real-provisioning modules deal through the typed driver and settle on Alkahest,
so by the runbook's own terms they make none of these observations. The lanes run their
once-only payment scenarios against an in-lane payments double, but only the bare-metal
one buys through the shipped buyer, its steps are its own rather than shared stages, and
no VM scenario buys through `market buy` in `arkhai.payments.v1`.

## What Changes

- **Locally verifiable buyer purchases.** A shared buyer-purchase stage set buys through
  the shipped buyer (`market buy`, `market bare-metal buy`) in `arkhai.payments.v1`. It
  runs in the VM and bare-metal lanes against mock provisioning and the in-lane payments
  double. The existing bare-metal payment purchase is restructured onto it, its physical
  end becoming the buyer's `market bare-metal teardown` before the seller refund. A new
  VM purchase with its own resource and host ends by the watchdog's expiry path.
- **Shared post-settlement stages.** The canonical compute deal's stages from fulfillment
  onwards are keyed on the deal's settlement reference, so the Alkahest and
  buyer-purchase sets share them. A lease's ending is shared only among scenarios that
  end the same way: the watchdog-expiry stages by the Alkahest set and the VM purchase,
  while the bare-metal purchase runs its own buyer-teardown stage. Each set supplies the
  shared stages' inputs from its own earlier stages, such as the expected host from the
  Alkahest preview or the buyer purchase's declared host, so their bodies stay one.
- **One settle-wait resolution for every storefront.** The settlement runtime kit's
  settle wait resolves a reference by its settlement reference, then its negotiation,
  for any mechanism, and owns its terminal states. The VM, bare-metal and API-credit
  storefronts supply only their settlement-evidence lookups and delivery status. Today
  the bare-metal storefront's wait cannot see an `arkhai.payments.v1` deal at all.
- **External-topology qualification scenarios** extend those purchases against a
  configured real-provisioning target and payments target, adding only the real-host
  observations:
  - **Observation 2:** two concurrent CPU-only VM purchases. The first guest's SSH
    heartbeat continues while the second is created and torn down. Both leases end
    through the watchdog's expiry path. The management client's and libvirtd's process
    generations are read before, during and after.
  - **Observations 4 and 5:** the bare-metal normal cycle, then the successor and refusal
    cycle. Each lease is ended by the buyer's teardown. There is no GPU check.
  - **Observation 6:** repeat registration and adoption across both hosts. The consumed-UID
    history is read through the existing working-data operator route.
- **Correlation and payment checks.** Each stage logs the identifiers it reads. Each
  observation's outcome is made only when every stage it requires passed, and unproven
  when one it requires skipped. Grant admission is checked against the key recorded for
  each lease. Each
  transaction is checked against its Agreement and receipt. The buyer's balance drop
  must equal the scenario's own debits, under a dedicated-account precondition.
- **One listing per real resource** offers every deal mechanism the stack composes. Adoption
  requires the adopting module's own mechanism.
- **A host diagnostics VM operator job** reports boot, kernel, running-guest count, and
  systemd facts for libvirtd, the buyer tunnel client and an optional management unit.
  The operator client submits it like every operator action, and a typed
  `HostDiagnostics` parse reads the succeeded job's result.
- **Target configuration.** The VM host gains an optional `management_unit`. Each relay
  access gains an optional `admission_log`: a harness-local file of the admission
  plugin's documented log lines.
- **The external run's payments target.** The external modules read the runner's
  existing payments settings, the buyer's token from a secret profile. The operator first
  runs each storefront chart's payments check; the deployment supplies the storefronts'
  CA bundle and payments key through the charts' existing options.
- **A pinned dispute authority.** The deployment pins an authority identity with a real
  payments account. No authority service or double is built here.
- **Runbook amendments.**
  - Observation 2's leases end through the watchdog's expiry path.
  - Observation 4 drops its GPU clause, since GPU work stays owed for each GPU offer.
  - Observation 5's notification is the reclaim job's recorded error and scheduled retry.
- **Testing guidance.** `TESTING.md` distinguishes locally verifiable from
  external-topology end-to-end scenarios, says what each covers, and states how external
  evidence is supplied.

No new settlement mechanism, funding call, default lane for the external scenarios,
host-specific configuration or LIVE-money test is introduced, and no buyer-facing settle
status route or settlement evidence store changes. Funding the buyer, and any
setup needing knowledge this repository lacks, is the deployment's topology. External
evidence is supplied free-form by the deployment's operator; no record format is defined.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: locally verifiable and external-topology scenarios; shared
  buyer-purchase and post-settlement stages; the qualification scenarios and their
  target fields; one listing per real resource.
- `physical-provisioning`: the host diagnostics VM operator job.
- `settlement-servicing`: the settle wait resolves a settlement by its reference or its
  negotiation, for any mechanism.

## Dependencies

None remain. `add-mvp-payments-lane-double`, archived, delivered the in-lane payments
double, the payer balance read, lane CA trust through `ca_bundle_path`, the lanes'
unanswerable dispute authority, and the storefronts' payments check.

## Impact

- `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py` and a new buyer-purchase
  stage set; their source checks under `e2e-tests/tests/unit/`.
- `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_payment_deal.py`,
  restructured onto the shared stages; a new VM payment purchase module in
  `e2e-tests/tests/e2e/roles/scenarios/vms/` with its resource, host and pool in
  `host_registry.py`; and three qualification modules.
- The VM real-provisioning driver's listing creation and adoption.
- `e2e-tests/src/e2e_harness/real_provisioning_target.py` and
  `config-real-provisioning-target.yml.example`: `management_unit` and `admission_log`.
- `e2e-tests/pyproject.toml`: markers for the new modules.
- `domains/vms/provisioning`: the host diagnostics action, its playbook, mock default
  output, and the operator client's `diagnose_host` and `HostDiagnostics`, with tests at
  the levels that own them.
- `kit/settlement-runtime`: the settle wait's resolution and terminality, and its
  resolver as a public operation; a breaking minor version, every exact pin on it raised.
- The VM, bare-metal and API-credit storefronts' settle-wait hooks, moved onto the kit's
  lookups, with tests at the levels that own them and version bumps.
- No chart or database migration change.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The two kinds of end-to-end scenario, minimal extension, topology ownership, and
  free-form external evidence: `docs/development/TESTING.md` (a new section), with the
  repository-wide rule in `docs/development/ARCHITECTURE.md`'s testing philosophy.
- The buyer-purchase and shared post-settlement stages, and the qualification
  scenarios: `openspec/specs/test-compatibility/spec.md`, and `architecture.md` at
  `#ordinary-arkhai-purchase-evidence`; `docs/development/TESTING.md`, "The
  real-provisioning lane".
- Running the scenarios on a candidate, and the amended observations 2, 4 and 5:
  `docs/development/VALIDATION_RUNBOOK.md` §25 and §29.
- `management_unit` and `admission_log`: `docs/development/TESTING.md` and the target
  example.
- The host diagnostics job: `openspec/specs/physical-provisioning/spec.md` and the VM
  IaC README.
- The settle wait's resolution: `openspec/specs/settlement-servicing/spec.md`.
- Goal 1's qualification row and the new unowned gaps: `docs/development/ROADMAP.md`.

Each decision's destination:

- D1: `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`
  (the new section on scenario kinds); `docs/development/ARCHITECTURE.md`, "Testing
  strategy".
- D2: `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`,
  "The real-provisioning lane".
- D3: `openspec/specs/test-compatibility/spec.md` (delta);
  `docs/development/VALIDATION_RUNBOOK.md` §29, observation 2.
- D4: `openspec/specs/test-compatibility/spec.md` (delta);
  `openspec/specs/test-compatibility/architecture.md`, "Ordinary Arkhai purchase
  evidence"; `docs/development/ROADMAP.md`, the debit-listing gap.
- D5: `openspec/specs/physical-provisioning/spec.md` (delta); the VM IaC README;
  `docs/development/VALIDATION_RUNBOOK.md` §29, observation 5;
  `docs/development/ROADMAP.md`, the operator-notification gap.
- D6: `docs/development/VALIDATION_RUNBOOK.md` §29, observation 4;
  `docs/development/ROADMAP.md`, the paid GPU purchase gap.
- D7: `docs/development/VALIDATION_RUNBOOK.md` §25 and §29.
- D8: `openspec/specs/test-compatibility/spec.md` (delta);
  `docs/development/VALIDATION_RUNBOOK.md` §29; `docs/development/TESTING.md` (the new
  section on scenario kinds).
- D9: `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`,
  "The real-provisioning lane"; the target example
  (`config-real-provisioning-target.yml.example`).
- D10: `openspec/specs/test-compatibility/architecture.md`, "Ordinary Arkhai purchase
  evidence".
- D12: `docs/development/ROADMAP.md`.
- D15: `openspec/specs/test-compatibility/spec.md` (delta).
- D16: `openspec/specs/test-compatibility/spec.md` (delta).
- D17: `openspec/specs/test-compatibility/spec.md` (delta).
- D18: no permanent destination — the storefront charts' CA option and the kit's
  transport rule are already specified, and this change adds nothing to them.
- D19: `docs/development/VALIDATION_RUNBOOK.md` §25 and §29.
- D20: no permanent destination — a dependency delivered, recorded in the change's
  history.
- D21: `docs/development/TESTING.md` (the new section on scenario kinds, citing "Tests
  wait on events, never on durations").
- D22: no permanent destination — an implementation cadence, recorded in the change's
  history.
- D23: `openspec/specs/settlement-servicing/spec.md` (delta);
  `docs/development/ROADMAP.md`, the buyer settle status route and shared evidence store
  gaps.
