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
so by the runbook's own terms they make none of these observations. No purchase settled
in `arkhai.payments.v1` runs in any lane: without a payments target every payment
scenario is a blocked skip.

## What Changes

- **Locally verifiable buyer purchases.** A shared buyer-purchase stage set buys through
  the shipped buyer (`market buy`, `market bare-metal buy`) in `arkhai.payments.v1`. It
  runs in the VM and bare-metal lanes against mock provisioning and the in-lane payments
  double from `add-mvp-payments-lane-double`.
- **Shared post-settlement stages.** The canonical compute deal's stages from fulfillment
  onwards are keyed on the deal's settlement reference, so the Alkahest and
  buyer-purchase sets share them.
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
  transaction is checked against its Agreement and receipt. The buyer's balance drop
  must equal the scenario's own debits, under a dedicated-account precondition.
- **One listing per real resource** offers every mechanism the stack composes. Adoption
  requires the adopting module's own mechanism.
- **A host diagnostics VM operator job** reports boot, kernel, running-guest count, and
  systemd facts for libvirtd, the buyer tunnel client and an optional management unit.
  It is read through a typed `HostDiagnostics` result.
- **Target configuration.** The VM host gains an optional `management_unit`. Each relay
  access gains an optional `admission_log`: a harness-local file of the admission
  plugin's documented log lines.
- **In-cluster payments over HTTPS.** The storefront charts gain an option to trust a
  deployment-supplied CA bundle through `SSL_CERT_FILE`, and a kit test pins the
  cluster-service HTTPS origin.
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
host-specific configuration or LIVE-money test is introduced. Funding the buyer, and any
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
- `deployment-state`: the storefront charts' trusted CA bundle option.

## Dependencies

- `add-mvp-payments-lane-double` gates implementation: the locally verifiable purchases
  need its in-lane payments double, the payer balance read, and its lane CA trust.

## Impact

- `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py` and a new buyer-purchase
  stage set; their source checks under `e2e-tests/tests/unit/`.
- New local payment scenarios in `e2e-tests/tests/e2e/roles/scenarios/vms/` and
  `.../bare_metal/`, and three qualification modules.
- The VM real-provisioning driver's listing creation and adoption.
- `e2e-tests/src/e2e_harness/real_provisioning_target.py` and
  `config-real-provisioning-target.yml.example`: `management_unit` and `admission_log`.
- `e2e-tests/pyproject.toml`: markers for the new modules.
- `domains/vms/provisioning`: the host diagnostics action, its playbook, mock default
  output, and the operator client's `diagnose_host` and `HostDiagnostics`, with tests at
  the levels that own them.
- `helm/charts/storefront`, `helm/charts/bare-metal-storefront`: the CA bundle option and
  render tests.
- `kit/arkhai-payments` tests: the cluster-service HTTPS origin.
- No database migration.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The two kinds of end-to-end scenario, minimal extension, topology ownership,
  stepping rather than waiting, and free-form external evidence:
  `docs/development/TESTING.md` (a new section), with the repository-wide rule in
  `docs/development/ARCHITECTURE.md`'s testing philosophy.
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
- The CA bundle option: `openspec/specs/deployment-state/spec.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- Goal 1's qualification row and the new unowned gaps: `docs/development/ROADMAP.md`.
