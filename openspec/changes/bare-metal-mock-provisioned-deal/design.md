# Design — bare-metal mock-provisioned deal

## Context

Found while designing the end-to-end evidence for
`bare-metal-publication-reads-pool-declarations`. That change proves publication on a
new bare-metal lane and deliberately stops before a deal, which would exercise
negotiation, settlement, fulfillment, and teardown paths it does not touch.

What the codebase does today, verified 2026-09-25:

- **The end-to-end pipeline runs only in GitHub Actions**, with no Kubernetes cluster
  and no live host inventory, and never will have either.
- **The provisioning service's mock profile** (`ACTIVE_PROFILES=mock`) replaces the VM
  adapter's Ansible service with `ProgrammableMockAnsibleService` and mounts the `/test/*`
  controller, whose when→then rules can shape, pause, or fail any job. VM's deal
  scenarios run against it.
- **Bare-metal jobs already reach that mock.** The bare-metal operations service submits
  grant and reclaim jobs (`NODE_GRANT_ACCESS_ACTION`, `NODE_RECLAIM_ACCESS_ACTION`)
  through the VM runtime's job service, so they execute through the same Ansible
  service the mock replaces.
- **The mock's default result is a VM creation** (`_FAKE_STDOUT`: a VM name, tenant
  user, external SSH port). The bare-metal fulfillment provider reads a grant's tenant
  user, host, and port under its own keys, so a default mock result is not a bare-metal
  one. The provisioning service's integration tests already fake a bare-metal grant's
  playbook output, so the shape is known.
- **The bare-metal storefront starts two unpausable loops** at startup: the negotiation
  watchdog and the settlement-servicing worker. `TESTING.md` requires every loop an
  end-to-end scenario advances to offer a pause and an explicit step that works while
  held, and names the traps of a loop with none.
- **The canonical storefront client already speaks lifecycle controls**:
  `admin_pause_lifecycle_loops`, `admin_resume_lifecycle_loops`,
  `admin_run_lifecycle_cycle(loop)`, and `admin_dry_run_lifecycle_cycle(loop)`, which the
  VM storefront implements. `bare-metal-publication-reads-pool-declarations` adds the
  bare-metal `publication` step.
- **The release-qualified scenario** (`test_bare_metal_complete_deal`) SSHes into the
  leased host and asserts access is revoked after teardown. The permanent
  `test-compatibility` requirement "Bare-metal hosted evidence is attributed by layer"
  says whole-host release acceptance must observe real access and revocation on a
  disposable host, and that mocks do not satisfy it.

## Decisions

### The deal runs on the bare-metal lane, against the mock

The deal scenario runs on the lane `bare-metal-publication-reads-pool-declarations`
builds: one site in the mock profile, trusting the bare-metal storefront, a bare-metal
registry, and the dev chain. It proves what VM's mock-provisioned deals prove — that
the services compose into a working deal — and reports nothing about a real host.

### Mock provisioning gets bare-metal results, not a second mock

Bare-metal jobs already reach the programmable mock, so this change adds bare-metal
results to it rather than a parallel mock: a grant returns the access coordinates the
bare-metal fulfillment provider reads, and a reclaim succeeds. The `/test/*` rules keep
the power to override either, which is what lets a later scenario exercise a failed
grant or a slow reclaim.

### Every loop the scenario advances can be held and stepped

The bare-metal storefront's negotiation watchdog and settlement-servicing worker gain
the lifecycle pause and per-loop step the canonical client already calls, joining the
publication step. A step runs exactly the cycle the timer runs, whether or not the
loops are held, so a scenario advances production behaviour rather than a test path;
the pause holds every loop at once, as VM's does.

### The scenario uses typed clients only

Discovery goes through the registry client, and the seller side through
`StorefrontClient` and whatever typed buyer client the bare-metal domain owns; the
scenario does not run the `market` command. Its domain-specific assertions — the
listing, the access result, the teardown carrier — go through the shared domain-deal
helpers as codecs, not copied VM orchestration, per "Per-domain end-to-end deal path".

### Teardown is proven up to the site, not the host

With no host, teardown is observed as far as it is observable: the storefront reports
the lease torn down, the site's capacity for that Physical Resource returns, and the
next publication pass reopens its listing. That access was actually revoked stays the
protected lane's evidence.

### The lane settles through Alkahest

The lane has no hosted authority, and a backed whole-host listing that settles by
introduction is the unbacked case `unbacked-bare-metal-listings` owns. Alkahest on the
lane's dev chain is how a backed bare-metal listing settles without a hosted service,
and the lane already needs the chain for publication's Alkahest options.

### The bare-metal mock is the bare-metal adapter's own

Decided with the maintainer. The programmable mock is the VM adapter's and doubles for VM
fulfillment; it does not double for another domain. The bare-metal provisioning adapter
gets a mock of its own, mounted by the same mock profile, returning the results its own
fulfillment provider reads and accepting when→then rules as the VM mock does. Where the
two mocks turn out to share mechanism — rule matching, pause gates, job waiting — that is
a candidate for a kit, discussed when the bare-metal mock is written rather than
extracted in advance.

**Consequence found while recording this.** Bare-metal grant and reclaim do not execute in
the bare-metal adapter today. The bare-metal operations service submits them through the
VM runtime's job service, whose Ansible service recognizes the bare-metal actions
(`_BARE_METAL_ACTIONS`) and parses their results (`node_grant_access_data`). The VM mock
intercepts them only because it replaces that service. A bare-metal mock therefore needs
bare-metal execution to have a seam of its own, which means at least giving the job
service a way to hand bare-metal actions to a bare-metal-owned executor, real or mock,
and possibly moving bare-metal execution out of the VM adapter. How far to go is settled
when this change is planned (1.5).

### The buyer side uses the client built for each backend, mirroring VM

Decided with the maintainer. Each call goes through the typed client built for the
backend it calls, and the scenario mirrors VM's typed-client deal,
`e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal.py`: fulfillment, access, and
teardown are driven and observed the way that scenario drives and observes them,
including reading fulfillment state through the site's own client and holding provider
teardown at a mock gate. Where no typed client covers a bare-metal backend route yet, the
plan adds the method to the client that owns that backend rather than building requests
by hand.

### The real-host scenario stays until its replacement is written

Decided with the maintainer. `test_bare_metal_complete_deal` stays, unselected, until the
mock-provisioned deal scenario exists, since it has code worth migrating — its
domain-deal state, buyer run handling, and teardown polling. Whether it is then removed,
and what that means for the permanent protected-lane requirement, is decided when the
replacement lands.

### Pause holds every loop; every transition is stepped

Decided with the maintainer, following VM's convention. The lifecycle pause holds every
loop the bare-metal storefront runs — the negotiation watchdog and the settlement-
servicing worker — and each loop has its own step, alongside the publication step. The
scenario pauses once at the start, as VM's session fixture does, and deliberately
invokes every state transition it depends on; nothing advances on a timer while it runs.

## Risks / Trade-offs

- **The deal surfaces bare-metal defects outside this change** → likely, since bare metal
  has never completed a deal in CI. They are recorded against their owning change.
- **Buyer discovery by filter does not find bare-metal listings** until
  `bare-metal-listing-shapes` lands, because the compute schema's filters read top-level
  fields a bare-metal listing does not have. The scenario discovers by listing identity,
  and says so.
- **Mock results drift from real playbook output** → the bare-metal result shape comes
  from the adapter that parses it, and the provisioning service's own tests keep the two
  agreeing.
