## Why

Every market domain intended for deployment must prove a complete deal —
discovery, negotiation, settlement, delivery, and domain-defined teardown — against
running services. VM proves it on every pull request, with the provisioning service
running its mock profile. Bare metal proves it nowhere that runs: its only complete-deal
scenario, `test_bare_metal_complete_deal`, needs a real whole host to SSH into and a
hosted settlement authority, and the end-to-end pipeline runs in GitHub Actions, where
neither exists. It skips on every run.

`bare-metal-publication-reads-pool-declarations` gives bare metal its own end-to-end
lane, with a single mock-profile site, a bare-metal storefront, a registry, and a dev
chain, and proves publication there. It stops before a deal. This change proves the
deal on that lane.

Three things stand in the way:

- **The mock produces VM results.** Bare-metal grant and reclaim jobs already go
  through the same job service, and so through the programmable mock Ansible service
  the mock profile installs. But the mock's default result is a VM creation; bare-metal
  fulfillment reads a tenant user, host, and SSH port instead, so a deal would fail at
  delivery.
- **The bare-metal storefront's loops cannot be held or stepped.** It runs a negotiation
  watchdog and a settlement-servicing worker on timers with no pause, so a scenario
  cannot drive their transitions deterministically, as `TESTING.md` requires of every
  loop an end-to-end test advances.
- **No scenario exists for it.** The release-qualified scenario asserts real SSH access
  and its revocation, which no mock can satisfy.

## What Changes

- Give the bare-metal provisioning adapter a mock of its own, mounted by the mock
  profile: a successful grant returns the access coordinates bare-metal fulfillment
  reads, a reclaim succeeds, and when→then rules can override either, as VM's mock
  allows. Bare-metal execution, which runs inside the VM adapter today, gains the seam
  that mock needs.
- Add lifecycle controls to the bare-metal storefront matching the canonical storefront
  client: a pause that holds its loops, a resume, and an explicit single step per loop
  that runs exactly the cycle its timer runs, alongside the publication step
  `bare-metal-publication-reads-pool-declarations` adds.
- Add a mock-provisioned complete-deal scenario to the bare-metal lane, driven through
  typed clients only: discovery, negotiation, Alkahest settlement on the lane's dev
  chain, fulfillment through the mock, the buyer-safe result and access view, teardown,
  and the site's capacity returned.
- Keep the release-qualified real-host scenario, unselected, until the replacement
  scenario is written, migrating what is useful from it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: a deployable domain's deal path runs on every end-to-end run
  against mock provisioning, distinctly from any protected real-host evidence.

## Non-Goals

- Real SSH access or its revocation; that remains the protected lane's.
- Hosted (Stripe) settlement in the lane; the lane has no hosted authority.
- Finding bare-metal supply by hardware filters, owned by `bare-metal-listing-shapes`.
- Multiple sites, or a site trusting several storefronts (roadmap Goal 1).
- Changing bare-metal negotiation, settlement, or fulfillment behaviour. Defects the
  scenario surfaces in those are bare-metal findings, recorded against their owning
  change rather than absorbed here.

## Impact

- The bare-metal provisioning adapter (its own mock) and the VM adapter's job service,
  which executes bare-metal actions today (the seam that mock needs).
- `domains/bare_metal/storefront/`: lifecycle pause, resume, and step routes; its
  negotiation watchdog and settlement-servicing worker become holdable.
- `e2e-tests/`: the deal scenario on the bare-metal lane, and whatever shared domain-deal
  helpers it needs generalized.
- `openspec/changes/bare-metal-and-credits-domain-stacks/`: its bare-metal deal path is
  evidenced here.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/test-compatibility/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A deployable domain's deal path runs on every end-to-end run against mock
  provisioning, distinct from protected real-host evidence —
  `openspec/specs/test-compatibility/spec.md`.
- The bare-metal storefront's loops follow the pause-and-step convention —
  `docs/development/TESTING.md`'s loop table.

## Dependencies

Depends on `bare-metal-publication-reads-pool-declarations`, which builds the bare-metal
end-to-end lane, splits the pipeline into VM and bare-metal jobs, and adds the
publication step. Supplies the bare-metal deal-path evidence
`bare-metal-and-credits-domain-stacks` requires for Goal 4, short of real access, which
stays with the protected lane.
