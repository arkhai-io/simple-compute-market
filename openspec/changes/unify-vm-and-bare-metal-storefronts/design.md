# Design: unify-vm-and-bare-metal-storefronts

## Context

**What exists.** A storefront's composition root discovers installed contributions
through the entry-point group `market.storefront_contributions`, applies the
operator's `[[storefront_domains]]` selection and freezes one registry
(`core/storefront/src/core_storefront/domain_plugins.py`; `domain_registry.py`,
`StorefrontDomainRegistry`). Each registration binds a contribution, an offering mode,
a domain identity, a contract version and the validated contract. The common database
holds an immutable binding for every listing, copies it to every negotiation thread,
and checks it again on the fulfillment context
(`core/storefront/src/core_storefront/sqlite_client.py`, `load_listing_binding`,
`copy_listing_binding_to_thread`, `validate_fulfillment_context_binding`). Capacity and
fulfillment calls for accepted work go to the recorded site and nowhere else
(`core/storefront/src/core_storefront/aggregation.py`). The VM storefront's
distribution declares the bare-metal storefront wheel, so one image installs both
contributions (`domains/vms/storefront/pyproject.toml`). Three kit pieces are already
built once per process and know no domain: the loop controller
(`kit/storefront/src/market_storefront_kit/lifecycle.py`), the trading pause, and the
per-site projection state, which holds whatever generation a site serves and lets each
domain apply its own acceptance rule when it reads (`market-composition`'s "Per-site
projection state is kit-owned and held once per process").

**A composition is given one binding.** The kit's `StorefrontComposition` carries the
registry, one selected binding, that binding's contract, one set of service hooks and
one ordered route contribution, and its lifespan builds one container for that one
contract (`kit/storefront/src/market_storefront_kit/composition.py`). All three
storefronts build exactly one: the VM storefront resolves the `vm` registration, the
bare-metal storefront builds a registry of its own with one registration
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/storefront_registry.py`),
and the API-credit storefront does the same
(`domains/apicredits/storefront/src/apicredits_storefront/server.py`).

**Where a second registration stops being served.** In a VM storefront configured with
`vm` and `bare_metal`:

- the application builds VM services for the `vm` registration alone
  (`domains/vms/storefront/src/market_storefront/server.py`, `build_vm_storefront_app`);
- the negotiation runtime refuses a durable binding other than the VM one
  (`negotiation_runtime.py`, `require_domain_binding`), and the listing service
  refuses a capacity source that resolves to another registration
  (`services/listing_service.py`);
- the publication loop builds the VM source alone and reports serving the VM mode
  alone, so that its registry sweep leaves a bare-metal storefront's listings open
  (`publication_wiring.py`, `build_vm_storefront_publication_selection`;
  `services/publication_service.py`, `served_offering_modes`);
- the migration chain creates no bare-metal table (`utils/migrations.py`, `CHAIN`);
- system status reports both registrations
  (`services/system_service.py`).

**The two compute storefronts are two programs.** They serve the same paths over the
same core models: listings, negotiate, settle, fulfillment events, system status, the
lifecycle controls, pool overrides, identity rotation and time. The VM storefront
mounts routers from its own controllers and three middleware (`server.py`). Bare
metal serves them from one module,
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py`, with one
response-authentication middleware (`server.py`). Each has routes the other lacks:
the buyer's reads of fulfillment status, result and access under
`/api/v1/fulfillments/{negotiation_id}` are bare metal's alone. No shared route set
exists: neither
`core/storefront` nor any kit defines a router, only framework-free route services
(`kit/storefront/src/market_storefront_kit/deal_control_routes.py`,
`lifecycle_routes.py`, `introduction_routes.py`).

The two hold their services differently. The VM storefront keeps them in module-level
variables that its controllers and services read
(`domains/vms/storefront/src/market_storefront/container.py`), and reads a module-level
settings object (`utils/config.py`). Bare metal builds one runtime object holding its
services, its loop controller and its site clients (`runtime.py`,
`BareMetalStorefrontRuntime`), from a typed settings model (`config.py`,
`BareMetalStorefrontSettings`). Both register their loops under the same names:
`publication`, `site-projections`, `deal-servicing`, `delivery-recovery`,
`payment-reconciliation`, `settlement-servicing`, `negotiation-watchdog`
(`docs/guidance/repository/deterministic-tests.md`, "Pause the loop, then advance it
explicitly"). The VM storefront alone runs `capacity-events`.

**The kit runtimes know no binding.** `kit/negotiation-runtime`,
`kit/settlement-runtime` and `kit/deal-servicing` name neither an offering mode nor a
domain binding. Each is built with one domain's hooks, and its workers scan the tables
they own: the settlement worker claims obligations from the one journal
(`kit/settlement-runtime/src/market_settlement_runtime/servicing.py`,
`SettlementServicingWorker.run_once`). Two such workers over one database would each
claim the other's records.

**Publication.** The core runner builds publication sources for the contributions a
publisher names and no others, because building every registration's source would call
a factory without the arguments it needs
(`core/storefront/src/core_storefront/publication_plugins.py`,
`build_registry_publication_sources`). Each compute storefront drives its own cycle
through the kit's driver and names only its own contribution. The registry sweep that
ends a cycle closes open listings under the storefront's principal for the modes the
publisher says it serves
(`kit/capacity-publication/src/market_capacity_publication/publication.py`).

**Persistence.** Each storefront declares one migration chain: the core storefront's
baseline, the baselines of the settlement, contact-exchange and pool-override kits,
its own baseline, then the core migrations and its own
(`domains/vms/storefront/src/market_storefront/utils/migrations.py`;
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/migrations.py`). The
shared baselines are the same objects in both chains. Each domain's baseline creates
its own tables: bare metal's are `bare_metal_selected_site_bindings`,
`bare_metal_fulfillment_lifecycle`, `bare_metal_settlement_records` and
`bare_metal_opening_listings`. Several kit-owned tables are created by each chain under
an identifier of its own: deal servicing's store, its payment observations and its page
position are `20261109_001_vm_store_open_tables`, `20261115_001_vm_payment_observations`
and `20261116_001_vm_servicing_page_position` in one chain and
`bare-metal-storefront-0017-store-open-tables`,
`bare-metal-storefront-0019-payment-observations` and
`bare-metal-storefront-0020-servicing-page-position` in the other. The engine treats a
database as a chain's once it records any of the chain's baselines; from then an
identifier the chain does not list makes the database ahead, which is refused, and a
listed identifier it lacks is pending
(`kit/schema-migrations/src/market_schema_migrations/engine.py`, `classify`). Both
chains declare marketplace 0.3.0 as their floor.

**Configuration and deployment.** Both storefronts read `storefront.toml`, under the
same keys for the same concepts (`deployment-state`'s "Independently deployable
bare-metal seller role"), each through a settings model of its own. Sites, service
peers, registries, settlement mechanisms and identity are stated alike. `[pricing]`
and `[negotiation]` carry each domain's own terms and policy chain, and each loop's
interval is a key of its own. The umbrella chart's `storefront` subchart is the VM
storefront's chart; `helm/charts/bare-metal-storefront` deploys the dedicated
one. The umbrella refuses a release whose bare-metal storefront is bound to the
release's own provisioning service, naming a second release
(`helm/templates/tests/helm-profile.yaml`; `helm/tests/test_release_topology.py`). The
supported Kubernetes topology is therefore several storefronts per registry, each in
its own release with its own provisioning service
(`docs/development/DEPLOYMENT_AND_CONFIG.md`, "Release topology"). Compose runs the
dedicated storefront from `domains/bare_metal/compose.yml`. The seller has two command
lines, `market-storefront` and `bare-metal-storefront`, each with its own migration
command.

**The site.** One provisioning service composes the VM and bare-metal adapters with a
mock executor for each (`docs/development/TESTING.md`, "System Integration Tests
(End-to-End)"). A machine offered as VM slices and as a whole host is registered as two
hosts in two pools, and `physical_host_id` lets the site's accounting see one machine
(`docs/development/ARCHITECTURE.md`, "One name per concept"). The site refuses an
exclusive claim on a machine a shareable allocation holds, and the reverse, before any
executor work (`site-capacity`'s "Cross-mode physical accounting"). A provisioning
service names one storefront URL and one trusted storefront principal
(`provisioning/compute/service/src/compute_provisioning_service/identity.py`,
`storefront_principal`), and its capacity-released event carries the reservation's
offering mode (`services/deal_event_sink.py`).

**What is proven today.** The VM lane runs complete VM deals through a storefront that
registers both contributions and serves one. The bare-metal lane runs complete
bare-metal deals through the dedicated storefront on a site of its own. No lane has one
storefront sell both, and no lane sells one machine both ways. The site's cross-mode
refusal is proven by `kit/site/tests/integration/test_ledger.py` and
`provisioning/compute/service/tests/integration/test_capacity_api.py`.

**Released.** `marketplace-v0.4.0` carries all of the above, the dedicated chart and
the two-release topology included.

## Decisions

### D1 — One storefront process sells VM and bare metal

A compute storefront serves every registration its frozen registry holds. Configured
with `vm` and `bare_metal`, one process publishes listings of both, opens and continues
negotiations on either, settles, delivers, recovers and tears down deals of both, and
reports both. Every record is handled by the registration its immutable binding names,
and by no other: a route, a loop or a callback that meets a record resolves the
record's registration first. A storefront configured with one registration is the same
program with one entry.

This is the unification of the two compute storefronts, and it changes the deployment
topology: one storefront beside one provisioning service sells that site's hardware in
both form factors. It is Goal 3's defining work and this change is the one that
completes the goal.

Rejected:

- `kit-owned-storefront-shell` taking it by dropping its non-goal. That change
  extracts what three storefronts duplicate, API credits included, and changes no
  deployment. This one merges two domains into one process and changes what an
  operator deploys. Folding it there would put Goal 3's defining work in a Goal 4
  change and make an extraction that is meant to preserve behaviour carry a topology
  change.
- `bare-metal-and-credits-domain-stacks` taking it by settling its deferred deployment
  shape. Its section moves bare metal's routes; making one process serve both is far
  larger than that section and touches the VM storefront, which that change's
  non-goals exclude.
- A change that only proves. There is no storefront to prove: the scenario cannot be
  written until a process serves both, so the proof is the acceptance of the work and
  not separate work.
- A new change. Nothing would be left in this one.

### D2 — Goal 3 is complete when one process completes a deal of each form factor from one site's hardware

Goal 3 is complete when, on every pipeline run, a lane shows one storefront process
publish a VM listing and a bare-metal listing from one site's hardware, complete a deal
of each, and the site refuse the cross-mode conflict. That scenario is this change's
acceptance.

It is a locally verifiable scenario: it runs against the repository's own stack with
provisioning in its mock profile and the lane doubles in place of the payment and
dispute authorities, holds every timer the lane's stages can meet, and reaches every
instant by setting lane time
(`docs/guidance/repository/deal-scenarios.md`;
`docs/guidance/engineering/system-tests.md`, "Locally verifiable and external-topology
scenarios").

Rejected: a goal that ends at the registry and the bindings. They let a process serve
two domains and no process does; the goal's value statement is about hardware sold two
ways, which nothing delivers until a deal of each completes from one site.

### D3 — One storefront over several sites is neither this change's nor Goal 3's

This change adds no second provisioning service, no lifecycle of each domain at each of
two sites, and no proof about identifiers that are equal across sites. Goal 3's value
needs one site: the exclusivity it speaks of is arbitrated inside one site's
accounting.

The code handles several sites per storefront: per-site trust, per-site projection
state and exact-site routing, proven at unit and integration level
(`core/storefront/tests/unit/test_aggregation.py`;
`domains/vms/storefront/tests/integration/test_site_trust.py`;
`domains/bare_metal/storefront/tests/test_site_clients.py`). No deployment and no lane
runs one storefront over two sites. Making that a deployed and release-qualified
topology is planned as a roadmap goal of its own, and its live proof stays unowned
until then, beside the two-seller introduction scenario the change index records.

Rejected: keeping a two-site proof here as coverage. It would hold Goal 3 open on work
that is not the goal's.

### D4 — The order against Goal 4's extractions is settled in this change's design session

`kit-owned-storefront-shell` moves every storefront's route set and executable assembly
into kit, and two more extractions follow it. This change and those extractions each
cost less if the other lands first. Built after the shell, the dispatch from a
record's binding to its registration is written once, on the kit's routes. Built
before it, every remaining extraction handles two storefronts where it would handle
three. Which order is taken is decided in this change's design session (Q1), and both
changes say so.

Until then the change index records this change as waiting for
`kit-owned-storefront-shell`, the order accepted as the default, with its cost: Goal 3
waits on a Goal 4 change. The dependency gates implementation and not design, since
the design session is where the order is settled.

Rejected: fixing the order now, in either direction. What each order costs depends on
what the shell's own design settles, and two of its questions are open.

### D5 — Restart and unavailability are proven at integration level

A lane holds a party's loops and never stops the party
(`docs/guidance/repository/deterministic-tests.md`, "Pause the loop, then advance it
explicitly"), and the lanes start from empty state and restart no service
(`test-compatibility`'s "Bare-metal storefront restart recovery is proven at
integration level"). The lane scenario therefore has no stage that restarts the
storefront, restarts the site, or makes the site unavailable. Those behaviours are
proven where an application can be rebuilt over its database, and the proofs exist:

- a storefront rebuilt over its database:
  `domains/bare_metal/storefront/tests/test_restart_recovery.py`,
  `domains/bare_metal/storefront/tests/test_site_clients.py`
  (`test_every_fulfillment_verb_routes_to_persisted_site_after_restart`),
  `domains/vms/storefront/tests/integration/test_restart_persistence.py` and
  `domains/vms/storefront/tests/integration/test_restart_recovery.py`;
- a site resuming durable work after a restart:
  `provisioning/compute/service/tests/integration/test_fulfillment_convergence.py`
  (`test_fresh_watchdog_resumes_a_teardown_from_durable_state_after_restart`);
- a site that cannot be reached:
  `core/storefront/tests/unit/test_aggregation.py`
  (`test_reserve_pinned_to_a_broken_site_propagates_not_falls_back`).

What this change adds at that level is the two-registration case: a storefront holding
deals of both registrations, rebuilt over its database, resumes each under its own
registration.

### D6 — Nothing here needs a real GPU or a real-host run

The change touches neither the Ansible layer nor how an adapter executes it, and the
lane scenario delivers through mock provisioning. A real-host run is owed again only
when one of those changes, so none is owed here, and no GPU is involved.

### D7 — A path is owed to deployments of marketplace 0.4.0

`marketplace-v0.4.0` ships the dedicated bare-metal storefront, its chart and the
two-release topology. An operator running that release upgrades to this one by a
documented procedure that covers the dedicated chart, the two-release topology and the
bare-metal storefront's database, and no deal either 0.4.0 storefront accepted is lost
or served under another registration. What the procedure is, is Q2 and Q5.

### D8 — The mode a record is bound to is its offering mode

A record's binding names its offering mode, and the documents and code of this change
say "offering mode" for it. "Executor" names the action-dispatch component and nothing
else (`docs/development/ARCHITECTURE.md`, "One name per concept").

### D9 — API credits keeps its own storefront

API credits is not a compute-family domain: it has no family and shares no vocabulary
with VM and bare metal (`docs/guidance/repository/package-layers.md`, "Scope"). Its
storefront stays a one-registration program. It composes the same frozen registry and
the same kit composition as the compute storefronts, so a change to what a composition
is given (Q3) reaches its composition root as a signature change and nothing else.

### D10 — There is one compute storefront executable

The compute family has one storefront program, and which domains it serves is
configuration. A deployment that sells bare metal alone runs that program with one
registration. No bare-metal storefront executable, route set, runtime, server, image
or chart of its own remains. What stays under `domains/bare_metal/storefront` is the
bare-metal contribution: its contract, hooks, codecs, publication semantics and
tables. The storefront is to the two compute domains what the provisioning service
already is to them: one service composing both, where a domain contributes handlers
and not a second server.

What goes with the dedicated program: the `bare-metal-storefront` and
`bare-metal-storefront-migrate` commands, the routes in `api.py`, `server.py` and the
composition in `runtime.py`, the `bare-metal-storefront` image and its entry among the
release's declared images (`manifests/release-components.json`),
`helm/charts/bare-metal-storefront`, and the dedicated storefront service in
`domains/bare_metal/compose.yml`. Whether one release keeps the chart while operators
move is Q2.

Rejected:

- Keeping a supported separate bare-metal executable. The repository would go on
  maintaining a second route set, runtime and chart, which is what unification exists
  to remove.
- Leaving it to the design session. The chain, the configuration, the lanes and the
  command line each have a different answer for one program than for two.

### D11 — Bare metal's own routes, runtime and server are deleted here

`bare-metal-and-credits-domain-stacks` planned to route bare metal's negotiation and
listings through shared routes and to reduce its runtime and server to contribution
adapters (its tasks 4a.3 to 4a.6). Under D10 they are neither moved nor reduced: they
are deleted when the compute storefront serves bare metal. That work is this change's,
and those tasks move here. What they asked to be shown, that bare metal's negotiation
stages pass unchanged through shared routes, is shown by the bare-metal scenarios
passing against the compute storefront.

The fallbacks to a module getter go with them. Bare metal's runtime and persistence
client take their contract from `get_market_domain_contract()` when given none
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py`,
`build_runtime_from_configuration`; `sqlite_client.py`). The contribution's
`build_contract` stays the one place its contract is built, as the VM contribution's
is.

Two things follow in the roadmap:

- The gap "the bare-metal storefront serves its own negotiate and listing routes" is
  Goal 3's, owned by this change.
- Goal 4's completion test is stated over the storefronts that remain: API credits and
  the compute storefront each run a full deal through a composed storefront, with no
  domain-local copy of an extracted concern.

Rejected: moving the routes onto shared routes first and deleting the program later.
The routes would be moved for a program that is going.

## Open Questions

Each is decided in this change's design session.

### Q1 — The order against Goal 4's remaining extractions

Three extractions remain in Goal 4. `kit-owned-storefront-shell` moves the route set,
executable assembly, health and system service into kit.
`kit-owned-listing-and-fulfillment-lifecycles` and
`kit-owned-storefront-auth-and-persistence` follow it. Each composes every storefront
and removes every domain-local copy, so each is smaller with two storefronts than with
three, and this change removes one (D10). Against that, this change needs routes that
choose a record's registration, and the shell is where shared routes come to exist.

| Order | Each extraction handles | The dispatch is built | Goal 3 waits for |
|---|---|---|---|
| (a) shell, this change, the two that follow | the shell three storefronts, the others two | once, on the kit's routes | the shell |
| (b) this change, shell, the two that follow | two | in the VM storefront's controllers, then moved into kit by the shell | nothing |
| (c) the shell's route set, this change, the shell's executable assembly and health, the two that follow | the route set three, everything else two | once, on the kit's routes | a change carved out of the shell for its route set |
| (d) all three extractions, this change | three | once, with one authentication arrangement and one listing lifecycle in place | all of Goal 4's next wave |

What each costs beyond the table:

- **(a)** This is the gate the owner accepted, knowing Goal 3 then waits on a Goal 4
  change. The shell composes bare metal's program onto kit: its routes become hooks,
  which this change keeps, and its server and runtime become an entry point, which
  this change then deletes. The shell could leave that second part alone, turning
  bare metal's routes into hooks and having its existing server mount the kit's
  routes, under a recorded exception to the extraction rule that names this change as
  the one removing the copy; what it saves is the assembly of one executable. The
  shell's design has two questions that gate its executable-assembly step, the
  Alkahest lifespan seam and the compute shell's home, and Goal 3 waits on both.
- **(b)** This change deletes bare metal's routes, runtime and server directly. Its
  routes are folded into the VM storefront's controllers behind a hook seam designed
  here and replaced by the shell's. The VM storefront package then
  composes its sibling in code, where today it only installs it, under the two scope
  exceptions `docs/development/ARCHITECTURE.toml` records against the shell change.
  Bare-metal requests authenticate through the VM storefront's middleware set, so no
  second arrangement needs reconciling. This change decides where the compute
  storefront's composition lives.
- **(c)** The dispatch is built once and Goal 3 does not wait on the shell's
  executable-assembly questions, which do not bear on routes. It takes carving the
  shell change in two, as `kit-owned-storefront-loop-lifecycle` was carved out of it
  before. This change deletes one of the three executables the second half would
  otherwise assemble.
- **(d)** Nothing is reconciled twice, and Goal 3 is last.

One consideration cuts across (a) and (c). The two storefronts authenticate by
different arrangements, the VM storefront through a middleware set of its own and bare
metal through one response middleware and its routes, and one path served for both
needs one. Either the shell owns its routes' authentication, which its design lists as
open, or this change reconciles the two as far as its scenario needs, or
`kit-owned-storefront-auth-and-persistence` also lands first.

Recommended: (a), the order the change index records. It builds the dispatch once and
splits no change. It would move to (c) if the shell's route set is ready while its
executable-assembly questions are still open, and to (b) if the shell's design has not
begun when this change is ready to plan.

### Q2 — The path from a 0.4.0 bare-metal deployment

Under 0.4.0 the dedicated storefront runs as the umbrella's `bare-metal-storefront`
subchart, in a release of its own beside its own provisioning service and over its own
database (`helm/bare-metal-release-values.yaml`), or from
`domains/bare_metal/compose.yml`. Under D10 the program, its commands and its chart
go. Three things are open together: what an operator does, what becomes of the
database, and whether a release keeps the old chart while operators move.

- (a) **Upgrade in place, onto the storefront chart.** The release stops enabling the
  `bare-metal-storefront` subchart and enables the `storefront` subchart with
  `bare_metal` alone, bound to the existing volume. The database upgrades under Q5's
  chain and its deals continue.

  ```text
  1. Back up the bare-metal storefront's database; preview with the migration
     command's --check.
  2. Move the release's values from `bare-metal-storefront.config` to the storefront
     subchart's agent, with one registration:
       storefront_domains:
         - contribution: bare_metal
           offering_mode: bare_metal
           domain_identity: bare_metal.v1
           contract_version: "1.0"
  3. Upgrade the release, binding the agent to the existing volume claim.
  4. Verify with --check and system status.
  ```

  The operator rewrites values and rebinds a volume across subcharts in one step, and
  the Service name buyers and the site call must be kept.
- (b) **Upgrade in place under the old chart, for a stated period.** One release keeps
  `helm/charts/bare-metal-storefront`, rendering the compute storefront's image and
  commands with `bare_metal` alone, so an upgrade works with the values an operator
  already has. The release handbook's "Compatibility to retire" names the release at
  which the chart goes, and the operator makes the move of (a) before it. A second
  chart for one program is kept for that time.
- (c) **Drain and re-declare.** The operator pauses the dedicated storefront's
  trading, keeps it on the 0.4.0 image until its deals end, then declares its pools
  and hosts at a compute storefront's site and removes the release. The database is
  discarded, and no chain has to adopt a bare-metal database. A bare-metal lease can
  run for its seller's whole horizon, so the 0.4.0 image runs until the last one ends.

Recommended: (b). The database is adopted in place under (a) and (b) alike. (b)
splits the operator's work into an upgrade that changes nothing they wrote and a
change of chart at a time they choose, and the chart's end date keeps it from staying
by default. It would move to (c) if adopting a bare-metal database under the compute
chain proves unsafe, and to (a) if no 0.4.0 deployment runs the dedicated chart.

Under (a) and (b) the two-release topology keeps working as two compute storefronts,
each beside its own provisioning service. Moving both onto one site is a further step
an operator may take, and it carries no deal across (Q5).

### Q3 — How one process holds two registrations

Three kinds of thing meet a record: a request on a shared path, a loop over a shared
table, and a callback from the site. What the route can read to choose a registration
differs by route:

| Route family | What names the registration |
|---|---|
| Open a negotiation, read or change a listing | the listing's binding |
| Continue a negotiation, settle, read delivery, tear down | the negotiation thread's binding |
| Capacity released, lease ended | the reservation the event names, and the event's offering mode |
| System status, lifecycle controls, trading pause, time, identity, pool overrides | none: they are the process's |

- (a) **A service set per registration behind dispatching routes.** The kit's
  composition is given the registry and, per registration, that contribution's hooks
  and service builder. The lifespan builds each registration's services; a route reads
  the record's binding and calls the selected registration's hooks. What the process
  has one of is built once by the composition root and handed to every set: the
  database, the loop controller, the trading pause, the time source, identity state,
  site trust and clients, the projection state and the registry client.

  ```text
  request ─► kit route ─► record's binding ─► registry ─┬─► vm hooks ─► vm services
                                                        └─► bare_metal hooks ─► bare-metal services
  ```

  A loop over a shared table cannot be one per registration as the kits stand: the
  settlement worker, the servicing cycle and the negotiation watchdog scan tables that
  hold both domains' records and know no binding. Each such loop runs once and
  dispatches each record it claims to its registration's hooks.
- (b) **One service set whose collaborators take the binding.** One negotiation
  runtime, one settlement composition, one fulfillment service, each holding every
  registration's hooks and choosing per call, as the provisioning service's job engine
  resolves an executor by offering mode and action. The kit runtimes change to hold a
  table of hooks where they hold one set today.
- (c) **Two applications in one process**, mounted under a path each. A buyer would
  meet two storefronts at two addresses, and a route would select a registration by
  its address, which record-bound selection rules out.

Recommended: (a), with the rule that anything scanning a shared table runs once and
dispatches per record. It matches the shape `kit-owned-storefront-shell` gives a
contribution, hooks and a service builder, whichever of the two changes lands first
(Q1). It keeps a domain's services the domain's, and a third compute domain
registers a contribution without a kit learning it
(`docs/guidance/repository/family-kits.md`, "Placement tests"). It would move to (b)
for a kit runtime whose dispatch per record turns out to be most of the runtime.

Three things the session settles with it:

- **Loop names.** Both contributions register `publication`, `site-projections` and
  the four servicing loops under the same names, and one controller cannot hold two
  loops of one name. `site-projections` is already one loop over one state. For the
  rest, one loop of each name that serves every registration keeps the lifecycle
  routes and the canonical client's methods as they are.
- **The VM storefront's module-level services and settings**, which
  `kit-owned-storefront-shell` may or may not have turned into instances by then, and
  bare metal's runtime object, whose services stay and whose composition goes (D10).
- **Process-wide routes.** System status reports every registration; one trading pause
  refuses new negotiations of every mode.

### Q4 — Publication

Each registration's publication differs in what it derives and closes: VM publishes the
shapes a pool states, bare metal one listing per whole machine.

- (a) **One `publication` loop whose cycle runs every registration's source in turn.**
  The core builder is given each source's own arguments by its contribution, the
  cycle's report names each registration's results, and one registry sweep runs for
  every mode the process serves. One step, one preview, one wake.
- (b) **A loop per registration**, named for its mode: `publication-vm`,
  `publication-bare-metal`. Each has its own interval, step and preview. The lifecycle
  routes gain loop names, and the `publish` commands name one.

Recommended: (a). One loop keeps the loop layout the two storefronts already share and
the routes and client methods released in 0.4.0, and one sweep covers every mode the
process serves. It would move to (b) if a seller needs to hold one form factor's
publication while the other runs.

In either case the VM contribution's `served_offering_modes` stops being a statement
about a neighbouring storefront: the process names the modes it serves.

### Q5 — Persistence

One process has one database
(`docs/guidance/repository/service-databases.md`, "Each service owns its database").
Its chain must create both domains' tables and each shared table once.

- (a) **One chain composed per registration.** The composition declares the shared
  baselines, then each registered contribution's baseline and migrations.

  ```text
  vm and bare_metal registered
    baselines:  core, settlement, contact-exchange, pool-overrides, vm, bare_metal
    migrations: core…, vm…, bare_metal…
  vm alone
    baselines:  core, settlement, contact-exchange, pool-overrides, vm
    migrations: core…, vm…
  ```

  A database's compatible state then depends on which registrations are configured,
  and removing a registration leaves identifiers the chain no longer lists, which the
  engine refuses as ahead.
- (b) **One fixed chain for the compute storefront**, the first of the two above
  whatever is registered. Every compute storefront database has every table, and a
  one-registration storefront leaves the other domain's tables empty. A database's
  state does not depend on configuration.
- (c) **A database per registration**, each with its own chain, in one process. The
  common tables that bind a listing to its negotiation and its settlement would be
  split in two, and the shared loops of Q3 would scan two databases.

Under (a) with both registered, and under (b) always, a released database upgrades in
place. A 0.4.0 VM database records the shared baselines and the VM one, so the engine
reads it as this chain's and behind, with the bare-metal baseline and migrations
pending, and applies them in the chain's order. A 0.4.0 bare-metal database is the
mirror case. One thing stands in the way: the kit-owned tables each chain creates
under its own identifier would be created twice.

Recommended: (b). A chain that does not vary with configuration keeps the migration
command and its `--check` a statement about the release alone, as they are today. The
doubly created tables are reconciled once, by moving their creation to the kit's own
migrations, which is where `deployment-state`'s "Composition-owned migration ordering"
already says a kit's tables come from. A released database records them under its own
domain's identifiers, so the reconciled chain still lists both sets and each tolerates
the tables being present.

Under every alternative two live databases are not merged. An operator who moves a
bare-metal deployment's hosts onto another storefront's site carries no deal across;
Q2 is how such a deployment upgrades without doing so.

### Q6 — Configuration and the chart

`[[storefront_domains]]` already selects registrations. Three things are open.

**Sections both domains read under one name.** `[pricing]` and `[negotiation]` carry
each domain's own terms and policy chain. One file must hold both.

- (a) Shared sections stay at the top level and each registration's own settings move
  under a table named for its offering mode:

  ```toml
  [[storefront_domains]]
  contribution = "vms"
  offering_mode = "vm"
  domain_identity = "compute.v1"
  contract_version = "1.0"

  [[storefront_domains]]
  contribution = "bare_metal"
  offering_mode = "bare_metal"
  domain_identity = "bare_metal.v1"
  contract_version = "1.0"

  [capacity.sites]
  default = "http://provisioning:8081"

  [vm.pricing]
  settlements = [
    { mechanism = "alkahest.v1", asset = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0", rate = "100", per = "hour" },
  ]

  [vm.negotiation]
  policies = ["has_matching_inventory_guard", "escrow_shape_guard", "bisection"]

  [bare_metal.pricing]
  settlements = [
    { mechanism = "alkahest.v1", asset = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0", rate = "10", per = "hour" },
  ]
  default_max_duration_seconds = 86400

  [bare_metal.negotiation]
  policies = ["escrow_shape_guard", "bisection"]
  ```

  A 0.4.0 file's top-level `[pricing]` is then a key that moved: read as the one
  registration's when one is registered, refused by name when two are.
- (b) One meaning for each section, reconciled across the domains, so `[pricing]`
  prices both by shape and nothing is namespaced. This is the larger reconciliation
  of sibling domains, and much of what differs is already stated per pool, by pool
  overrides and pool hints.

Recommended: (a) for what differs today, with each difference recorded as one to
reconcile or as a stated domain difference
(`docs/guidance/repository/family-kits.md`, "Sibling domains behave alike").

**A registration that serves nothing.** The umbrella chart's default values and the VM
lane's seller register `bare_metal` on a storefront that serves none of it. Nothing is
shipped disabled to be enabled later, so a default must not advertise a mode the
process does not serve.

- (a) The default values keep both registrations, which become true when this change
  lands: the default release's storefront serves both from the release's site. Until
  then the chart ships a default that advertises an unserved mode, as it has since
  0.3.0.
- (b) The default values register `vm` alone, and an operator adds `bare_metal` with
  the pools that back it. Removing the second registration from the defaults is a
  correction that need not wait for this change.

Recommended: (b). A release that sells bare metal needs pools and hosts an operator
declares, so a default registration alone sells nothing. The lane's seller keeps both
registrations, where it is the one running process that proves both wheels install and
a two-entry registry freezes.

**The umbrella's refusal and the local two-release topology.** The umbrella refuses a
bare-metal storefront bound to the release's own provisioning service, and
`make helm-topology-up` installs a second release to run it. Under D10 a release has
one compute storefront, so the refusal goes with the dedicated subchart, at the end of
any period Q2 keeps it for.

- (a) The local topology becomes one release whose storefront registers both, and the
  two-release targets go.
- (b) The two-release targets stay as the rehearsal of several storefronts on one
  registry, the second release a compute storefront with `bare_metal` alone.

Recommended: (b). Several storefronts per registry stays the supported topology and
is worth rehearsing, and the second release rehearses the bare-metal-only deployment
D10 keeps possible.

### Q7 — Which lanes run what

`test-compatibility`'s "Each domain runs in its own lane" gives each market domain a
lane and a pipeline job of its own, and
`openspec/specs/market-composition/testing.md` says the multi-domain composition's
system evidence is a VM deal and a bare-metal deal, each in its own lane. Today the
bare-metal lane runs the dedicated storefront, which goes (D10).

- (a) **Two lanes of one program.** The VM lane's storefront serves both registrations
  and runs the VM scenarios and the scenario of D2; its site gains a machine declared
  both ways. The bare-metal lane runs the same image with `bare_metal` alone and its
  scenarios unchanged. No stack or job is added, a failure still names one domain's
  lane, and the bare-metal-only deployment is proven on every run, release-image mode
  included.
- (b) **One compute lane.** Both domains' scenarios run against one storefront serving
  both, and the bare-metal lane and its stack go. One job's failure then covers both
  domains, the lane grows by the bare-metal modules, and the one-registration
  deployment is proven only by integration and render tests.
- (c) **A compute-family lane beside both**, a fourth stack and job running only the
  scenario of D2.

Recommended: (a). It changes each lane least and keeps every deployment D10 allows
under a deal on every pipeline run. The scenario's stages are the shared compute deal
stages both lanes already run
(`e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`) with each domain's driver.
It would move to (b) to shorten the pipeline once the one-registration deployment has
no operator.

Under (a) the requirement is restated over stacks: each lane composes one stack, the
compute storefront's two-registration lane runs both of its domains, and the
bare-metal-only lane keeps bare metal's evidence apart.

### Q8 — The seller and buyer command lines

- **Seller.** One program has one command line and one migration command (D10).
  Today `market-storefront` and `bare-metal-storefront` each have `serve`,
  `check-payments`, a publish command and the groups `deals`, `config` and
  `pool-override`; the first adds `check-mediation` and groups for logs, network,
  escrow and settlement, the second `redeliver-introduction`. The direction is the
  fewest differences between the two domains' commands.

  - (a) One set of commands that act on every registration, or on the registration a
    record names, with the offering mode given where nothing names it:

    ```text
    market-storefront publish                              # every registration
    market-storefront publish --offering-mode bare_metal   # one
    market-storefront deals end <negotiation>              # the deal's own
    ```

  - (b) A group per domain, registered by its contribution, as the buyer executable
    loads its domains:

    ```text
    market-storefront vm publish
    market-storefront bare-metal publish
    ```

  Recommended: (a). A seller learns one command for both form factors, and a third
  domain adds no group. Whether the shell owns the operator command line is open in
  `kit-owned-storefront-shell`'s design, and this follows it. Whether the
  `bare-metal-storefront` command names stay for a period follows Q2.
- **Buyer.** The buyer executable loads each domain's commands as a plugin and takes
  a deal's storefront address from the listing and the run's record, so nothing in it
  assumes a storefront serves one domain. The bare-metal buyer filters discovery by
  offering mode and the VM buyer does not; a VM buyer that opens a negotiation on a
  bare-metal listing is refused by the listing's binding, in one process as across
  two. Provisional answer: no buyer change, confirmed by the lane scenario buying both
  from one address.

### Q9 — A record whose registration is no longer configured

Once a process serves two registrations, removing one while it holds live deals is an
operation an operator can perform. `market-composition`'s "Storefront roots inject a
frozen domain registry" has the scenario "Durable work names an unavailable
contract", in which startup or recovery fails readiness for a record whose binding
cannot resolve. Startup reads no stored binding today: such a record fails with a
binding error when an operation next resolves it
(`openspec/specs/market-composition/configuration.md`, "Combined compute-family
storefront"), and the binding inventory
(`core/storefront/src/core_storefront/sqlite_client.py`,
`list_storefront_domain_bindings`) has no production caller.

- (a) Startup refuses while any nonterminal record names a registration the registry
  lacks, naming the registration and the count.
- (b) Startup proceeds, status reports the unresolvable records, and each fails where
  it is next used, as today. The scenario's startup half is then removed.

Recommended: (a). An operator who removes a mode with leases running finds out at once
and not when a lease next needs servicing.

### Q10 — Provisional answers

Each follows from something settled or from the nearest precedent, and is confirmed or
moved in the design session.

- **Requirements this change modifies**, their deltas written once Q2 to Q7 settle.
  `market-composition`: "Role-owned executable composition", which names a bare-metal
  storefront executable as a composition root; "Storefront roots inject a frozen
  domain registry"; and "Both compute storefronts run one loop layout".
  `deployment-state`: "Independently deployable bare-metal seller role", which
  requires a dedicated image and chart and whose scenario "Operator enables both
  compute storefronts" requires two processes on one provisioning service;
  "Multi-domain storefront configuration is explicit"; "Deployable stack per market
  domain"; and "Composition-owned migration ordering". `storefront-publication`:
  "Publication runs as a controllable storefront lifecycle loop" and "Bare metal joins
  the site-scoped pool-override store", whose scenarios name the
  `bare-metal-storefront publish` command, and "A storefront retires registry listings
  it does not hold open". `test-compatibility`: "Each domain runs in its own lane",
  "Multi-domain storefront selection has focused compatibility coverage" and
  "Bare-metal storefront restart recovery is proven at integration level", whose
  rebuilt application becomes the compute storefront, and one added requirement for
  the scenario of D2. `settlement-servicing`'s scenario "VM and
  bare-metal obligations service concurrently" becomes reachable and is proven, not
  changed. No `site-capacity` or `physical-provisioning` requirement changes.
- **Normative scenarios this change makes true or replaces.** Each is in the
  permanent specifications today and unreachable or only true to the letter:
  `settlement-servicing`, "Accepted domain binding governs the servicing lifecycle",
  scenario "VM and bare-metal obligations service concurrently"; `market-composition`,
  "Storefront roots inject a frozen domain registry", scenarios "VM and bare-metal
  contributions start together", "One explicit contribution starts" and "Durable work
  names an unavailable contract" (Q9), and its body, which is true of the VM
  executable alone; `deployment-state`, "Multi-domain storefront configuration is
  explicit", scenario "Combined storefront is rendered", and "Deployable stack per
  market domain", scenario "A domain's deployment topology changes";
  `storefront-publication`, "Durable bindings govern multi-domain publication",
  scenario "One pool exposes VM and bare-metal modes"; and `test-compatibility`,
  "Multi-domain storefront selection has focused compatibility coverage", scenario
  "Full live proof is requested", which the scenario of D2 replaces.
- **A scenario to add with its test.** `storefront-publication`'s "Commercial mapping
  identity" states that the derivation key includes offering mode and domain identity
  and has no scenario for it. This change adds "One pool exposes two offering modes"
  and the test that two modes over one source identity yield different keys.
- **Test levels.** Dispatch from a record's binding to its registration, and the
  refusal of a record under the wrong one, are application integration tests of the
  compute storefront through its typed client, with two registrations and one fake
  site. The two-registration restart case of D5 is the same level, and so is a
  storefront with `bare_metal` alone. The bare-metal storefront's existing
  application tests move with the code they prove. The chain is library integration,
  with the chain tests each storefront has today and one for each released database
  it adopts. Chart and Compose renders are render tests. The lane scenario is the one
  system-level proof and repeats none of those.
- **The scenario's shape.** One site declares one machine as a VM host in a VM pool and
  as a whole host in a bare-metal pool, sharing a `physical_host_id`. The storefront
  publishes a listing of each. A VM deal completes on the shared stages; while its
  lease holds the machine, a bare-metal claim on it is refused at the site and the
  storefront does not sell it; the VM lease ends and the capacity returns; a
  bare-metal deal completes; while it holds the machine a VM claim is refused. Each
  refusal is observed through typed clients.
- **Current-state text this change rewrites when it lands.**
  `docs/development/ARCHITECTURE.md`'s paragraph beginning "VM, bare metal, and API
  credits each run a dedicated storefront executable";
  `openspec/specs/market-composition/architecture.md`, "Frozen storefront registry and
  executable ownership"; and the last paragraph of
  `openspec/specs/market-composition/configuration.md`, "Combined compute-family
  storefront", which says a second registration serves nothing.
- **Documents.** `docs/development/ARCHITECTURE.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md` describe one compute storefront;
  `docs/development/TESTING.md` describes the lanes; `docs/operator-handbook.md` gains
  the upgrade from 0.4.0; `docs/bare-metal-seller-quickstart.md` and
  `docs/seller-quickstart.md` describe one program and how to sell either form factor
  or both from it; `docs/release-handbook.md` gains a row if Q2 keeps the old chart
  for a period.

### Q11 — Implementation cadence

Recommended: three rounds, under the order of Q1 (a). First, a composition that holds
several registrations, with routes dispatching by binding and the shared loops
dispatching per record, serving bare-metal records, proven by integration tests with
a fake site; two sessions. Second, publication for both registrations, the chain and
the configuration, and the deletion of bare metal's own routes, runtime, server and
commands; two sessions. Third, the charts, the Compose stacks and lanes, the lane
scenario and the operator's path from 0.4.0; two sessions. Another order under Q1
changes what the first round builds on, not the rounds.

## Verification

Provisional levels are in Q10. The acceptance is the lane scenario of D2, on mock
provisioning and the lane doubles. Nothing here is proven on a real host (D6), and
nothing is proven over two sites (D3).

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 one storefront process sells VM and bare metal | `openspec/specs/market-composition/spec.md` and `architecture.md`; `docs/development/ARCHITECTURE.md`, "Capacity publication and multi-domain storefront composition" and "Production and staging"; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D2 what completes Goal 3 | `docs/development/ROADMAP.md`, Goal 3; `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md` |
| D3 several sites per storefront is another goal's | `docs/development/ROADMAP.md`, Goal 3; `docs/development/ARCHITECTURE.md`, "Site authority" and "Production and staging" |
| D4 the order against Goal 4's extractions is this design session's | None: the change index records the default while both changes are open |
| D5 restart and unavailability at integration level | `openspec/specs/market-composition/testing.md` |
| D6 no real GPU or real-host run | None: stated with the scenario under D2 |
| D7 a path from marketplace 0.4.0 | `docs/operator-handbook.md`, "Upgrading a deployment"; `openspec/specs/deployment-state/spec.md` |
| D8 offering mode | None: `docs/development/ARCHITECTURE.md`, "One name per concept", states it |
| D9 API credits keeps its own storefront | `docs/development/ARCHITECTURE.md`, "Capacity publication and multi-domain storefront composition" |
| D10 one compute storefront executable | `openspec/specs/market-composition/spec.md` and `architecture.md`; `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`, "Local development" and "Production and staging"; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D11 bare metal's own routes, runtime and server are deleted here | `docs/development/ROADMAP.md`, Goals 3 and 4 |
