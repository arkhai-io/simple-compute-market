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

*Refined by "Section 6 design: bare metal on the negotiation runtime (2026-10-07)": the
listing recheck, the trading pause, the retryable refusal, and the order of acceptance
writes become kit behaviour shared with VM and API credits, and bare metal places no
hold.*

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

*Refined by "Section 7 design: one explicit settlement composition (2026-10-07)": one
mechanism-neutral worker over the configured settlement runtime, composed inside the
runtime whenever it has a settlement composition, which is now required; its ready and
terminal hooks dispatch by mechanism, contact exchange declining.*

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

*Refined by "Controls and routes (5B.8)": the lease lifecycle is mode-agnostic and
release goes through the fulfillment aggregate through one provider-neutral executor
(7.3 is folded into 5B.8's lease slice); `/api/v1/leases` and the bare-metal lease routes
are removed in favour of the one family lease surface; backdating goes through the
site's truncate-lease, not a lease update.*

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
such as `CredentialResponse` are removed. *Refined by "Controls and routes (5B.8)",
decision 8: the family's wire models and route contracts move again, out of
`compute_provisioning` into a thin `arkhai-compute-provisioning-contracts` distribution,
and every typed client into a thin `arkhai-compute-provisioning-client` distribution.*

**`system_service.py` is split by owner**: aggregate health and status go to the
service, which composes contributed diagnostics; Ansible readiness goes to the Ansible
distribution; convergence and lease controls go to their owning capabilities. Generic
lease read, update, terminate, and admin routes move to `compute_provisioning` and serve
the neutral `LeaseView` (reopened with the maintainer; see "Job and host authority
shape"). *Refined by "Controls and routes (5B.8)": Ansible readiness is a contributed
component of the service's system status, not a route of the Ansible distribution
(decision 7); there is no generic lease update (decision 2); routes are framework-free
route services in the family kit that the service binds (decision 4).*

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
  the assembled table. *Corrected by "Controls and routes (5B.8)", decision 8: the
  service's authentication reads the assembled table; each typed client signs from its
  owner's contracts.*
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
- **An administrator can do everything** (ruled 2026-10-04). This is a repository-wide
  stance, applied in this change to the provisioning service's route table only, with no
  retrofit elsewhere: every route on that table admits the `admin` role (decision 1 of
  "Controls and routes (5B.8)").

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
neutral view. *Refined by "Controls and routes (5B.8)", decisions 1–3: the family lease
surface is `/api/v1/contract/leases`, with no update route; a lease's end moves only
through the site's truncate-lease.*

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

### Maintainer rulings on the 5B.6 implementation review

Decided with the maintainer after the review of slices B and C (2026-10-03). The
corrections land now, as part of 5B.6, which stays unchecked until they do.

1. **A held mock execution is cancellable.** Cancellation belongs to the runner: the
   executor reports the handle the runner gives a run and passes it back to the runner's
   `cancel`. The real runner's handle is the process id, signalled with `SIGTERM` (never
   an id of zero or less); the mock's names the run, and cancelling it ends that run's
   gate wait as a failed playbook, so the processing coroutine exits, the gate's held
   count drops, and the queue slot is released with no resume. The engine's conditional
   transition keeps the job `cancelled`. Proven by an integration test of the sequence
   submit, held, cancel, nothing held, nothing running, still cancelled.
2. **An inventory section means nothing to the host registry.** The group was only an
   import filter: a host's domain follows from its Resource Pool, and connection,
   capacity, and pool come from the entry's own variables; the group was never
   recorded. It existed because the service seeded from the VM operators' own
   inventory, which also lists infrastructure (`[frp_servers]`,
   `[provisioning_servers]`) and, written by the VM role on every create, the VMs
   themselves (`[kvms]`). Ruling: the importer registers every host entry, under any
   section, skipping only Ansible's `[group:vars]` and `[group:children]` sections,
   and names no group; the host authority logs every host it registers. The file
   given to the service lists only hosts to sell. VM's inventory becomes a directory:
   `inventory/hosts` (infrastructure, and the VMs the role records) and
   `inventory/provisioning-hosts.ini` (hosts to sell, under `[kvm_hosts]`, the group
   VM's playbooks target); the IaC tooling runs against the directory, and the
   service's `inventory_path` names only `provisioning-hosts.ini`. VM's own
   `ansible.cfg` skips the committed templates, the VM role's backups, and the YAML
   variable files kept in that directory, which Ansible would otherwise load. Bare
   metal already seeded from a host-only file.
3. **Shared Ansible configuration belongs to the distribution.** The distribution ships
   the generic `ansible.cfg` (callback, host-key checking, logging, deprecation warnings)
   and the service's `ansible_cfg` defaults to it. VM needs no role-path
   contribution: every VM playbook names its roles by relative path and no role
   includes another by name, so VM's `roles_path` served only operators running its
   playbooks by hand, who keep VM's own `ansible.cfg`. Bare metal declares its
   own Ansible collections (`requirements.yml`); the image installs the union. Bare
   metal's compose stack no longer mounts the VM tree. 5B.10's boundary check covers
   deployment configuration as well as Python imports: no domain's compose files,
   profiles, or settings defaults name another domain's tree.
4. **Real-run failure classification is a known limitation, deferred.** Classification
   reads only the runner's terminal message, so the transport, codec, and operator
   patterns classify mock failures but not real ones. Scanning raw output is rejected
   (an ignored task failure would stop retries). The follow-up is structured
   terminal-failure evidence from the runner (unreachable host, fatal task); recorded as
   deferred work in `tasks.md`.
5. **`non_retryable_errors` becomes `additional_non_retryable_errors`**, its meaning
   (patterns added to the built-in ones), stated by its name. Pre-release: no alias.
6. **The readiness wire contract is 5B.8's.** The operator client's dependency on the
   Ansible distribution for the readiness and connectivity models, and readiness
   reporting only VM's playbook, are resolved by 5B.8 (question 7 of its planning).
7. **Obsolete vocabulary is removed when touched**: the compute mock module no longer
   mentions job-done notification.
8. **Tests that use real SQLite are integration tests**: both job-row migration tests
   move to `tests/integration`.

### Architecture review: adapter imports of the deployed service (2026-10-03)

An architecture review checked the "Family kits" claim that neither provisioning
adapter imports the other or the deployed service. The first half holds (bare metal's
source and tests no longer import VM). The second does not yet: VM's adapter imports
`compute_provisioning_service` from 11 files and bare metal's from 3. All of it is
5B's to remove; the items no 5B task named are now assigned. Decided with the
maintainer:

- **Container reach-through (5B.8).** Exactly eight controller files resolve services
  through the service's `container` module: VM's `hosts_controller.py`,
  `jobs_controller.py`, `system_controller.py`, `test_controller.py`,
  `leases_controller.py`, `vms_controller.py`, and bare metal's
  `bare_metal_leases_controller.py` and `test_controller.py`. 5B.8 names them.
- **`ReservationNotProvisionableError` (5B.8 slice A).** Both domains' `compute_adapter.py`
  raise it, importing it from `compute_provisioning_service.services.compute_contract_service`.
  An error both domains raise belongs to the family kit: it moves to `compute_provisioning`
  beside the compute-adapter contract both implement. *Superseded by "Controls and routes
  (5B.8)", decision 10: the compute adapters that raise it, and the action route that
  reaches them, are deleted, so the error goes with them.*
- **`config.Settings` (5B.8 slice A).** Imported, as a type, by VM's
  `services/job_service.py` (the review attributed it to `runtime.py`, which does not
  import it). It goes when the job engine is built at the composition root and the job
  service receives the values it needs.
- **`resolve_identity_context` (5B.8 slice C).** Lazily imported by VM's
  `services/system_service.py`; it moves to the service with aggregate health and status
  when `system_service.py` is split.
- **Pool configuration and relay imports (5B.9).** `ansible_pool_config_handler.py`
  imports `AnsiblePoolConfig` and `Relay` from the service's `db.models` and
  `relay_rebinding` from its services; they move with the table metadata and relay
  modules. Relays are VM's: `compute_provisioning/relays.py` (relay models and client
  methods) also moves to VM in 5B.9, and the family-kit sentence in `ARCHITECTURE.md`
  already lists no relays.
- **Service-side adapter imports.** `capacity_inventory.py` imports both runtimes'
  resource-projection functions: the composed bundles carry a resource-projection
  contribution the service iterates without naming a domain (5B.8 slice C, with the
  contributed diagnostics). `db/migrations.py` imports VM's `legacy_backfill`: it stays,
  as a sanctioned composition-root entry point. It is a historical migration whose
  purpose is reconstructing VM's legacy rows, and migrations run in the migration init
  container where no adapter composition exists. The service's import-boundary test
  allowlists (file, module) pairs rather than modules any file may import:
  `container.py` and `main.py` the runtimes and routers, `db/migrations.py`
  `legacy_backfill`, nothing else.
- **What "depends on" means.** `ARCHITECTURE.md` now states that any import is a
  dependency — top level, function-local, under `TYPE_CHECKING`, or behind
  `try`/`except` — and that a repository-wide kit must never depend on a family kit.
  5B.10's adapter boundary test walks every `Import` and `ImportFrom` node of the
  syntax tree, relative imports included, not only module-level ones.

Out of scope, recorded elsewhere by the review: the `kit/capacity-publication` →
`core_storefront` edge, which this change does not touch. The review also assigned the
storefronts' import of the whole family kit for its wire contracts (a client
distribution split) to `kit-owned-listing-and-fulfillment-lifecycles`; this change now
does it ("Controls and routes (5B.8)", decision 8). That change's documents never
recorded the item, so nothing there changes.

### Controls and routes (5B.8)

Decided with the maintainer on 2026-10-04, question by question. 5B.8's premise did not
match the code: the plan assumed two lease surfaces and there are three, with different
roles and different jobs. The questions put to the maintainer, each with the
recommendation it carried, were: one lease surface or two (one); what a neutral lease
update may change (lease times only); the by-escrow lookup (a filter on the list route);
what a route service is (router factories in `compute_provisioning`); whether the
composition root builds the job engine (yes); the slices (A, B, C); and the readiness wire
contract (a lightweight projected contract). A further question, where the family's typed
client methods live, arose while answering them. Several recommendations changed in
discussion; what follows is what was decided. A design review the same day, discussed
point by point with the maintainer, corrected decisions 2, 4, 6, and 8 in place and added
decisions 9–11; "Design review corrections" at the end of this section lists what changed
and why.

**1. One family lease surface, and the lease lifecycle is mode-agnostic.**

A lease is not a resource and delivers nothing. It is the lifecycle tail on a site
reservation: the lease window, the executor target, the create and release handles, and
the lease state. `LeaseLifecycleService` and `ExecutorLeaseService` in `compute_provisioning`
own it for every mode, over the site ledger. Delivery is fulfillment's: a domain's
fulfillment provider creates the VM or grants the access, tracked by the fulfillment
aggregate. The two meet at release, where lease termination asks the aggregate to tear
down and the lease is released only when the aggregate reaches `torn_down`.

The three surfaces found:

| Surface | Serves | Roles | Callers |
|---|---|---|---|
| `/api/v1/contract/leases` (family) | `LeaseView`: register, get, terminate, retry-release, force-release | seller | the VM storefront through `ComputeProvisioningClient`; Section 7.2 plans the same for bare metal |
| `/api/v1/leases`, `/api/v1/admin/leases` (VM) | `LeaseResponse` with VM vocabulary: list with filters, create, by-escrow, get, update, terminate, release-oversight, retry-release, force-release | admin | the VM operator client, `test_leases_api.py`, e2e's `DealLease` |
| `/api/v1/bare-metal/leases` (bare metal) | `BareMetalLeaseView` with `physical_host_id` and `access_ref`: list, create, by-escrow, get | admin | the two bare-metal integration test files and the client's unit test |

Decisions:

- **The family surface absorbs VM's.** `/api/v1/contract/leases` serves register, get,
  list, terminate, release-oversight, retry-release, and force-release, all returning
  `LeaseView`. VM's routes, their route declarations, and VM's `Lease*` operator models
  are removed.
- **Bare metal's lease surface is deleted, and a bare-metal grant happens only through
  fulfillment.** Its create submits `node_grant_access` outside the fulfillment aggregate
  when no `create_job_id` is supplied. No production code calls it; it is a superseded
  manual delivery path that predates `BareMetalFulfillmentProvider`, which calls the same
  `grant_access` with a contract envelope and records the job in the aggregate. Once
  release goes through the aggregate, a lease granted this way cannot be released by
  expiry or termination (`submit_release` finds no aggregate), and because the route and
  the provider derive different operation ids, one reservation could receive two grants.
  Deleted: the route, its controller, `BareMetalLeaseService`, `BareMetalLeaseClient`,
  `BARE_METAL_LEASE_ROUTES`, `BareMetalLeaseView`, and `bare_metal_access_ref`.
  `BareMetalLeaseCreate` survives only as the grant parameters the provider prepares,
  renamed to say so (`BareMetalAccessGrant`). The integration tests drive grants through
  fulfillment, as VM's do. The generic action route, the other path that granted outside
  fulfillment, is deleted too (decision 10).
- **`physical_host_id` stays out of the lease.** It belongs where the grant happens: the
  job parameters, the provider's metadata, and the result. The site's cross-mode
  accounting reads it from the Physical Resource's declared attributes, not from a lease.
- **A lease surface records and releases; it never delivers.** A domain extends what a
  lease shows by contributing a versioned projection, never by adding or overriding lease
  routes. Nothing needs such a projection today: a buyer's access details come from the
  fulfillment result.
- **The lease lifecycle is mode-agnostic.** The offering mode belongs to the reservation,
  recorded by the site when capacity is claimed; a lease only reads it. `LeaseRegistration`
  drops `offering_mode`, whose only effect was a guard against a mismatch with the
  reservation. `LeaseView` keeps reporting the reservation's mode. Release goes through
  one provider-neutral fulfillment release executor and its status port for every mode:
  the aggregate already knows its provider through the pool, so a mode key carries no
  information. The per-bundle `release_executor` contribution, both mode-keyed dispatch
  tables (`ExecutorReleaseDispatcher`, `ReleaseJobDispatcher`), `BareMetalReleaseExecutor`, and
  the `direct-release` sentinel it alone produced (which released capacity with no
  teardown proof) are removed; the lifecycle's VM-named failure reasons (`vm_remove_failed`,
  `vm_remove_timeout`) become neutral. **7.3 is folded into 5B.8's lease slice.** Revisit
  trigger: a future mode whose delivery is not fulfillment-backed would route release on
  the aggregate, not on the mode.
- **Roles.** Every route on the provisioning service's table admits `admin` (the
  maintainer's stance, "Maintainer rulings for review"): the family table's default for an
  unlisted operation becomes seller and admin, the separate dual-role set is removed as
  redundant, and `route_contract_from_declaration` refuses a domain declaration that does
  not admit `admin`. Only identity rotation and VM's operator idempotency read the caller's
  principal, and both are admin routes already. The lease routes:

  | Route | Roles |
  |---|---|
  | register, get, terminate | seller, admin |
  | list, release-oversight, retry-release, force-release | admin |

  A storefront addresses its leases by reservation id; a list would show it every lease
  at the site, including other storefronts'. Retry-release and force-release lose the
  seller role the contract routes gave them; no production code calls them as seller.

**2. No lease update; a registered lease's end moves only through the site's truncate-lease.**
(Amended at the slice B design review, below: registration and `commit` rules.)

VM's `PATCH /api/v1/leases/{id}` wrote any non-terminal reservation, `releasing` included.
It is removed rather than reproduced, field by field:

- Executor identity (`host_id`, `vm_target`, `executor_target`, `executor_ref`) is
  immutable after registration, because changing it can redirect teardown. If VM
  migration ever becomes real, it gets an explicit migration operation.
- Lifecycle evidence (`release_job_id`, `create_job_id`) is written only by the lifecycle,
  never by an operator.
- Agreement evidence (`lease_start_utc`) is immutable.
- The offering mode was never writable in substance.

The site already ends a lease early: `POST /api/v1/capacity/reservations/{id}/truncate-lease`
(`CapacityLedgerService.truncate_lease`), open to seller and admin, typed in
`SiteCapacityClient`, and reached through `kit/capacity-publication`, which routes it to
the reservation's recorded site. The VM storefront uses it for uncollected terminal
settlements and spot interruption, and it is what on-demand early termination needs. It
stays the one primitive and stays on the capacity surface: `kit/capacity-publication`, a
repository-wide kit, reaches sites only through the site client and may not depend on a
family kit, and the capacity runtime's calls are pinned to the reservation's site where
the VM storefront's provisioning client talks to one configured URL. e2e backdates through
the typed site client, signed as admin.

Three defects in it are fixed:

- Truncation refuses `releasing`, `release_failed`, and `unmanaged`, returning `null` as
  both callers already handle; it used to force them back to `leased`, undoing the release,
  oversight, or repair the lifecycle recorded. It also refuses `reserved` and
  `provisioning`: an uncommitted hold is released, not truncated (decision 9).
- Truncation refuses a later end; extension belongs to on-demand work as a deliberate
  operation with its own commercial check.
- Truncation forced a `reserved` reservation to `leased`, which happens when a VM
  settlement terminates before commit; with release through the aggregate, it then landed
  in `release_failed`. First recorded as a gap for VM's storefront; the design review moved
  the fix into slice B (decision 9): the storefront releases the hold, and truncation
  refuses the state.

**Lease registration writes the lease tail once.** `attach_lease` accepted any held state
and overwrote the target, `executor_ref`, start, end, and `create_job_id`, setting the
state to `leased`; the VM storefront's fulfillment-resume pass re-registers with the
deal's original window, which would restore a truncated end or flip a releasing lease back
to `leased`. Now a lease is registered once its executor target is recorded: a first
registration (no target recorded) on a `reserved`, `provisioning`, or `leased` reservation
records the tail and leaves it `leased`; a repeat with the same target and start returns
the record unchanged and never moves the end; a repeat with a different target or start
is refused (409); registration on `releasing`, `release_failed`, or `unmanaged` is
refused; a recorded `create_job_id` is never replaced. `commit` gets the matching guards:
it refuses the lifecycle's states and leaves a registered lease's window alone. The
maintainer weighed accepting that an operator can break things through admin routes, and
chose consistency with decision 2. (The first sentence of this rule originally said a
first registration applies only to a reservation not yet leased; the slice B design
review found that `commit` always leaves the reservation `leased` first, and keyed
registration on the executor target instead.)

**3. Leases are keyed only by reservation id.** `escrow_uid` is Alkahest's mechanism
reference, not the universal deal identity (`obligation_ref`); the site lifts it out of
the caller's `deal_ref` only when present, and a bare-metal hosted deal records
`{"negotiation_id": …, "hosted_obligation_ref": …}`, so a by-escrow lookup cannot find
its lease. `ARCHITECTURE.md` ("Identifiers") also keeps commercial agreement identity from
crossing the provisioning boundary merely for correlation; every caller that owns a deal
already holds its reservation id. A `deal_ref` filter would correlate by commercial
identity under a neutral name and make the family surface interpret the caller's opaque
dict. So: no by-escrow route and no escrow or `deal_ref` filter; the list filters on the
neutral `status` and `offering_mode`; VM's `host_id` filter is not carried over, since a
host is not a family-neutral lease concept. An operator starting from an escrow uses the
site's existing reservation-list filter, then reads the lease by id. `LeaseView.deal_ref`
stays as reported data.

**4. Route services are framework-free, the service binds them, and adapters bind their
own routes through accessors.**

The precedent survey: pool overrides, the storefront lifecycle and deal controls, the
settlement admin and hosted routes, and introductions each put a framework-free route
service in their kit and leave the FastAPI binding to the storefront; `kit/pool-overrides`
also owns its path constant, operations, signed-resource builder, models, and typed client.
`kit/site` is the exception: it ships its own FastAPI router (`make_capacity_router`). The
dominant pattern is promoted to `ARCHITECTURE.md` ("Route contracts and their HTTP
binding") as five pieces — wire models, route contract, typed client, route service, HTTP
binding — with the binding owned by whatever composes the process. The first
recommendation (router factories in the family kit, after `make_capacity_router`) is
withdrawn: it contradicted "Deal controls are kit-owned route services" and the family
kit's own `MockRuleRouteService`, and the maintainer wants the family kit framework-agnostic.

- `compute_provisioning` gains `JobRouteService`, `HostRouteService`, `LeaseRouteService`,
  and `JobTestRouteService` (summary, drain, wait), with one `ProvisioningRouteError(status_code,
  detail)` into which `MockRouteError` folds. `HostRouteService` serves host CRUD, enable
  and disable, and connectivity, taking probes keyed by connection kind as contributions
  (decision 7).
- **Host import is the Ansible implementation's** (design review). `POST /api/v1/hosts/import`
  takes a multipart Ansible INI file and an `ssh_key_type` field; injecting the parser
  would not make the operation family-neutral, and a domain with a non-Ansible executor
  should not see it in the family contract. `compute_provisioning_ansible` owns its route
  contract (a plain declaration it contributes), an `AnsibleHostImportRouteService` over the
  host authority and the existing parser, and a typed client extension (async and sync)
  over the family client's `authenticated_request`. The provisioning service binds it at
  the existing path.
- The provisioning service binds them in thin controllers in
  `compute_provisioning_service/controllers/`; the contract controller's lease routes move
  into the lease controller. System routes for the service's own workers (fulfillment
  convergence and the lease watchdog live in `compute_provisioning_service/services`) are
  bound there directly with no kit route service.
- Each adapter exports router factories for its own routes taking zero-argument accessors,
  because `main.py` mounts routers when it builds the app and services are resolved later in
  the lifespan; the service passes the accessors, so no adapter imports `container`. The
  service cannot bind domain routes itself without naming them.
- Both adapters declare their own web dependencies; they import FastAPI and
  `fastapi_utils` today through `arkhai-compute-provisioning-service`, which 5B.10 removes.
- **Drift guard (option 1):** a service test asserts every route the app mounts resolves to
  exactly one contract and every contract to a mounted route. Recorded as a possible
  follow-up (option 2): path templates in the family contracts, from which the regex is
  derived and the service binds, single-sourcing the family's paths.

**5. The composition root builds one `HostAuthority` and one `JobEngine`.** The root
supplies the `ssh` codec from `compute_provisioning_ansible` (with the service's decryption
key), capacity derivation, VM's relay pool-change hook as a VM contribution (a static
declaration the adapter exports and the root merges, like `HOST_REQUIREMENT`, because the
authority exists before any runtime does), the retry policy (`retry_policy_from` moves to
the service), and the executor table (created empty, filled and frozen by
`compose_adapter_bundles`). Both runtimes receive the authorities; neither owns them for its
sibling. VM's `AnsibleJobService` shrinks to VM submission (`VmJobParams` into an engine
submission, with `default_host_id` passed as a value, so its `Settings` import goes) and is
renamed to say so (`VmJobSubmitter`); every other caller reads the engine.
~~`ComputeContractService` consumes `JobEngine` directly~~ (superseded by decision 10: the
contract service is deleted with the action surface), and the lifespan runs the engine's
queue handler and retry scheduler. The maintainer's instruction that
`ReleaseJobDispatcher`'s bare-metal entry consume the engine is met by removing the
dispatcher with the fold of 7.3. A composition unit test asserts one engine and one host
authority reach both runtimes (`TESTING.md`'s composition-boundary convention).

**6. Slices.** A0 → A → B → C, each ending with the provisioning-family suites green,
comment hygiene, and a checkpoint:

- **A0, the contracts and client packages** (decisions 8 and 11), opened by the route
  ownership matrix and by deleting the generic action surface (decision 10), so no client
  is written for routes about to go: `VersionedEnvelope` to `arkhai-core`; the compute contracts and client
  distributions; the resource-pool contracts and client distributions; capacity-definition
  import in `kit/site-client`; every existing operation moved to its owner's client, with
  sync variants and parity tests; VM's extension client and the Ansible host-import client;
  every caller migrated. No wire change beyond the action surface's removal.
- **A, authorities at the root and the job and host routes**: decision 5;
  `ProvisioningRouteError`; the job, host, and test-job route services and their bindings;
  the Ansible host-import route service; VM's jobs controller removed and its hosts
  controller reduced to the VM capacity route; the connectivity probe contribution and its
  runner; adapters' web dependencies; the drift-guard test.
- **B, the lease surface and mode-agnostic release** (decisions 1–3, 9, and 7.3): the lease
  route service and roles; registration without `offering_mode`; `attach_lease` write-once
  and the truncation and commit guards in `kit/site`; the release guard where capacity is
  freed; one release executor and status port, deciding by the aggregate's state; the VM
  storefront releasing an uncommitted hold instead of truncating it; VM's and bare metal's lease surfaces deleted; grants only through
  fulfillment; e2e `DealLease` through the family client and the site client.
- **C, the system split and the last `container` reach**: health, status, version, and the
  worker controls bound by the service; status with the execution section and contributed
  components (decision 7); `resolve_identity_context` stays in the service;
  `capacity_inventory.py` iterating a resource-projection contribution; VM's
  `system_service.py` deleted; VM's VM-operation, capacity, and mock-rule routes and bare
  metal's mock-rule routes as accessor-taking router factories; the service's
  import-boundary test allowlisting (file, module) pairs.

**7. Execution readiness is part of system status; connectivity is a contributed probe.**

Today `GET /api/v1/system/ansible/readiness` returns `AnsibleReadinessResponse`
(`ansible_version`, `ansible_mode` from `ACTIVE_PROFILES`, `executor_modes` from the table,
`inventory`, VM's `playbook`, `ssh_keys`). The operator client imports the Ansible
distribution for it; bare metal's playbook is invisible; the profile-derived mode can
disagree with the executors (5B.6 slice C found exactly that); and `inventory.path` is
`settings.database_url`, which can carry a password that "Operator lifecycle controls"
forbids a diagnostic to expose.

- **No readiness route.** `GET /api/v1/system/status` carries it. `SystemStatusResponse`, a
  new model separate from `HealthResponse` so `/health` stays lean, keeps today's
  `status`, `checks`, and contract-version fields and gains:
  - `checks.execution`: `ok`, or `degraded` when a contributed component is not ready;
  - `execution`: `mocked` (true when every composed executor is the mock) and `executors`,
    a list of `{offering_mode, mocked}`;
  - `components`: `{name, ready, detail}`, the detail a versioned envelope.
- **"Mode" is not used for mock versus real**, because offering mode is the reserved term:
  mock versus real is the boolean `mocked`, and executors are listed by `offering_mode`.
  `ansible_mode` and the profile-derived value are removed; `JobExecutorTable.executor_modes()`
  becomes a method returning `{offering_mode: mocked}`.
- **The Ansible distribution contributes the `ansible` component**: `ansible_version`, each
  Ansible executor's offering mode and playbook (path, existence, sha256), and the SSH key
  references from the registered hosts, found by reading the Ansible executors in the table
  so every contributed playbook is reported. It is ready when every playbook exists and
  Ansible is on `PATH`, or the executors are mocked. `FileInfo` and `SshKeyInfo` stay as its
  payload models; `AnsibleReadinessResponse`, `InventoryInfo`, and the database URL go.
- A degraded status still answers 503; the typed client accepts that body, so e2e reads
  `execution.mocked` whatever else is degraded. Status already calls the storefront; it now
  also runs `ansible --version` and hashes playbooks.
- Callers: e2e's mock-mode checks read `execution.mocked`; the smoke readiness test becomes
  a status test; the validation runbook's `jq` follows.
- **Connectivity**: `ConnectivityResult` (host, reachable, detail) becomes a neutral host
  model; `HostRouteService` takes probes keyed by connection kind (the shape of
  `ConnectionCodecs`), and a host whose kind has no probe is refused (422); the root
  registers `ssh` → the distribution's `probe_connectivity` over a runner the root builds
  (`AnsibleRunner`, or `MockAnsibleRunner` under the mock profile, whose connectivity always
  succeeds) instead of borrowing VM's runner, which today serves bare-metal hosts too.

**8. The family's wire contract and its client become thin distributions.**

Two clients served one service, split by history: `ComputeProvisioningClient` in
`compute_provisioning` (async, caller-chosen role; contract operations, contract leases,
rotation, fulfillment, relays) and `vm_provisioning_operator`'s `ProvisioningClient` and
`SyncProvisioningClient` (always admin; of about seventy methods only the ten VM operations
and the host capacity check are VM's, the rest being family routes, service routes such as
pools, and site capacity reads that duplicate `kit/site-client`). Bare-metal e2e uses VM's
client to administer pools; the bare-metal adapter declares a dependency on VM's client it
never imports. A thin client must not carry the family kit's weight (`kit-site` brings
FastAPI and SQLAlchemy), and `ARCHITECTURE.md` lets a family split its kit where weight
would force consumers to install what they do not use. So:

- **`provisioning/compute/contracts`** (`arkhai-compute-provisioning-contracts`,
  `compute_provisioning_contracts`; depending on `arkhai-core` for `VersionedEnvelope`,
  `kit-identity` for the empty-body sentinel and the rotation models, and pydantic): the
  versioned contract models, the host, job, lease, and system models,
  `SystemStatusResponse`, the neutral `ConnectivityResult`, and the route contracts
  (`ProvisioningRouteContract`, the family routes and roles, `ProvisioningRouteTable` and
  its assembly, declaration validation, canonical request bodies). It carries no
  resource-pool or site model: those belong to their capabilities (decision 11). The family
  kit, the service's authentication, the adapters, and the client import them from here.
  Two packages rather than one so the server never depends on its own caller (the
  direction `kit/site/auth.py` names as wrong).
- **`provisioning/compute/client`** (`arkhai-compute-provisioning-client`,
  `compute_provisioning_client`; the contracts, `kit-identity`, and httpx):
  `ComputeProvisioningClient` and `SyncComputeProvisioningClient` over one signing base (the
  family client's and VM's `_ProvisioningClientBase`, merged), one error hierarchy,
  `authenticated_request` in both variants for domain extensions, the polling helper, and
  the client protocol, covering every route the ownership matrix gives the compute family
  and nothing else. Family methods return typed models.
- **Who reads which table** (design review): the provisioning service's authentication
  resolves requests against the table the composition root assembles from every
  contribution. The family client signs family routes from the family contracts; a domain's,
  an implementation's, or a capability's typed client signs its routes from that owner's
  contracts through an `authenticated_request` transport. Both sides use the same
  contributed contract data, so operation, resource binding, and roles cannot diverge.
  Qualified at the A0 checkpoint review: the site capacity authority keeps separate server
  and client declarations (decision 11), so for its routes a contract-parity test holds the
  two equal instead; the delta requirement says so.
- **A route-ownership matrix opens A0** (design review): every route the provisioning
  service serves is assigned its owner (compute family, Ansible implementation, VM, bare
  metal, resource pools, site, or the provisioning service itself) before anything moves,
  and the matrix decides which contracts package and client receive each operation, so
  A0 does not become "everything in `vm_provisioning_operator` moves to the family client".
  Planning made the matrix (`tasks.md`, 5B.8). One consequence: the family table stops
  copying the site's capacity routes, and the service assembles `kit/site`'s own
  `CAPACITY_ROUTE_CONTRACTS` instead, so the site's contracts are declared twice (server
  and client, held by their parity test) rather than three times.
- **Deleted**: `ComputeProvisioningClient` and the route-table code from
  `compute_provisioning`; the generic clients from `vm_provisioning_operator`; their parity
  test.
- **A sync variant replaces VM's sync client like for like**, because e2e's generic calls
  use one today; `TESTING.md`'s parity rule is conditional ("when a client package exposes
  both"), is not amended, and requires the parity test because the new client exposes both.
- **VM keeps a small extension client**: `vm_provisioning_operator` keeps VM's models and
  route declarations plus `VmOperatorClient` and `SyncVmOperatorClient`, typed methods for
  VM's ten operations over the family client's `authenticated_request` (the
  `kit/pool-overrides` shape), depending only on the two thin packages. The family client
  names no domain route.
- **Relays skip a move**: their wire models, route contracts, and client methods go
  straight to VM's packages; 5B.9 still moves the serving code and tables.
- **Site capacity stays with `kit/site-client`**, that capability's client; e2e drives
  `SiteCapacityClient` through `asyncio.run` for capacity reads and backdating, as
  bare-metal e2e already drives `SiteCapacityAdminClient`.
- **Integration tests use the async variant**: httpx's in-process ASGI transport is
  async-only, and a sync client in-process would need Starlette's `TestClient`, which runs
  the app on its own loop thread, away from the tests' synchronization seams. The sync
  variant is covered by the parity test and by e2e.
- **`VersionedEnvelope` moves to `arkhai-core` (`market_core`)**, which depends only on
  pydantic: the versioned-envelope rule applies to every provider-specific payload crossing
  a boundary, which makes it universal to every market. `kit/fulfillment` and every importer
  take it from there; no re-export.
- Package dependencies follow: the family kit, the service, both adapters, and the Ansible
  distribution depend on the contracts; both storefronts on the contracts and the client,
  dropping `arkhai-compute-provisioning` if nothing else they import remains there;
  `e2e-tests` on the client, plus VM's package for VM operations only; the bare-metal
  adapter's unused dependency on VM's client goes.

**9. A lease that was never delivered is released by what its fulfillment proves**
(design review). In this codebase `commit` moves a reservation straight from `reserved` to
`leased`, and nothing sets `provisioning`; so `leased` spans everything from "committed,
fulfillment never begun" to "active". Fulfillment teardown can begin only from `active`
(convergence retries it from `teardown_failed`); the settlement-abandonment hook abandons
only an `assigned` aggregate; and a `failed` aggregate may have left a workload (the slice B
design review corrected the causes first recorded here: see its point 3). Under
mode-agnostic release every undelivered lease would therefore end in `release_failed`. The
review proposed releasing `reserved` and `provisioning` directly and truncating `leased`; the
first half is adopted, the second does not hold, because a `leased` reservation is not
necessarily delivered. Decided:

- **An uncommitted hold is released, not truncated.** The VM storefront's
  terminal-settlement path asks the capacity runtime to release the reservation and
  truncates only if the release is refused; the site's release guard (slice B design
  review, point 4) frees an uncommitted hold and refuses a delivered lease. Truncation
  refuses `reserved` (and `provisioning`).
- **Release follows the aggregate's state.** The complete table, by every aggregate state,
  is the slice B design review's point 3; in summary:

  | Aggregate | Release |
  |---|---|
  | `active`, or teardown already begun | begin or adopt teardown |
  | absent, `assigned`, or `abandoned`, with provenance proving no dispatch; or `torn_down` | free the capacity directly, as a completed release, through the release guard |
  | `dispatch_pending` or `dispatching` | the release is remembered and waits for the create to settle |
  | `failed`, or absent, `assigned`, or `abandoned` without that proof | `release_failed`, for an operator to verify the host and force-release |

- **Provenance proving no dispatch** is all three of: the aggregate is absent, `assigned`, or
  `abandoned`; the reservation records no create handle; the job authority holds no job
  bound to the reservation (job rows carry an indexed `capacity_reservation_id`). With the
  generic action route deleted, fulfillment is the only path that puts a job on a
  reservation. The proof is checked by the release guard inside the transaction that frees
  the capacity (slice B design review, point 4).
- **An in-flight termination is remembered by the lease lifecycle** (option (a), chosen over
  a teardown intent on the aggregate). Expiry or terminate moves the reservation to
  `releasing` at once, with the fulfillment id as its release handle; `releasing` is already
  durable and already the lifecycle's state, so it survives a restart and a second request
  finds it. The release poll begins teardown when the aggregate reaches `active`, and records
  `release_failed` if it ends `failed`; the grace timeout does not run while the create is
  in flight. `kit/fulfillment` is unchanged. The maintainer noted the tension between the
  two lifecycles here and chose the lease lifecycle for this case.

**10. The generic action surface and the compute-adapter architecture are deleted**
(design review). `POST /api/v1/actions` reaches each domain's compute adapter: VM's only
action is `create`, which makes a VM outside fulfillment, and bare metal's only action is
`node_grant_access`. Refusing delivery actions on it would refuse everything, so it is not
narrowed but removed. No production code calls it or the three contract job routes beside
it (`GET /api/v1/jobs/{id}/contract`, its credentials, and its cancel), and the compute
adapters are the `ExecutorAdapterRegistry`'s only users. Deleted: the four routes and their
contracts; both domains' `compute_adapter.py`; `ExecutorAdapter`, `ExecutorAdapterRegistry`,
the bundles' compute-adapter contribution; the action half of `ComputeContractService` and
its client methods; `ReservationNotProvisionableError`. `ExecutorActionEnvelope` stays: the
fulfillment providers submit their jobs with it as the job's contract record. The
`physical-provisioning` requirement "Validated executor registration" is modified: its
executor-adapter dimension goes, and its duplicate-key guarantee is the job executor
table's, already required by "Job execution resolves its executor by offering mode and
action". Delivery happens only through fulfillment, for every mode.

**11. Resource pools and capacity definitions get thin surfaces of their own** (design
review). The family route table declared the pool routes and the capacity-definition
import, `compute_provisioning` re-exported their models (`market_resource_pools`,
`market_site`), and decision 8 first had the family client cover them. Hosting a route does
not make it the host's: under the five-piece pattern each belongs to its capability. Typed
pool methods on the family client would also have required `kit-resource-pools`, which
brings SQLAlchemy. The maintainer chose to make the thin surfaces now rather than record
the debt:

- **`kit/resource-pools-contracts`** (`arkhai-kit-resource-pools-contracts`; pydantic and
  `kit-capability-shape`): the pool models, the declaration hints they validate with, and
  the pool route declarations as plain data. The hints module moves whole, so its many
  importers across kits, storefronts, listings, and the API-credit service repoint to it. `market_resource_pools` keeps the authority and
  persistence and imports its models from here; `ResourcePoolService` is the framework-free
  route service, and the provisioning service keeps the HTTP binding and assembles the
  declarations into its table.
- **`kit/resource-pools-client`** (`arkhai-kit-resource-pools-client`; the contracts only):
  `ResourcePoolClient` and `SyncResourcePoolClient` over any transport offering
  `authenticated_request`, the shape `kit/pool-overrides` uses, so a repository-wide kit never
  imports the compute family's client.
- **Capacity-definition import goes into `kit/site-client`**, the site capability's existing
  thin client, under the site's current convention: its own model copies, its own route
  table entry, and the server-and-client parity test extended to cover it. A site contracts
  package is recorded as the alternative for later.
- `compute_provisioning` stops re-exporting pool and capacity-definition models, and the
  `physical-provisioning` delta no longer claims to own resource-pool models.

**Design review corrections (2026-10-04).** The review endorsed the 5B.8 direction and
asked for seven corrections, each verified in code and discussed with the maintainer:

| Review point | Outcome |
|---|---|
| Resource-pool contracts are not compute contracts | Accepted, with thin surfaces now rather than debt (decision 11) |
| Host import is Ansible-specific | Accepted (decision 4) |
| The assembled-table rule contradicts the client design | Accepted; the same contradiction stood in this document (decision 8) |
| Fix pre-fulfillment termination in slice B | Accepted and widened: the hole is any undelivered lease, because `leased` begins at commit (decision 9) |
| Close the direct bare-metal grant on the action route | Widened: VM's create is the same hole, so the whole action surface goes (decision 10) |
| The contracts depend on `arkhai-core` | Accepted (decision 8) |
| Reconcile stale decisions and plan implementation-sized tasks | Accepted: superseded passages are marked and listed under "Superseded decisions"; the task plan follows in planning |

**Findings recorded for closeout** (none is fixed by 5B.8 unless stated above):

- `kit/site` ships its own FastAPI router, outside the five-piece pattern.
- VM's storefront binds pool overrides with a literal path under a router prefix rather than
  `POOL_OVERRIDES_PATH`, as bare metal does.
- The site's route contracts are declared twice, `kit/site/auth.py` and `kit/site-client`,
  held by a parity test (the family table's third copy goes in 5B.8.A0.3); a site contracts
  package would make them one.
- Bare metal's mock-rule routes have no typed client.
- `ReservationState.provisioning` is never set: `commit` moves a reservation from `reserved`
  to `leased`.
- "An administrator can do everything" holds only on the provisioning service's route
  table; the repository-wide stance is a roadmap gap.
- Path templates in the family route contracts (decision 4, option 2).
- `CapacityLedgerService.find_active_lease_by_vm_target` has no production caller and
  carries VM vocabulary in `kit/site`.
- A lease truncated after commit but before registration can still be extended (slice B
  design review, point 2).
- Published packages depend on unpublished ones (found in A0): `arkhai-compute-provisioning-service`
  and the VM storefront depended on `arkhai-compute-provisioning`, and `kit-site` depends on
  `kit-resource-pools`, none of which `.github/workflows/publish-pypi.yml` publishes. After A0
  the storefronts, `kit-site`, VM listings, and the API-credit service depend on the new thin
  packages, which are unpublished too, so the gap keeps its shape. 13 of the 31 published
  packages depend on an unpublished internal package, so publishing the thin packages alone
  would not make the graph installable from PyPI, and each newly published package needs its
  one-time trusted-publisher setup. Ruled at the A0 checkpoint review: fixed in this change,
  before closeout, for the whole graph (`tasks.md`, 2.0); until then the thin packages are
  deliberately unpublished.

**Slice A0 implementation findings (2026-10-04).** Verified in code during A0; each corrects
the plan, not a decision above. The first two, and the publishing gap above, were reviewed
with the maintainer at the A0 checkpoint's start; the rest are open for review.

| Finding | Resolution |
|---|---|
| `UnsupportedExecutorActionError` is the job executor table's lookup error, which the engine catches to fail a job | Kept beside the table; only the adapter registry's names went |
| `ComputeContractService` had no lease half: the lease routes call the lease services from the controller | The service is deleted whole in A0.1; the controller keeps a private error for a reservation recording no mode (still 409) until B |
| `test_job_contract_values.py` tests `JobRetryPolicy`, `ConnectionEnvelope`, and `ExecutionHost`, which stay in the family kit | Not moved; `test_contracts.py` and `test_route_table.py` were split by owner instead: contract tests to the contracts package, client-signing tests (and `test_fulfillment_client_opacity.py`) to the client package, the event-sink test to `test_events.py`, the two site-route cases to the service's route-table test |
| The family table's assembly needs the pool, capacity-definition, host-import, and relay declarations to exist in their owners' packages | A0.5 and A0.6 ran before A0.3; the slice's content is unchanged |
| The site's canonical body differs from the family's for its query-bearing routes | The service canonicalizes a site route with `market_site.auth.canonical_site_request_body` and every other route with the family's (`compute_provisioning_service/route_table.py`); the family contracts carry no capacity paths |
| The site client always signed as `seller`, while decision 2 has e2e backdate through it as admin and capacity-definition import is admin-only | Both site clients take `caller_role` (`seller` by default) |
| Site contracts admit `admin` by rule rather than by name | Translated into named roles when the service assembles them, so `capacity_reserve` and the other seller routes now admit `admin` on this service too, as the administrator ruling intends; relay declarations admit seller and admin (seller-only before, by the family default) |
| VM's and Ansible's extension clients need only the transport's `authenticated_request` | They depend on the contracts and duck-type the transport, as `kit/pool-overrides` does, not on the client distribution |
| The service's import-boundary test forbids `vm_provisioning_operator`, while its relay controller reads VM's relay models until 5B.9 | A named (file, module) allowlist entry, the mechanism C.4 plans, for that one import |
| System status, health, readiness, and worker controls return dicts in VM's client, and callers index them | The family client keeps dicts for those until C types status as `SystemStatusResponse`; fulfillment, lease, job, host, and version methods return contract models |
| The bare-metal adapter declared dependencies on VM's adapter and VM's client it never imports | VM's client removed; VM's adapter restored at the gate, because the service module the adapter reads its collaborators from loads VM's adapter at import |
| Checkpoint review: `ExecutorActionEnvelope` stayed in the thin contracts package after the action route's deletion, and four contract-job models lost their only route | Maintainer decision: the envelope becomes the job authority's internal `JobActionRequest`, the error envelope moves beside `JobFailure`, and the dead models go (5B.8.A.5) |

**Slice A implementation review (2026-10-05).** A code review of slice A approved its
direction and raised three findings, each verified in code and decided with the maintainer
before any change. They are fixed in 5B.8.A.6, ahead of slice B.

1. **An imported inventory moved hosts around the pool-change hooks.** `update_host` moved a
   host through `_move_to_pool`, which runs every contributed hook, but `apply_inventory`
   assigned the pool directly. An operator could bypass VM's relay rule — a host whose VM
   tunnels a buyer holds may not move to a pool dialling another relay — by importing an
   inventory. It also contradicted this design's own statement that the host authority
   applies an inventory "with its pool-change and capacity effects".

   Decided:
   - Every change of an existing host's pool goes through the hooks, on either path.
   - Assigning a host its current pool is not a move and runs no hook (`update_host` used to
     run them anyway).
   - The import is one transaction, so a refusal leaves every host it names unchanged.
   - A refusal is a conflict, not a bad request. `compute_provisioning.hosts` gains
     `PoolChangeRefusedError`, which a hook raises, and both the host update route and the
     Ansible import route answer it with 409. VM's hook adapter translates the relay
     module's `RelayRebindingRefused` into it. The relay route already answered that
     refusal with 409, on the same reasoning: the request is valid once the host is drained.

   The service's integration harness had built its host authority without hooks, so no
   service-level test could have caught this. It now takes the hooks from the production
   container.

2. **The job list's `sort` had no client method argument.** The route and its route service
   accepted `created_at_asc` and `created_at_desc`; neither client could send them, against
   the "a method for every route" rule of the five-piece pattern. Decided: the order
   vocabulary is defined once in the contracts package (`JobListSort`), the clients send it,
   and the route service validates against it.

3. **`JobActionRequest` was half wire contract.** It carried `parameters`, which the engine
   never persisted or compared, beside the parameters the engine did run; and it still
   derived from the versioned wire-contract base. The two identity mechanisms also disagreed:
   - a repeated `operation_id` with different parameters was refused;
   - a repeated contract identity returned the existing job without looking at content.

   The providers inherited the difference. Bare metal, which derives an `operation_id` from
   its idempotency key, refused the case; VM, which submits under the contract identity
   alone, did not. Fulfillment replays a frozen prepared operation, so neither case occurs
   today, but the model should not depend on that.

   Decided:
   - `JobActionRequest` is the identity record only: reservation, deal reference, offering
     mode, action, and idempotency key, as a plain frozen model.
   - Either identity, repeated with the same parameters, returns the job; with different
     parameters it raises `JobIdentityConflictError`.
   - `contract_version`, read only by `JobEngine.get_contract_job_record`, which had no
     caller once the contract-job routes went, is dropped with that method; migration
     `20261005_001_drop_job_contract_version` removes the column as
     `20260927_001_drop_reservation_release_mirror` removed the release mirror.
   - Bare metal's derived `operation_id` stays: it is now redundant, and removing it would
     only change its job ids.

   This corrects A.5's description of the record as purely the job authority's
   "correlation and idempotency record", which the extra field and base class contradicted.

The review also asked for an end-to-end run at the slice A boundary. The maintainer's run on
the A checkpoint already provided one (`tasks.md`, 5B.8.A notes), and A.6 is covered by its
integration tests, so the next pipeline run is slice B's checkpoint.

**Slice B design review (2026-10-05).** Slice B was audited against the code before any of
it was implemented. Decisions 2 and 9 rested on premises the code does not hold, and
several states and callers they did not consider needed a ruling. Each point was discussed
with the maintainer and decided as recorded here; decisions 2 and 9 above are amended in
place where they stated the overturned rule.

1. **Registration is recorded by executor target.** Decision 2 said a first registration
   applies only to a reservation not yet leased. `commit` moves a reservation from
   `reserved` straight to `leased` and records its window, and every storefront commits
   before it registers, so read literally every first registration would be refused.
   Decided: a lease counts as registered once the reservation records an executor target.
   - A first registration (no target recorded) on a `reserved`, `provisioning`, or `leased`
     reservation records the executor target and reference, the window it names, and the
     create handle (never replacing a recorded one), and leaves the reservation `leased`.
   - A repeat with the same target and start returns the record unchanged and never moves
     the end.
   - A repeat with a different target or start, or any registration on a `releasing`,
     `release_failed`, or `unmanaged` reservation, raises `CapacityConflictError` (409).
   - `None` means no such live reservation.

   Every guarantee decision 2 states is kept.

2. **`commit` is a second writer of the lease window.** `HELD_RESERVATION_STATES` includes
   `releasing`, `release_failed`, and `unmanaged`, and `commit` set every held state back to
   `leased` while rewriting the window: the defect decision 2 fixes in `attach_lease` and
   `truncate_lease`. On a `leased` reservation it also rewrites start and end. The VM
   storefront depends on that rewrite: it commits at settlement, commits again after
   provisioning to move the window to provision-complete plus the duration, then registers.
   Its resume pass re-commits before re-registering, and when the deal records no start it
   recomputes the window from the current time, so it could undo a truncation or a release
   however strict registration became.

   Decided:
   - `commit` refuses `releasing`, `release_failed`, and `unmanaged` with
     `CapacityConflictError` (409), as it already refuses a state that is not held.
   - On a `leased` reservation, `commit` re-records the window only until the lease is
     registered. After registration it returns the record unchanged, whatever window it
     names.
   - The resulting invariant: once a lease is registered, its window moves only through
     truncation, and only earlier. Before registration the window is the commit's.
   - API credits commits through the same ledger but never registers a lease, so its
     behaviour is unchanged.

   The maintainer added one consequence. Write-once registration refuses a repeat whose
   start differs, so a resume pass that registered with a start it computed from the
   current time would have its own re-registration refused. Both registration paths
   therefore register with the window `commit` returns rather than one they computed:
   - before registration that is the window the commit just recorded;
   - after registration it is the recorded window, so the repeat matches;
   - when the commit fails, the pass skips registration and leaves it to the next pass,
     rather than registering a window `commit` never recorded.

   This applies to the VM storefront's post-provision path, its resume pass, and the
   bare-metal registration task 7.2 adds.

   **Recorded gap.** A lease truncated after commit but before registration can still be
   extended, by a later pre-registration commit or by the first registration, which records
   the window it names. The maintainer accepted this as negligible. Closing it would need
   the reservation to record that it was truncated.

3. **Release covers every aggregate state.** Decision 9's table named five aggregate
   conditions; the aggregate has ten states. The code corrected two premises.
   - **`teardown_failed` is not terminal.** Convergence requeues it every cycle with no
     attempt ceiling. `begin_fulfillment_teardown` treats it, like every state from
     `teardown_dispatch_pending` on, as already initiated: it returns the current view and
     starts nothing. The lifecycle therefore never restarts a teardown; it adopts one.
   - **`failed` has more causes than decision 9 recorded.** It also arises when the
     provider reports the create failed, when the provider reports success but the metadata
     cannot resolve to a resource identity, and through a permanent dispatch failure. Each
     may leave a partial workload. `failed` has no outgoing transition, so no automated
     teardown exists, and the outcome decision 9 gave it, `release_failed`, stands.

   A dispatch failure that can be retried leaves the aggregate `dispatch_pending`, possibly
   after the job reached the provider. The create handle reaches the reservation only when
   the dispatch is acknowledged, and that write is best-effort (`attach_executor_job`
   swallows its failure). So the aggregate's state, not the handle, is the primary evidence
   that nothing was dispatched.

   Decided, by the aggregate's state when expiry or termination asks for release:

   | Aggregate | How it arises | At expiry or terminate | While `releasing` |
   |---|---|---|---|
   | none | committed, never scheduled | free directly if the proof holds | — |
   | `assigned` | scheduled, `begin` never called | abandon, then free directly if the proof holds | — |
   | `abandoned` | abandoned before dispatch (only `assigned` can be) | free directly if the proof holds | — |
   | `dispatch_pending` | `begin` accepted, dispatch not acknowledged; may have reached the provider | `releasing`, release handle the fulfillment id | wait; no grace timeout |
   | `dispatching` | dispatch acknowledged, create running | as above | wait, no grace; at `active` begin teardown; at `failed`, `release_failed` |
   | `active` | delivered | begin teardown; `releasing` | wait; grace timeout applies |
   | `teardown_dispatch_pending`, `tearing_down` | teardown begun elsewhere | adopt it (begin is idempotent); `releasing` | wait; grace timeout applies |
   | `teardown_failed` | teardown failed; convergence retries | adopt it; `releasing` | `release_failed` |
   | `torn_down` | torn down elsewhere, capacity not yet freed | free directly (teardown proven) | released |
   | `failed` | see above | `release_failed` | `release_failed` |

   "The proof" is decision 9's provenance: no create handle on the reservation and no job
   bound to it. For `assigned` the order matters: abandon first, then check. Abandonment is
   a compare-and-set, and once an aggregate is abandoned nothing can dispatch it, so a
   concurrent dispatch cannot outrun the check. If dispatch wins, release follows the new
   state. Freeing directly goes through the release guard (point 4); if the guard refuses
   because the state moved, the release executor reads the aggregate once more and follows
   its new state.

   Rulings on the questions the table raised:
   - **(a) `teardown_failed` while `releasing` keeps today's mapping to `release_failed`.**
     Convergence keeps retrying, so the aggregate may reach `torn_down` while the lease is
     `release_failed`. An operator's retry-release then adopts the finished teardown and
     releases. The alternative, treating it as still in flight, would need a new state,
     because the grace timeout is anchored at the lease's end and termination does not move
     the end.
   - **(b) A dispatch that never succeeds leaves the lease `releasing` indefinitely.** No
     grace timeout runs while a create is in flight, as decision 9 decided, and convergence
     has no attempt ceiling. Accepted; the stuck aggregate stays visible through
     convergence's recovery diagnostics.
   - **(c) Existing `releasing` rows** whose release handle is a legacy job id or the
     `direct-release` sentinel resolve to no fulfillment and end `release_failed`. Accepted
     under "Pre-release wire and schema changes are accepted".
   - **(d) Decision 9's rationale for `failed` is corrected** as above; its outcome is
     unchanged.

4. **Capacity is freed only behind a release guard.** Releasing an uncommitted hold from
   the storefront needs to know the hold is uncommitted. The site's `release` frees any
   held state with no teardown proof, so reading the state and then releasing leaves a
   window in which a concurrent commit and dispatch would have delivered capacity freed.
   The maintainer proposed enforcing the rule where capacity is freed: it protects every
   caller with no precondition to pass and less client work, and a refused release leaves
   the hold to the lifecycle's teardown path.

   A fixed rule in `kit/site` would break legitimate callers that free *committed*
   reservations on proof the site cannot see. The bare-metal storefront releases after
   proving `torn_down` (`fulfillment_service.py`, and the hosted lifecycle's `_teardown`)
   and when no fulfillment ever began (the hosted `_teardown`). API credits composes the
   same ledger and has no teardown at all.

   Decided: the rule is enforced in the ledger, with the proof supplied by composition.
   - **The guard replaces the abandonment hook.** `kit/site`'s
     `SettlementAbandonmentHook` becomes a `CapacityReleaseGuard`, still a protocol that
     names no fulfillment type. It is called in the reclaiming transaction, with the
     ledger's session, in the same three places the hook runs: `release`, the supersede
     step of `resize_reservation`, and TTL-hold expiry. It answers whether the capacity may
     be freed and may abandon an `assigned` aggregate in that session; it never commits.
   - **A refused reclaim changes nothing.** That includes no abandonment.
     - A refused `release` returns `None`, as truncation does under decision 2, and every
       existing caller already handles `None`.
     - A refused resize leaves the old reservation as it was and returns `None`.
     - A refused TTL expiry leaves the hold for the next sweep.
     - For an already-released reservation the guard is still offered, for its abandonment,
       and the record is returned, as the hook is today.
   - **The compute provisioning composition supplies the guard.** It permits a `torn_down`
     aggregate, and an absent, `assigned`, or `abandoned` one when the proof holds,
     abandoning `assigned` first. It refuses every other state. It reads the fulfillment
     repository and the job rows through the ledger's session, because that transaction
     already holds SQLite's single writer slot; a second session would wait out the busy
     timeout, which is why `fulfillment_persistence.py` writes the create handle in the
     caller's session. So the job check is a session-accepting query beside the job
     authority, not a `JobEngine` method opening its own session.
   - **A composition with no guard frees as today.** API credits supplies none.
   - **Force-release stays the operator's override.** It is recorded as forced, so audit
     still distinguishes it from proven teardown.

   Consequences:
   - **One place for the proof.** Decision 9's provenance check lives in exactly one place.
     The lease lifecycle's "nothing delivered" outcome is a guarded release, and the
     storefront's terminal-settlement path becomes "release, and truncate if refused", with
     no state read first. A storefront release attempt on a delivered lease is refused, so
     it never frees delivered capacity, consistent with "Storefront teardown goes through
     lease termination".
   - **VM admin bulk release.** `/api/v1/admin/portfolio/release-reservations` no longer
     frees delivered leases; they wait for expiry. An e2e module teardown calls it
     best-effort, and the pipeline's fresh stacks are unaffected.
   - **VM failure-policy release.** The `release_capacity` call after a failed create is
     refused, so the capacity stays held until expiry and then goes to `release_failed`:
     decision 9's stance for `failed`. No e2e scenario exercises it.
   - **Bare metal's hosted no-fulfillment path.** The guard would rightly refuse when the
     storefront crashed after dispatch but before recording the fulfillment id. That path
     ignores `release`'s return today, so it now treats `None` as not released.

5. **Plan corrections** (agreed; no design change).
   - `bare_metal_access_ref` lives in the adapter's lease service, not in
     `arkhai_bare_metal`.
   - `BareMetalOperationsService.reclaim_access` takes a reservation-shaped dict, so it
     takes explicit parameters once the lease service goes.
   - `bare_metal_executor_ref` builds the job's `executor_ref`, which decision 1 permits,
     and stays.
   - `route_contract_from_declaration`'s admin check requires every existing declaration
     to admit the administrator; implementation verifies each before enabling it.
   - Two narrowings follow from decisions 2 and 3:
     - The ledger's general field writer (`update_lease_fields`, its session form, and the
       port's `update_reservation_fields`) loses its last route callers. Its one remaining
       use is fulfillment recording the create handle, so it narrows to a session-accepting
       create-handle write that never replaces a recorded handle.
     - The site authority port's by-escrow lookup loses its compute callers. The ledger's
       `get_reservation_by_escrow` stays for the API-credit service.

**Slice B implementation findings (2026-10-05).** Found while implementing slice B. Each
either settles a detail the review left open or records a gap; the first two refine the
review's point 4 and are reflected in the spec deltas.

| Finding | Resolution |
|---|---|
| `record_release_success` is implemented with the ledger's `release`, so once the guard is consulted there, force-release would be guarded too | A release to `force_released`, the operator's recorded override, does not consult the guard; every other release does. `record_release_success` is therefore the lifecycle's guarded release, and the site authority port needs no separate `release` (B.1 had planned one) |
| Point 4 said the guard abandons an `assigned` aggregate and then checks the proof. A refusal would then have written, breaking "a refused reclaim changes nothing" | The guard checks the proof first, then abandons by compare-and-set (`abandon_if_assigned` became a conditional update reporting whether it abandoned), and refuses if the aggregate moved. Equally race-free: a job or a create handle exists only after an aggregate has left `assigned` |
| The old contract controller answered a lifecycle state refusal with 422 | `LeaseRouteService` answers it with 409, as the ledger's refusals are answered; a missing lease is 404 |
| The grace timeout is anchored at the lease's end, and the releasing pass reads a lease in the cycle that begins its teardown | A lease whose end is further in the past than the grace period (after watchdog downtime, or a long in-flight create) is marked `teardown_timeout` in the cycle its teardown begins; retry-release later adopts the teardown. The old lifecycle behaved the same way. Fixed by 5B.8.B.8 (below, finding 5) |
| Bare metal's fulfillment provider never implemented `resolve_executor_job_id`, so a bare-metal reservation never recorded its create handle | Implemented, as VM's provider does; the guard's create-handle proof and `LeaseView.create_job_id` now hold for bare metal |
| `BareMetalLeaseView` had one more user than B.4 listed: `receipt_from_lease_view`, which adapted only that view and had no caller but its own test | Deleted with the view |
| The service's integration harness composed its own ledger without the guard and its fulfillment orchestrator with VM's provider only, and its fulfillment unit of work recorded no create handle | The harness composes as production does: the release guard, both providers, and the capacity ledger in the unit of work. A shared helper (`tests/integration/bare_metal_deal.py`) sets a bare-metal deal up through scheduling and `begin`, so grants in tests go through fulfillment |
| `services/compute_contract_service.py`, which B.2 planned to tombstone | Already deleted in A0 |
| B.3 placed the release tests in the family kit's unit suite | The guard, executor, and status port read three real tables inside one transaction, so their tests are library integration (`provisioning/compute/tests/integration/test_release.py`); the lifecycle's decisions over scripted ports stay unit tests |
| The VM storefront's test site released any reservation | Its fake site models the guard (`delivered`), so the terminal-settlement tests show a hold released and a delivered lease truncated |
| Found by the first end-to-end run of slice B: no VM lease was registered, so the scenarios found no escrow-tagged reservation. Point 2 has the storefront register the window `commit` returns, but `commit` returned nothing at every client layer (`SiteCapacityClient`, core's capacity protocol and aggregate client, `CapacityRuntime`), although the site's route answers with the reservation; the storefront's unit tests had mocked a return the stack never gave | Decided with the maintainer, over reading the reservation back after each commit (an extra request per commit): `commit` returns the reservation as the site recorded it through every layer, as `release` and `truncate_lease` already did; the wire is unchanged. A VM storefront component test commits through the real site client, aggregate client, and capacity runtime against a mocked site (an `httpx` transport that keeps a registered lease's window), so the window's path through the client layers is covered; the full multi-service proof is the end-to-end run (5B.8.B.7) |

**Slice B implementation review (2026-10-05).** The review approved slice B's layering
and asked for fixes before slice C. Each finding was discussed and agreed with the
maintainer; 5B.8.B.8 implements them.

| Finding | Decision |
|---|---|
| 1. For an `active` aggregate the executor began teardown, and only then did the lifecycle record `releasing`: a crash between the two left a teardown the lease did not know of | The executor's decision writes nothing. The lifecycle records `releasing`, with the fulfillment as its handle, then begins teardown; a failure to begin it is left to the releasing pass, which begins it while the aggregate reads `active`, including after a restart |
| 2. Bare metal registered no lease on the family surface; its reservations read as leases only because commit records a lease end | The hosted path registers at access readiness, the machine the grant reports as target; the Alkahest path, which does not yet commit, registers in 7.2. Counting only registered leases in the family reads waits for 7.2, since tightening it now would hide committed Alkahest leases |
| 3. `LeaseRegistration` carried `create_job_id`, so a caller could write lifecycle evidence; `LeaseView` inherited the request; `deal_ref` looked unused | Registration names the executor target, an optional window, and `deal_ref`, and forbids anything else; `LeaseView` is its own model with the lifecycle evidence. `deal_ref` stays: a storefront's acceptance hold is reserved before the deal has an escrow, so registration is the only place the escrow can be recorded, once, as `reserve` records it. A.6 had done that at registration, and 5B.8.B.1 dropped it with the escrow lookup; the first end-to-end run of slice B failed its escrow lookups for this reason as well as for the missing commit window (5B.8.B.7) |
| 4. A first registration could write its window over the committed one, undoing a truncation | A first registration writes a window only where none is recorded. A commit before registration can still re-record a window, the gap point 2 accepted |
| 5. The grace timeout ran from the lease's end, so a terminated lease far from its end waited that long, and a long-expired one timed out as its teardown began | `capacity_reservations.release_requested_at` records when a reservation entered `releasing`; a retry begins a new attempt. Both services that own such a table migrate it. The releasing pass times a stalled teardown from it, falling back to the lease's end for reservations that began releasing before the column existed |
| 6. B.3's record named tests that did not exist as described, and no test showed a dispatch racing the guard | B.3's list is corrected. A race test on file-backed SQLite has a test-only repository commit a dispatch from a second connection between the guard's proof and its compare-and-set; the guard refuses and writes nothing |

**Slice B re-review (2026-10-05).** The re-review found the six findings above fixed and
B.7's design correct, and raised two more, each discussed and agreed with the maintainer;
5B.8.B.9 implements them. It also stated that B.7 and B.8 had not been run end to end; they
had (run 37298149909, both lanes green), in a record the reviewed snapshot predated.

| Finding | Decision |
|---|---|
| High: stale lifecycle work could undo an operator's decision. `begin_releasing` accepted every held state, including `unmanaged`; the failure and oversight writes were unconditional; the lifecycle ignored what `begin_release` returned. A stale failure could turn `force_released` back into `release_failed`, re-holding freed capacity. The review missed one path: an unforced release also freed `unmanaged` | Each lifecycle write is a transition conditioned on the current state, in the ledger: entering `releasing` from `reserved`, `provisioning`, `leased`, or `release_failed`, idempotent under the same handle and refused under another; a failure from `reserved`, `provisioning`, `leased`, or `releasing` under the observed handle; `unmanaged` only from `leased`; only a forced release frees `unmanaged`. `reserved` and `provisioning` stay sources because a VM reservation is still the acceptance hold while its create is in flight. A refused write returns `None`; the lifecycle re-reads and leaves the reservation in the winning state, and never begins teardown after a refused begin |
| Medium: VM lease registration was one-shot; a failure logged a warning and the deal became `ready`, after which the resume pass skips it | The maintainer chose to gate the deal on registration (A) over a separate checkpoint and sweep (B). Investigation found A's premise false: an error after provisioning is a failed settlement outcome, and the escrow is marked `failed`. A was made possible by a third settlement outcome, `deferred` (`kit/settlement-runtime`), persisted without binding or waking. The VM main path returns `deferred` when the commit records no window or registration fails, and, on the maintainer's instruction, when publishing the fulfillment evidence fails; the escrow stays open for the resume pass, which now raises rather than proceeds when its commit or registration fails, so no evidence is published before the lease is registered. Hosted VM deals already retry a non-fulfilled outcome through the settlement runtime |

**Slice C design review (2026-10-05).** Slice C was audited against the code before any of
it was implemented, after B.9. Four premises needed a ruling, and the open question on the
VM storefront's expiry hook was settled. A design review agent commented on the proposals,
and each point, with its refinements, was decided with the maintainer as recorded here.

| Finding | Decision |
|---|---|
| 1. The bundles' `readiness_checks` (`ansible_service is not None`, `operations_service is not None`) and the composed `readiness_checks` and `router_mounts` are read by nothing; `main.py` mounts the adapters' routers itself. Decision 7 builds the Ansible component from the executor table, so there is nothing for the checks to become, and a bundle cannot build routers that need accessors at app-build time | Both fields are deleted from `ExecutorAdapterBundle` and `ComposedComputeAdapters`, with their builders and tests |
| 2. `capacity_inventory.py` holds more domain vocabulary than the two functions it imports: bare metal's publication attribute, its `bare_metal.v2` view and whole-resource availability rule, VM's `vm.ansible_pool_defaults.v1` view, the `provider == "ansible"` gate, and its reads of `AnsiblePoolConfig`. Passing only the two functions as contributions would meet the import test while the service kept both domains' semantics | Option (b) of three (the literal injection, contributions at their natural level, deferral to 5B.9). Domains contribute inventory views through one protocol in the family kit, `InventoryViewProjection`, whose two methods follow the wire's two attachment points: `resource_views(declaration, pool_id)` for a projected resource's `publication_views`, and `pool_views(db, pool_id, provider)` for a pool's `pool_views`. Each projection declares the view ids it emits and the declaration attributes it consumes (omitted from the neutral projection); composition refuses a view id declared twice. Bare metal's projection owns its attribute, host eligibility, and availability rule; VM's owns its provider gate and its table read, in the session it is given, until 5B.9 moves that table. `capacity_inventory.py` keeps only reading the authorities and merging views. The review asked for a test with a fake third domain's projection |
| 3. The plan typed only status. `HealthResponse` carried the contract fields only because status shared it, and the worker controls answered "not initialised" three ways: 200 with an `error` key (pause, resume, check-leases), 409 (advance, as for "not paused"), and 503 (run-cycle) | Health returns `HealthResponse` with `status` and `checks` only; the contract fields belong to `SystemStatusResponse`. The worker-control bodies stay untyped (a finding for closeout task 2.6). An uninitialised collaborator answers 503, a transition that conflicts with the current state 409 (advance while convergence runs). In production nothing is uninitialised once the lifespan has run, and the integration harness composes everything, so the 503 cases are unit tests of the controller and the integration suite covers the 409 |
| 4. Callers the plan did not list index the provisioning status as a dict: the contract-pin check of `test_full_deal.py` and the storefront checks of `test_full_deal.py` and `test_full_deal_buyer_cli.py`. The integration harness built `SystemService` without the executor table or the convergence watchdog | They join C.5 and read the typed model, with no `dict()` shim. The harness composes the status service as production does, from its executor table, lease lifecycle, convergence watchdog, and component providers; the service's collaborators are required, not optional |
| 5. The VM storefront's expiry hook (`schedule_shutdown=_do_shutdown`) always raises, and every VM deal logs "Failed to schedule VM expiry" while the lease watchdog does the expiry. The 2026-10-05 reconciliation had routed it to `remove-dead-storefront-physical-surfaces` task 3.8 | Removed in slice C as its own task (5B.8.C.6), as the maintainer ruled at this review. Task 3.8 of that change is marked delivered here |
| 6. Refinement (readiness): status should consume a neutral diagnostic, not inspect concrete executor classes. A per-executor `diagnostic()` does not fit: the Ansible component runs `ansible --version` once, reads SSH key references from the host registry, and aggregates every Ansible executor's playbook | The executor table exposes `executors_by_offering_mode()` and `mocked_by_offering_mode()`, judged by the family's own mock mechanism (`executor_is_mocked`). `compute_provisioning_ansible.readiness` takes those and a host-listing callable and returns a neutral `SystemStatusComponent` (`name`, `ready`, a versioned detail); the check for `AnsibleJobExecutor` lives there, beside the class. The root composes the provider; `SystemStatusService` takes component providers and names no implementation |
| 7. Refinement (projections): a real projector protocol, not named domain callbacks | Adopted as decision 2 describes, with the protocol's methods following the two attachment points rather than one view stream, because the site kit and both storefronts read the views where they are attached |
| Plan correction: C.4's allowlist said "nothing else", but A0's named exception (`relays_controller.py` reading `vm_provisioning_operator.relays`) stands until 5B.9 | Kept in the (file, module) allowlist. The adapters also keep importing the service's relay modules and table models until 5B.9 and 5B.10; C's acceptance is that no adapter imports `compute_provisioning_service.container` |
| Plan correction: C.1 placed readiness in `probes.py` "becoming" `readiness.py`, but `probes.py` also holds the connectivity probe the root registers | `probes.py` keeps `probe_connectivity`; the readiness models and functions move to `readiness.py`, and their tests to `test_readiness.py` |

**Slice C implementation review (2026-10-05).** The review approved slice C's layering
and design and raised four findings, each verified in code and agreed with the maintainer.
5B.8.C.8 fixes them on top of 5B.9.A, which was already built; the maintainer ruled
against reordering the checkpoints.

| Finding | Decision |
|---|---|
| 1. High: the `ansible` component could report ready when real execution could not run. An unreadable host registry was reported but left the component ready, and a test codified that; a missing key file was reported (`exists=False`) but never counted | The component is ready only when the host registry is readable, whatever runs, since every job resolves its host there and the hosts' credentials cannot be verified without it; and, once any Ansible executor is real, Ansible is on `PATH`, every real executor's playbook exists, and every key file an enabled host names exists. A host's mode comes through its pool, which the component does not see, so a missing key counts once any executor is real. Mocked executors need none of these. The detail lists `not_ready_reasons`, so an operator reading a degraded status sees why |
| 2. Medium: a contributed readiness provider that raised turned the status route into a 500 | Providers are registered with the name they report (`StatusComponentProvider`), and the status service owns the boundary: a provider that raises, or reports another name, is reported under its registered name, not ready, with a detail of its own kind naming only the exception's type (a message could carry a path or credential reference). Status degrades instead of failing |
| 3. Medium: two checked task bullets described what was planned rather than what landed: status composed from the convergence watchdog (convergence is bound by the system controller), and VM's view tests in a VM test directory (they stay in the service tree until 5B.9.B moves `AnsiblePoolConfig`) | The bullets are corrected; no code change |
| 4. Medium: the service's OpenAPI metadata still described a VM-only, seller-only service ("Asynchronous VM provisioning", "KVM host registry", "Ansible jobs", a SIGTERM on cancellation) | Rewritten to the compute family's service: contributed adapters, roles per route contract, execution hosts with typed connections, executor-neutral jobs and cancellation. The app's declared version, a stale literal, now reads the service's version |

### Relays to VM (5B.9)

**Design review (2026-10-05).** 5B.9 was audited against the code before implementation.
Its plan moved three service modules, the relays controller, and three tables into VM's
adapter; relay ownership runs through four more places in the service, and moving only
the named files would have left the service importing VM's internals, which 5B.10
forbids. Each point was put to the maintainer with options and a recommendation and
decided as recorded. The maintainer's ruling on scope: there is no value in the move
until the dependency direction is resolved, so the seams it needs are part of it.

| Finding | Decision |
|---|---|
| A. Fulfillment convergence holds VM's `RelayPortAllocator` and releases a fulfillment's relay port inside the transaction that makes its record terminal (`failed`, `torn_down`, `abandoned`), so the release and the state that justifies it commit together. Convergence is the service's domain-neutral worker | Option (a) of three (contributed terminal hooks; a provider-protocol method in `kit/fulfillment`, which would widen a repository-wide kit for one domain; one injected port). A bundle contributes **fulfillment terminal hooks**, each called with the session, the capacity reservation id, and the terminal state. The root creates one `FulfillmentTerminalHooks` registry, which composition fills and freezes as it does the executor table; convergence runs every hook in its terminal transaction, and names no relay |
| A, continued: the VM provider leases a port in `prepare_create`, in its own transaction, before `begin` records `dispatch_pending`, and the release guard (slice B) can abandon an `assigned` aggregate outside convergence, so a port leased in that window was freed only by the reconciliation backstop | The release guard runs the same hooks, in the ledger's session, when it abandons an aggregate, so every path to a terminal record releases in the transaction that makes it terminal. Reconciliation stays as the backstop for anything else |
| B. Relay administration extends past the three named services: `relay_service.py`, `relay_definitions.py`, the definition-document importer's relay step (run before pools, because pool configuration references relays), its startup step and `relay_definitions_path` setting, and the `relay-port-reconciliation` background task with its settings | Option (a) of three (move all of it behind contribution seams; move only what was named, leaving the service importing VM's internals; defer past 5B.10). All relay code moves to VM's adapter. Two more contribution seams: **definition-document kinds** (kind, label, path, an apply step over the session), which the importer runs before pools in bundle order under the same digest guard, the relay kind keeping the name `relays` so recorded digests stay valid; and **background tasks**, which the service starts with its own. A generic startup-step seam is not needed: the relay import is a document kind. The reconciliation's terminal predicate becomes the family kit's (`fulfillment_is_terminal`), since what makes a fulfillment terminal is fulfillment's, not VM's. Settings keys are unchanged, so no deployment changes |
| C. `Relay`, `RelayPortLease`, and `AnsiblePoolConfig` are declared on the service's base, created by its migrations, and seeded for the default pool by one of them | The models move to VM-owned metadata (`vm_provisioning_adapter/db.py`). The service's schema creation and the integration harness create that metadata after the pool tables it references. The existing migrations stay in the service's chain as its history and read the models from VM's module, an allowlisted (file, module) pair beside `legacy_backfill` |
| D. The relay routes admit seller and admin, from A0's old family default; only VM's operator client calls them, as admin | Admin only, as VM's operation routes are: relay creation, enabling and disabling, and token rotation are operator infrastructure |

Sequencing: **5B.9.A** adds the three seams and moves convergence and the release guard
onto terminal hooks, behaviour-neutral (the service still contributes the relay release
itself until B); **5B.9.B** moves the code, tables, controller, and tests to VM and
narrows the roles.

**5B.9.B implementation findings (2026-10-05).**

| Finding | Resolution |
|---|---|
| With the relay code moved, VM's adapter imports no service module, so its runtime dependency on the service had no reason left (bare metal's went in slice C for the same reason) | Removed; 5B.10 keeps the boundary test and the deployment-level checks |
| The service's dependency on VM's operator client existed only for the relay routes' wire models | Removed from its runtime dependencies; the integration suite, which drives VM's routes through `VmOperatorClient`, declares it in the dev group |
| The relay unit tests the plan would run under VM's adapter target build their databases through the service's migrations | They stay in the service's suite, which already hosts VM's tests; VM's adapter target is unchanged |
| The restart-safety tests imported the relay document through the service, which no longer builds it | They take it from VM's runtime (`relay_definitions`), so they exercise the contribution as composed |

### Boundary check (5B.10)

**Design review (2026-10-05).** 5B.10 was audited before implementation. Every Python
boundary it names already held; one deployment rule did not, and was put to the
maintainer.

| Finding | Decision |
|---|---|
| "No domain's compose files, profiles, or inventory settings name another domain's tree" failed on `domains/apicredits/compose.yml`, which mounted the local dev chain's Alkahest address book from VM's storefront package (`market_storefront/data/alkahest_anvil_addresses.json`). The generator wrote it there, and the buyer CLI helper and e2e scenarios read it as VM's package data | Option (a) of three (move the file to a neutral home; scope the check to the compute provisioning family and route the reference to closeout; a named exception). The address book moves to the Alkahest kit (`market_alkahest/data/`), beside the `alkahest-py` pin it is generated from, so the two cannot drift; every storefront, every buyer, and the e2e suite already install the kit. `market_alkahest.dev_chain.anvil_address_book_path()` locates it for a process running from the installed kit. Deployments keep mounting it at `/app/alkahest_anvil_addresses.json`, so no storefront's settings change. The generator runs in the kit's environment |
| `@fission-ai/openspec` 1.14.1, published 2026-10-05 23:28 UTC after this change's earlier validations, fails `--strict` on requirement text over 500 characters: 19 of this change's requirements and 21 of the 22 permanent specs | Option (a) of three (pin the validator and restructure in a change of its own; restructure only this change's requirements, leaving the permanent specs failing; drop `--strict`). `openspec/README.md` pins 1.14.0, and `shorten-long-requirements` restructures the permanent specs and moves the pin forward. This change's own long deltas are restructured at its closeout, before promotion |
| The plan named one test covering every boundary | Split, with the maintainer's agreement: each thin distribution proves its own boundary in its own suite (the compute client gains the one it lacked); the cross-package rules (adapters, neutral modules, the family's job and host authorities, deployment configuration, the Ansible distribution) are in the service's boundary test, which already scans both adapters from the repository tree |

### Implementation review of 5B.9 and 5B.10 (2026-10-06)

The review approved the relay move and the boundary checks, and raised four findings;
each was discussed and decided with the maintainer and fixed as 5B.10.D.

| Finding | Decision |
|---|---|
| 1. High: VM's relay port was released on every terminal fulfillment state, `failed` included, and reconciliation used the same predicate. A `failed` fulfillment can still have a running guest (the provider reported the create succeeded but its identity could not be resolved; or a playbook failed partway), which is why slice B holds its capacity until an operator verifies. Capacity held and port released could not both be right: the port could be reissued to a second VM | The concept changes from "the fulfillment is terminal" to "the reservation's capacity is released" (option (b) of two; narrowing the terminal states was the other). The maintainer asked first whether force-release bypasses the guard: it does (`CapacityLedger.release` consults the guard only for a non-forced release), so a guard-level seam would miss it, and the effect belongs to the ledger. `kit/site`'s ledger takes a neutral `release_effect` run in every transaction that releases capacity (a guarded release, a forced release, a lapsed hold, a resize's supersede) before commit, a failing effect aborting the release. The family's `ReleaseEffects` registry (`compute_provisioning/release_effects.py`, replacing `fulfillment_terminal.py`) is that effect; VM contributes `release_reservation_ports`; reconciliation asks whether the reservation is released (`reservation_is_released`); convergence and the release guard run no effects. A failed fulfillment's port is now held with its capacity and returned when an operator forces the release |
| 2. Medium: a contributed background task could reuse a service worker's name; composition checked contributions only against each other | `app_runtime.background_tasks()` refuses any two tasks with one name across the service's workers and the contributions |
| 3. Medium: suites exercising real SQLite were filed as unit tests | By `TESTING.md`'s standard, the convergence suite's 32 database tests and the four VM relay and pool-configuration suites are integration tests and move to the service's integration suite; the convergence suite's pure backoff test stays a unit test. Moving the four VM suites into VM's adapter, with schema fixtures of VM's own instead of the service's migrations, is a closeout finding |
| 4. 5B.9's note said the composition root lost its relay wiring; it lost relay implementation ownership, and still correctly composes VM's relay service into VM's router | The note is corrected |

### Job-backed fulfillment (5B.12)

**Design review (2026-10-05).** 5B.12 planned a helper both domains' providers would
call. Read against the code, almost nothing in either provider is domain-specific, and
the maintainer asked for every difference to be justified or removed. Each point below
was decided with the maintainer.

| Finding | Decision |
|---|---|
| Submission: VM submits through `VmJobSubmitter`, bare metal through `BareMetalOperationsService.grant_access`/`reclaim_access`; both end in the same `JobEngine.submit` call. They differ only incidentally: bare metal checks the host is registered and enabled and derives a stable operation id from the contract's idempotency key, VM does neither; the parameter serialization differs | The family owns submission, with one host check and one operation-id rule (bare metal's) for every job, including VM's operator routes and legacy backfill, which use `VmJobSubmitter` today. `VmJobSubmitter`, and bare metal's operations service if nothing else uses it, are deleted |
| Credentials: VM reads the job's credential store and its result from `current_job_id`; bare metal reads only the grant job's result from `create_job_id`. Credentials are fetched only while a fulfillment is active, when both ids name the create job, so the reads are one operation. The job authority already stores a result envelope and encrypted credential envelopes for every job | The family reads the create job's result and credentials and assembles the delivery. A domain contributes no delivery mapping: its codec, which already splits output into result and credentials, emits the delivery's neutral fields |
| Identity: `vm_target` is the guest's libvirt name on the KVM host `host_id` names, not a host id; bare metal's provisioned resource is the host itself. `VmJobParams` already carries a neutral `executor_target` (`vm_target or host_id`), and bare metal registers its lease with `executor_target=host_id` | Fulfillment metadata and prepared jobs carry `host_id` (where the job runs) and `executor_target` (what it acts on); `vm_target` remains only VM's playbook variable |
| Delivery: `vm.fulfillment.result.v1` and `bare_metal.fulfillment.result.v1` spell one concept two ways (what was provisioned, where to connect, secrets issued, when it became ready). VM's adds an internal guest name, its internal address, and the root key's path on the KVM host; bare metal's adds escrow and obligation references, action, status, the grant job id, and the lease's end | One delivery envelope in `compute_provisioning_contracts`: provisioned resources (id, status), endpoints (protocol, host, port, user), credentials (role, secret, the resources each grants), and `ready_at`. Nothing else is returned. The guest's name is the fulfillment's `executor_target`; its internal address stays in the job's stored result (the frp client is configured from the playbook's own variable, never from the reported field); key paths on provisioner hosts never leave provisioning. Bare metal's extra fields are dropped for both domains: the deal references are the buyer's own, action and status restate an active fulfillment, the grant reference is an internal handle, and the lease's end is the site's lease tail, which each storefront already shows from its own record. Root credentials remain a credential role, delivered to the seller's storefront only |
| Guest naming: the VM storefront generates `tenant-<hex>` in three places and passes it to provisioning in its fulfillment requirements and to lease registration | Provisioning names what it provisions: VM's preparation derives the target from the capacity reservation, stable across retries by construction and checked against libvirt's name rules; the requirement loses the field. Lease registration takes `executor_target` from the fulfillment record, so neither storefront passes it and a registered target cannot disagree with what was provisioned. Existing deals keep their recorded names; nothing is migrated for this |
| Persisted shapes: settlement records store each provider's prepared operations and metadata, and an active VM fulfillment's create job stores VM's result keys, which credential fetching reads | A provisioning-service migration rewrites VM's stored prepared operations, metadata (`vm_target` → `executor_target`), and active fulfillments' create-job results into the family's shapes; the family decodes only those. No legacy decoding remains. Bare metal is not live and is not migrated. The legacy VM backfill writes the family's shapes directly. Stored credentials are already the job authority's neutral envelopes; the delivery reads an allowlist of their fields, so a stored key path is never returned |
| Status: bare metal's table maps `pending`, which the job authority never writes, instead of `queued`, so a queued grant reported `unknown` (which convergence treats as pending, so nothing visible went wrong) | One table, keyed on the job authority's `JobStatus` |
| Isolation (outside this change): every guest attaches to libvirt's `default` NAT network, one bridge per host, with no `nwfilter` or isolation rule, so guests on one host, including different buyers', share a layer-2 segment | A finding for VM's provisioning owner, routed at closeout task 2.6 |

Sequencing: each slice keeps both end-to-end lanes green, so a domain's producer and its
storefront consumer move together. **5B.12.A**: the family provider, job submission, and
delivery contracts, with bare metal moved onto them. **5B.12.B**: VM moved onto them end to
end, with the migration. **5B.12.C**: provisioning names the guest. **5B.12.D**: lease
registration removed, behind the decision gate in the audit below.

**5B.12 implementation audit (2026-10-06).** Before 5B.12.A, the plan was re-read against
the code and reviewed independently, and the planning author answered the audit's first
findings. 5B.10.D changes nothing here: no 5B.12 step names a terminal hook, and VM's
relay-port lease is released by the ledger's release effect wherever the provider code
lives. Each finding was discussed with the maintainer and decided as recorded. Rows 4, 6,
8, and 11 refine the "Submission", "Delivery", and "Guest naming" rows of the review above;
where they differ, these govern.

| Finding | Decision |
|---|---|
| 1. The design had codecs "emit the delivery's neutral fields" with no contract for them, so a generic provider would have to parse both domains' spellings. A create job reported succeeded whose output cannot be read would also make its fulfillment `active`, failing only when the delivery is read | A family `DeliveryEvidence` in `compute_provisioning_contracts.delivery`: endpoints (protocol, host, port, user) and a timezone-aware `ready_at`, which a codec emits as its create job's result under a family result kind. The provider's `get_status` validates it before reporting a create succeeded; missing or invalid evidence reports `failed` with a detail naming it, so the fulfillment holds its capacity and port as any failed create does. Teardown jobs carry no evidence |
| 2. `prepare_teardown` receives only the settlement result, and the family metadata dropped what a bare-metal reclaim needs: the buyer's access reference, the escrow identity, `physical_host_id` | Option (a) of three (the create job's stored parameters; an opaque domain slot in the metadata; widening `kit/fulfillment`'s `SettlementResult` to carry the prepared create). The family reads the create job and hands its parameters to the domain's teardown preparation, so teardown undoes what create ran, for every domain. The metadata keeps `host_id` and `executor_target` as the canonical target; the parameters supply only a domain's extras. A missing create job fails preparation as a configuration error. VM's legacy-backfilled records already carry a prepared teardown, so preparation is not called for them; 5B.12.B checks that their create jobs exist and migrates their prepared teardowns |
| 3. The family resolves provisioned resources from `executor_target`, which for bare metal is `host_id`; the bare-metal provider resolved `physical_host_id`. The review asked for a third field, `provisioned_resource_key`, set to `physical_host_id` for bare metal | The key is `executor_target`; no third field. Convergence never stores or returns the key: `_apply_create_success` derives `provisioned_resource_id` from the fulfillment id and the key, so neither identity crosses a boundary. Bare metal's `executor_target` stays `host_id`, which the access playbook runs against; `physical_host_id` stays the declaration's cross-mode identity, checked by bare metal's preparation. A job-backed fulfillment produces one provisioned resource |
| 4. The design put submission in the fulfillment module, though VM's operator routes submit too. Bare metal refused a disabled host for a reclaim as well as a grant, so disabling a host blocked its own reclaim. The design's premise that the legacy backfill submits through `VmJobSubmitter` is false: it is built with no submitter and never submits | A family `JobSubmissionService` (`compute_provisioning/jobs/submission.py`) beside the job engine, used by the fulfillment provider and VM's operator routes. Every job requires a registered host; a fulfillment create also requires it enabled, which VM gains. A fulfillment job's operation id derives from its contract; operator routes keep their request operation ids |
| 5. VM's job contract used action kind `create`/`teardown` and key `<reservation>:create`; bare metal's used the executor action and `<reservation>:grant-access` | VM's form for every domain, so VM's job identities do not change in 5B.12.B and a create in flight across the upgrade finds its job. The job's action stays the executor action, which the executor table routes on |
| 6. The prepared job was to carry an "escrow reference". Hosted deals have no escrow. VM wrote the capacity reservation id into the job's `escrow_uid`, so the jobs list's escrow filter, which exists so an operator can find a deal's jobs, found no VM deal by its buyer's escrow; an end-to-end scenario already filters jobs by `escrow_uid=reservation_id`. The job's `deal_ref` column is written and never read | Jobs correlate on the capacity reservation, the generic physical-lifecycle identity (`ARCHITECTURE.md`, "Identifiers"), which every job-backed fulfillment has whatever its settlement mechanism. The jobs list filters by `capacity_reservation_id`; job records drop `escrow_uid` and `deal_ref`; `JobActionRequest` loses `deal_ref`, and the prepared job carries no deal reference. A buyer quotes its negotiation id to the seller, whose storefront maps it to the reservation. Rejected: an opaque `deal_ref` on the prepared job (agreed first, superseded here) and a negotiation id (a storefront's commercial identity, scoped to one storefront). VM's playbook variable `escrow_uid` is VM's own parameter and is unchanged. The site ledger's escrow keying is routed to closeout task 2.6 |
| 7. The plan rewrote create-job results only for VM fulfillments `active` at migration time. A `dispatching` fulfillment whose create job had already succeeded would be read under the new code in VM's old shape and, by row 1, failed. The migration test was planned as a unit test | The migration rewrites, in every state, each create-job result a VM fulfillment references, both metadata fields (`provider_metadata`, `teardown_provider_metadata`), and both prepared operations; its test is an integration test. It re-wraps VM's job parameters without changing them, because the engine finds a repeated contract identity's job but refuses it with different parameters; a test retries a migrated in-flight dispatch and gets the existing job |
| 8. The delivery repeated the outer `fulfillment.result.v1`'s provisioned resources, its credentials named the resources they grant, and the credential allowlist was a dictionary copy | `AccessDelivery` carries endpoints, credentials, and `ready_at`, and no resource list. Credentials are a typed allowlist: role, password, key type. VM's `ssh_commands` is dropped, since the endpoint carries what it encodes; a test proves `ssh_key_path_host` and unknown fields cannot cross |
| 9. `BareMetalAccessResult` has three roles: provisioning's payload; bare metal's market-domain result codec, stored and served on the buyer's `/result`; and the input to the lease-ready result. The Alkahest path's `/access` route (`fulfillment_service.py`) reads it, and the plan did not name that file | Split as VM's are (`VmResult` beside its provisioning envelope). Provisioning returns only the delivery; bare metal keeps a domain-owned buyer result the storefront writes from the delivery and its own record (access method, user, `ready_at`, the lease end from its materialization). Rejected: the delivery as the domain's result codec, which would make `arkhai_bare_metal` depend on the provisioning contracts. The stored result carries no endpoint, as today; `/access` serves it live from the delivery. The VM storefront stores its endpoint and bare metal does not, a difference no domain requires; routed to closeout task 2.6 for a change of its own |
| 10. `BareMetalLeaseReadyResult.access_grant_ref` is a required field of the signed, content-addressed lease-ready evidence; the design dropped the grant reference without it | Removed in place, under "Pre-release wire and schema changes are accepted": bare metal is not live, and `fulfillment_ref` identifies the fulfillment. No test pins a digest and no permanent specification names the field; the tests that build results change. The result's `expires_at` comes from the storefront's materialization |
| 11. The review asked whether storefront-triggered lease registration remains needed once provisioning names the target. Reading the code: the target is read by nothing that acts; the window is recorded only where none is committed, and every path commits before beginning fulfillment; commit already sets `leased`. Registration has two real roles. It records the escrow a negotiation-time hold lacks. It freezes the window: commit rewrites a leased reservation's window until a target is recorded, which VM uses to restart a window with no negotiated start at delivery, while bare metal's starts at commit. Provisioning recording the target at activation would freeze VM's window before VM's post-delivery commit arrives | The direction is agreed: storefront-triggered registration is removed and provisioning records the target. It becomes 5B.12.D, a decision gate: decide when a lease with no negotiated start begins, then remove registration. Options: (a) at commit, for every domain; (b) when its fulfillment becomes active, for every domain, the site moving the window to the activation, keeping its committed duration, and marking it final, with storefronts reading the window back; (c) VM's post-delivery commit finalizes the window, keeping a post-delivery write. The maintainer leans to (b). The options return with the code read through before D starts. 5B.12.C removes only `LeaseRegistration.executor_target`, the minimum guest naming forces |
| 12. Neither end-to-end lane exercises bare metal's provisioned fulfillment: the bare-metal lane runs publication and introduction, and the deal scenario arrives with Section 9 | 5B.12.A's evidence for bare-metal fulfillment is the service's integration suite through the real orchestrator and convergence, and its records say so |

**5B.12.B implementation audit (2026-10-06).** Before 5B.12.B, its plan was re-read
against the code. Three premises did not hold; each was discussed with the maintainer and
the planning author, and decided as recorded (rows 1 to 5). The design review then agreed
and added four refinements (rows 6 to 9). Row 1 refines row 1 of the audit above.

| Finding | Decision |
|---|---|
| 1. A job stores one result, and the family provider accepts only the evidence kind, so the plan's "the codec emits `DeliveryEvidence`, keeping the guest's internal address in the stored result only" could not hold. VM's codec also interprets the operator `create_vm` route's jobs, whose results operators read: the guest's name and internal address, GPU, network, relay, and state | Option (b) of three (evidence only, dropping VM's operator data from every create; a family result of evidence plus an opaque detail; different shapes for operator and fulfillment creates, which the codec cannot tell apart). A create job's result is the family's `CreateJobResult` (`compute.create-result.v1`): the `DeliveryEvidence`, or none when the output cannot say how to connect, and a `detail` mapping of non-secret operator data. Secrets go only to credential envelopes; nothing the codec would classify as a credential enters the detail. The family validates the evidence, fails a create whose evidence is missing or invalid, and never reads or delivers the detail; operator routes see the whole result. Every domain uses the one shape: bare metal moves onto it, and its fallback of storing the raw fact under its own kind is replaced by a result with no evidence and the fact as its detail |
| 2. A relay-backed VM is reached through the relay's address and its leased port, which the playbook reports under `frp`. The codec reported the KVM host's address and replaced only the port, so the delivered address has been wrong for relay-backed pools since relays existed. The VM lane runs no relay, and the buyer CLI ignored the delivered host, so nothing caught it | Fixed in 5B.12.B. The evidence endpoint is the relay's address and leased port when the playbook reports the relay enabled, and otherwise the host's buyer-facing address and its external port. The migration applies the same rule to stored create results, from their stored relay facts. The tenant's external SSH command the playbook builds already uses the relay address in relay mode and the host's otherwise (`vm-create.yml`); it is not delivered (the credential allowlist), and a test proves the stored command and the evidence endpoint agree on both paths |
| 3. The VM storefront builds `connection_details` from the old result's connection fields (guest name, KVM host, time, tenant user, internal address, port), persists it on the escrow and the listing's `fulfillment_resource`, and submits it with the Alkahest fulfillment. The VM buyer CLI reads it, looking for a port under a key never present, so its "connect" line never printed. The plan named neither the buyer nor the stored rows | `connection_details` becomes exactly the delivery's SSH endpoint (`host`, `port`, `user`), `ready_at`, and the provisioned-resource ids. The buyer CLI reads `host`, `port`, and `user` from it, which also makes its "connect" line print; the VM buyer joins 5B.12.B with a version bump and a hand-lock. A VM-storefront data migration rewrites stored `connection_details` (escrows and listings) into the new shape rather than leaving a dual read: `port`, `user`, `ready_at`, and the ids from the old fields; `host` from `host_ip` where a row has one. Rows written since fulfillment existed record only the KVM host's inventory name, never a buyer-facing address, so their `host` is omitted rather than invented, and the CLI prints the connect line only when all three are present. Rejected: the KVM host name as the address, and the storefront's configured public URL, which a migration would have to read from configuration. What was submitted on chain stays as it was |
| 4. The legacy VM backfill prepares teardowns through VM's provider with no job authority, and the family provider's teardown preparation reads the create job | The backfill builds the family's prepared teardown from VM's plan directly; VM's teardown takes its target from the metadata, its relay from the lease, and its playbook from the pool, and reads no create parameters. Backfilled records that name a target always name their create job (the compiler refuses otherwise), and carry a prepared teardown, so their teardown never reads it |
| 5. A backfilled `dispatching` record may name no target (`vm_target: ""`), which the family metadata refuses | The migration takes the target from the record's create-job parameters, and aborts atomically when neither names one, as the legacy cutover refuses unsafe rows; a test covers the abort |
| 6. Design review (2026-10-06): the detail must not become a dump of the raw execution fact, in which unvetted fields would reach the job-read API because they appeared in output | The detail is opaque to the family but deliberately projected by the domain's codec. VM's create detail is its named operator fields (guest name and state, internal address, host, action and status, time, GPU, network, relay, messages), without the raw `ansible_result` its other actions' results still carry. Bare metal's is its access fact's named, non-secret fields |
| 7. Design review: the relay endpoint's authority is the allocation, not whatever the playbook reports under `frp` | The leased port in the job's parameters is authoritative: the evidence's port is that port, and a reported relay port that disagrees yields no evidence, so the create fails rather than publishing an endpoint the relay authority did not grant. The relay's address is resolved at execution and not stored with the job, so the evidence takes the address the playbook reports it dialled. The migration applies the same check against the stored parameters. An end-to-end lane with a relay-backed pool is routed to closeout task 2.6 |
| 8. Design review: the storefront and the buyer CLI each rebuilt a free-form dict | One typed `VmConnectionDetails` in `arkhai_vms` (host, port, user, `ready_at`, provisioned-resource ids), which the storefront writes and the buyer reads; both already depend on the domain package |
| 9. Design review: a backfilled fulfillment's prepared teardown must stay executable without its create job | A persisted prepared teardown is dispatched as persisted: the orchestrator reuses it, and the provider's dispatch reads no job; only preparing a new teardown reads the create job's parameters. The migration's tests cover a record with a metadata target, a blank target recovered from the create job, the abort when neither names one, and a legacy prepared teardown dispatched after its create job is gone |

**Implementation review of 5B.12.B (2026-10-06).** The review approved the slice's
architecture: the domain-neutral provider, VM contributing preparation and result
interpretation, `CreateJobResult` separating delivery evidence from operator detail, and
the storefront and buyer consuming the delivery. It raised six findings. Each was
discussed with the maintainer and fixed as 5B.12.B.D.

| Finding | Decision |
|---|---|
| 1. High: the migration wrote no evidence for a VM fulfillment in any state, so an `active` fulfillment could stay active with a delivery the new provider cannot produce (its relay-mismatch test did exactly that). A missing create job or result on an active row also passed | For an `active` fulfillment the migration aborts atomically unless its create job exists and its result converts into valid evidence. It never marks the fulfillment `failed`, since its VM may be running. Other states may migrate to no evidence: one in flight then fails through the provider's own rule, and a teardown never reads the delivery |
| 2. High: a dispatch that submitted its create job and crashed before recording it leaves the job unnamed in the metadata, so the migration missed its result; a retry then found the job and read an old-shape result as a failed create | A record naming no create job takes it from the engine's contract identity (the reservation, action kind `create`, key `<reservation>:create`) when exactly one job matches. The prepared operation is rewritten from that job's parameters and its result is converted; the metadata stays empty for the retried dispatch to fill |
| 3. High: the storefront's connection-details migration paired an older record's `host_ip` with its `ssh_port`; behind a relay those were the KVM host's address and the relay's port, the defect 5B.12.B fixed for new jobs, which the buyer CLI's now-working connect line would print | A record whose relay was enabled takes its host and port from its relay record, and omits the host when that record lacks either; otherwise `host_ip` and the forwarded port. Records written since fulfillment already omit the host. Rejected: parsing the stored `ssh_command` as a fallback, whose format varies by key and mode and would be a second derivation able to disagree with the first |
| 4. Medium: both SSH codecs returned evidence with no username, so an SSH create could become active with an endpoint nobody can connect to | Each codec reports no evidence without a non-empty tenant account; the provisioning migration applies the same rule. `AccessEndpoint.user` stays optional for protocols that have none |
| 5. Medium: the task note claimed the migration tests proved each shape "in every state"; they covered few states | The migration's tests enumerate the states that store differently, and the note names exactly those |
| 6. Medium/low: VM's plan tests were filed in the deployed service's suite, and VM's adapter target reached outside its package to run them | Moved now to `domains/vms/provisioning/adapter/tests/unit/test_vm_fulfillment_plan.py`; the adapter target runs its own tests and the one service-hosted inventory-view file. The service-hosted VM codec suite (`test_vm_codec.py`) joins the relay and pool-configuration suites already routed to closeout task 2.6 |

**5B.12.C implementation audit (2026-10-06).** Before 5B.12.C, its plan was re-read against
the code, and the audit was reviewed by the agent that implemented 5B.12.B and by a second
reviewer. Each finding was discussed with the maintainer and decided as recorded. Row 1 refines the "Guest naming" row
of the design review above.

| Finding | Decision |
|---|---|
| 1. The plan checked the derived name against libvirt's name rules, which are loose. What binds is how VM's playbooks use the name (`vm-create.yml`, `vm-undefine.yml`): as the guest's hostname (cloud-init `local-hostname`, `hostnamectl`); unquoted in shell; as a substring in the `/tmp` cleanup every create ends with (`find /tmp -name "*<name>*"`, each match deleted); and, stripped of every character but letters and digits and lowercased, as the tenant's login passed to `useradd`, which on shadow 4.13 (Ubuntu 24.04, Debian 12) refuses a login over 32 characters (verified: 32 accepted, 33 refused). The storefront's `tenant-<4 hex>` has 16 bits, so a collision on one host is likely within a few hundred guests, and a name equal to or contained in another lets one create's cleanup delete the other guest's staging files. The audit first proposed the full 32 hex characters of a UUIDv5, a 38-character login every create would have failed on; the review caught it. A second review then proposed the reservation's own 32 hex characters, the same length, and was rejected for the same reason. The constraint lived only in the playbooks, which is why neither the design review nor the audit saw it | `tenant-` and the first 24 hex characters of a UUIDv5 of the capacity reservation id, under a namespace VM's adapter fixes: 31 characters and a 30-character login, 96 bits, lowercase hex after a letter, and a fixed length, so no derived name contains another. The reservation id stays opaque and does not appear inside the buyer's guest, and the derivation follows the submission service's UUIDv5 rule for operation ids. The derivation test asserts the hostname-label, login, shell-character, and fixed-length rules, so the constraint cannot drift unseen. Rejected: the reservation id's own hex (a 38-character login, and it reads into an identifier the architecture keeps opaque). The constraint becomes permanent knowledge: a normative requirement in `physical-provisioning` (delta "Provisioning names what it provisions"), its rationale in that capability's architecture companion at promotion, the IaC README's description of `vm_target`, and a comment at the playbook's login derivation, the place a future change to the name would be made |
| 2. An old 11-character name can be contained in a new name whose hex starts with the same 4 characters, so a retried old-name create's cleanup on the same host could delete a new guest's `/tmp` staging files. Teardown's deletions anchor the name with a following `_` (`/tmp/<name>_*`), so tearing down an old guest cannot reach a new guest's files | Accepted, not fixed: it needs an old create still in flight and retried on the same host across the upgrade, and a 1-in-65,536 prefix match |
| 3. The lease route service has no reader of fulfillment records: it is built over the lease registry and the lease lifecycle only. Both domains register only once their fulfillment is `active` (VM after delivery, on both its foreground and resume paths; bare metal in `hosted_lifecycle.py` after reading the delivery), so a record is always there to read. The audit first had the provisioning service supply the reader, on the belief that fulfillment records were the service's persistence; they are the fulfillment kit's (`SettlementRepository`), which the family kit already depends on | One family operation, `executor_target_for(capacity_reservation_id)`, in the family kit over the fulfillment kit's settlement repository, which `LeaseRouteService` uses and 5B.12.D can reuse when provisioning records the target itself. It returns the target only for an `active` job-backed fulfillment, decoded from the family's own `JobFulfillmentMetadata`; a reservation with no fulfillment, one not `active`, or metadata that is not job-backed is refused with 409. The target is authoritative from activation, and both domains already register after it, so nothing changes for them. Rejected: `resolve_provisioned_resources`, which names what a create produced and only equals the target today. A lease already registered under a storefront-chosen name repeats unchanged, since that name is the one provisioning was given. The ownership tests prove the authority moved, not only that a field went: a registration body naming a target is refused at the route; VM and bare metal each record exactly their fulfillment's target; no fulfillment, or one not yet active, is refused. Bare metal still loads its materialization for the evidence's `expires_at`; only its line restating the host as the target goes |
| 4. The storefront's recovery context stores the fulfillment request, resume replays it verbatim, and the fulfillment kit's `accept_fulfillment` compares requests exactly, as stored JSON. So a context written before 5B.12.C still sends `vm_target` after it. Where provisioning already accepted that request, its stored copy names the guest too and its prepared create keeps the name; where provisioning never accepted it, nothing was created. Only `begin_fulfillment` and `validate_fulfillment` prepare from a request, and an accepted request is never prepared again | As 5B.12.B did, the stored shapes are migrated on both sides so no legacy decoding remains, rather than tolerating the field or asking operators to drain in-flight deals. A VM storefront data migration removes `vm_target` from every escrow's stored fulfillment request, and a provisioning migration removes it from every VM settlement record's stored request, in every state, so a replayed request still equals provisioning's copy. An accepted fulfillment keeps the name its prepared create recorded; a request provisioning never accepted takes the derived name when it is. VM's requirement model then refuses unknown fields, so a request naming a guest is refused rather than ignored. Rejected: an optional field the plan ignores, removed by a later change (Goal 7 ships as one release, so removal could not fall inside it), and an upgrade that requires no VM deal to be between settlement and provisioning. Tests: both migrations, idempotent; a replayed migrated request for an accepted fulfillment returns it with its prepared name; a migrated request never accepted takes the derived name; a request naming a guest is refused |
| 5. The plan had the VM storefront's `vm_target` column "filled from the fulfillment". The column is in `compute_allocations`, and no production code writes or reads it: only its schema, a column-add migration, and one unit test name it | Left as it is, and the task corrected. The table belongs to the VM storefront's local physical inventory, which `ROADMAP.md` Goal 1 schedules for removal |
| 6. The plan's file list missed: `core/storefront-client` (`notify_usage_started`, async and sync, sends `vm_target`; `evaluate_settle`'s docstring promises one); `core/storefront`'s `EvaluateSettleResponse.vm_target`; the VM storefront's usage-started event (`UsageStartedEventRequest.vm_target`), whose controller passes it and `host_id` into `_apply_fulfillment_event`'s `**_extra`, where both are ignored, under a comment saying the host is recorded; and e2e stage 08a and `test_non_erc20_settlement.py`, which carry the settle dry run's target into the provisioning evaluate-job call. The dry run's target was always a fresh random name the real settle never used. Usage-started has no production sender | All join 5B.12.C. Usage-started loses `vm_target` from the client, the request model, and the controller; the controller stops passing either value, and its false comment goes. `host_id`'s own removal, with the route's purpose, is routed to closeout task 2.6. The dry run stops reporting a target, and the two e2e evaluate-job calls use the harness's placeholder name, since that operator dry run names whatever it is given. The two core packages take version bumps, and the exact-pin cascade reaches `arkhai-kit-capacity-publication`, the bare-metal storefront, and the API-credit storefront |
| 7. VM's resume pass registers only when `vm_host` and `vm_target` are both present; `vm_host` is the delivered endpoint's host, which a registration never reads. The foreground path gates on `vm_target`. Since 5B.12.B an active fulfillment cannot deliver without an endpoint host, so the silent skip is latent rather than live | Both gate on the reservation and the settlement resource only; a test covers a delivery with no host. `_register_vm_lease_with_settings` loses the target, host, and resource parameters it carried only for call-site compatibility |
| 8. `LeaseRegistration` forbids extra fields, so a storefront that still sends `executor_target` to an upgraded provisioning service is refused with 422 | Accepted under "Pre-release wire and schema changes are accepted": both storefronts and provisioning move in this one slice, the completion note says so, and the end-to-end run is the evidence that both sides moved together |
| 9. Several service integration tests register leases on reservations with no fulfillment: some test registration itself, others only need a lease to release | Tests of registration register over a real job-backed fulfillment. Tests that only need a lease take it from commit, which already records the window and leaves the reservation `leased`, the shape 5B.12.D leaves, so they do not change twice |
| 10. Outside 5B.12.C: the site ledger's reservation payload emits a `vm_target` key for VM reservations, beside the uncalled `find_active_lease_by_vm_target` that closeout task 2.6 already lists. VM's operator `create_vm` route checks no name against row 1's rules, so an operator's name over the login limit fails at `useradd` | Both routed to closeout task 2.6, the payload key in the existing entry |

**Input for 5B.12.D's gate (2026-10-06).** Recorded from the 5B.12.C review as input, not
a decision. Today `commit` gives a deal with no negotiated start a provisional window from
now, VM commits again after delivery to restart it, and registration freezes the second.
The review's model for option (b): a negotiated start is final at commit; with none, commit
records only the lease's duration (the site would need a durable duration), and activation
records the target, the start, and the end in one write, which makes the window final. An
unactivated lease then has no end, so the watchdog cannot expire a deal whose VM never came
up. Registration's remaining role, recording the escrow on a negotiation-time hold, would
instead be served by resolving an escrow to its reservation through the storefront's own
record; if a real consumer needs the site indexed by escrow, that is an explicit correlation
operation, not registration.

**5B.12.D decision gate (2026-10-06).** Decided with the maintainer after reading the code
the gate named. What the code does today: `commit` takes an end and an optional start that
defaults to now only where the reservation has none, so nothing says "no negotiated start".
VM passes a start at every commit (the negotiated one, or now), so its post-delivery commit
restarts the clock, and registration freezes it. Bare metal commits once with now, but its
evidence's `expires_at` comes from its materialization, a second clock that a restart
between the commit and the materialization's save can make disagree. `reserve` already
records a provisional window, and windows are the site's calendar for future-dated
matches. API credits commits with no lease end. VM's published evidence carries no window.
Registration is the only writer of an escrow onto a negotiation-time hold; VM's admin
interruption path and e2e scenario lookups read it, while API credits and `reserve`'s
idempotency use escrows recorded at reserve.

| Question | Decision |
|---|---|
| 1. When does a lease with no negotiated start begin? | At commit, for every domain (option (a)). Exclusive capacity is consumed from commit, so the buyer pays from commit; capacity-reservation pricing will refine this later. VM's post-delivery commit and lease registration go, and VM's lease starts at the settlement commit, as bare metal's already does. Commit becomes write-once: a repeat returns the reservation unchanged, since nothing needs the refresh, which retires the closeout finding about a commit re-recording a truncated window. Open-ended commits (API credits) and the calendar are unchanged. Rejected: (b) as the only behaviour, which starts every buyer's clock at activation whatever the seller's policy; (c), which keeps a post-delivery storefront write and the asymmetry between domains |
| 2. Who decides? | The storefront, as policy configuration like its service agreements: one policy for every site it sells, as a retailer sets one return policy for all its suppliers. Buyers see it as the storefront's published policy, not as a negotiated term. A site's input, if ever wanted, is a pool listing hint, with the storefront's own setting taking precedence, as `listing_shapes` works. 5B.12.D builds only "at commit", the start being now or the negotiated one. Starting "on activation" is deferred until a seller needs it: a rule recorded at commit and carried out by provisioning in the activation transaction, where 5B.12.D already writes the target, so adding it later is a new rule value and a window write in that place. Recorded as an open gap at closeout |
| 3. How does a negotiation-time hold learn its escrow? | Commit records the deal's escrow where the reservation lacks one (E1), the rule `reserve` already follows: commit is where a hold becomes the deal's, and VM already passes the escrow to it. VM's admin path and the e2e lookups keep working unchanged. Rejected: resolving through the storefront's escrow row (the e2e scenarios read the site and would need a storefront route, and settlement-time reserves would still carry an escrow on the site); a separate correlation operation, which no consumer needs |
| 4. Where is the target recorded? | In the provisioning service's convergence, inside the transaction that marks a fulfillment `active`, through an in-session ledger write like the create handle's, with the family's `fulfillment_executor_target` decoding the record's metadata. `FulfillmentTargets.executor_target_for` opens its own session, which inside that transaction would wait on SQLite's single writer slot, as `attach_executor_job`'s docstring explains; with registration gone it has no caller and goes. This corrects 5B.12.C's expectation that D would reuse it: the decoder is what is reused |
| 5. Deals in flight across the upgrade | A provisioning migration records the target for every active job-backed fulfillment whose reservation has none. A VM deal still awaiting its post-delivery commit keeps the window its settlement commit recorded, which is the window (a) gives it |
| 6. Bare metal's two clocks | Its materialization and its evidence's `expires_at` take the window its commit returned, so the evidence states the site's lease |

**Implementation review of 5B.12.C and 5B.12.D (2026-10-07).** The review approved C,
and D's architecture: guest naming in VM provisioning, registration removed end to end,
write-once commit, and the target recorded at activation. It raised five findings. Each was
checked against the code, discussed with the maintainer, and is fixed as 5B.12.D.D except
the fifth, already met.

| Finding | Decision |
|---|---|
| 1. High: with registration gone, activation is the only writer of a lease's target, and its write catches every failure, so a failure leaves an active fulfillment whose lease records no target, with nothing to repair it. Checked against the code, the exposure is narrower: the write shares the activation's session, so a database failure already aborts the activation's commit and convergence retries it, though only because a later commit fails after the broad `except` swallowed the error. What really leaves a target unrecorded is deterministic: metadata that does not decode as a job-backed target, a reservation the ledger refuses (no offering mode), a missing reservation, or a different target already recorded; a retry fails the same way | The activation's handler catches only those data errors (`ProviderConfigInvalidError`, `CapacityConflictError`); anything else escapes, the activation rolls back, and the record stays `dispatching` for the next cycle, never failed. Each convergence cycle ends with a sweep over active job-backed fulfillments on non-terminal reservations: one whose reservation records no target has it recorded wherever the write now succeeds, and the cycle's diagnostics log counts what it repaired, what it could not record (by reason), and each reservation recording a different target, which is never overwritten. The log alone, at the maintainer's choice; system status is not extended. No admin repair operation: nothing acts on the site's recorded target (teardown reads the fulfillment's metadata, and the only reader, `find_active_lease_by_vm_target`, has no caller), so a missing or different one is a reporting gap; the data-side remedies are the existing release controls or a correction the sweep then picks up, and overriding a recorded target would break the rule that it is never replaced. Should something come to act on the site's target, a deliberate resolution operation is needed then: recorded in closeout task 2.6 |
| 2. Medium: the guest-name tests prove determinism, distinctness, and the playbook rules, but would all pass if the namespace or the derivation changed, which would rename an old fulfillment's guest on retry | A fixed vector: `fulfillment_guest_name("alloc-1") == "tenant-ea780533c5915a9b85ba26b9"`, the value the function produces |
| 3. Medium: the `physical-provisioning` delta still describes registration in "Leases have one family surface that records and releases" (its route list and roles, and its bare-metal scenario) and in the admin-route scenario's example; `site-capacity` keeps "once registered"; and D's task text says the target write is refused in states where what was built records nothing | The deltas describe one design: the lease surface lists get, list, terminate, and the release controls; the bare-metal scenario has the target recorded at activation; the admin example becomes lease termination; `site-capacity` says "once committed", since commit begins a lease. D's task text states the write as built and as finding 1 amends it |
| 4. Medium: commit records an escrow on the reservation's own `escrow_uid`, but the VM storefront's fulfillment-failed handler resolves the escrow from the request or the reservation's `deal_ref` only, so a hold correlated at commit loses its escrow when the request omits it. Latent: the fulfillment-failed callback has no production sender | The handler takes the request's escrow, else the reservation's `escrow_uid`, else the `deal_ref`'s. The callback's missing sender is routed to closeout task 2.6 beside usage-started's |
| 5. The C and D completion notes said "Not yet run end to end", which their gate requires | Already met: run 37581956819 passed both lanes on the C and D tree, recorded in both notes |

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
use it. *Superseded by "Controls and routes (5B.8)", decision 1: the bare-metal lease
surface and `BareMetalLeaseClient` are deleted; the transport shape survives for the
VM, Ansible, and resource-pool client extensions.*

The same rule exposes a second gap: the provisioning route-contract table in
`compute_provisioning/client.py` lists bare-metal routes (`/api/v1/bare-metal/leases*`
and `/test/bare-metal/*`), so a third compute domain would have to edit the family kit
to have its routes signed. Decided with the maintainer: 5B.1 makes the table
contributable. Each domain contributes its route contracts beside its typed client, the
provisioning service assembles them, and both the client and the service's
authentication read the assembled table. *Corrected by "Controls and routes (5B.8)",
decision 8: the service's authentication reads the assembled table; each client signs
from its owner's contracts, as "Clients take contracts, not the assembled table" below
already said.*

Settled with the maintainer when 5B.1 began:

- **The `Lease*` operator models stay VM's.** *Reopened under "Job and host authority
  shape": the generic lease routes serve the neutral `LeaseView`.* They are the VM administration surface
  (`LeaseCreate` and `LeaseResponse` require `vm_target`), and `compute_provisioning`
  already owns the neutral lease contract (`LeaseRegistration`, `LeaseView`,
  `LeaseTermination`, `LeaseRetryRelease`, `LeaseForceRelease`). When the generic lease
  routes move (5B.8), the lease lifecycle serves the neutral view and VM keeps
  `/api/v1/leases` as a compatibility surface built from it, its VM fields blank for
  bare metal. *Superseded by "Controls and routes (5B.8)", decision 1: `/api/v1/leases` is
  removed; the family lease surface is the only one.* Moving them would put VM vocabulary in the family kit; neutralizing them
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

### Section 6 design: bare metal on the negotiation runtime (2026-10-07)

Re-read against the code before planning, then reviewed by the previous implementation
agent and a review agent; decided with the maintainer. The premise behind every
decision below is the long-term one: the VM and bare-metal storefronts become one shared
compute storefront, as the provisioning service already is, so a behaviour the two
domains share is built once in kit and each domain contributes only what is its own.

What the code showed, against the plan Section 6 carried:

| Finding | Consequence |
|---|---|
| Bare metal places no hold during negotiation; it reserves when fulfillment starts. 6.2 said "`place_hold` as today" | Decision 1 |
| The listing recheck is an async site call; the runtime's `validate_opening` is synchronous | Decision 2 |
| The runtime calls `evaluate_round` only for an opening and a counter. A buyer's accept and administrative acceptance resume the thread and accept without it, in VM as in bare metal | Decision 2 |
| VM's recheck is the `has_matching_inventory_guard` middleware, always prepended to its chain, reading a result the storefront computes before the round. It skips every listing without a `gpu_model`, and reports a site projection it has not loaded as a declared mismatch (409); bare metal reports a source it cannot read as retryable (503) | Decisions 2 and 3 |
| Bare metal never checks a backed listing's availability, which `storefront-publication`'s inventory-guard requirement asks of every capacity-backed listing; every bare-metal listing is backed | Decision 2 |
| The runtime's known opening refusals include no retryable type, so a 503 refusal would escape evaluate-negotiate as a 500 | Decision 3 |
| Bare metal's trading pause is a database row (`bare_metal_operator_state`), read asynchronously; VM's and API credits' are identical in-memory module flags, read by the runtime's synchronous hook | Decision 4 |
| Bare-metal openings record `initial_proposal`, which the runtime's transcript reader refuses, and number their own rounds | Decision 5 |
| Exact-option openings skip seller policy and accept at the trusted option's amount | Decision 6 |
| The escrow path's opening returns a plan built without the seller wallet and commits none; verify rebuilds it with the wallet. The buyer funds from the plan the negotiation response carries | Decision 7 |
| The runtime records a thread's terminal `success` before it commits the agreed terms and plan. `storefront-publication`'s bare-metal lifecycle scenario says the accepted thread's principals, binding, agreement, and plan persist atomically | Decision 8 |
| Bare metal's seller chain is fixed to `escrow_shape_guard` then `listed_price`, which never counters: it accepts at or above the listed rate and exits below it, so no bare-metal thread is ever open after round zero | Decision 11 |
| The signed resource of the stage-event read is rebuilt by hand in VM and API credits, and only VM's copy refuses unauthenticated query aliases and a stream request | Decision 12 |

Decisions:

1. **No hold at negotiation.** Bare metal's hooks set no `place_hold`; it reserves
   when fulfillment starts. This follows the interim posture of
   `default-no-pre-settlement-capacity-hold`; when `negotiation-time-capacity-hold`
   lands, bare metal adds its hold through this hook. Acceptance and force-accept record
   the terms and the settlement plan and reserve or hold nothing.
2. **The listing recheck is the runtime's, for every domain.** The runtime decides when;
   each domain contributes only what it checks.
   - `NegotiationDomainHooks` gains an optional async `check_listing_source`, returning a
     verdict whose outcome is one of matches, declared mismatch, unavailable, or
     unverifiable, with a reason and the differing fields for the log. The verdict
     type, and one pure classifier mapping a verdict to nothing, a refusal with its
     reason, or a retryable refusal, live in `kit/policy`, below the runtime, so the
     guard that uses them needs no runtime import.
   - The runtime obtains the verdict before every seller round, opening and counter (so
     the preview reports it), and before the first write of a buyer's accept and of
     administrative acceptance. It is never obtained on exit, so a buyer can always
     leave.
   - The runtime enforces it, through the classifier, on every one of those paths: after
     a seller round whose decision is neither reject nor exit (a refusal becomes a
     reject with the classifier's reason; a retryable refusal raises before any write),
     and before any write of an acceptance. The source check is therefore a runtime
     invariant whatever a domain's chain contains.
   - `has_matching_inventory_guard` migrates from VM's negotiation package to
     `kit/policy`, under the same name, and uses the same classifier at its chain
     position, so a malformed request is still refused for its own reason by the guards
     ahead of it (`round_zero_opening_guard`, `buyer_counter_guard`), the reasons stay
     `no_matching_declaration` and `no_matching_inventory`,
     `accept_unpriced_selection` still runs after it, and every configuration naming it
     keeps working. It drops VM's `gpu_model` condition, leaves a retryable verdict to
     the runtime (a chain can only reject), and reads the verdict from the round's
     policy context, where each domain's round hook places what the runtime passed it.
   - VM contributes its existing `check_listing_source` (its cached projections and live
     capacity snapshot) and drops the per-round closure that fed the guard. Bare metal
     contributes its existing recheck, which also reports unavailable when its Physical
     Resource is taken, read from the same site's capacity snapshot VM reads. API credits
     sets no check; its listings are not derived from a declaration.
   - VM's behaviour changes in three ways: buyer accept and force-accept now recheck;
     listings without a `gpu_model` are checked; and an unloaded projection is
     unverifiable (503), not a mismatch.
   - Rejected: the recheck only in `evaluate_round`, which misses buyer and administrative
     acceptance; in the opening and continuation resolvers, or in an async
     `validate_continuation`, each of which also runs on exit (a site outage would stop a
     buyer leaving) and, for openings, runs before term decoding and the pause check;
     deleting the guard outright, which would break its chain-order dependents and every
     configuration naming it; the guard as the only enforcement in rounds, which a chain
     missing it would silently disable; enforcing before the chain, which would answer a
     malformed request on a stale listing with a source refusal, and on an unreachable
     site with a 503 no retry can cure.
   - Each domain keeps reading the source its own publication reads. Bare metal reading
     cached projections, as VM does, belongs with unifying publication and is recorded as
     an open gap (closeout task 2.6).
3. **One retryable refusal.** The kit runtime gains `NegotiationUnavailableError`, not a
   `ValueError` (VM's route answers any `ValueError` with 404), included in the
   refusals an opening preview reports. An unverifiable verdict and an absent site
   authority raise it. Acceptance now rechecks, so every route that starts, continues,
   or force-accepts a negotiation maps both source refusals:
   `OfferUnfulfillableError` to 409 and `NegotiationUnavailableError` to 503. That is
   each storefront's `negotiate/new` and `negotiate/{id}` routes (VM's continue route
   answers any exception that is not a `ValueError` with 500 today) and the kit's
   force-accept route service, which today translates only `NegotiationStateError`.
   Evaluate-negotiate keeps answering 200 with `refused: true` and the refusal named in
   `decision_reason`; no retryability field is added, since nothing reads one.
4. **One process-local trading pause, owned by kit: a deliberate reversal.** The
   bare-metal storefront's durable pause, and its scenario "Storefront is paused and
   restarted", were deliberately transferred to this change when
   `market-platform-bare-metal-10-storefront-composition` was archived; that design
   stored the pause in the database "so it survives process restart" and gave no use
   for that. The maintainer reverses it: a trading pause is used in end-to-end runs and
   by an operator actively correcting an issue, who would notice and handle a restart.
   VM's and API credits' trading pauses have always been process-local, and the
   permanent requirement ("Storefront is globally paused") refuses negotiations until an
   operator "resumes the process". The design review's objection, that a restart
   silently undoes an authenticated operator's pause, is recorded as an accepted risk.
   So:
   - `kit/storefront` owns one process-local trading pause, beside and separate from the
     loop controller's lifecycle pause, held by each storefront's composition and read by
     the runtime's synchronous `storefront_is_paused` hook and by system status, and set
     through one framework-free route service each storefront binds at
     `POST /api/v1/admin/pause` and `/resume`, with unchanged paths and responses. API
     credits reads a pause flag today that nothing sets, since it binds no pause route;
     it gains the two routes, which the canonical client's `admin_pause` and
     `admin_resume` already call.
   - VM's and API credits' `_GLOBALLY_PAUSED` flags and bare metal's database pause are
     removed; a bare-metal migration drops `bare_metal_operator_state`.
   - The test-compatibility delta's "Storefront is paused and restarted" scenario is
     dropped and task 3.6 withdrawn.
   - Rejected: making the runtime's pause hook async to read a durable flag, and a kit
     pause persisted through a repository port, both of which keep the reversed
     requirement.
5. **Legacy open threads are abandoned.** A bare-metal migration marks every
   non-terminal thread `abandoned`, the state the negotiation watchdog gives stale open
   threads; terminal threads are untouched. Continue was never served on them, and
   bare metal holds nothing, so there is nothing to release. Its test proves an
   abandoned thread can be neither continued nor force-accepted, and that the migration
   starts no settlement or release.
6. **Exact-option openings keep their round-zero acceptance.** An opening selecting an
   exact hosted or contact-exchange option is accepted at the trusted option's amount
   inside `evaluate_round`, after the listing recheck, without seller price policy, and
   is committed through the runtime's acceptance path like any other. Escrow proposals
   go through the configured chain every round.
7. **The plan is committed at acceptance, and the committed plan is the agreement.**
   `build_artifacts` builds the escrow path's plan from the inputs verify uses (the seller
   wallet and the chain configuration paths); `persist_artifacts` commits it on both
   paths, with `BareMetalTerms`, for negotiated acceptance and force-accept alike, and
   `commit_settlement_plan` already refuses a conflicting plan. The buyer funds from the
   plan the response carries, so a verify that rebuilds from changed configuration would
   describe an obligation nobody funded: Section 7 replaces verify's rebuild with a read
   of the committed plan. Until then, a test asserts that the response's plan, the
   committed plan, and verify's rebuild are equal under unchanged configuration. Whether
   today's walletless response plan differs from what verify registers is not
   established; that test will show it.
8. **A thread is successful only once its agreement is recorded.** The runtime writes a
   thread's terminal `success` last, after the agreed terms, any hold, and the plan, on
   every acceptance path (opening, counter, buyer accept, administrative acceptance);
   `_record_seller_decision` splits its message write from its terminal write. A crash
   mid-acceptance leaves a non-terminal thread, which the negotiation watchdog abandons,
   and settlement reads only successful threads, so it never sees a partial agreement.
   - Such a thread must also never be resumed, or a crash after the accepted message
     would leave a transcript that says accepted open to another round. The runtime
     therefore refuses to counter, accept, or force-accept a non-terminal thread whose
     transcript holds an acceptance or whose agreed terms or plan are recorded
     (`agreed_at`, `settlement_plan`); a buyer may still exit it. With that rule the
     order of the acceptance writes does not matter for safety, and no acceptance
     effect is ever retried, so none needs to be idempotent.
   - Widened after the implementation review (2026-10-07): a crash between a buyer's
     message and the seller's decision, at the opening or in a later round, also
     leaves a thread that must not resume, or a buyer's accept would take an offer
     the seller never made (with no seller counter recorded, the runtime falls back to
     the reference amount). The rule is therefore that a non-terminal thread can be
     countered, accepted, or force-accepted only when its transcript ends with the
     seller's counter, and its agreed terms and plan are unrecorded; this subsumes the
     recorded-acceptance marker. A buyer whose request was interrupted exits or waits
     for the watchdog rather than retrying. Bare metal's continuation also requires the
     opening message it recorded, whose absence means the opening was not completed.
   - Rejected (design review): writing the accepted message after the agreement and
     plan. A crash between them leaves a thread with a recorded, immutable plan and no
     acceptance in its transcript, which another round could reopen, and whose later
     acceptance at another amount `commit_settlement_plan` would refuse.
   - On VM and API credits, a hold placed before such a crash lives out its TTL. An
     orphaned thread blocks nothing: the only uniqueness on threads is
     `(negotiation_id, round)`.
   - The lifecycle scenario's "atomically" is replaced by these rules, since the runtime
     does not provide strict atomicity.
   - Rejected: a transactional repository contract across all three storefronts, too
     large for this section; amending the scenario alone, which would leave a successful
     thread with no agreement for settlement to refuse forever.
9. **Continuation is bound to the recorded thread.** Bare metal follows VM: its opening
   copies the listing binding to the thread, and continuation loads the thread's binding,
   requires the listing's current binding to equal it, and resolves from that frozen
   authority; nothing from the buyer's payload reselects a site, resource, or domain.
10. **Refusals keep their status codes.** A bare-metal refusal type, a `ValueError`
    carrying its status, keeps the domain's tested 400, 404, and 409 cases and is
    reported by the preview. The kit's retryable type owns 503 for an unverifiable source,
    `StorefrontPausedError` stays 503, and `OfferUnfulfillableError` stays 409. The
    runtime decodes terms before it checks the pause, so bad terms on a paused storefront
    answer 400, as on VM.
11. **Bare metal's seller chain is configured.** Bare metal reads its chain from
    `[negotiation] policies`, as VM does, defaulting to today's `escrow_shape_guard` and
    `listed_price`, with `has_matching_inventory_guard` prepended. The bare-metal lane
    configures `bisection` (registered in `kit/policy`), so round zero counters and the
    scenario's force-accept finds an open thread. Unit tests inject the chain they need.
12. **The kit owns the event read's signed resource.** `StageEventRouteService` rebuilds
    the resource the canonical client signs, refusing unknown or repeated query
    parameters and a stream request with 400s, as VM's copy does. VM and API credits
    rebind to it, so API credits gains the refusals it lacks, and bare metal binds it.
13. **Section 6 splits in two**, each keeping both lanes green:
    - **6A, kit and rebinding:** decisions 2, 3, 4, 8, and 12 in the kit, with VM and API
      credits rebound and VM's guard migrated; its gate is the kit, VM, and API-credit
      suites and both lanes.
    - **6B, bare metal on the runtime:** decisions 1, 5, 6, 7, 9, 10, and 11; its gate
      is the bare-metal suites and both lanes, the bare-metal lane's publication scenario
      unchanged.

Design review of this section (2026-10-07), with the maintainer's dispositions:

| Review point | Disposition |
|---|---|
| Keep the durable pause | Declined; decision 4 records the reversal and the objection as an accepted risk |
| A crash after the accepted message leaves a resumable thread whose transcript says accepted; move the message after the agreement | Gap accepted; the resumption rule in decision 8 closes it, and the proposed reordering is rejected there |
| Make the source check a runtime invariant, enforced before the policy chain | Invariant accepted; enforced after the seller's decision instead (decision 2), since the guards ahead of the inventory guard must still refuse malformed requests first |
| Force-accept can now raise a source refusal the kit route service does not map | Accepted and widened to every negotiation route (decision 3) |
| Section 6 tasks still the old plan; deltas not yet matching | Planned as 6A and 6B; the `storefront-publication` and `market-composition` deltas are written with the plan |
| The proposal still describes lease registration | Corrected with the plan |

Implementation review of 6A and 6B (2026-10-07), with the maintainer's dispositions:

| Review point | Disposition |
|---|---|
| Bare-metal force-accept answers a domain refusal (a plan the builder cannot make, an unreadable listing) with 500 | Fixed in the bare-metal binding, which answers it as `negotiate/{id}` does; the kit's force-accept service stays domain-free |
| The deltas say every unconfirmable source is retryable, but a seller's independent rejection or exit keeps its reason, as designed and tested | The deltas are corrected to the implemented precedence |
| A crash between a buyer's message and the seller's decision leaves a resumable thread | Closed in the runtime (decision 8, widened) |
| 6B.6 says existing status codes are kept | Corrected: the domain's refusal statuses are kept; seller-policy outcomes follow the configured chain |

Found while planning:

- `kit/policy`'s own environment cannot be built here (its development group needs the
  PyTorch index); its runtime dependencies are light, so its new tests run in the
  negotiation runtime's environment, which installs it from its wheel, and are disclosed
  as such.
- The domain conformance suite the old 6.4 named already runs under the bare-metal
  contract (`domains/bare_metal/tests/test_domain_runtime.py`); it covers contract
  capabilities, not negotiation, so nothing is added there.

What this changes beyond Section 6:

- **Section 7.** 7.2's commit half is done (the Alkahest path commits before fulfillment)
  and its registration half no longer exists (5B.12.D). Its trailing finding, that the
  family's lease reads should count only registered leases, is superseded: a lease now
  begins at commit for every domain, which is what those reads count. What remains of
  7.2 is `get_lease` and `terminate_lease` on `SelectedSiteFulfillmentClient`, routed by
  the reservation's recorded site. Verify reads the committed plan (decision 7). 7.6's
  test list drops lease registration.
- **Open gaps for closeout task 2.6:** bare metal reading cached projections; API
  credits' `credit_quota_guard`, which reads availability its storefront precomputes, as
  VM's guard did, and could move onto the kit verdict; and the fulfillment convergence
  sweep's counts, which the lanes' plain-text log format does not print.

### Section 7 design: one explicit settlement composition (2026-10-07)

Re-read against the code before planning Section 7, then reviewed by the previous
implementation agent and a review agent; decided with the maintainer. Section 7 makes
settlement the only thing that starts bare-metal fulfillment, so every configuration that
can adopt an obligation must also be able to service it. The code showed that it cannot.

| Finding | Consequence |
|---|---|
| With `BARE_METAL_STOREFRONT_SETTLEMENT` absent, `build_runtime_from_environment` enables Alkahest and builds chain clients for escrow verification, while the settlement runtime is built with no clients. Verify adopts the obligation; once `begin` is retired, nothing can service it. The HTTP settlement tests build exactly this state, and the restart test asserts the empty client map | Decision 1 |
| Alkahest resources are built only when Alkahest is in `priority`. The registry's `runtime_clients` builds a client for every configured section, disabled ones included, so a configured but disabled Alkahest section gets a client with no chains, and an obligation accepted before an operator disabled Alkahest cannot be checked or collected | Decision 2 |
| The hosted callbacks, and with them the servicing worker, exist only when `fiat.stripe.v1` is enabled; a hosted obligation accepted before Stripe is disabled is stranded the same way. The worker is attached after construction, so the lifecycle step registration in `__post_init__` never sees it, even with Stripe | Decisions 2 and 3 |
| `on_ready` calls the hosted `fulfill` for every record, and that callback refuses any other mechanism. Alkahest reaches it between verify and `begin` on a storefront with Stripe enabled, and contact exchange reaches it when a reveal is interrupted between materialize and bind | Decision 4 |
| A ready hook that returns or raises before it reserves the obligation's `fulfill` operation leaves no operation row. The due query then lists the obligation on every pass and the worker's `_schedule` sets no backoff, which applies only to an existing pending row | Decision 4 |
| `on_terminal` calls the hosted `cleanup` for every uncollected terminal state. On an Alkahest record it raises, and the worker's cleanup path retries it indefinitely | Decision 5 |
| A runtime built with no composition is not settlement-free: acceptance falls back to `default_hosted_selection_dispatch()`, settle verify checks Alkahest escrows with whatever chain clients were injected, and health reports settlement as available whenever chain clients exist | Decision 6 |
| The Helm chart's `alkahestEnabled` restates what the settlement Secret declares; the chart reads that Secret only through `secretKeyRef` and never its contents, so it cannot derive the flag. Neither the chart nor production `compose.bare-metal.yml` passes `BARE_METAL_STOREFRONT_CHAINS` or `BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY`; only the local lane does, so a production deployment with Alkahest enabled starts with an address and no chain clients | Decision 7 |

Decisions:

1. **The settlement composition is explicit and required.** The bare-metal executable
   refuses to start without `BARE_METAL_STOREFRONT_SETTLEMENT`. Mechanism enablement,
   verification resources, and servicing clients all come from that one composition;
   absence no longer means Alkahest. An explicit configuration that enables no mechanism
   stays valid, and leaves settlement and publication unavailable, as the permanent
   requirement "Peer mechanism configuration hierarchy" in
   `openspec/specs/settlement-configuration/spec.md` says. Options considered:
   - **A.** Synthesize an Alkahest-only configuration when the root is absent. Rejected:
     it is the implicit mechanism default that requirement forbids.
   - **B.** Require the root, as Compose and Helm already do. Chosen.
   - **C.** Leave the fallback. Rejected: a paid Alkahest escrow would never be fulfilled
     once `begin` is retired.

   This enforces existing permanent requirements ("Peer mechanism configuration
   hierarchy"; `openspec/specs/settlement-servicing/spec.md`, "Configuration composes
   one settlement runtime"); no delta requirement is added for it.
2. **A configured mechanism stays serviceable.** A mechanism's resources are built
   whenever its section is configured, not only while it is enabled, because
   "Mechanism configuration cannot reinterpret durable plans" requires recovery after an
   operator disables a mechanism for new deals.
   - **Alkahest.** While the section is configured, enabled or not, the seller address,
     at least one chain, and the wallet key are required, or startup refuses. VM's
     composition omits a disabled mechanism's client when its resources are missing;
     that still abandons its obligations, so bare metal does not follow it.
   - **No section.** Alkahest resources supplied without an Alkahest section (the seller
     address, chains, or wallet key) are refused at startup: they would be a second,
     stale statement of what the one settlement root says.
   - **Hosted.** The hosted lifecycle callbacks are built whenever the Stripe section is
     configured.
   - **Verify** follows the plan committed at acceptance whether or not Alkahest is still
     enabled for new deals: the committed plan is the agreement (Section 6, decision 7).
   - Rejected, from the review: deriving Alkahest resources from the enabled set alone.
     It keeps the stranding described in the second finding.
3. **One worker over the settlement runtime, composed inside the runtime.** Whenever the
   runtime has a composition, it composes the one mechanism-neutral
   `SettlementServicingWorker` during its own construction, so the lifecycle step
   registration sees it and the settlement-servicing step exists on every path. This
   replaces "a worker for every mechanism", which described one worker per mechanism.
4. **The ready hook dispatches through an explicit table**, built in `runtime.py`, the
   composition root, keyed on the record's mechanism:

   | Mechanism | Ready hook |
   |---|---|
   | `fiat.stripe.v1` | The hosted lifecycle's `fulfill`, unchanged |
   | `alkahest.v1` | Bare metal's Alkahest step: decision 9 of "Section 7 design: bare-metal Alkahest delivery, scope narrowed (2026-10-07)" |
   | `contact-exchange.v1` | Decline without reserving: the reveal registers, materializes, binds, checks, and collects the obligation itself, and every step is idempotent |
   | Anything else | Raise |

   A hook that starts anything reserves first, so its failures back off on the worker's
   schedule. Declining contact exchange without reserving means an interrupted reveal is
   re-examined on every pass, without backoff, until the buyer retries the start; VM's
   ready hook behaves the same way. Having the worker finish an interrupted reveal from
   the persisted introduction record would redesign contact exchange, and is routed to
   closeout task 2.6. The final row is a guard: the registry admits only installed
   mechanisms, and an obligation whose mechanism section was removed fails earlier, at
   the status step, for want of a client.
5. **The terminal hook dispatches by mechanism too.**
   - **Hosted:** the hosted `cleanup`, unchanged.
   - **Alkahest:** an obligation that ends uncollected with its fulfillment started has
     its lease terminated through the selected site's lease terminate, the client the
     teardown uses; a repeated termination returns the same lease. This
     follows VM, whose terminal hook ends the lease of every uncollected obligation. With
     no fulfillment started there is nothing to release, since bare metal reserves only
     when fulfillment starts (Section 6, decision 1). A collected obligation needs nothing.
   - **Contact exchange:** nothing.
   - **Anything else:** raise.
6. **A runtime with no composition has no settlement.** Its acceptance dispatch is empty,
   settle verify is unavailable, health reports commercial settlement unavailable, and no
   worker is composed; publication already refuses. The escrow verifier takes its chain
   clients from the composition's resources, so verification and servicing cannot
   disagree about which chains exist. Tests that settle build the real composition, with
   the Alkahest client's chain clients doubled at the chain boundary; tests that only
   negotiate keep none.
7. **Each deployment surface carries each input once.**
   - **Helm.** `alkahestEnabled` is removed: enablement lives only in the settlement
     Secret. The chart gains:
     - `chains`, public values rendered as `BARE_METAL_STOREFRONT_CHAINS`;
     - `walletKeySecret`, a reference to an existing Secret rendered as
       `BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY` through `secretKeyRef`; the chart never
       renders private material, as the VM chart does not;
     - an optional existing ConfigMap holding the Alkahest address book, mounted
       read-only, which a development chain needs.

     `sellerEvmAddress`, `chains`, and `walletKeySecret` are one group: all set or all
     empty, or rendering fails. The runtime checks the group against the Secret's
     configured sections (decision 2).
   - **Production Compose** forwards the chains and an optional wallet credential file,
     kept apart from the identity file as API credits keeps it. The local overlay then
     supplies the lane's values through those inputs instead of setting them itself.

   The Helm end-to-end validation that comes later needs these inputs, so they are
   supplied here rather than recorded as a limit.

Design review of this section (2026-10-07), with the maintainer's dispositions:

| Review point | Disposition |
|---|---|
| Choose B; A conflicts with "Peer mechanism configuration hierarchy" | Accepted (decision 1) |
| Record the decision, alternatives, and the retired fallback in the design, proposal, and tasks | Accepted; Section 7's tasks are amended with the plan |
| State the invariant architecturally: one composition supplies enablement, verification resources, and servicing clients; derive Alkahest enablement from the composition | Accepted, refined: resources follow a configured section, not an enabled one (decision 2) |
| Keep the runtime's composition optional as a test seam | Accepted; no composition is a no-op (decision 6) |
| One mechanism-neutral worker, not one per mechanism; unknown mechanisms fail rather than return | Accepted (decisions 3 and 4), with contact exchange named as declining rather than unknown, and the terminal hook dispatched as well (decision 5) |
| Migrate the tests that normalize the fallback to the real composition | Accepted (decision 6) |
| `DEPLOYMENT_AND_CONFIG.md` should say the root is required | Accepted; the quickstart's Alkahest inputs and the chart's values change with it (decision 7) |

Routed to closeout task 2.6:

- Contact exchange: an interrupted reveal is finished only by the buyer retrying the
  start; the worker could finish it from the persisted introduction record.
- The seller's EVM address and wallet key are separate inputs nothing checks against each
  other. VM's `[Wallet]` has the same pair, so this is a repository-wide wallet-schema
  question rather than a bare-metal one.
- The Alkahest address book is named twice: by the settlement section's
  `address_config_path`, which the Alkahest runtime client applies to every chain, and
  by each chain's `alkahest_address_config_path`, which publication and the chain clients
  read. Both are kit-level and VM carries both; the bare-metal surfaces carry them as
  the runtime reads them today.

What this changes in Section 7's plan: these decisions are 7B's and 7C's, and the tests
that build the fallback migrate as decision 6 says. The lease client comes before the
Alkahest terminal branch. The `storefront-publication` delta gains the settlement-started
fulfillment and its terminal handling as scenarios of "Complete bare-metal seller
lifecycle".

### Section 7 design: bare-metal Alkahest delivery, scope narrowed (2026-10-07)

Planning Section 7 found that nothing makes a bare-metal Alkahest escrow collectable. The
worker collects only through a bound fulfillment reference, which for Alkahest must be an
on-chain attestation, and stage 09bb requires the claim. An audit of how every domain
gets from a ready obligation to a bound fulfillment then showed that the kit starts
fulfillment two ways (an in-process `SettlementJobCoordinator` task for Alkahest, the
durable servicing worker for hosted settlement), that each domain wrote the step between
them itself, and that VM publishes and stores buyer access material the other domains do
not. The maintainer first chose to unify that path in this change; a design review then
showed that the unification overlaps three active changes and is unfinished in four
places, and the maintainer narrowed the scope.

Moved out of this change (maintainer, 2026-10-07):

- **The unified fulfillment path** (one start path composed in kit, mechanism-owned
  evidence publishers behind one port, an evidence envelope, one access rule, one
  verification step, VM's and API credits' rebinding) goes to
  `kit-owned-listing-and-fulfillment-lifecycles`, which already owns restart-safe
  fulfillment convergence. Its design carries the audit, the proposed decisions, and the
  review's corrections: the envelope wraps each domain's public evidence rather than
  replacing it, because API credits' hosted condition verifies its issuance evidence
  field by field; verification needs a mechanism-neutral contract on the registration,
  since the registration's `settlement_verifier` has a mechanism-specific signature; the
  kit orchestrates access while each domain owns its typed access result; and VM's
  access cutover needs scenarios for deals in flight.
- **VM's plan rebuild.** `prepare_vm_settlement` registers obligations rebuilt from
  current configuration rather than the plan committed at acceptance. It goes with the
  verification contract.
- **Refusing startup while a mechanism with no configured section has unfinished
  obligations**, for all three domains together.
- **Resubmission after an ambiguous on-chain submission** is withdrawn: it contradicted
  the permanent "Ambiguous on-chain submission safety" requirement and the active
  `add-alkahest-attestation-reference-query`, which owns reconciling that window.

Decisions:

8. **Bare metal's Alkahest step is an interim domain step on kit pieces.** The ready and
   terminal dispatch tables of decisions 4 and 5 stand. Their Alkahest rows are bare
   metal's own step until `kit-owned-listing-and-fulfillment-lifecycles` composes the
   step in kit; it is built from the pieces that change will keep (the runtime's
   fulfillment operations, the `kit/alkahest` publisher), so what it absorbs is the
   sequence, not a mechanism.
9. **The Alkahest step.** Reserve the obligation's fulfillment; start fulfillment, or
   find it started, through the fulfillment service, which is idempotent by negotiation;
   defer while the lease is not yet active; once it is, build the lease-ready evidence,
   store it, publish its digest on chain (decision 11), and complete the fulfillment with
   the attestation's UID. The worker's check and collect then claim the escrow. A failure
   before publication records a retry; publication's outcomes are decision 11's.
10. **One evidence model, two accepted bindings.** The lease-ready evidence's accepted
    binding becomes one of two kinds: the hosted binding, unchanged, so stored hosted
    evidence and its digests are unaffected; and an Alkahest binding, built from the
    accepted thread, the plan committed at acceptance, the parties, and the escrow as
    condition anchor. Both are stored in the storefront's evidence store.
11. **Only the digest goes on chain, and publication is never ambiguous to the worker.**
    - The attestation's data is the evidence's `sha256:` digest, as a string obligation
      referencing the escrow. The body names the buyer, seller, and claimant principals
      and the lease result, and a chain is public and permanent; the arbiter decides by
      kind, so nothing on chain needs the body.
    - `kit/alkahest` gains a fulfillment publisher with four outcomes: *published* with
      the attestation UID; *not submitted*, when the failure provably preceded the
      transaction, which is retried; *outcome unknown*, when the transaction may have
      been sent; and *rejected*, when the chain refused it. A failure the pinned client
      does not let the publisher place is an unknown outcome.
    - Before submitting, the step records its submission intent on the obligation's
      fulfillment operation, through `kit/settlement-runtime`. The intent is
      first-write-wins: recording the same intent again changes nothing, a different
      intent for the same operation is refused, and the intent is cleared only under the
      held lease after a proven *not submitted*. The intent carries the evidence digest,
      which the future attestation lookup matches against.
    - On *published*, the step records the attestation UID in the same operation, also
      first-write-wins, and only then completes the fulfillment with it. A later attempt
      therefore finds one of three states: an intent and a UID, which completes with
      that UID and never submits; an intent and no UID, which parks the obligation for
      an operator (`manual_required`, reason `alkahest_submission_outcome_unknown`) and
      never submits; or neither, which may submit. A crash after the chain accepted the
      submission but before the UID was recorded lands in the second state, which is
      the window the lookup resolves.
    - *Outcome unknown* parks the obligation in the same way.
    - *Rejected* means the chain refused the transaction and no attestation exists, so a
      retry cannot duplicate one: the step clears its intent and records a retry, as
      for *not submitted*, until the deal's own count of refusals reaches a small bound,
      after which it parks the obligation (`alkahest_submission_rejected`). The count
      is kept apart from the operation's journal attempts, which also count the passes
      spent waiting for the lease, none of which is a refusal (implementation review,
      2026-10-08). A transient
      revert recovers by itself; a deterministic one is a defect, reported by the
      status count (decision 13). The maintainer preferred an operator resolution
      path, but not one `add-alkahest-attestation-reference-query` already plans to
      remove for VM.
    - This keeps the property of "Ambiguous on-chain submission safety" for bare metal,
      and the attestation lookup `add-alkahest-attestation-reference-query` adds becomes
      the way out of the unknown-outcome park for both domains.
12. **Evidence resolution authenticates its caller, by binding.** With the digest
    public, anyone could read the body from the storefront's unauthenticated evidence
    route. The route requires a signed request, as API credits' resolver does, loads the
    evidence, and admits callers by its accepted binding: the evidence's buyer and
    claimant and the seller's administrator for either kind, and the hosted authority's
    principals (role `authority`, from the Stripe section's trust) only for evidence with
    the hosted binding, since no hosted authority takes part in an Alkahest deal.
    The route follows the five-piece route pattern: its wire model, route contract,
    framework-free route service, and typed client (over the storefront client's
    generic `authenticated_request`) live in `arkhai_bare_metal`, and the
    storefront's `api.py` is only its binding (implementation review, 2026-10-08).
13. **Status reports what needs an operator.** The administrator's
    `/api/v1/system/status` carries `settlement_manual_required`: the number of
    obligations parked for an operator, by mechanism status or by any operation.
    `kit/settlement-runtime`'s repository counts them; the canonical storefront client's
    status model gains the field.

Composition decision 2 is tightened by the review: a configured mechanism's recovery
resources are required whether or not it is enabled, since logging that obligations
cannot be serviced is still abandoning them.

Design review of this section (2026-10-07), with the maintainer's dispositions:

| Review point | Disposition |
|---|---|
| The deltas and plan did not describe the design | Written with this plan |
| A common evidence envelope must preserve API credits' semantic evidence | Moved, with the correction, to `kit-owned-listing-and-fulfillment-lifecycles` |
| Resubmission contradicts a permanent requirement and an active change | Withdrawn; the publisher distinguishes an unknown outcome and parks it (decision 11) |
| The verify step has no mechanism-neutral interface | Moved, with the correction; bare metal's verify reads its committed plan in place |
| Scope A collides with active changes; split | Accepted: the unification moves to `kit-owned-listing-and-fulfillment-lifecycles` |
| Access ownership and VM's cutover are undesigned | Moved, with the correction |
| A configured but disabled mechanism may still strand obligations | Accepted: recovery resources are required while configured; the startup refusal for an unconfigured mechanism moves, for all three domains |
| Validation must grow with the scope | Moot for the moved work; this plan validates its own pieces |
| The Zone.Identifier files remain | They are tombstoned in the fileset and deleted after packaging |

Second design review of this section (2026-10-07), with the maintainer's dispositions:

| Review point | Disposition |
|---|---|
| The `settlement-servicing` delta imposed the Alkahest protocol on hosted publication, whose adapter already retries under a stable operation identity (`request_id` from the condition anchor and evidence digest) | Accepted: the requirement states the invariant (a stable operation identity, or recorded intent and no blind resubmission); the four outcomes are the contract of a publisher with no stable identity |
| Submission intent needs an immutable recovery contract and an explicit UID ordering | Accepted (decision 11): first-write-wins intent and UID, both in the kit journal rather than a bare-metal column, the UID recorded before completion, and the three restart states tested |
| A rejection has no recovery path | Accepted: a rejection is a known non-submission, retried up to a bound and then parked (decision 11); an operator resolution path was declined because the attestation-query change plans to remove VM's |
| Evidence authorization should follow the evidence's binding | Accepted (decision 12) |
| The attestation-query change's tasks remain VM-only | Accepted: its tasks now cover the shared publisher and bare metal |
| Composition decision 7 said "enabled set" for "configured sections"; stale Alkahest resources without a section | Accepted: corrected, and such resources are refused at startup (decision 2) |

### Merge reconciliation with Arkhai payments (2026-10-08)

The payments cutover removes `fiat.stripe.v1` and its hosted stack. Section 7's
references to the hosted ready/terminal hooks, accepted binding, authority reader,
and hosted-only test composition are superseded by that removal. Alkahest's
interim lifecycle, committed-plan verification, submission journal, rejection
bound, and authenticated evidence resolver remain in scope.

- The obligation worker services Alkahest and contact exchange. Arkhai payments
  continues through the receipt-based settle path and its reconciliation loop;
  it creates no conditional-escrow obligation and is not added to the worker's
  ready or terminal dispatch table. The retired buyer `begin` route stays retired.
- The accepted Agreement fixes its timestamps before every accepted-artifact
  build, including administrative acceptance. Exact Agreement bytes and opaque
  settlement data are persisted alongside the branch's accepted artifacts.
- Alkahest evidence keeps its accepted binding and canonical digest derivation.
  Its principal and digest primitives live with the evidence codec rather than
  depending on the deleted hosted contract. Only the buyer, claimant, and seller
  administrator can read it. Hosted evidence and authority access are removed;
  payment delivery remains gated by its signed receipt.
- Explicit settlement configuration and configured-but-disabled Alkahest recovery
  retain Section 7's rules. Payments-only configuration needs no EVM resources.
- Wheel versions reuse the newest existing pin from the two branches, with no
  additional increment; all locks are regenerated from the merged wheelhouse.
  The umbrella chart references its existing bare-metal subchart version, and
  the API-credit wheel-install fixture includes the storefront client it requires.

The alternative of retaining hosted compatibility would restore a mechanism the
payments cutover explicitly removes and is rejected. Reusing the obligation
worker for payment settlement would impose the conditional-escrow lifecycle on
an Agreement-based stage and is also rejected. No new financial-authority or
fulfillment-ownership model is introduced by this reconciliation.

Permanent destinations remain `openspec/specs/storefront-publication/spec.md`
for Alkahest delivery and evidence authorization,
`openspec/specs/settlement-servicing/spec.md` for submission safety,
`openspec/specs/negotiation-protocol/spec.md` for accepted Agreement artifacts,
and `openspec/specs/settlement-configuration/spec.md` for explicit peer mechanisms
and accepted-deal recovery. The deployment inputs are current in
`docs/development/DEPLOYMENT_AND_CONFIG.md` and
`docs/bare-metal-seller-quickstart.md`. The remaining Section 7 promotion and
end-to-end gates stay open; this merge does not complete the feature campaign.
`openspec/changes/README.md` records the reconciled implementation status; the
campaign graph is unchanged. `docs/development/ROADMAP.md` retains the outstanding
full-deal pipeline evidence gap until the remaining scenario work is qualified.

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

*Amended by "Section 6 design: bare metal on the negotiation runtime (2026-10-07)",
decision 4: the trading pause is process-local, so the pause-survives-restart case
(task 3.6) is withdrawn.*

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

*Superseded in part: 5B.12.D made the Alkahest path commit before fulfillment and
removed lease registration ("5B.12.D decision gate (2026-10-06)"); what remains for 7.2
is in "Section 6 design: bare metal on the negotiation runtime (2026-10-07)".*

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

Superseded by "Controls and routes (5B.8)" and its design review (2026-10-04):

- **`ComputeContractService` consuming `JobEngine`** (decision 5) → decision 10: the contract
  service is deleted with the action surface.

- **`BareMetalLeaseClient` and the contributed bare-metal lease routes** ("Implementation-review
  fixes for Sections 4–5") → decision 1: the bare-metal lease surface is deleted.
- **VM's `/api/v1/leases` as a compatibility surface** → decision 1: one family lease
  surface.
- **Both the client and the service's authentication read the assembled table** → decision
  8: authentication reads the assembled table; each client signs from its owner's contracts.
- **Generic lease update** ("Job and host authority shape") → decision 2: no lease update; a
  lease's end moves only through the site's truncation.
- **`ReservationNotProvisionableError` moving to `compute_provisioning`** ("Architecture
  review") → decision 10: deleted with the compute adapters.
- **Ansible readiness served by the Ansible distribution** ("Provisioning execution leaves
  the VM adapter") → decision 7: a contributed component of system status.
- **The job and host wire models living in `compute_provisioning`** → decision 8: the thin
  contracts distribution.
- **Release status selected by offering mode, and the `direct-release` sentinel** → decision
  1: one release executor and status port.

Superseded at the slice B design review (2026-10-05):

- **A first lease registration applies only to a reservation not yet leased** (decision 2)
  → point 1: registration is recorded by executor target.
- **Truncation is the only operation that moves a recorded lease end** (decision 2) → point
  2: once a lease is registered; before registration `commit` re-records the window.
- **`JobEngine.has_job_for_reservation`** (planned for the provenance proof) → point 4: a
  session-accepting query, because the proof runs inside the ledger's write transaction.
- **The storefront releases a `reserved` hold after reading its state** (decision 9) →
  point 4: it asks for release and truncates if the release guard refuses.
- **The settlement-abandonment hook** → point 4: the release guard, which also decides
  whether capacity may be freed.

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
- **Bare metal's Alkahest step is a temporary domain copy** of the step every domain
  writes (Section 7 design, decision 8) → `kit-owned-listing-and-fulfillment-lifecycles`
  absorbs it; it is built only from the pieces that change keeps.
- **A parked Alkahest submission waits for an operator** → rare (a process stopping
  between submission and recording its UID), reported by the administrator's status, and
  reconciled automatically once `add-alkahest-attestation-reference-query` lands.
- **Admin reserve's VM path** (`/api/v1/admin/portfolio/reservations`) carries VM
  vocabulary; it is kept for client compatibility. `remove-dead-storefront-physical-surfaces`
  does not retire it (checked 2026-10-01).
