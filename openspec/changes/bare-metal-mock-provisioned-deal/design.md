# Design — bare-metal mock-provisioned deal

## Context

The objective is parity: a bare-metal counterpart to VM's typed-client deal,
`e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal.py`, run on every pipeline run
against the provisioning service's mock profile. The pipeline runs only in GitHub
Actions, which has no live host inventory and never will, so this scenario is where
bare metal proves everything integration tests cannot: that the storefront, registry,
chain, site, and executor compose into a working deal.

What the codebase does today, verified 2026-10-01:

- **Bare-metal execution runs through VM's job service.** The bare-metal operations
  service submits grant and reclaim jobs to the VM runtime's `AnsibleJobService`.
  `_process_job` persists the job, checks the registered host, renders inventory, and
  calls one injected Ansible service — real, or `ProgrammableMockAnsibleService` under
  the mock profile. The bare-metal fulfillment provider reads status and credentials
  back from the persisted job. The mock's default stdout is a VM creation
  (`vm_creation_data`); a bare-metal grant is parsed from `node_grant_access_data`.
- **The `/test/*` controller assumes one Ansible service.** It resolves
  `resolved_ansible_service` and requires the VM programmable mock; the job service's
  `notify_job_done` also reaches that one service.
- **Bare metal negotiates through a domain-local copy.** `negotiation_service.py`,
  `negotiation.py`, the negotiate routes in `api.py`, and thread persistence implement
  round 0 only; continue refuses with "default bare-metal policy does not support
  additional rounds". VM and API credits run on `kit/negotiation-runtime`, which is
  where multi-round negotiation and force-accept come from.
- **The bare-metal storefront lacks the deal controls VM's scenario drives**: stage-event
  read, evaluate-negotiate, force-accept, settle verify and evaluate dry runs, settle
  wait, admin reserve, and the capacity-released callback. VM implements each in its own
  controllers; API credits has its own copies of the events read, settle wait, and
  force-accept. `kit-owned-storefront-shell`, in design and unplanned, would extract the
  route set wholesale.
- **Administrative negotiation bypasses the runtime.** VM's and API credits'
  force-accept call core `NegotiationService.force_accept`, which records the accept and
  commits agreed price and duration but never runs the domain's `place_hold` or
  `persist_artifacts`; VM's force-accepted thread therefore has no committed settlement
  plan today. VM's evaluate-negotiate checks the listing binding and runs round-zero
  policy only, skipping opening decode, `validate_opening`, principal checks, and
  settlement-selection validation, so it can approve an opening the real call refuses.
- **The settlement-servicing worker exists only with hosted settlement.** The bare-metal
  runtime composes `SettlementServicingWorker`, whose `on_ready` hook starts fulfillment
  for a ready obligation with none, only when Stripe hosted settlement is registered. An
  Alkahest-only storefront has no servicing loop at all.
- **Executor dispatch already has a compute-provisioning registry.**
  `compute_provisioning.adapters.ExecutorAdapterRegistry` selects an adapter by offering
  mode, validates its actions, and rejects duplicates; jobs persist their
  `offering_mode`. Playbook execution below it is VM's job service, which special-cases
  `bare_metal`.
- **Fulfillment never starts on the Alkahest path.** The `fulfill_bare_metal` hook is
  registered in the domain contract, but settlement only adopts the obligation; delivery
  waits for `POST /api/v1/fulfillments/begin`, which no buyer code calls. Settle status
  asserts no fulfillment is bound.
- **Capacity release has two owners.** Lease expiry submits a raw reclaim job through
  `BareMetalReleaseExecutor`, bypassing the fulfillment aggregate, so the aggregate stays
  `active` after the lease ends. Buyer teardown calls provisioning's fulfillment teardown
  directly, which the lease lifecycle never sees, so the storefront releases the site
  reservation itself when it observes `torn_down`. VM's release executor and release job
  port already delegate to the fulfillment aggregate and are provider-neutral in
  substance.
- **Bare-metal publication has a step but no dry run**, unlike VM's publication and
  capacity-events loops.
- **The lane starts empty.** Every lane takes its stack down with volumes before it comes
  up and never restarts a service mid-run; VM's restart recovery is covered by storefront
  integration tests.
- **Every lane builds every image.** Each pipeline job runs `make build-dev`, building
  the wheels and all runtime, dev-chain, and test images. The API-credit deal runs inside
  the VM lane because the VM stack includes `domains/apicredits/compose.yml`.
- **The real-host scenario is already unselected.** `e2e_bare_metal_deal` is in no lane's
  marker expression.

Found at the 2026-10-02 implementation review and its follow-up layering review:

- **The VM adapter is the false owner of provisioning-wide execution.** It holds the
  durable job engine (`job_service.py`), the Ansible runner with both VM and bare-metal
  vars and fact parsing (`ansible_service.py`, which imports `arkhai_bare_metal`), the
  host registry rendering both `[kvm_hosts]` and `[bare_metal_nodes]`
  (`host_service.py`), the mock runners, job parameters mixing VM and bare-metal fields,
  the service-wide system, job, host, and lease routes, and bare metal's playbook and
  role under `domains/vms/provisioning/iac`. The VM adapter imports the deployed service
  at 24 sites (its `container` globals, `Settings`, DB models, job queue, relay
  services), the bare-metal adapter at 6, and the bare-metal adapter imports VM's job
  service, job models, host service, and, since Section 4, VM's mock and Ansible service.
- **The job and host wire models live in `vm_provisioning_operator`**, so no neutral
  route service can serve them without importing a VM package.
- **`HostService` calls the service's relay rebinding** when a host changes pool; relays
  are VM tunnel rendezvous and are VM behaviour.

## Decisions

### The scenario is VM's deal, stage for stage

Decided with the maintainer. Every stage of VM's typed-client deal has a bare-metal
counterpart, including every dry run, so the scenario follows `TESTING.md`'s
pause, dry-run, advance convention end to end: the storefront's loops are paused once at
the start and every transition the scenario depends on is first previewed, then
advanced explicitly. No stage is dropped because bare metal lacks the control it needs;
the missing controls are built (below).

| VM stage | Bare-metal counterpart |
|---|---|
| 00 pause loops, health, contract pins, mock mode, provisioning→storefront link | Same, through the bare-metal storefront's lifecycle pause and system status, plus the site projection loaded |
| 00f seed resources, register host, declare capacity | Declare a backed bare-metal pool, register the host record, declare whole-host capacity |
| 02b–04a listing created, validated, published, discovered | Publication dry run then step; typed hardware query at the registry |
| 05a evaluate-negotiate, 05b negotiate, 06b force-accept | Same, through the kit negotiation runtime |
| 07 on-chain escrow, verify dry run, mock gate armed | Same, with the bare-metal grant gate |
| 08a evaluate-settle, 08c evaluate-job, 08b settle → dispatching | Same; bare metal's evaluate-settle previews scheduling and materialization |
| 09a release gate, converge to active; 09a2 listing closes | Same; the publication dry run then step closes the listing as unavailable |
| 09b ready and credentials | Buyer result carries no access coordinates; buyer access returns host, port, and user |
| 09bb settlement-servicing dry run then step → claim | Same |
| 09c lease registered | Same, through the bare-metal lease view |
| 10a–11b expire lease, gated teardown, release, re-reserve | Same; release reaches the storefront through the capacity-released callback |
| — | A second deal on the freed host: buyer-requested teardown sent twice returns the same operation, capacity is released once, and publication reopens the listing |

### Compute deal stages are shared

Decided with the maintainer. Stage definitions live once, in a new
`compute_deal_stages.py` module beside the shared domain-deal helpers
(`e2e-tests/tests/e2e/roles/helpers/`), as classes not named `Test*`
so pytest does not collect them where they are defined. Each compute domain's scenario
module declares its stages in order by subclassing them
(`class TestStage05b_Negotiate(Stage05bNegotiate): pass`), which keeps pytest's order
explicit and lets a domain override one stage or insert its own. What differs between
domains is supplied by a `deal_driver` fixture implementing a `ComputeDealDriver`
protocol: seeding supply, the listing's provision terms, the mock rules matched, the
lease view, the evaluate-settle expectations, and the domain's result and access
assertions. Negotiation needs no driver hook.

The module is compute-specific by name and scope. API credits, inference, and later
domains have different deal flows and keep their own scenarios; nothing here is shaped
for them.

VM's `test_full_deal.py` moves onto the shared stages without behaviour change and is
green on its lane before the bare-metal driver is added.

### Bare metal negotiates through the kit runtime

Decided with the maintainer. Bare metal's round-0-only negotiation is an artifact of its
domain-local copy, not a domain difference. This change composes bare metal onto
`kit/negotiation-runtime` — migrated from `bare-metal-and-credits-domain-stacks` tasks
4a.1, 4a.2, and the runtime half of 4a.3 — implementing `NegotiationDomainHooks` and
serving the existing `api.py` negotiate routes over the runtime, as VM serves its own
routes without the shell. The domain-local negotiation service, policy class, and thread
persistence are deleted. Moving those routes onto the shell's shared routes (the rest of
4a.3, and 4a.4–4a.5) stays with that change.

The implementation satisfies `bare-metal-and-credits-domain-stacks`' delta
"Bare-metal negotiation preserves demand and authority ownership", which that change's
4b.1 and 4b.2 continue to verify and promote.

### Deal controls are kit-owned route services

Decided with the maintainer: the parts of `kit-owned-storefront-shell` this scenario needs
are implemented here, in place, rather than blocking on the shell or splitting a new
change. Each control becomes a framework-free route service, following the precedent
`kit-owned-storefront-loop-lifecycle` and `kit/pool-overrides` set, bound by each
storefront behind its own authentication:

| Control | Route service lives in | Over | Bound by |
|---|---|---|---|
| Stage-event read (`/api/v1/system/events`) | `kit/storefront` | core stage log | VM, API credits, bare metal |
| Evaluate-negotiate | `kit/storefront` | `NegotiationRuntime.preview_opening` | VM, bare metal |
| Force-accept | `kit/storefront` | `NegotiationRuntime`'s administrative acceptance | VM, API credits, bare metal |
| Settle verify (dry run) | `kit/settlement-runtime` | the mechanism adapter's escrow read | VM, bare metal |
| Evaluate-settle (dry run) | `kit/settlement-runtime` | a new per-domain fulfillment-preview hook | VM, bare metal |
| Settle wait | `kit/settlement-runtime` | the domain's settle-status reader | VM, API credits, bare metal |
| Admin reserve | `kit/capacity-publication` | a listing's capacity binding | VM, bare metal |
| Capacity-released callback | `kit/capacity-publication` | a domain release hook | VM, bare metal |

Settle verify, evaluate-settle, admin reserve, and the capacity-released callback carry
domain-shaped requests and effects, so their kit route services own validation,
refusals, waiting, and response shape over per-domain hooks; a storefront that offers
no settle dry run binds only wait.

Wire paths and canonical client methods are unchanged except evaluate-negotiate's body
(below). Per "An extracted concern leaves no domain-local implementation", every domain
that carries a copy rebinds in this change and its copy is removed; a domain that lacked
the control gains it by composition. API credits gains only what it already has a copy
of: it has no evaluate-negotiate, settle dry runs, admin reserve, or capacity-released
callback today, and nothing here requires them. The shell, when planned, mounts these
route services rather than extracting them again. `kit/settlement-runtime` already holds
framework-free routes (`hosted_routes.py`).

### Administrative acceptance goes through the runtime

Decided with the maintainer after design review. `NegotiationRuntime` gains an
administrative acceptance operation: it loads the recorded thread and its domain binding,
builds the `Acceptance` through the domain's hooks at the administrator's amount, records
the administrator as the accepting author, and commits through the same
`_commit_acceptance` path a negotiated acceptance takes, so `place_hold` and
`persist_artifacts` always run. The force-accept route service calls it; VM and API
credits rebind to it; core `NegotiationService.force_accept` has no remaining caller and
is removed.

It reuses the runtime's continuation resolution, which already admits an administrator
actor; what it adds is acceptance at the administrator's amount rather than the seller's
last one. This changes VM's force-accept behaviour: a force-accepted VM thread now
carries its capacity hold and committed settlement plan. Planning found that VM and API
credits place their hold only at acceptance, never at opening, so administrative
acceptance places it once rather than twice; what needs proving is that settlement
consumes a hold after force-accept exactly as after a negotiated acceptance.

### Evaluate-negotiate previews the real opening

Decided with the maintainer after design review. `NegotiationRuntime` gains
`preview_opening`, which runs the same opening pipeline as `start` — domain decode,
`validate_opening`, principal and listing checks, settlement-selection validation, and
round-zero policy — and stops before anything is persisted, held, or recorded. The dry run
differs from the real operation only by its effects. Its request body is therefore the
`negotiate/new` opening itself rather than `{proposal, requested_duration_seconds}`: the
canonical client's `evaluate_negotiate` and VM's stage 05a change with it.

### Settlement starts fulfillment

Decided in `bare-metal-listing-shapes`, implemented here; refined after design review.
Every bare-metal storefront with a settlement mechanism composes the kit
`SettlementServicingWorker`, not only one with hosted settlement. Its `on_ready` hook
dispatches by the obligation's mechanism: hosted obligations to the existing hosted
lifecycle callbacks, Alkahest obligations to the fulfillment service. When `verify`
adopts an obligation it wakes the worker and steps that obligation once through the
worker's own path, so the settle response normally reports fulfillment started; if that
attempt fails, the worker's schedule retries it. The worker has no public way to service
one obligation today, so the kit gains `service_obligation`, the same per-record body
`run_once` applies to each due row, with the same retry scheduling; the runtime's
operation leases already make a concurrent loop pass see the obligation as busy. The domain supplies what fulfillment
means; the kit worker alone decides when an unstarted ready obligation is retried, so no
second retry path exists in the domain.

Implementation found that the kit's due-obligation query listed only obligations that
already had a fulfillment, so no domain's `on_ready` hook was reachable from the
worker's loop. Decided with the maintainer (option A): a ready obligation whose
fulfillment never started is due through its `fulfill` operation, so the worker starts
it and its retry schedule governs every later attempt, for every domain.

Settle status stops asserting that no fulfillment is bound.
`POST /api/v1/fulfillments/begin` and `BareMetalFulfillmentTransport.begin()` are
retired. The buyer makes one call, as in every domain, and the settlement request names
the negotiation, the buyer, and the EVM address only. With the worker composed on the
Alkahest path, the settlement-servicing step VM's stage 09bb advances has its bare-metal
counterpart.

### The lease lifecycle owns release for every offering mode

Decided with the maintainer. The storefront's direct site release is a workaround for
buyer teardown bypassing the lease lifecycle, and it is removed.

- VM's release executor and fulfillment release job port move to
  `compute_provisioning.release` as provider-neutral components and are registered for
  bare metal as well as VM, so lease expiry begins fulfillment teardown and completion is
  read from the aggregate, never from a raw job. `BareMetalReleaseExecutor` is deleted.
- Buyer teardown at the bare-metal storefront calls the site's storefront-role lease
  terminate (`/api/v1/contract/leases/{id}/terminate`), the same release path expiry
  takes. A repeated teardown returns the same `releasing` or `released` lease, which is
  what makes it idempotent.
- The lease cycle records release and delivers the capacity-released callback; the
  bare-metal storefront binds the kit callback route and marks its lifecycle released
  only on that callback.

The site's lease view and backdating used by the expiry stages go through typed
clients. `/api/v1/leases/{id}` (read, update, terminate) is served over the
kind-agnostic lease lifecycle and already reads and backdates a bare-metal
reservation, so the bare-metal lease routes gain nothing; its VM-named fields are
blank for bare metal.

### Executors are selected by offering mode and action, and each adapter owns its mock

*Refined by "Provisioning execution leaves the VM adapter": the table now resolves a
complete `JobExecutor`, the job storage and Ansible mechanics leave the VM adapter, and
the bare-metal mock no longer reuses VM's. What follows is the Section 4 state.*

Decided with the maintainer; placement corrected after design review. Executor selection
authority belongs to compute provisioning, keyed the way "Validated executor
registration" requires:

- Compute-provisioning composition already validates `(offering_mode, action)` ownership
  and refuses duplicates for the actions a bundle submits through the compute contract
  (`compute_provisioning_service.composition`). Each `ExecutorAdapterContribution` gains
  the job executor that runs its mode's actions, the actions it runs, and the playbook
  it runs them with; composition builds the job-executor table from those under the
  same duplicate refusal. The resolver protocol a job service depends on lives in
  `compute_provisioning`, which both adapters already import.
- VM's job service receives a narrow resolver port and owns no routing decision. It
  resolves a job's executor and playbook from the job's persisted `offering_mode` and
  action, so its `bare_metal` playbook special case goes. Job storage stays in the VM
  adapter behind that port; moving it is out of scope, but no new cross-domain authority
  is added there.
- The bare-metal bundle registers its access actions: the real Ansible service in
  production, the bare-metal mock under the mock profile. The job record, host check,
  inventory rendering, and result parsing are unchanged, so the mock's playbook output is
  parsed by the same `node_grant_access_data` and `node_reclaim_access_data` path as a
  real run. A default grant returns a tenant user and SSH port, with the tenant address
  taken from the registered host record as a real run's is; a default reclaim succeeds.
  Job-done notification goes to the executor that ran the job. The Ansible-shaped fake
  (vars files, inventory, playbook start and wait, delegation to the real parser) stays
  in the VM adapter, because generic compute modules may not know playbooks; the
  bare-metal adapter constructs its own instance of it with bare-metal default output and
  its own rule store, through the VM-adapter dependency job execution already has.

The rule store, pause gates, matching, job-done events, evaluate-job dry run, and a
framework-free `/test` route service move out of the VM mock into a compute-family module,
`compute_provisioning.executor_mock`, on which the VM programmable mock and the
bare-metal mock are both built. It is not a foundation kit: it serves the compute family
only, and a foundation kit knows no family. `compute_provisioning` is a compute-family
library both adapters already depend on, which makes it the home for now; if that package
is re-homed as a compute-family kit, the module moves with it. An API-credit or inference
executor mock would not live there. VM keeps its rule routes at `/test/mock-rules`; the
bare-metal adapter mounts its own under `/test/bare-metal/mock-rules`, with route
contracts and test-client methods. The job routes (`/test/jobs/drain`,
`/test/jobs/{id}/wait`) stay shared.

### Compute provisioning is a family kit

Decided with the maintainer, with the definition refined after architectural review.
`ARCHITECTURE.md` defines a family vocabulary package but not its operational
counterpart, which is what `compute_provisioning` already is; without the category it
has been pulled between kit, domain, and service implementation. This change defines it;
the definition, placement tests, layers, and compute example were promoted to
`ARCHITECTURE.md` ("Family kits") on 2026-10-02, ahead of closeout, at the maintainer's
request. The text below is the decision record. Unqualified "kit" there means
a repository-wide, family-neutral kit capability.

> A **family kit** owns reusable mechanism, authority, and optionally persistence for
> concepts whose scope is one market family rather than every market or one concrete
> domain. It is the operational counterpart to a family vocabulary package.
>
> A family kit is appropriate when a capability belongs intrinsically to the family:
> either several sibling domains use it, or it is the family's single cross-domain
> authority. Code that merely looks similar across domains does not qualify. A family
> kit must remain meaningful independently of any one domain, and a new sibling domain
> must be able to consume it by contributing values, codecs, hooks, or registrations,
> never by adding domain-specific branches to it.
>
> Because a family kit uses family-specific vocabulary, it is not a repository-wide kit
> capability, whose abstractions are family-neutral. Because it carries no concrete
> domain's listing schema, policy, result meaning, domain-specific infrastructure
> choices, or composition wiring, it belongs to no sibling domain.
>
> A family kit may own durable state, workers, and authority lifecycles for its family.
> It may depend on its family's vocabulary package, repository-wide kit capabilities,
> core contracts, and lower-level family-kit distributions of the same family.
> Dependencies among a family's kit distributions must be acyclic: an optional
> implementation distribution may depend on the family's base mechanisms and
> authorities, and those base distributions must not depend back on it. A family kit
> must not depend on a concrete domain, another family's packages, a concrete role
> implementation, or a deployed service; imports used only for typing obey the same
> rule. Domains define the values, codecs, hooks, and registrations a family kit
> consumes; composition roots select and assemble them, provide configuration and
> external resources, and wire runtime instances. A family kit never discovers or
> imports its domains. A family may split its kit into more than one distribution where
> dependency weight or an optional implementation technology would otherwise force
> unrelated consumers to install dependencies they do not use; such optional
> implementation distributions are not a further architectural tier.
>
> Family vocabulary packages stay a lower and narrower layer: they define a family's
> shared names, schemas, identifiers, and value semantics, own no authority or
> persistence, and never depend on a family kit.
>
> Another market family needing apparently similar behaviour is a signal to evaluate
> extraction into a repository-wide kit, not an automatic promotion. Promotion is right
> only when the capability's vocabulary and authority semantics can be made
> family-neutral without depending on either family's identity or domain meaning.
> Behaviour invariant across marketplace roles, rather than merely reusable across
> families, may instead belong in core.

Placement tests:

- **Contribution or change.** If adding a sibling domain would mean registering a new
  contribution, the capability belongs in the family kit; if it would mean changing the
  capability's internal domain semantics, it belongs in the domain.
- **Third domain.** Could a third domain of the family use the capability without the
  family kit learning that domain's schema or branching on its identity?
- **Outside the family.** If the capability is meaningful and family-neutral for every
  market, it belongs in a repository-wide kit; instance wiring, process lifecycle, route
  mounting, and aggregation of contributions belong in the composition root.

Repository layers, top to bottom: composition roots and deployed services; domain
packages and role implementations; family kits; family vocabulary packages;
repository-wide kit capabilities; core carrier and role contracts.

The compute family: `domains/compute` (`arkhai_compute`) is its vocabulary.
`provisioning/compute` (`compute_provisioning`) is its family kit for cross-domain
physical provisioning — executor registration, provisioning jobs, operational hosts,
lease lifecycle, shared release, job-backed fulfillment support, and the mock gate
mechanism. `provisioning/compute/ansible` is the compute family kit's optional Ansible
implementation distribution: it depends on `compute_provisioning`'s job, executor, and
host contracts, never the reverse, so consumers of jobs or hosts do not install
subprocess and Ansible dependencies. VM and bare-metal adapters contribute their
preparation, codecs, playbooks, result interpretation, credentials, and provider
semantics. `compute_provisioning_service` is the composition root. Applied to this
change: the job state machine, executor registry, host authority, lease lifecycle, and
job gates are family kit; the Ansible process mechanics are the Ansible family kit; VM
vars and facts are VM's; bare-metal access vars and facts are bare metal's; service
startup and router mounting are the composition root's.

### Provisioning execution leaves the VM adapter

Decided with the maintainer after the layering review, reversing the former non-goal.
Bare-metal execution never belonged in the VM adapter, and neither did the
provisioning-wide execution machinery around it. The postcondition is concrete:
**neither provisioning adapter imports the other, and neither depends on or imports
`compute_provisioning_service`, including under `TYPE_CHECKING`.** Placement:

| Concern | Owner | What domains contribute |
|---|---|---|
| Durable job engine: identity, state, the route key, `host_id`, retry counts and timing, scheduling, cancellation through the executor and its opaque handle, logs, `ResultEnvelope` and `CredentialEnvelope` persistence, the job queue and retry coordination, job routes | `compute_provisioning.jobs` | whether a failure is retryable, decided by the executor |
| Host authority: identity, enabled state, pool association, a connection envelope (`kind`, version, public fields, and opaque protected values it never decrypts or discloses), CRUD, applying an imported inventory to the registry with its pool-change and capacity effects, the capacity-derivation port, the pre-execution lookup yielding an immutable `ExecutionHost`, host routes, a pool-change hook | `compute_provisioning.hosts` | connection codecs (public fields, protected values and their schemes, just-in-time decryption) come from implementation distributions; VM subscribes its relay rebinding to the pool-change hook |
| Executor table: `(offering_mode, action)` → one complete `JobExecutor` | `compute_provisioning` | each bundle's executors |
| Rule and gate mechanism, with a deterministic gate-reached signal | `compute_provisioning` (beside the job engine) | each mode's rule routes and default outputs |
| Job-backed fulfillment-provider shape (5B.12) | `compute_provisioning` | job preparation and result mapping |
| Composition contract types (`ExecutorAdapterBundle`, `ExecutorAdapterContribution`, `compose_adapter_bundles`) | `compute_provisioning` | — |
| SSH connection codec (validation, decrypting a protected private key just in time, transient key material) and Ansible mechanics: subprocess and run lifecycle, transient inventory rendering from an `ExecutionHost`, INI parsing and rendering to and from host records with `ssh` connections (not applying them), group naming, redaction, failure classification for transport and Ansible errors, fact extraction, connectivity probes, readiness, the `AnsibleJobExecutor` and its mock | `provisioning/compute/ansible` (`compute_provisioning_ansible`), the compute family kit's optional Ansible implementation distribution (confirmed by the maintainer) | codec, playbook, preparation |
| VM vars, golden-image credentials, VM facts and credential meaning, VM playbooks and roles, relays, pool configuration with VM defaults, VM operations and routes | VM domain | — |
| Bare-metal access vars and facts, the `node-access` playbook and `bare-metal-access` role, access parameters | bare-metal domain | — |
| Aggregate health and diagnostics, instance wiring, table composition, route mounting | the provisioning service | domain diagnostics (Ansible readiness, host reachability) are contributed, not built in |

**A job executor is one complete executable.** The table resolves
`(offering_mode, action)` to a `JobExecutor` that executes a job and returns a
normalized outcome and cancels through its own handle (refined by "Job and host
authority shape" below). Composition builds, for example,
`AnsibleJobExecutor(runner, codec, playbook)` per mode. The job engine knows job
identity, state, opaque parameters, route key and action, `host_id`, retries,
scheduling, outcomes, cancellation through the executor, logs, and generic result and
credential envelopes; it never knows playbooks, facts, inventory, process IDs, SSH, or
how a domain's parameters are built. The VM provider's extra-vars check calls the VM
codec directly instead of the job service.

**The job and host wire models move to `compute_provisioning`**, the provisioning client
library, with the client operations. No neutral provisioning module imports
`vm_provisioning_operator`. The models are classified by owner, not copied wholesale:
the job authority's canonical result and credential forms are the existing opaque
`ResultEnvelope` and `CredentialEnvelope`, and they are also its wire forms. Refined
under "Pre-release wire and schema changes are accepted": there are no compatibility
models or re-exports; callers import models from their owners, and SSH-shaped models
such as `CredentialResponse` are removed.

**`system_service.py` is split by owner**: aggregate health and status go to the
service, which composes contributed diagnostics; Ansible readiness goes to the Ansible
distribution; convergence and lease controls go to their owning capabilities. Generic
lease read, update, terminate, and admin routes move to `compute_provisioning` and serve
the neutral `LeaseView` (reopened with the maintainer; see "Job and host authority
shape").

**The job-backed fulfillment-provider helper lands last (5B.12).** Decided with the
maintainer. VM's and bare metal's fulfillment providers share one shape: prepare a domain
job from the settlement resource, submit it, map job status to fulfillment status, and
read the result and credentials. Once the job boundary has landed and been checked, that
shape becomes a helper in `compute_provisioning`, above both `kit/fulfillment` and the
job authority, so `kit/fulfillment` stays provider-neutral and each domain keeps only its
job preparation and result mapping. It is a separate step so the boundary is proven
before the providers are restructured.

Invariants this change must leave true:

- `provisioning/compute` owns durable physical-execution jobs and operational host
  registration.
- The job engine has no Ansible, SSH, playbook, VM, or bare-metal vocabulary in its
  interface or its persistence: results and credentials are stored as envelopes, and an
  execution handle is opaque.
- The engine owns retry counts and timing; the executor decides whether a failure is
  retryable, and redacts what it reports.
- A cancelled job stays cancelled whatever its executor later reports.
- The host authority's model is connection-neutral; a connection kind's codec belongs to
  the implementation distribution that supports it, and executors receive an immutable
  `ExecutionHost`.
- Connection secrets are persisted, stored, and passed to executors only in a protected
  form; the host authority never encrypts, decrypts, or discloses them; a connection
  codec protects a submitted secret before it is persisted and decrypts it just in time
  for execution.
- `(offering_mode, action)` resolves to a complete job executor.
- Shared Ansible machinery owns process, inventory, and redaction mechanics and no VM or
  bare-metal result meaning.
- VM and bare metal own their codecs, playbooks, action preparation, result meaning, and
  credential semantics.
- `kit/site` references `host_id` and never owns provisioning connection information.
- No provisioning adapter imports another adapter or the deployed service.
- No neutral provisioning module imports `vm_provisioning_operator`, and no compatibility
  models or re-exports remain.
- `compute_provisioning` names no domain's routes: the provisioning route-contract table
  is assembled from contributions, and the client and the service's authentication read
  the assembled table.
- Test gates are owned beside the job lifecycle and expose a gate-reached observation.
- Provider-neutral fulfillment stays unaware that these providers are job-backed; the
  job-backed shape lives in `compute_provisioning`.
- Each domain's fulfillment provider supplies only job preparation and result mapping.


### Maintainer rulings for review

Rulings the maintainer made in conversation, recorded here because reviewers see only
these documents. A review finding that contradicts one of these is a ruling to revisit
with the maintainer, not an implementation defect.

- **Connection secrets are submitted in plaintext over the authenticated host API
  (option A), and protection on the wire is out of scope for this change** (ruled
  2026-10-02, and restated after the second implementation review the same day). The
  host authority stores secrets only in the protected form the connection codec
  produces and never encrypts, decrypts, or discloses them; the codec protects a
  submitted secret on write and decrypts it just in time for execution ("The host
  authority is connection-neutral, and connection secrets stay protected"). Sealed
  submission remains the recorded follow-up.
- **`docs/development/ARCHITECTURE.md` describes the target compute family-kit
  ownership, including postconditions of steps not yet landed, because this branch
  merges whole** (ruled when 5B began, and restated after both implementation
  reviews). The document is not revised step by step.

### Pre-release wire and schema changes are accepted

Decided with the maintainer on 2026-10-02. The system is pre-release: no deployment runs
a storefront or provisioning service of one version against another, and users of an
early version are expected to migrate with it. This change therefore makes wire and
schema changes directly instead of carrying compatibility models, re-exports,
dual-written columns, or expand-then-contract phases. Each schema change is one forward
migration that converts existing rows and drops what it replaces; rollback does not
cross a migration that has run. Earlier decisions in this document that kept a legacy
shape only to avoid a wire change are refined where they appear.

### Job and host authority shape

Decided with the maintainer after design review (2026-10-02). Implementation of the job
move found that `vm_provisioning_adapter/services/job_service.py`'s `AnsibleJobService`
mixes the generic engine (submission and idempotency, the queue, retry and backoff, the
retry scheduler, reads, cancellation, every database transition) with Ansible and domain
work (rebuilding the `AnsibleJobParams` dataclass, relay-token resolution, vars files,
inventory, `start_playbook`, result parsing into a VM-vocabulary payload, extracting
`root` and `tenant` credentials from VM's `authentication` fact, log redaction, and
`SIGTERM` cancellation), and that its persistence is Ansible- and SSH-shaped
(`ansible_jobs.process_id`, the SSH columns of `credentials`). The host registry has the
same problem: its models and `hosts` table carry `ssh_host`, `ssh_port`, `ssh_user`,
`ssh_key_type`, and `ssh_key_value`. Moving either as-is would fail the third-domain test:
a compute domain whose credential is a certificate or token, or whose target is reached
through a cloud or cluster API, would have to change the family kit's model.

**The executor contract.** `compute_provisioning.jobs` defines
`JobExecutor`: `async execute(run) -> JobOutcome` and `async cancel(handle)`. `JobExecutorTable`
resolves `(offering_mode, action)` to one, replacing `JobExecution(runner, playbook_path)`.
A `run` carries the job id, its opaque parameters, the immutable `ExecutionHost` from the
host authority's pre-execution lookup, and callbacks through which the executor reports
an opaque cancellation handle and streams logs. A `JobOutcome` is `JobSuccess(result:
ResultEnvelope | None, credentials: tuple[CredentialEnvelope, ...], logs)` or
`JobFailure(error: ProvisioningErrorEnvelope, logs)`, the error carrying `retryable`.
Responsibilities split as follows:

- The executor decides whether a failure is retryable. Today's operator-configurable
  `non_retryable_errors` patterns are Ansible and VM semantics, so they configure the
  executor, not the engine; the Ansible implementation classifies transport and Ansible
  failures, and each domain's codec its own.
- The engine decides whether and when a retry happens: attempt counts, maximum attempts,
  backoff, and scheduling, from a family-kit `JobRetryPolicy` value the composition root
  builds from its settings. The engine never reads the service's `Settings`; execution
  timeouts and similar values stay on the executor side.
- The executor redacts everything it hands the engine; `compute_provisioning.jobs` does
  not import an Ansible redactor.
- There is no `notify_job_done` on the executor. The engine knows when a job reaches a
  terminal state and signals its own observer, which the rule and gate mechanism beside
  it and the shared `/test/jobs/{id}/wait` route read.

**Cancellation is terminal.** Once a job is cancelled, a later outcome from its executor
cannot change its state, result, or credentials: every transition, cancellation
included, is one conditional SQL `UPDATE` on the job's current status, so the guarantee
holds across sessions and worker processes, and credentials are written only in the
transaction whose transition applied. A cancellation requested before the executor
reports its handle takes effect when the handle arrives. The executor's logs are still
recorded after cancellation, to show what the cancelled execution did. Today's job service writes the outcome unconditionally, so a job
finishing after cancellation overwrites `cancelled`; this change fixes that, and the fix
is tested.

**Job persistence is neutral.** The `ansible_jobs` and `credentials` tables keep their
names (a physical name costs nothing when the model and interface are neutral) and move
to a declarative base of their own in `compute_provisioning.jobs`, which the service's
`db/database.py` composes. One forward migration:

- adds `host_id`, filled from each row's parameters with today's fallback (the
  parameter, else `executor_target`, else the deployment's `default_host_id`), which is
  why the migration runs in the service, where settings are available;
- replaces `process_id` with a JSON `execution_handle` the engine stores and returns
  without interpreting (the Ansible executor stores `{"pid": ...}`);
- stores `result` as a `ResultEnvelope` labelled by the action the job's executor
  ran, as the executors label new results;
- adds `executor_action`, the action the executor runs and the job is routed by,
  beside `action_kind`, the contract action that is part of a contract job's
  identity: a VM teardown is submitted as contract action `teardown` and runs
  executor action `vm_remove`;
- replaces the SSH columns of `credentials` with one `CredentialEnvelope` per row,
  converted exactly as VM's contract credentials route builds it today (`offering_mode`
  `vm`, `credential_kind` from the row's role, the remaining non-empty columns as its
  value). Every existing credential row is VM's — bare-metal grants write none — so this
  one-time conversion may name VM's kinds; the migration lives in the service, never in
  the family kit.

The job routes return the envelopes; `CredentialResponse` and `CredentialListResponse`
are removed, and every reader of a job's result (both fulfillment providers, the
contract route, and the shared test wait route) reads the envelope.

**The host authority is connection-neutral, and connection secrets stay protected.**
Settled with the maintainer after design review of the secret question (2026-10-02),
then corrected against the code the same day. Today an operator submits an embedded
private key as plaintext over the authenticated host API (the route documents "raw
PEM"), `HostService` encrypts it with the service's Fernet key before storing it, and
the runner decrypts it when writing inventory; `HostCreate`'s description of the field
as already encrypted was stale. That submission behaviour is kept. What changes is who
holds the cryptography: the host authority owns protected secret persistence, not
secret cryptography, and the connection codec protects a submitted secret on write and
decrypts it just in time for execution:

> Connection secrets are persisted, stored, and passed to executors only in a protected
> representation. The host authority treats protected values as opaque, keeps them out
> of every read and logging surface, and never encrypts or decrypts them. A connection
> kind's codec turns a submitted secret into a protected value before it is persisted
> and decrypts a protected value just in time for execution; plaintext exists only in
> the submitting request, at those two codec boundaries, and in the transient storage
> the connection needs.

`compute_provisioning.hosts` defines a host as `host_id`, `pool_id`, `enabled`, and a
`ConnectionEnvelope`: `kind`, `version`, `public` fields, and `protected` values, each a
`ProtectedValue` (`scheme`, `ciphertext`) whose representation never shows the ciphertext.
A registration or update may also carry submitted secrets, which the authority hands to
the codec to protect and never stores, returns, or logs.
The authority owns identity, pool association, enabled state, the durable envelope,
keeping protected values out of responses and logs, CRUD, the import operation and its
pool-change and capacity effects, and the pre-execution lookup, which yields an immutable
`ExecutionHost` carrying the protected envelope; executors receive that, never the
persistence row, and never decrypted material from the authority. A connection kind's
codec (its public fields, which secrets it takes, how it protects them and in which
schemes, and just-in-time decryption) belongs to the implementation distribution that
supports it, so the family kit accumulates no per-kind connection types and no
cryptography.

The `ssh` codec is a connection codec, not an Ansible one: its public fields are
`ssh_host`, `public_host`, `ssh_port`, `ssh_user`, and optionally `key_path` (a key on
the service's own filesystem, not secret); its protected value is optionally
`private_key` in the `fernet-v1` scheme; exactly one of the two names the key. With the
Fernet key composition gives it, it protects a submitted private key into `private_key`,
validates an envelope, and materializes a connection for execution: it decrypts
`private_key`, writes it to a transient owner-only file, and removes that file when
execution ends. The Ansible executor consumes
the materialized connection and holds no cryptography of its own. It lives in the Ansible
distribution while that is its only consumer, behind an interface another SSH-based
executor can use without importing Ansible mechanics. The current host authority
implements only this codec; that is an implementation capability, not part of the
family's model: a future kind adds a codec, not a change to the host authority or the
executor contract.

The wire models follow, pre-release: `HostCreate`, `HostUpdate`, and `HostResponse` carry
`connection` (`kind`, `version`, `public`, and write-only `secrets`) in place of the
`ssh_*` fields; an embedded key is submitted as `secrets.private_key`, plaintext as
today, and a response's connection names each protected value and its scheme without its
ciphertext. The
`hosts` table's `ssh_*` columns are replaced in one forward migration by
`connection_kind`, `connection_version`, JSON `connection_public`, and JSON
`connection_protected`: a `path` key becomes `key_path`, and an `embedded` key's stored
ciphertext, which the service encrypted when the key was submitted, becomes a
`fernet-v1` `private_key` unchanged, so the migration performs no cryptography. Callers change with them: the VM operator client, the e2e harness and host
registration, and the development environment's host configuration.

Deferred, not in this change: an embedded key crosses the operator-to-provisioning hop in
plaintext, protected only by the authenticated transport, and `fernet-v1` is a single
service-held symmetric key. Sealed submission to the provisioning service's public key
(which also removes the plaintext hop), references to a secret authority, or managed
envelope encryption need only a new protected-value scheme and its codec support, not a
change to the host authority or the executor contract. Recorded for the roadmap at
closeout.

**The generic lease routes serve the neutral view.** Reopened with the maintainer: the
`Lease*` operator models stayed VM's only to avoid a wire change. When the generic lease
read, update, terminate, and administration routes move (5B.8), they serve
`compute_provisioning`'s `LeaseView` and its request models; VM-only fields
(`vm_target`, `resource_id`) leave the generic surface, and the e2e lease stages read the
neutral view.

**The transitional executor.** The Ansible half of today's `_process_job` becomes an
`AnsibleJobExecutor` in the VM adapter first (5B.2), with today's classification,
redaction, and cancellation, so the Ansible distribution later implements a contract that
already exists. The bare-metal bundle registers an instance through its existing
VM-adapter dependency until 5B.6 and 5B.7 remove it; "neither adapter imports the other"
is claimed only once 5B.10 enforces it.

**Order.** The host authority moves before the engine, because the engine performs the
pre-execution host lookup, and the Ansible distribution's `ssh` codec is needed before the
host authority: the executor contract with the transitional executor (5B.2); the Ansible
distribution's skeleton holding the `ssh` codec (5B.3); the host authority (5B.4); the job
authority (5B.5); the rest of the Ansible distribution (5B.6); domain codecs (5B.7);
controls and routes (5B.8); relays (5B.9); the boundary check (5B.10); the gate (5B.11);
the job-backed fulfillment-provider helper (5B.12). Steps 5B.4, 5B.5, and 5B.8 change
wire formats and schemas; the others are behaviour-neutral.

### The Ansible job codec (5B.6 slice B, absorbing 5B.7)

Approved by the maintainer to settle while implementing; the four questions below were
decided with the maintainer and the reviewer when slice B began (2026-10-02).

**The codec protocol.** `compute_provisioning_ansible` owns `AnsibleJobExecutor(runner,
codec, playbook_path, timeout_seconds, non_retryable_errors)` and the `AnsibleJobCodec`
protocol a domain contributes:

- `inventory_group`: the group the domain's playbooks target. The runner lists every host
  under the group it is given and is indifferent to its value.
- `secret_fields`: field names the domain's playbooks print whose values are secret. The
  runner always scrubs `password`, an SSH identity-file argument, and an `sshpass`
  password; a codec adds its own names, which are scrubbed in both the JSON and the bare
  YAML form.
- `prepare(run) -> AnsibleJobPlan`: the job's own `variables`, operator-supplied
  `extra_variables`, the run `limit`, and an optional per-job `playbook_path`. Called
  immediately before the playbook starts, so a value resolved here (a relay token) is
  current on every attempt. Raising is an unanticipated failure and is never retried.
- `interpret(run, host, output) -> AnsibleJobInterpretation`: the `ResultEnvelope` (the
  codec names its kind) and `CredentialEnvelope`s a successful run reports.
- `is_retryable(message)`: the domain's own failures only.

The executor renders the plan's variables (each value written as JSON, which is YAML, so
a string stays a string), refuses an extra variable naming one of the job's own, writes
the file owner-only, renders the inventory, runs the playbook, and removes both files on
every ending. A failure is not retried if its message matches a transport pattern the
distribution owns (`TRANSPORT_FAILURES`), an operator pattern
(`non_retryable_errors`, now additional to the built-in ones), or the codec's own. The
reserved variable names a caller may need before submission are not part of the
protocol: they are the keys of a plan's variables, and a domain that lets operators
supply extra variables before a job exists (VM's pool configuration) exposes its own
check; the VM fulfillment provider calls the VM codec's `reserved_var_keys` directly.

**Decisions.**

1. **The bare-metal mock keeps its VM import until slice C.** `bare_metal_mock_executor.py`
   still builds on VM's `ProgrammableMockAnsibleService`. After slice B the production
   bare-metal submission and execution path no longer depends on the VM adapter; the
   mock path still does, intentionally, and "neither adapter imports the other" is not
   claimed until slice C and 5B.10. No temporary abstraction is introduced to remove the
   import one slice earlier.
2. **Bare metal's parameters and results are bare-metal-shaped.** Each domain owns its
   parameter model: VM's is `VmJobParams` (the former `AnsibleJobParams`, without
   bare-metal fields), bare metal's its own. A bare-metal access job's result value is the
   access fact its playbook prints, not VM's payload; it carries no credentials. Stored
   parameters (`JobStatusResponse.params`) and mock-rule matching follow. Readers were
   audited first: the bare-metal fulfillment provider is the only production reader of a
   bare-metal job result; no e2e scenario reads bare-metal job results or installs
   bare-metal mock rules; integration tests asserting the old keys change with it.
   Existing rows are converted by one forward migration rather than decoded in two forms.
3. **The inventory group is the domain's.** VM keeps `kvm_hosts`; bare metal's relocated
   playbook targets `bare_metal_nodes`, the name the inventory importer already uses for
   bare-metal hosts.
4. **Bare metal submits to the family job authority directly.** `BareMetalOperationsService`
   submits through `JobEngine` with its own parameter model and owns the reclaim policy's
   allowed values and default; it no longer imports VM's job service or parameter model.

### Findings for review (5B.6 slice B)

Found while implementing slice B. Recorded for the reviewer; none changes behaviour
unless it says so.

- **Retry classification reads only the exception message.** The executor classifies a
  failure on `str(AnsibleError)`, which for a real run is "Playbook failed", "Playbook
  timed out", or "Playbook error: …"; the patterns in `non_retryable_errors` (and now the
  transport and VM ones) therefore never match a real failure, only a mock rule's
  `fail_with` message. Preserved as found. Classifying on stderr and stdout too would make
  the configured patterns effective, and is a behaviour change awaiting a ruling: a
  pattern printed by a task whose failure Ansible ignored would then stop retries.
- **The operator setting's meaning changes.** `non_retryable_errors` was the complete
  list; the transport patterns now belong to the distribution and the VM ones to the VM
  codec, and the setting adds to them (its default is empty). The default classification
  is unchanged; an operator can no longer remove a built-in pattern.
- **The inventory importer still names both domains' groups.**
  `compute_provisioning_ansible/inventory.py` imports only hosts under `[kvm_hosts]` and
  `[bare_metal_nodes]`. That is domain vocabulary in the distribution's import format; a
  contributed set of groups would remove it. Not in slice B.
- **The legacy VM backfill checks reserved variables with the real codec.** It used a
  four-name stub; it now uses the VM codec, as runtime teardown preparation does. A legacy
  pool whose extra variables collide with a job variable is refused there, as dispatch
  already refuses it.
- **The variables file changed form.** Values are written as JSON (strings always quoted,
  which YAML reads as the same strings and which no longer lets an unquoted value such as
  a password with a colon or a numeric-looking host name change type), and the file is
  created owner-only; before, it was written with the process's default permissions
  although it can hold golden-image root credentials and a relay token.
- **The bare-metal playbook no longer receives VM variables.** It received `vm_action`,
  `root_ssh_filename`, and `root_ssh_password` from the shared renderer and read none of
  them; its `vm_action` fallback is removed with them.

### The mock runner and the probes (5B.6 slice C)

**The mock runner.** `compute_provisioning_ansible.mock.MockAnsibleRunner` replaces both
domain mocks. It offers the runner's playbook, inventory, and connectivity surface over
the compute mock mechanism's rules and gates, so the real `AnsibleJobExecutor` runs it
unchanged: the codec still prepares the job (relay resolution included), the variables
and inventory are still rendered from the registered host, and the codec still
interprets the output. A domain contributes only `default_output(MockPlaybook)`, the
output a run produces when no rule replaces it, rendered from the job's stored
parameters and the registered host the run is limited to (VM: a successful create; bare
metal: the access fact for the job and its host). Each runtime composes its own runner,
so rules stay per domain. Rules keep matching the job's stored parameters (`vm_action`
and `host_id` for VM, `action` and `host_id` for bare metal). The executor hands the
runner those parameters through a declared `job_parameters` on `start_playbook` and the
run handle, which the real runner records and never reads; it replaces the undeclared
`_params` attribute. The mock's unused construction-time hooks (`provision_result`,
`should_fail`, `fail_message`) are not carried over.

**The probes.** `compute_provisioning_ansible.probes` owns `probe_connectivity` (the host
listed under the probe's own inventory group, so connectivity no longer borrows VM's) and
`ansible_readiness`, with its wire models `AnsibleReadinessResponse`, `InventoryInfo`,
`FileInfo`, and `SshKeyInfo`. The connectivity route already served the distribution's
`ConnectivityResult`; the operator client's identical `HostConnectivityResponse` is
removed in its favour. Which route serves readiness, and from where, is 5B.8's; VM's
system service still mounts it and supplies the mode, the executor modes, the host
listing, and the playbook.

### Findings for review (5B.6 slice C)

- **Readiness reported `real` under the mock profile after slice B.** The family's
  `JobExecutorTable.executor_modes()` reports a mode as mock when its executors carry the
  mock mechanism's `rules`; the transitional executor exposed its runner's, the
  distribution's executor did not. Fixed: `AnsibleJobExecutor.rules` returns the runner's
  rules, and a distribution test asserts the modes the table reports for a mock and a real
  runner. No test covered the modes before; e2e reads `ansible_mode`, which comes from
  `ACTIVE_PROFILES`, so it did not notice.
- **Cancelling a mocked job signalled the service's own process group.** A mocked run
  reports process id 0 and the executor's `cancel` passed it to `os.kill`, which for 0
  signals every process in the caller's group. The transitional executor and mock did the
  same. Fixed: `cancel` refuses a process id of zero or less, which names a group and never
  a playbook; tested.
- **The VM operator client depends on the Ansible distribution.** It takes the readiness
  and connectivity models from there, which brings the distribution's own dependencies
  (`arkhai-kit-config`, `arkhai-kit-resource-pools`) into the client and its consumers'
  locks (`e2e-tests` among them; `domains/vms/storefront` does not include the client).
  If a lighter client is wanted, 5B.8, which decides where the readiness route and its
  client method live, is the place to move them.
- **Readiness reports one playbook.** `AnsibleReadinessResponse.playbook` is VM's; bare
  metal's access playbook is not reported. Changing the response to report each domain's
  playbook is a wire change left to 5B.8.
- **Bare metal no longer imports the VM adapter.** Neither its source nor its tests do;
  the declared dependency is removed with the import-boundary test in 5B.10.

### Implementation-review fixes for Sections 4–5

Decided with the maintainer after the 2026-10-02 implementation review. The successful
force-accept path is proven through `StorefrontClient` in VM and API credits. Bare-metal
lease registration gets a typed client method, and both existing test-route clients
gain what the tests need, rather than raw requests. Gated tests wait on the
gate-reached signal and `AsyncJobQueue.on_job_started`, never on sleeps, in keeping with
the pause, dry-run, advance convention. Checked task claims are corrected to what the
tests prove, and the missing tests (endpoint coverage, the bare-metal credential
consumer, the `service_obligation` concurrency case) are added. Touched tests running
against real SQLite move to `integration/`.

The typed bare-metal lease client follows `kit/pool-overrides`, not the family kit's
client (corrected with the maintainer when 5A started). A bare-metal-typed method on
`ComputeProvisioningClient` would make `compute_provisioning` depend on
`arkhai_bare_metal`, which "Family kits" forbids. Instead `ComputeProvisioningClient`
exposes a market-neutral `authenticated_request`, and `arkhai_bare_metal` owns
`BareMetalLeaseClient` beside the models it sends and returns, wrapping any transport
that offers that method. Both the mock-profile test and the bare-metal lease API test
use it.

The same rule exposes a second gap: the provisioning route-contract table in
`compute_provisioning/client.py` lists bare-metal routes (`/api/v1/bare-metal/leases*`
and `/test/bare-metal/*`), so a third compute domain would have to edit the family kit
to have its routes signed. Decided with the maintainer: 5B.1 makes the table
contributable. Each domain contributes its route contracts beside its typed client, the
provisioning service assembles them, and both the client and the service's
authentication read the assembled table.

Settled with the maintainer when 5B.1 began:

- **The `Lease*` operator models stay VM's.** *Reopened under "Job and host authority
  shape": the generic lease routes serve the neutral `LeaseView`.* They are the VM administration surface
  (`LeaseCreate` and `LeaseResponse` require `vm_target`), and `compute_provisioning`
  already owns the neutral lease contract (`LeaseRegistration`, `LeaseView`,
  `LeaseTermination`, `LeaseRetryRelease`, `LeaseForceRelease`). When the generic lease
  routes move (5B.8), the lease lifecycle serves the neutral view and VM keeps
  `/api/v1/leases` as a compatibility surface built from it, its VM fields blank for
  bare metal. Moving them would put VM vocabulary in the family kit; neutralizing them
  would change the wire the lease stages read.
- **Client packages stay light.** A domain declares its route contracts as plain data in
  its own package, with no dependency on `compute_provisioning`; the family kit adapts
  them when it assembles a table.
- **Clients take contracts, not the assembled table.** `ComputeProvisioningClient`
  resolves against the family kit's contracts; a domain's typed client passes its own
  contract to `authenticated_request`. Each adapter contributes its declarations beside
  its router mounts, the service's composition root (`main.py`) assembles them for
  request authentication, and the e2e test client assembles the family and domain
  declarations it uses. Assembly refuses a duplicate operation or route; within one
  contribution the first matching contract decides, as its owner ordered them
  (`/api/v1/pools/export` before `/api/v1/pools/{pool_id}`), and a path two
  contributions both match is refused.
- **Roles travel with each contract.** The family kit keeps writing its own routes
  with its operation sets (`ADMIN_PROVISIONING_OPERATIONS`,
  `DUAL_ROLE_PROVISIONING_OPERATIONS`), converted to per-contract roles when its table
  is built; a domain declaration states its roles. Chosen over restating roles on every
  family entry because it leaves the family kit's declarations unchanged.
- **Relay routes stay in the family table until relays move.** Relay models, client
  methods, controller, and services all live in `compute_provisioning` and the service
  today; their contracts move to VM with them (5B.9). Today they admit the seller role
  only, because they are absent from the admin set; that is preserved, and worth a
  review when they move.
- Noted, not pursued here: a complete plain-data route declaration is close to what a
  generator would need to produce the controller skeleton and client method from one
  source.

### Bare-metal publication has a dry run

The publication loop gains a dry-run step that reports what one pass would open, close,
refresh, or hold without publishing, so publication transitions follow the same
preview-then-advance convention as VM's.

### Restart recovery is proven at integration level, as VM's is

Decided with the maintainer. The lane begins from an empty database and never restarts a
service mid-run, the same as VM's; nothing about bare metal requires otherwise. Former
tasks 3.5 and 3.6 become bare-metal storefront integration tests that rebuild the
application over the same database file and a fake site: after settlement commit and
after teardown acceptance the buyer retrieves the same operation with no second
obligation, mechanism selection, or teardown, and the trading pause survives the
restart.

### The scenario uses typed clients

Discovery goes through the registry client; the seller side through `StorefrontClient`;
the site through the provisioning clients; on-chain escrow through a shared helper. The
bare-metal fulfillment routes go through `BareMetalFulfillmentTransport`, so e2e-tests
takes `arkhai-bare-metal-buyer` as a dependency. That is the interim the shell records
under "Where each route's typed client lives"; this change does not move the client.

### Lanes run on images built once

Decided with the maintainer. One pipeline job builds the wheels and every image once and
publishes them as a short-lived workflow artifact; each lane job depends on it, loads the
images, and runs its stack and scenarios without building. Each lane gains a run-only
Make target, and the existing `test-e2e-<lane>` targets become build plus run so local
use is unchanged. Toolchains needed only to build move to the build job.

### API credits runs in its own lane

Decided with the maintainer, and migrated from `apicredits-end-to-end-lane`: the third
lane runs the API-credit stack (`compose.apicredits.yml`) and `e2e_credits_deal` as its
own pipeline job, and the VM lane's stack no longer includes the API-credit services.
`e2e_alkahest_escrow_codecs` needs only the chain and stays in the VM lane. Planning
fixes the identity overlay split and checks `multi_registry` for a dependency on the
API-credit registry. Holding and stepping the API-credit storefront's loops in that lane,
and its production-application integration tests, stay with `apicredits-end-to-end-lane`.

### The real-host scenario stays, deactivated

Decided with the maintainer. `test_bare_metal_complete_deal` keeps its marker, which no
lane selects; the mock-provisioned scenario gets its own, `e2e_bare_metal_mock_deal`, so
selecting it never selects the real-host one. The permanent protected-lane requirement,
"Bare-metal hosted evidence is attributed by layer", is unchanged.

### Buyer CLI requirements belong with the buyer

Decided with the maintainer. Exact demand, refusing provisioning routes, strict result
and evidence decoding, and `teardown --from` semantics are properties of the `market`
command; this scenario drives typed clients and cannot observe them. Former tasks
3.1–3.4 and their `buyer-orchestration` delta move to `bare-metal-and-credits-domain-stacks`
Section 4b. The storefront-side half of teardown — one operation for a repeated request,
capacity released once — is proven here.

### The lane settles through Alkahest

The lane has no hosted authority, and a backed whole-host listing that settles by
introduction is the unbacked case `unbacked-bare-metal-listings` owns. Alkahest on the
lane's dev chain is how a backed bare-metal listing settles without a hosted service.

### Teardown is proven up to the site, not the host

With no host, teardown is observed as far as it is observable: the fulfillment reaches
`torn_down`, the site releases the reservation, the storefront receives the
capacity-released callback, and the next publication pass reopens the listing. That
access was actually revoked stays the protected lane's evidence.

### Every loop the scenario advances can be held and stepped

Implemented by `kit-owned-storefront-loop-lifecycle`. The lifecycle pause holds every
loop the bare-metal storefront runs, each loop has its own step, and the scenario pauses
once at the start and invokes every transition it depends on.

### The Alkahest path commits the lease window and registers the lease

Found in planning. Bare metal's Alkahest fulfillment reserves and schedules but never
commits the reservation or registers a lease: its hosted path commits with the lease
window, and VM's storefront commits and registers. An uncommitted hold expires under the
site's reservation watchdog and carries no lease end for expiry to find, so stages
09c–11b could not run. Fulfillment start commits the reservation with the materialized
lease window, as the hosted path does, and the storefront registers the lease through
the site's contract lease route once fulfillment is active, as VM does. This is inside
"add the functionality required for the 10b–11 stages".

### Lane composition files

Found in planning. `compose.local-identities.yml` binds both the VM and API-credit
services, so the VM stack cannot drop the API-credit services while it is layered.
`compose.apicredits.yml` redefines services it `include`s, which the overlay convention
says compose refuses, and it omits the API-credit storefront's EVM key that the shared
overlay carries. The overlay therefore splits per market, following
`compose.bare-metal-local.yml`: `compose.vms-local.yml` and `compose.apicredits-local.yml`,
with `compose.local-identities.yml` removed and `docker-compose.yml` layering both;
`compose.apicredits.yml` becomes `include`-only. `test_multi_registry` reads only the VM
stack's two registries and stays in the VM lane.

## Superseded decisions

Superseded after the 2026-10-02 job and host design review:

- **Compatibility models and re-exports** (`CredentialResponse` built from envelopes at
  the route boundary; `vm_provisioning_operator` re-exporting moved models) → "Pre-release
  wire and schema changes are accepted".
- **The `Lease*` operator models stay VM's** → the generic lease routes serve the neutral
  `LeaseView` ("Job and host authority shape").
- **The proposed job authority shape with credential option A** (the job authority owning
  `credentials` with its SSH columns) and **the executor's `notify_job_done`** → "Job and
  host authority shape": envelopes in persistence, engine-signalled terminal observation.
- **Host connection information as SSH fields in the family kit's models** → a
  connection envelope with per-kind codecs.
- **The host authority encrypting codec-declared secret fields at rest** (and the codec's
  `secret_fields`) → protected values the connection codec produces from a submitted
  secret, the authority stores opaquely, and the codec decrypts just in time ("Job and
  host authority shape").
- **Callers encrypting embedded keys before submission**, a premise taken from a stale
  model description → submission stays plaintext over the authenticated API, as the
  code does; on-wire protection is deferred with sealed submission.

Superseded after the 2026-10-02 layering review:

- **`JobExecution(runner, playbook_path)` in the executor table** → "A job executor is
  one complete executable", under "Provisioning execution leaves the VM adapter".
- **The bare-metal mock as an instance of VM's Ansible-shaped mock**, reached through
  the VM-adapter dependency → the Ansible distribution's mock executor with bare metal's
  contributed default output.
- **Job storage staying in the VM adapter behind a resolver port** → the job authority
  in `compute_provisioning.jobs`.

Superseded after the 2026-10-01 design review:

- **Force-accept over core `NegotiationService.force_accept`** → "Administrative
  acceptance goes through the runtime".
- **Evaluate-negotiate over a round-zero policy callable** → "Evaluate-negotiate previews
  the real opening".
- **An executor table keyed by action inside VM's job service** and **a
  `kit/compute-executor-mock` foundation kit** → "Executors are selected by offering mode
  and action, and each adapter owns its mock".
- **The settle path invoking the fulfill hook directly, with domain-local resumption** →
  "Settlement starts fulfillment" as refined.

Earlier:

- **"Mock provisioning gets bare-metal results, not a second mock"** was superseded
  before planning by "The bare-metal mock is the bare-metal adapter's own", now
  "Executors are selected by offering mode and action, and each adapter owns its mock",
  which also places the shared rule mechanism.
- **"The real-host scenario stays until its replacement is written"** is settled by
  "The real-host scenario stays, deactivated".
- **Restart in the lane** (former tasks 3.5–3.6) is replaced by integration tests.

## Risks / Trade-offs

- **Scope.** The change now carries kit route-service extractions, two new runtime
  operations, a compute-provisioning executor table, a negotiation composition,
  a release-ownership change, and pipeline restructuring. Accepted deliberately over
  managing further changes. Mitigation: each section is a reviewable unit that ends at a
  green gate, and sections land in an order that keeps every lane green — the executor
  seam and kit and runtime operations with VM and API-credit rebinding first, then
  bare-metal behaviour, then the shared stages with VM moved onto them, then the
  bare-metal scenario, then the pipeline.
- **VM's force-accept starts placing holds and committing plans** → a behaviour change
  in VM's deal path; a focused test proves settlement consumes the hold after
  force-accept as after a negotiated acceptance, and VM's lane is the gate.
- **VM regression through shared stages and rebinding** → VM moves onto the shared
  stages before any bare-metal driver exists, and each rebinding keeps wire paths and
  client methods.
- **The deal surfaces further bare-metal defects** → likely. Those inside the deal path
  this change already touches are fixed here; others are recorded against their owner.
- **Mock results drift from real playbook output** → the mock's output is parsed by the
  real result parser; drift is confined to the playbook's own output, which
  `node-access.yaml` already under-reports (no tenant address; tracked as unowned in the
  change index).
- **Image artifact size** → one compressed artifact kept for a day; if transfer time
  rivals build time, a registry-backed cache is the fallback.
- **Admin reserve's VM path** (`/api/v1/admin/portfolio/reservations`) carries VM
  vocabulary; it is kept for client compatibility. `remove-dead-storefront-physical-surfaces`
  does not retire it (checked 2026-10-01).
