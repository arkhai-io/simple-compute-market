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
- **Bare-metal execution lives in the VM adapter.** The VM adapter owns the
  provisioning-wide job engine, Ansible runner, host registry, and service-wide routes,
  knows bare-metal vars and facts, and hosts bare metal's playbook; both adapters import
  the deployed service.

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
  4a.1, 4a.2, and the runtime half of 4a.3). What the two compute storefronts share is
  built once in kit first, with VM and API credits rebound to it: the runtime rechecks a
  listing against its source before every seller round and every acceptance through a
  domain-contributed check, with VM's inventory guard moved to `kit/policy`; a retryable
  refusal for a source that cannot be confirmed; one process-local trading pause; and a
  thread recorded as successful only after its agreement and plan.
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
- Move provisioning execution out of the VM adapter: the durable job engine and host
  authority into `compute_provisioning`, defined as the compute family kit; shared
  Ansible mechanics into a sibling family-kit distribution, `provisioning/compute/ansible`;
  each domain contributes only its codec, playbooks, preparation, and result meaning.
  Neither adapter imports the other or the deployed service. The composition root
  builds the one job authority and the one host authority and hands both to every
  adapter runtime.
  Once that boundary is proven, job-backed fulfillment becomes the family's: one provider
  in `compute_provisioning` submits through one job submission, reads status, and
  delivers, and each domain contributes only its preparation and its codec. A codec
  reports a create as typed delivery evidence, which the provider validates before the
  create succeeds; the delivery says only how to reach what was provisioned; teardown is
  prepared from the create job's own parameters; jobs correlate on the capacity
  reservation rather than a deal reference; provisioning names the guests it creates; and
  lease registration by the storefront is removed, once when a lease begins is decided.
  Job results and credentials are stored and served as envelopes, executors classify
  retryability and redact, a cancelled job stays cancelled, and hosts carry a connection
  envelope whose codec belongs to its implementation (only `ssh` today); connection
  secrets are protected by their codec before they are stored, opaque to the host
  authority, and decrypted only by their codec at execution. Being
  pre-release, this changes the host, job-credential, and generic lease wire formats and
  their schemas directly, through forward migrations, with no compatibility layer.
- Give the family's wire contract and its client thin distributions of their own: the
  wire models and route contracts move to `provisioning/compute/contracts`, and both
  existing generic clients are replaced by `provisioning/compute/client`, async and sync,
  with VM keeping a small extension for its own operations. `VersionedEnvelope` moves to
  `arkhai-core`, so the contracts carry no kit weight. Routes the provisioning service hosts
  for other capabilities keep their owners: resource pools get thin contracts and client
  distributions of their own, capacity-definition import joins `kit/site-client`, and
  Ansible host import moves to the Ansible distribution.
- Consolidate leases on one family surface that records and releases and never delivers:
  VM's lease routes are absorbed into it, bare metal's lease routes (and the access grant
  they made outside fulfillment) are deleted, there is no lease update, a registered lease's
  end moves only through the site's truncation, lease registration writes the lease tail
  once, `commit` neither resurrects a lease nor moves a registered lease's window, and the
  lease lifecycle and release are mode-agnostic. A lease that was never delivered is
  released by what its fulfillment proves, and an uncommitted hold is released rather than
  truncated. The site authority frees capacity only behind a release guard the
  provisioning composition supplies, replacing the settlement-abandonment hook. Every
  route on the provisioning service admits the administrator.
- Delete the generic executor-action route, its contract job routes, and the
  compute-adapter architecture behind them, so delivery happens only through fulfillment.
- Serve the family's job, host, lease, and test-job routes from framework-free route
  services the provisioning service binds, with adapters binding their own routes through
  accessors rather than reaching into the service's module state; report execution
  readiness in system status instead of a route of its own; record the five-piece route
  pattern in `ARCHITECTURE.md`.
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
  compute mock executors share one compute-family mechanism; the runtime rechecks a
  listing's source before every seller round and acceptance, refuses a source it cannot
  confirm as retryable, and records success only after the agreement and plan; the
  trading pause is one process-local kit mechanism.
- `physical-provisioning`: compute provisioning owns the job and host authorities;
  adapters contribute preparation and meaning while shared execution technology invokes
  it; job, host, and readiness wire models are compute-owned; no adapter imports another
  adapter or the deployed service; lease release delegates to durable fulfillment teardown for
  every offering mode; storefront teardown goes through lease termination; job execution
  resolves its executor by offering mode and action from a compute-provisioning table;
  leases have one family surface that records and releases, with no lease written by a
  caller: commit begins a lease, and provisioning records its executor target when the
  fulfillment becomes active; every provisioning route admits the administrator;
  execution readiness is reported in system status; host connectivity is probed by
  connection kind; the family's wire contract and client are thin distributions; delivery
  happens only through fulfillment; an undelivered lease is released by what its
  fulfillment proves; host import belongs to the implementation that reads its format;
  executor registration is the job executor table's.
- `site-capacity`: a reservation's lease tail is written once; `commit` neither resurrects
  a lease nor moves a registered lease's window; lease truncation neither resurrects nor
  extends a lease, and refuses an uncommitted hold; every capacity reclaim consults a
  composition-supplied release guard, which replaces the settlement-abandonment hook;
  capacity-definition import has a thin typed client.
- `compute-provisioning-contract`: the versioned executor action submission is removed;
  jobs are submitted by fulfillment providers.
- `resource-pool-management`: the pool wire contract and client are thin distributions.
- `fulfillment`: `VersionedEnvelope` is provided by `arkhai-core`.
- `storefront-publication`: bare-metal fulfillment starts at settlement verification,
  and bare-metal teardown releases capacity through the site's lease lifecycle; the
  inventory guard's recheck runs before every seller round and acceptance, and a backed
  bare-metal listing is checked for availability; an accepted thread is successful only
  once its agreement and plan are recorded, rather than persisted atomically.

## Non-Goals

- Real SSH access or its revocation; that remains the protected lane's.
- Hosted (Stripe) settlement in the lane; the lane has no hosted authority.
- Moving bare metal onto the shell's shared routes, or the rest of the shell extraction.
- Moving `BareMetalFulfillmentTransport` into the bare-metal domain package; the shell
  decides where route clients live.
- Holding and stepping API-credit loops in its lane, and API-credit production-application
  integration tests; `apicredits-end-to-end-lane` keeps them.
- Multiple sites, or a site trusting several storefronts (roadmap Goal 1).

## Impact

- The VM provisioning adapter loses its job engine, Ansible runner, host registry, mock
  runners, job and host models, and service-wide routes, keeping its codec, playbooks,
  relays, pool configuration, operations, and routes; the bare-metal provisioning
  adapter gains its codec, access parameters, and playbook and role, and loses every
  import of the VM adapter and the deployed service.
- New `provisioning/compute/ansible` distribution (Ansible mechanics, the Ansible job
  executor, its mock, its readiness component).
- New `provisioning/compute/contracts` (the family's wire models and route contracts) and
  `provisioning/compute/client` (the family's async and sync typed client) distributions.
- New `kit/resource-pools-contracts` and `kit/resource-pools-client` distributions;
  `kit/resource-pools` imports its models from the former. `kit/site-client` gains
  capacity-definition import.
- `provisioning/compute/ansible`: the host-import route contract, route service, and client
  extension.
- `domains/vms/provisioning/client` (`vm_provisioning_operator`): its generic clients are
  deleted; it keeps VM's models, route declarations, relays' client surface, and a VM
  extension client over the family client.
- `core` (`arkhai-core`): `VersionedEnvelope`. `kit/fulfillment` and its importers take it
  from there.
- `kit/site`: write-once lease attachment, guarded commit and truncation, and the release
  guard in place of the settlement-abandonment hook. `kit/fulfillment` records the create
  handle through the ledger's narrowed create-handle write.
- `provisioning/compute/service`: Dockerfile and settings copy each domain's `iac`; the
  service composes contributed diagnostics and mounts the moved route services.
- `provisioning/compute`: the `(offering_mode, action)` executor table, the
  compute-family mock mechanism, the provider-neutral release executor and status port
  (no mode-keyed dispatch), and framework-free job, host, lease, and test-job route
  services; its client and route contracts move to the thin distributions.
- `domains/bare_metal`: its lease surface and lease client are deleted.
- Both provisioning adapters: their compute adapters are deleted, with the generic action
  route, its contract job routes, and `ExecutorAdapterRegistry`.
- `kit/negotiation-runtime`: administrative acceptance and opening preview; the listing
  source check hook, the retryable refusal, and success recorded last. `kit/policy`: the
  listing-source verdict and `has_matching_inventory_guard`, moved from
  `domains/vms/negotiation`. `kit/storefront`: the process-local trading pause and the
  stage-event read's signed resource.
  `kit/settlement-runtime`, `kit/capacity-publication`, and `kit/storefront`:
  deal-control route services and the evaluate-settle hook. `core/storefront`: the
  bypassing `NegotiationService.force_accept` removed; `core/storefront-client`:
  `evaluate_negotiate` takes the opening request.
- `domains/vms/storefront` and `domains/apicredits/storefront`: rebinding to the kit
  route services and removing their copies, including their trading-pause flags and
  event-resource rebuilds; VM contributes its listing source check to the runtime.
  `domains/vms/negotiation`: the inventory guard leaves for `kit/policy`.
- `domains/bare_metal/storefront`: negotiation on the kit runtime with a configured
  seller chain and no hold, its durable pause removed, deal controls,
  settlement-started fulfillment, teardown through lease termination, the
  capacity-released callback, the publication dry run, restart integration tests.
- `domains/bare_metal/buyer`: `begin()` removed from the fulfillment transport.
- `e2e-tests`: shared compute deal stages, VM's scenario moved onto them, the bare-metal
  scenario and driver, shared helpers, the bare-metal buyer dependency, lane targets; the
  family client in place of VM's generic client, and lease backdating through the site
  client.
- `domains/vms/storefront` and `domains/bare_metal/storefront`: the thin contracts and
  client in place of the family kit.
- Root `Makefile`, compose files, and `.github/workflows/e2e.yml`.
- `openspec/changes/bare-metal-and-credits-domain-stacks/`,
  `openspec/changes/kit-owned-storefront-shell/`, and
  `openspec/changes/apicredits-end-to-end-lane/`: migrated scope recorded.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the definition of a family kit and its
      layer, the compute family's packages (including the contracts and client
      distributions), the deal-control route services in the kit layers, the five-piece
      route pattern, the compute-provisioning executor table and mock mechanism, release
      ownership (mode-agnostic), `VersionedEnvelope`'s home in core, and the bare-metal
      fulfillment hook statement, which is stale today.
- [x] `docs/development/ROADMAP.md` — the repository-wide administrator stance as an
      open gap, and the findings recorded under "Controls and routes (5B.8)".
- [x] `docs/development/TESTING.md` — three lanes on shared images, the loop table's
      bare-metal publication dry run, shared compute deal stages, the mock profile's
      per-adapter executors, and the stale "blocked—not mocked" bare-metal statement.
- [x] Existing subsystem specification — `test-compatibility`, `market-composition`,
      `physical-provisioning`, `storefront-publication`, `site-capacity`, `fulfillment`,
      `compute-provisioning-contract`, `resource-pool-management`.
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
- A family kit is the family-level owner of mechanism, authority, and persistence;
  `compute_provisioning` and the Ansible distribution are the compute family's —
  `docs/development/ARCHITECTURE.md`.
- Compute provisioning owns jobs and hosts; adapters contribute preparation and meaning;
  no adapter imports another adapter or the deployed service —
  `openspec/specs/physical-provisioning/spec.md`, `docs/development/ARCHITECTURE.md`.
- Job execution resolves its executor by `(offering_mode, action)` from a
  compute-provisioning table — `openspec/specs/physical-provisioning/spec.md`,
  `docs/development/ARCHITECTURE.md`.
- Lease release delegates to durable fulfillment teardown for every offering mode, and
  storefront teardown goes through lease termination —
  `openspec/specs/physical-provisioning/spec.md`, `docs/development/ARCHITECTURE.md`.
- Bare-metal fulfillment starts at settlement verification —
  `openspec/specs/storefront-publication/spec.md`, `docs/development/ARCHITECTURE.md`.
- A capability's HTTP surface is five pieces, the binding owned by whatever composes the
  process — `docs/development/ARCHITECTURE.md` ("Route contracts and their HTTP binding",
  promoted during design at the maintainer's request).
- Leases have one family surface that records and releases; commit begins a lease, and
  executor identity and evidence are fixed once recorded; leases are keyed by reservation
  id; every
  provisioning route admits the administrator; readiness is part of system status;
  connectivity is probed by connection kind; the family's wire contract and client are
  thin distributions — `openspec/specs/physical-provisioning/spec.md`,
  `docs/development/ARCHITECTURE.md`.
- A lease tail is written once; `commit` neither resurrects a lease nor moves a registered
  lease's window; truncation neither resurrects nor extends a lease, nor ends an
  uncommitted hold; capacity reclaims consult a release guard; capacity-definition import
  has a thin client —
  `openspec/specs/site-capacity/spec.md`.
- Delivery happens only through fulfillment; an undelivered lease is released by what its
  fulfillment proves; host import belongs to its implementation —
  `openspec/specs/physical-provisioning/spec.md`; the executor-action submission is removed
  from `openspec/specs/compute-provisioning-contract/spec.md`.
- The pool wire contract and client are thin distributions of the resource-pool capability —
  `openspec/specs/resource-pool-management/spec.md`, `docs/development/ARCHITECTURE.md`.
- `VersionedEnvelope` lives in `arkhai-core` — `openspec/specs/fulfillment/spec.md`,
  `docs/development/ARCHITECTURE.md`.
- Job-backed fulfillment is the compute family's: one provider and one job submission,
  domains contributing preparation and codecs; a create succeeds only with readable
  delivery evidence; delivery says only how to reach what was provisioned; jobs correlate
  on the capacity reservation; provisioning names what it provisions —
  `openspec/specs/physical-provisioning/spec.md`, `docs/development/ARCHITECTURE.md`
  ("Family kits", "Fulfillment status and results").

## Dependencies

Depends on `bare-metal-publication-reads-pool-declarations` (archived), which built the
bare-metal lane, and `kit-owned-storefront-loop-lifecycle` (archived), which built the
bare-metal lifecycle pause and steps. No active dependency.

Takes over, and records as migrated in the source change:
- `bare-metal-and-credits-domain-stacks` 4a.1, 4a.2, and the runtime half of 4a.3;
- the deal-control route services from `kit-owned-storefront-shell`'s scope;
- the separate API-credit lane from `apicredits-end-to-end-lane`.

Also takes over the storefronts' thin compute-provisioning client, which an architecture
review had assigned to `kit-owned-listing-and-fulfillment-lifecycles`; that change's
documents never recorded the item, so nothing there changes.

Hands to `bare-metal-and-credits-domain-stacks` its former tasks 3.1–3.4 and the
`buyer-orchestration` delta. Supplies that change's pipeline deal evidence for Goal 4,
short of real access, which stays with the protected lane.
