# Design: complete-real-provisioning-qualification

## Context

**What the runbook owes.** `docs/development/VALIDATION_RUNBOOK.md`, "Observations the
qualification owes", lists six observations a deployment makes on real hosts:

| # | Observation | Made by |
|---|---|---|
| 1 | Negative relay admission, four refusals at each buyer relay | An operator's probe; the runbook gives a procedure for one refusal |
| 2 | Two concurrent VM deals | `e2e_vm_qualification` |
| 3 | The two-VM cycle over direct access | `e2e_vm_qualification` against a direct-access target, mislabelled |
| 4 | The bare-metal normal cycle | `e2e_bare_metal_qualification` |
| 5 | The bare-metal refusal and retry | `e2e_bare_metal_qualification` |
| 6 | Repeat registration and adoption | `e2e_real_provisioning_reapply` |

The paragraph above them freezes one source candidate, binds every cycle to it, and
says any change to a path that enters a wheel, an image, a chart or the e2e image
"makes a new candidate, on which every observation is made again". It keeps every
offer closed until all six have passed on the candidate, and until a paid purchase with
checked GPU work has passed for each GPU offer.

**How releases are validated.** The deployment owns validation: it validates each
release candidate "with its live end-to-end tests" and runs every local lane on the
candidate's images (`docs/release-handbook.md`, "The deployment's part"). The release
description lists "observations its live evidence left unproven" among its known
limits. Real hosts were exercised for the 0.3.0 and 0.4.0 releases. The handbook names
no module a live run consists of, and nothing says when a release owes one.

**Observation 1.** The runbook's probe ("Prove admission before enabling a pool")
requests one proxy with no grant and requires the refusal `grant_missing`. Observation
1 also owes `signature_invalid`, `port_mismatch` and `port_outside_range`. The plugin
checks, in order, that a grant is present, that its key id names a configured key,
that its signature verifies, and only then that its port equals the requested port and
lies in the issuer's range (`tools/frp-grant-admission/README.md`, "Admission"). So:

- `signature_invalid` needs a grant under a configured key id whose signature does not
  verify. Anyone can build one.
- `port_mismatch` and `port_outside_range` need a grant the relay's own signing key
  signed, for a port other than the one requested, or outside the issuer's range. The
  provisioning service holds that key and signs only a lease's own port (`sign_grant`
  in `provisioning/compute/src/compute_provisioning/relays/grants.py`). The relay
  routes create, change, enable, disable and read relays, rotate the token and stage
  and activate signing keys; none issues a grant. The plugin's command line has `serve`
  and `check`.

`make -C tools/frp-grant-admission test-frp` runs every reason code against the pinned
frp binaries in a fixture of its own; it does not reach a deployed relay.

**Observation 3.** `e2e_vm_qualification` runs under either access mode: a direct
target delivers no relayed lease, so its admission check has nothing to read
(`e2e-tests/tests/e2e/roles/helpers/qualification.py`), and its driver takes the
buyer's address from the target's mode
(`e2e-tests/tests/e2e/roles/scenarios/vms/real_purchase_driver.py`). The module
declares one observation, `OBSERVATIONS = ("2",)`, whatever the mode, so a run against
a direct target logs observation 2 as made. It checks neither of observation 3's
preconditions: a pool drained as the runbook's live-lane steps require, and no
unreleased relay lease for the pool. A pool that names a relay delivers over it, and a
pool that names none delivers over the host's own address.

**The Alkahest real-provisioning modules.** `e2e_vm_real_provisioning` and
`e2e_bare_metal_real_provisioning` deal through the typed driver and settle on the dev
chain. They share the stages from fulfillment onwards with the qualification modules,
which settle through Arkhai payments. `e2e_vm_guest_isolation` subclasses every stage
of the VM module and adds fourteen of its own
(`e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_guest_isolation.py`). All are in no
lane: the pipeline has no host.

**The native gates.** The pipeline's `native-ansible-gate` job builds the provisioning
image and runs `make test-provisioning-iac-native`, which runs the VM and family
native suites from the image's packaged trees with no network. `make
test-bare-metal-iac-native` runs the bare-metal working-data helper's native tests in a
container with `SYS_ADMIN` and AppArmor unconfined, mounting the checkout's
`domains/bare_metal/provisioning/iac` read-only (`Makefile`). No workflow runs it.
`shorten-the-end-to-end-pipeline` left it out because it had never run on a hosted
runner.

**Guest isolation.** `e2e_vm_guest_isolation` reports nine observations of its own.
Its last recorded run made eight; the ninth, a buyer from a private address reaching
their guest, is unproven under relay access for want of a route and under direct
access because the create masquerades the buyer's address. The runbook describes the
module under "Prove guest isolation" and does not list it among what the qualification
owes.

**Live disputes.** `e2e_vm_live_dispute` files on a running rate deal against a hosted
mediation authority, on mock provisioning. Its run for marketplace 0.4.0 made the
seller's filing, the buyer's filing and the storefront's contest; the policy's ruling
of the contested case is unproven
(`docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`).

**GPUs.** The real-provisioning target states a host's vCPUs, memory and disk and no
GPU, and allows one host per domain
(`e2e-tests/src/e2e_harness/real_provisioning_target.py`). The qualification modules
check that no GPU reaches a guest. No real GPU host is available to a qualification
deployment.

**Released.** `marketplace-v0.4.0` carries all of the above. Between that tag and the
development branch, the Ansible trees and both provisioning adapters differ in lock
files alone.

## Decisions

### D1 — Qualification is recorded per release candidate, and a real-host run is owed only when the Ansible layer changes

Real-provisioning qualification is a record the deployment makes for a release
candidate. It is not a milestone this or any change reaches.

A real-host run verifies the Ansible layer and how each provisioning adapter executes
it. It is owed again when a change touches either, and not otherwise. The question for
any real-hardware test is whether anything since the last qualified release changes
what the test would verify. A release whose changes touch neither rests on that
release's record, which stands.

The runbook's candidate rule is rewritten to this. A release that owes a run makes its
observations on its release candidate, and the release's known limits name whatever it
left unproven.

This change ships the scenarios and procedures the observations need and proves each
new one once against a target, so that a release can rely on it. It makes no release's
record, and its closeout waits on no release.

`qualify-per-period-bare-metal-and-setup-charges` states the same rule (its design,
D3). The rule has one home, `docs/guidance/repository/qualification-evidence.md`, and
whichever change lands first writes it there.

Rejected:

- Every observation made again on any change to source. No release meets it, and it
  spends real hardware repeating what the last run showed.
- All six observations made on the commit this change's closeout archives. The change
  would wait on hardware in closeout, and its evidence would be stale at the next merge
  that touched a role.
- Qualification as a roadmap gap a goal waits for. It is a property of each release.

### D2 — The hosted dispute scenario is not this change's

No scenario here files or follows a dispute. A dispute proves the payment and dispute
authorities, not delivery, which is why the live dispute scenarios run on mock
provisioning; nothing about one is particular to a real host.

What remains unmade live has owners. An operator's ruling of a buyer's contested case
is an acceptance criterion of `qualify-per-period-bare-metal-and-setup-charges`, and
bare-metal live scenarios are that change's too.

A deployment qualifying real provisioning still pins a dispute authority whose account
is real at its payments target, and nothing needs to answer at its origin
(`openspec/specs/test-compatibility/architecture.md`, "Ordinary Arkhai purchase
evidence").

Rejected: a live twin of the VM dispute controls scenarios on a fixed-term deal, kept
here. It would be a dispute scenario in a change about hosts.

### D3 — An access-mode observation is owed only where a deployment's pools offer that mode

The two-VM cycle is one observation per access mode: over a relay, and over direct
access. A deployment owes the one for each mode its pools offer. A deployment whose
pools all name a relay owes no direct-access observation, and its offers do not wait
for one.

`e2e_vm_qualification` names the observation it makes by its target's access mode. Run
against a direct-access target it checks that observation's preconditions before any
hold or purchase: the pool is drained, and no relay lease for it is unreleased.

Rejected:

- The direct-access observation owed by every deployment. A deployment selling only
  over relays could then never open, for want of a path it does not sell.
- Dropping the direct-access observation. Direct access is supported, and a deployment
  that offers it has nothing else to show the cycle on.

### D4 — Work that needs a GPU is a change of its own

Anything, anywhere in the repository, that requires GPUs is isolated to changes that
focus on GPU-specific concerns, and is not mixed into broader features that can be
validated on machines without GPUs.

The paid GPU purchase with checked GPU work is `qualify-paid-gpu-purchases`, deferred
until a GPU host is available to a qualification deployment. It owns the definition of
checked GPU work, the target's GPU capacity and host count, and the runbook's sentence
keeping GPU offers closed.

Every scenario, procedure and gate in this change is satisfied on machines without a
GPU: the relay probes, the two-VM cycle, the bare-metal cycles on a whole machine sold
without GPU work, the reapply, the Alkahest real modules' GPU-less shape, guest
isolation, and the native gate.

Rejected: a GPU section planned last in this change. The change would be held open by
hardware nobody has, for work unrelated to the rest of it.

### D5 — The change sits with the lesser goal "Reach hosts and VMs that have no inbound route"

This change and `qualify-paid-gpu-purchases` are listed in the change index's campaign
"Lesser goal — Reach hosts and VMs that have no inbound route", beside their
predecessors: `prove-real-vm-provisioning`, `qualify-arkhai-real-provisioning`,
`qualify-real-provisioning-by-scenario` and `bound-bare-metal-working-data`.

Goal 1's value is that the storefront holds no physical authority, and that is current
state. This change is qualification and coverage of the path that reaches hosts. Under
D1 qualification is a property of each release, so no goal waits for it. The roadmap
keeps no rows for lesser goals; the gaps are stated in the two changes' index rows.

Rejected: keeping them under Goal 1. Its open-gap table would carry rows whose closing
changes nothing about where physical authority lies.

### D6 — What is left stays one change

The runbook's rule, observations 1 and 3, the Alkahest real modules' trigger and the
native gate are one change. Each is small, none has another open change to live in,
and all concern how real provisioning is shown to work.

Rejected: a change for each. Four designs, reviews and closeouts for pieces that share
their documents.

## Open Questions

Each is decided in this change's design session.

### Q1 — Observation 1's means, and its three signed-grant probes

The owner prefers a handbook procedure over a new command where an existing
administrator API covers the case. None covers issuing a probe grant.

- (a) A runbook procedure with the probes an operator can build without the relay's
  signing key, and the other two left to the plugin's own suite.

  | Probe | Grant sent | Refusal required |
  |---|---|---|
  | No grant | None | `grant_missing` |
  | Forged | A grant under a configured key id, signed with a key generated for the probe | `signature_invalid` |

  ```toml
  [[proxies]]
  name = "example-forged-probe"
  type = "tcp"
  localIP = "127.0.0.1"
  localPort = 22
  remotePort = 6100
  metadatas.grant = "<grant signed with the probe's own key>"
  ```

  `port_mismatch` and `port_outside_range` then rest on `make -C
  tools/frp-grant-admission test-frp` and on the procedure's first step, which records
  the deployed configuration's issuer ranges and key thumbprints. Observation 1 is
  reworded to two refusals at a deployed relay. No surface is added. What a deployed
  relay no longer shows is that its own issuer range is the one enforced.
- (b) A compute-family operator job, submitted like `diagnose_host`, that has the
  provisioning service sign deliberately wrong grants for an unleased port of the
  relay and present each through a relayed host's pinned client, reporting the refusal
  each drew.

  ```json
  {"relay_id": "relay-a", "host": "kvm-1", "probe_port": 6100, "refusals": {
    "grant_missing": "grant_missing", "signature_invalid": "signature_invalid",
    "port_mismatch": "port_mismatch", "port_outside_range": "port_outside_range"}}
  ```

  It makes observation 1 a scenario stage in both domains' qualification modules, from
  one implementation in the family's relay machinery. It is a new provisioning action,
  an Ansible task file and a result parse, with a mock default, and it signs grants
  for something other than a lease.
- (c) An administrator route that issues a probe grant for a named port, which the
  operator presents by hand. It is a second signer of grants; a grant for an in-range
  port is a working grant.

Recommended: (a). It asks nothing new of the service and leaves an operator a
procedure they can run today. It would move to (b) if observation 1 is to be made at
every release that owes a run, by a module, without an operator at the relay. (c) is
not recommended.

### Q2 — The Alkahest real-provisioning modules: keep, retire, or name their trigger

No workflow in this repository reaches a real host, so a trigger can only be the
deployment's, stated here as what the repository relies on.

- (a) Keep both. `docs/release-handbook.md`, "The deployment's part", and the runbook
  name the modules a release's real-host run consists of when one is owed under D1:

  ```text
  e2e_vm_qualification              e2e_vm_real_provisioning
  e2e_bare_metal_qualification      e2e_bare_metal_real_provisioning
  e2e_real_provisioning_reapply     e2e_vm_guest_isolation (see Q3)
  ```

  Documentation only.
- (b) Retire `e2e_bare_metal_real_provisioning` and keep the VM module, which guest
  isolation subclasses. Bare metal then has no real-host evidence of a deal settled
  through Alkahest.
- (c) Rebase guest isolation onto the purchase stages and retire both. No real-host
  evidence of the Alkahest mechanism or of the stages before fulfillment remains.

Recommended: (a). The modules are the only real-host evidence for one of the two deal
mechanisms, and naming them costs a paragraph. It would move to (b) or (c) if Alkahest
on real hosts is not something a release should show.

### Q3 — Whether the guest-isolation observations are among what a release owes

- (a) They are owed for VM offers when a run is owed under D1. The runbook's list
  names them, with the private-address observation's known limit stated as a limit and
  not as a failure.
- (b) They are not part of what a release owes. The runbook says so, and the module
  stays a proof made once, by the change that built the isolation, and again when host
  preparation's guest policy changes.
- (c) Only the observations a relay-access deployment can make are owed.

Recommended: (b), read through D1. Guest isolation is the Ansible layer's behaviour,
so D1 already owes its module again whenever that layer's guest policy changes, and a
separate entry in the list of six would say the same thing twice. It would move to (a)
if the list is meant to be everything a real-host run consists of, in which case Q2's
list and this one are the same list.

### Q4 — A teardown after an interrupted create

A lease can end while its create is in flight, and the release guard holds its
capacity until the create settles and teardown is proven. With a delivery deadline
recorded at commit, as `renewable-compute-lease-deadlines` records it, every delivery
slower than its deadline is reclaimed mid-create. The site's part is proven in
`kit/site` and in a lane, where a provisioning job is held at a gate under lane time.
What a lane cannot show is that a real host is left clean when teardown follows an
interrupted create. That behaviour is the provisioning roles', and the six
observations cover teardown of delivered machines only.

- (a) No new observation. The roles are unchanged, and D1 owes a real-host run when
  they change.
- (b) A seventh observation, for each domain: a lease reclaimed while its create runs,
  then the host shown clean — no guest, account, tenant data or relay proxy left, and
  capacity restored. A stage in each qualification module ends a lease before its
  create job settles.
- (c) The observation stated in the runbook as owed, with no scenario, made by an
  operator's procedure until a scenario exists.

Recommended: (b). The path exists today and has never been observed on a host, and
`renewable-compute-lease-deadlines` makes it routine. It would move to (a) if the
roles' create and teardown are shown, by their own tests, to be safe at any point of
interruption.

### Q5 — What counts as touching the Ansible layer, and where a release's record is stated

D1's rule needs something a releaser can apply.

- (a) A path list in `qualification-evidence.md`. A release owes a run when the diff
  from the last qualified release's tag touches any of:

  ```text
  provisioning/compute/iac/            domains/vms/provisioning/iac/
  provisioning/compute/ansible/        domains/bare_metal/provisioning/iac/
  domains/vms/provisioning/adapter/    domains/bare_metal/provisioning/adapter/
  ```

  Between `marketplace-v0.4.0` and the development branch those paths differ in three
  lock files alone, so the list also has to say whether a lock change counts.
- (b) The rule as prose, applied by judgement at each release, with the release
  description saying which it was:

  ```markdown
  **Known limits.** No real-host run was owed: nothing since 0.4.0 touches the Ansible
  layer or how an adapter executes it. Real-provisioning qualification rests on 0.4.0's
  record.
  ```
- (c) Both: the list as the default reading, and the release description stating the
  outcome either way.

Whether the relay's admission plugin and the pinned relay binaries count is part of
this question: observation 1 verifies them, and they are neither Ansible nor an
adapter.

Recommended: (c). A list makes the rule checkable and the description makes each
release's reading visible. A check that enforces the list is not proposed.

### Q6 — How the module names its observation

- (a) One module, its observation read from the target's access mode, and the other
  mode's observation logged as not owed by this target:

  ```text
  observation 2 (two concurrent VM deals, relay access): made
  observation 3 (two concurrent VM deals, direct access): not owed — target access is relay
  ```
- (b) A second marker, `e2e_vm_direct_qualification`, subclassing the first module's
  stages and adding the precondition stages.
- (c) One observation with two recorded variants, the runbook's list renumbered.

Bare metal's observations 4 and 5 name the relay endpoint. Whether they are stated per
access mode as the VM cycle is belongs here, since the two domains should differ as
little as they can.

Recommended: (a), with bare metal's wording made mode-neutral in the same edit. The
precondition check and the naming are proven by the module's unit tests over sample
targets; the direct-access run itself is owed when a deployment offers direct access
(D3).

### Q7 — Where the bare-metal native gate runs

- (a) A step in the `native-ansible-gate` job, which already builds the image the gate
  runs in:

  ```yaml
      - name: Native Ansible gate
        run: make test-provisioning-iac-native
      - name: Bare-metal cleanup native gate
        run: make test-bare-metal-iac-native
  ```
- (b) A job of its own, so a refusal of its container cannot fail the other gate. It
  builds the image a second time.
- (c) A narrower gate that needs no `SYS_ADMIN`, if a hosted runner refuses the
  container.

One more point for the session: this gate mounts the checkout's tree, where the other
runs the image's packaged trees, so it does not show the image carries the helper.

Recommended: (a), by the precedent of the job itself, moving to (c) only if the hosted
runner refuses the container.

### Q8 — The shape of a new or extended scenario

A consequence to confirm, not a choice. Any scenario this change adds or extends
follows `docs/guidance/engineering/system-tests.md` and `test-compatibility`'s "An
external-topology scenario extends a locally verifiable scenario": it extends a lane
twin, runs on wall time, reports each observation made, failed or unproven through
`e2e-tests/tests/e2e/roles/helpers/qualification.py`, states what a topology must
provide in `e2e-tests/README.md`, and funds nothing.

### Q9 — Order with the neighbouring changes' edits

A consequence to confirm. Three open changes edit text this one edits:
`qualify-per-period-bare-metal-and-setup-charges` (the rule of D1),
`report-provisioning-failures-to-operators` (observation 5's notification clause) and
`harden-shared-relays` (the runbook's relay section). Each pair is resolved by the
second to land reverifying against the first; none is a dependency.

Provisional, for planning and review to confirm:

- **Documentation.** The runbook's sections on running the real-provisioning
  scenarios, preparing buyer relays and qualifying a purchase;
  `docs/guidance/repository/qualification-evidence.md`;
  `docs/guidance/repository/ansible-gates.md`; `docs/development/TESTING.md`, "The
  real-provisioning lane"; `docs/release-handbook.md`; `e2e-tests/README.md`.
- **Requirements to modify.** `test-compatibility`'s "Real-provisioning qualification
  scenarios make the owed observations" and the scenario "Direct access is qualified"
  under "Equivalent physical proof preserves lifecycle invariants".
- **Test level.** System, external-topology, for a scenario; unit for the helper's
  judgements, as `e2e-tests/tests/unit/test_qualification_helper.py` holds them today.
- **Evidence.** A sanitized summary per observation under `docs/attachments/`, in the
  form of `docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`.
