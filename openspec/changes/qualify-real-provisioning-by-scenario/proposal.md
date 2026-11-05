# Proposal

## Why

Real-provisioning offers stay closed to general buyers until the observations the
qualification owes pass on a frozen, reviewed candidate
(`docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes`).
`docs/development/ROADMAP.md` Goal 1 records none made that way.
`qualify-arkhai-real-provisioning` made them as an operator-run procedure, driving
the shipped buyer and typed operator APIs from orchestration kept outside this
repository. Those results are not qualification, because they were not bound to a
frozen candidate. The procedure also cannot be rerun from this repository: its
steps, its correlation and the half of its pass criteria that no helper asserts
live with whoever ran it.

End-to-end scenarios are defined here. A deployment supplies only the topology a
scenario runs against: its services, secrets, accounts, funding and hosts. This
change makes the owed observations into scenarios. Any operator with a conforming
deployment can then run them on a candidate, and the criteria cannot drift from
the runbook.

Today's real-provisioning modules deal through the typed driver and settle on
Alkahest, so by the runbook's own terms they make none of these observations: a
deal driven through the typed operator clients does not make observation 2. The
payment scenarios buy through the shipped buyer in `arkhai.payments.v1`, but only
against mock or controlled delivery.

## What Changes

- **Scenarios** for observations 2, 4, 5 and 6, each buying through the shipped
  buyer CLI and paying in `arkhai.payments.v1` TEST, against a real-provisioning
  target:
  - **Observation 2:** two concurrent CPU-only VM deals. The first guest's SSH
    heartbeat continues while the second is created and torn down. Both leases
    expire naturally. The management client's and libvirtd's process generations
    are observed before, during and after.
  - **Observation 4:** the bare-metal normal cycle. The pinned relay endpoint, the
    nonroot tenant and wrong-key refusal are checked. Bounded working-data seeding
    precedes an ordinary reclaim that the scenario starts with the buyer's teardown,
    and its verification follows it. There is no GPU check: GPU hosts are a
    different scenario.
  - **Observation 5:** the bare-metal successor cycle: the foreign-descendant
    refusal, the queued same-job retry, held capacity and notification, then
    fixture-only repair and completion.
  - **Observation 6:** repeat registration and adoption as a stage. Typed reads
    are taken before and after reapplying the canonical registrations and one
    publication cycle, including relay quarantine and the consumed-UID history.
- **Correlation** in each scenario of the buyer run, Agreement, signed receipt and
  transaction, reservation, jobs, relay lease and grant, and the deployment's
  funding reference. Each link is read from the authority that owns it, and a link
  not read is reported unproven.
- **An outcome per observation:** made, failed or unproven. It is written with its
  correlation and candidate binding to an operator-supplied restricted output
  directory, never into the repository.
- **Observability in the typed clients.** Reads an observation needs that no typed
  client offers are added to the owning service and its client: a VM host's
  management and hypervisor process generations, and a bare-metal host's
  consumed-UID history.
- **Configuration the deployment supplies.** Each relay the real-provisioning
  target names gains an optional `admission_log` setting: a harness-local file of
  the admission plugin's documented log lines, from which the scenario reads each
  lease's grant admission. The scenarios reuse the existing `PAYMENTS` settings for
  the payments target and parties, and use only the payments interface this
  repository already imports. Like every real-provisioning module, they are in no
  default lane, and they report a blocked skip without a target.
- **In-cluster payments over HTTPS.** The storefront charts gain an option to trust
  a deployment-supplied CA bundle through `SSL_CERT_FILE`. A kit test pins that an
  `https://<service>.<namespace>.svc.cluster.local` payments origin is accepted
  and plain HTTP to it refused. The HTTPS requirement is unchanged.
- **A pinned dispute authority.** The deployment supplies the dispute authority
  identity each payment listing needs, with a real payments account. No owed
  observation exercises a dispute, so no authority service or double is deployed,
  and the scenarios record the buyer's delivery-end filing as outside their
  observations. A hosted, controllable dispute authority is an unowned roadmap gap.
- **Method amendment.** The scenarios join the accepted operator-procedure
  method, which is retained, as the repeatable and deterministic way to make
  these observations. The runbook, testing guide and test-compatibility documents
  are amended.

No new settlement mechanism, payments API, funding call, default pipeline lane,
host-specific configuration or LIVE-money test is introduced. Funding a buyer stays
the deployment's step: the testing boundary leaves operator test funds to the
payments target (`docs/development/TESTING.md#private-service-dependencies`).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: qualification observations are made by scenarios against a
  configured deployment. The configuration a deployment supplies, the outcome
  record and the correlation a scenario owes.

## Impact

- `e2e-tests/tests/e2e/roles/scenarios/vms/` and `.../bare_metal/`: new scenario
  modules, or a buyer-purchase mode of the real-provisioning modules (design
  decides). Shared payment, SSH, buyer-CLI, working-data and real-provisioning
  helpers are reused.
- `e2e-tests/src/e2e_harness/real_provisioning_target.py` and
  `config-real-provisioning-target.yml.example`: each relay's `admission_log`.
- The owning services and their typed clients: signed admin reads for the missing
  observations, with tests at the levels that own them.
- `e2e-tests/pyproject.toml`: markers for the new scenarios.
- `helm/charts/storefront`, `helm/charts/bare-metal-storefront`: the trusted CA
  bundle option.
- `kit/arkhai-payments` tests: the cluster-service HTTPS origin.
- Documentation: `docs/development/VALIDATION_RUNBOOK.md` §29,
  `docs/development/TESTING.md`, `openspec/specs/test-compatibility/`,
  `docs/development/ROADMAP.md` Goal 1, and `openspec/changes/README.md`.
- No database migration is expected. The new admin reads are additive.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Qualification observations are made by scenarios against a configured deployment,
  and the configuration and funding the deployment supplies:
  `openspec/specs/test-compatibility/spec.md` and `architecture.md`, at
  `#payment-evidence-ownership`.
- How to run the scenarios on a candidate, and how outcomes are recorded:
  `docs/development/VALIDATION_RUNBOOK.md` §29, and `docs/development/TESTING.md`,
  *Accepted Arkhai purchase qualification*.
- The target's `admission_log`: `docs/development/TESTING.md` and the target
  example.
- The new admin reads: the owning services' specifications.
- Goal 1's qualification gap gains this change as its owner:
  `docs/development/ROADMAP.md`.
