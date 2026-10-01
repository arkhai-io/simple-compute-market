## Why

Every market domain intended for deployment must prove a complete deal —
discovery, negotiation, settlement, delivery, and domain-defined teardown — against
running services. VM proves it on every pipeline run with a typed-client scenario that
holds every loop, previews every transition with a dry run, and advances it explicitly,
against the provisioning service's mock profile. Bare metal proves it nowhere that runs:
its only complete-deal scenario needs a real whole host and a hosted settlement
authority, and the end-to-end pipeline runs in GitHub Actions, where neither exists and
neither ever will.

`bare-metal-publication-reads-pool-declarations` gave bare metal its own lane, with a
mock-profile site, a bare-metal storefront, a registry, and a dev chain, and proved
publication there. This change brings the bare-metal deal on that lane to parity with
VM's. What stands in the way:

- **The mock produces VM results**, and bare-metal execution has no seam of its own: its
  jobs run through VM's job service and its one Ansible service.
- **Bare metal negotiates through a domain-local, round-0-only copy** rather than the kit
  negotiation runtime, so it has no multi-round negotiation or force-accept.
- **The storefront lacks the deal controls** VM's scenario drives: stage events,
  evaluate-negotiate, force-accept, settle verify and evaluate, settle wait, admin
  reserve, and the capacity-released callback. Where VM has them, force-accept bypasses
  the runtime's acceptance hooks and evaluate-negotiate skips the opening's own guards.
- **Fulfillment never starts on the Alkahest path**; it waits for a buyer call no buyer
  makes, and the settlement-servicing worker that would retry it exists only with hosted
  settlement.
- **Release has two owners and bypasses the fulfillment aggregate**: lease expiry submits
  a raw reclaim job, and buyer teardown makes the storefront release site capacity itself.
- **No scenario exists**, and stage definitions are VM's alone.

The pipeline itself also needs restructuring: every lane rebuilds every image, and the
API-credit deal runs inside the VM lane.

## What Changes

- Give compute provisioning an executor table keyed by `(offering_mode, action)` that
  adapter bundles populate and VM's job service resolves through. Move the mock
  rule-and-gate mechanism into a compute-family module, `compute_provisioning.executor_mock`,
  rebuild VM's programmable mock on it, and give the bare-metal adapter its own mock
  under the mock profile, with its own `/test/bare-metal` rule routes.
- Compose bare metal onto `kit/negotiation-runtime` through its existing routes and
  delete its domain-local negotiation (migrated from `bare-metal-and-credits-domain-stacks`
  4a.1, 4a.2, and the runtime half of 4a.3).
- Move the deal controls into kit as framework-free route services, bound by every
  storefront that has or needs them (implemented in place of the corresponding part of
  `kit-owned-storefront-shell`). Force-accept goes through a new administrative
  acceptance on the negotiation runtime, so domain holds and artifacts are always
  recorded; evaluate-negotiate becomes a side-effect-free preview of the full opening,
  taking the opening request as its body.
- Start bare-metal fulfillment when settlement verifies the escrow through the kit
  settlement-servicing worker, composed for every mechanism rather than only hosted
  settlement, and retire `POST /api/v1/fulfillments/begin`.
- Make the lease lifecycle the only owner of release for every offering mode: lease
  release delegates to durable fulfillment teardown, buyer teardown goes through lease
  termination, and the storefront's direct site release is removed.
- Give bare-metal publication a dry run.
- Share compute deal stages in `compute_deal_stages.py` with a per-domain driver, move
  VM's scenario onto them, and add the bare-metal mock-provisioned deal.
- Prove bare-metal storefront restart recovery at integration level, as VM's is.
- Build pipeline images once and share them across lanes; give API credits its own lane
  (migrated from `apicredits-end-to-end-lane`).
- Keep the real-host scenario, deactivated; move the buyer CLI requirements to
  `bare-metal-and-credits-domain-stacks`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: a deployable domain's deal runs on every pipeline run against
  its ordinary local authorities, with compute provisioning in its mock profile where
  delivery crosses it; compute domains share deal stages; every lane runs on images
  built once; bare-metal storefront restart recovery is proven at integration level.
- `market-composition`: storefront deal controls are kit-owned route services;
  administrative acceptance and opening previews go through the negotiation runtime;
  compute mock executors share one compute-family mechanism.
- `physical-provisioning`: lease release delegates to durable fulfillment teardown for
  every offering mode; storefront teardown goes through lease termination; job execution
  resolves its executor by offering mode and action from a compute-provisioning table.
- `storefront-publication`: bare-metal fulfillment starts at settlement verification,
  and bare-metal teardown releases capacity through the site's lease lifecycle.

## Non-Goals

- Real SSH access or its revocation; that remains the protected lane's.
- Hosted (Stripe) settlement in the lane; the lane has no hosted authority.
- Moving bare metal onto the shell's shared routes, or the rest of the shell extraction.
- Moving bare-metal execution or its job storage out of the VM adapter.
- Moving `BareMetalFulfillmentTransport` into the bare-metal domain package; the shell
  decides where route clients live.
- Holding and stepping API-credit loops in its lane, and API-credit production-application
  integration tests; `apicredits-end-to-end-lane` keeps them.
- Multiple sites, or a site trusting several storefronts (roadmap Goal 1).

## Impact

- The VM adapter's mock, test controller, and job service; the bare-metal provisioning
  adapter's runtime, mock, routes, and release.
- `provisioning/compute`: the `(offering_mode, action)` executor table, the
  compute-family mock mechanism, provider-neutral release executor and job port, release
  dispatcher composition, and the provisioning client's route contracts.
- `kit/negotiation-runtime`: administrative acceptance and opening preview.
  `kit/settlement-runtime`, `kit/capacity-publication`, and `kit/storefront`:
  deal-control route services and the evaluate-settle hook. `core/storefront`: the
  bypassing `NegotiationService.force_accept` removed; `core/storefront-client`:
  `evaluate_negotiate` takes the opening request.
- `domains/vms/storefront` and `domains/apicredits/storefront`: rebinding to the kit
  route services and removing their copies.
- `domains/bare_metal/storefront`: negotiation on the kit runtime, deal controls,
  settlement-started fulfillment, teardown through lease termination, the
  capacity-released callback, the publication dry run, restart integration tests.
- `domains/bare_metal/buyer`: `begin()` removed from the fulfillment transport.
- `e2e-tests`: shared compute deal stages, VM's scenario moved onto them, the bare-metal
  scenario and driver, shared helpers, the bare-metal buyer dependency, lane targets.
- Root `Makefile`, compose files, and `.github/workflows/e2e.yml`.
- `openspec/changes/bare-metal-and-credits-domain-stacks/`,
  `openspec/changes/kit-owned-storefront-shell/`, and
  `openspec/changes/apicredits-end-to-end-lane/`: migrated scope recorded.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the deal-control route services in the kit
      layers, the compute-provisioning executor table and mock mechanism, release
      ownership, and the bare-metal fulfillment hook statement, which is stale today.
- [x] `docs/development/TESTING.md` — three lanes on shared images, the loop table's
      bare-metal publication dry run, shared compute deal stages, the mock profile's
      per-adapter executors, and the stale "blocked—not mocked" bare-metal statement.
- [x] Existing subsystem specification — `test-compatibility`, `market-composition`,
      `physical-provisioning`, `storefront-publication`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A deployable domain's deal runs on every pipeline run against its ordinary local
  authorities, with compute provisioning mocked where delivery crosses it; compute
  domains share deal stages; lanes run on images built once —
  `openspec/specs/test-compatibility/spec.md`, `docs/development/TESTING.md`.
- Storefront deal controls are kit-owned route services; administrative acceptance and
  opening previews go through the negotiation runtime; compute mock executors share
  `compute_provisioning.executor_mock` — `openspec/specs/market-composition/spec.md`,
  `docs/development/ARCHITECTURE.md`.
- Job execution resolves its executor by `(offering_mode, action)` from a
  compute-provisioning table — `openspec/specs/physical-provisioning/spec.md`,
  `docs/development/ARCHITECTURE.md`.
- Lease release delegates to durable fulfillment teardown for every offering mode, and
  storefront teardown goes through lease termination —
  `openspec/specs/physical-provisioning/spec.md`, `docs/development/ARCHITECTURE.md`.
- Bare-metal fulfillment starts at settlement verification —
  `openspec/specs/storefront-publication/spec.md`, `docs/development/ARCHITECTURE.md`.

## Dependencies

Depends on `bare-metal-publication-reads-pool-declarations` (archived), which built the
bare-metal lane, and `kit-owned-storefront-loop-lifecycle` (archived), which built the
bare-metal lifecycle pause and steps. No active dependency.

Takes over, and records as migrated in the source change:
- `bare-metal-and-credits-domain-stacks` 4a.1, 4a.2, and the runtime half of 4a.3;
- the deal-control route services from `kit-owned-storefront-shell`'s scope;
- the separate API-credit lane from `apicredits-end-to-end-lane`.

Hands to `bare-metal-and-credits-domain-stacks` its former tasks 3.1–3.4 and the
`buyer-orchestration` delta. Supplies that change's pipeline deal evidence for Goal 4,
short of real access, which stays with the protected lane.
