# Design — share site projection state

## Context

Opened 2026-10-14, after `encapsulate-capacity-backing` was archived, from a review of
`unbacked-bare-metal-listings` against the implemented tree. That review found that
unbacked bare-metal listings would depend on source reconciliation alone, which bare
metal ran only when an operator invoked publication, and that the unbacked design had to
scope the inventory guard around bare metal's live recheck. Both follow from bare metal
holding no projections. Design settled with the maintainer on 2026-10-15.

What exists:

- `core_storefront.site_projections.ProjectionCache` is the shared primitive: one
  projection family's cached value with its identity, polled by version, refreshed on
  demand, retaining its last generation as `stale` when a refresh fails, and accepting a
  `validate` hook.
- VM's `market_storefront.services.site_projection_cache` composes it into a
  process-global `_caches` dict: one resource-pool and one capacity-bucket cache per
  configured site; a poller loop that wakes VM's publication loop when a resource-pool
  identity changes; per-site refreshes for override writes and inline reconciliation; a
  topology-error handler; a status summary; and VM's own `listing_cardinality_mode`
  explanations. About ten production modules read it through module functions, and
  thirteen test files set it by patching `_caches`.
- `kit/capacity-publication`'s "exact site projection" is `CapacityRuntime.projections()`,
  a live per-site capacity snapshot fetched on every call. It holds no state and is not
  either projection family.
- The bare-metal storefront holds nothing. Each publication run fetches every site's
  resource-pool projection live, accepts it through `trusted_bare_metal_projection`, and
  records the accepted pools durably in `bare_metal_accepted_site_generations`, which
  override status reads. Its opening recheck fetches the listing's site live. Its
  publication step is registered on the storefront's loop controller with no timer, and
  `bare-metal-storefront publish` runs a pass in its own process against the database.
- The bare-metal storefront reads its application settings from about twenty-six
  environment variables, and `helm/charts/bare-metal-storefront` passes them as pod `env`
  entries, contrary to `docs/development/DEPLOYMENT_AND_CONFIG.md`'s mounted-file rule.
  The VM storefront reads `storefront.toml`, `storefront.json`, and
  `storefront.secrets.toml` through `kit/config`'s `storefront_config_files()`, and its
  chart renders an agent's `config` through unchanged under a values schema generated
  from its typed models.

### Corrections to the change as first written

1. The proposal said the publication command "keeps running one cycle through the
   storefront's API". It ran in its own process and wrote the database directly; the
   permanent spec relied on that ("Publication runs from the command … in its own
   process"). It becomes an API client (C1).
2. The combined compute-family storefront registers the bare-metal contract for routing
   but never composes bare-metal publication. The first delta's wording would have
   required bare-metal publication inside it (D1).
3. "The kit already owns exact site projection" named the live capacity snapshot, not
   the projection families. The kit owns per-site projection state after this change,
   not before it; `ARCHITECTURE.md`'s "VM publication reads the kit's site projections"
   is false on `dev` and becomes true here.
4. The first delta left "Bare metal joins the site-scoped pool-override store", which
   mandates the durable accepted-generation record, unmodified (C3).
5. Bare metal already breached "Projection-backed listing candidate derivation" (every
   storefront loads, polls, and holds both families) and `site-capacity`'s prohibition
   on persisting projection generations. This change closes both breaches.
6. The recheck's availability comes from the `bare_metal.v2` view in the resource-pool
   projection, not from a capacity snapshot.
7. VM's held state copied defects the move must not carry: a whole-map reload on admin
   refresh and on the `site-projections` step that turns a stale site unknown (D3); a
   step that is not the timer's cycle (C2); a topology-error drift check of the
   capacity-bucket family only (D4); and an unused module-level
   `refresh_after_topology_error`.
8. VM verifies every site's responses against one shared `[provisioning.identity]` set,
   which breaches "Storefronts hold an exact principal per site authority" ("a principal
   registered for one site does not authenticate another"). Bare metal pins per site but
   holds one principal with no rotation set, short of "Site authority principals rotate
   with bounded overlap" (D14b).
9. With no listing `demands`, `escrow_shape_guard` skips its demand check and
   `validate_selected_escrow_plan` skips its arbiter check, while materialization uses
   the buyer's proposed demand. A bare-metal buyer could therefore propose an Alkahest
   escrow released by an arbiter of its choosing. Traced in code, not yet reproduced by a
   test (D14d).
10. `ROADMAP.md`'s Goal 4 gap row still assigns "VM keeps its own per-site projection
    cache" to `kit-owned-listing-and-fulfillment-lifecycles`. Owed at closeout.

## Decisions

### D0. A prerequisite carved out of the kit lifecycle change

Replacing VM's projection cache with kit-owned per-site state was an item of
`kit-owned-listing-and-fulfillment-lifecycles`, which waits on `kit-owned-storefront-shell`.
It needs neither, and Goal 7 needs it now, so it moved here. Rejected: a version watch
inside bare metal's publication, waking it on a resource-pool generation change while it
still fetched live; it would keep two projection routes and the live recheck and be
discarded when bare metal moved onto held projections.

### D1. Each dedicated storefront publishes its own domain

The VM storefront, alone or within the combined compute-family storefront, and the
bare-metal storefront each run their own domain's publication as a timer-driven loop.
The combined storefront keeps publishing VM only. Per-domain loops are interim: the
storefronts are converging on one compute storefront whose loops cover every listing
type, which is a future roadmap goal, not this change's. Rejected: bare-metal publication
inside the combined storefront, as a second loop or one loop over both domains; either
composes bare-metal publication into the VM shell, overlaps Goal 3 and
`market-platform-compute-40-multi-domain-proof`, and is scope this change does not take.

### D2. One injected state instance per storefront process

`kit/capacity-publication` gains `SiteProjectionState`, built once by the composition root
over its aggregate capacity client, with one resource-pool and one capacity-bucket cache
per configured site, held by VM's container and the bare-metal runtime and passed to every
consumer. Its constructor installs each site's topology-error handler and takes an
`on_resource_pool_change` callback, the publication wake. Tests build their own instance
over a fake aggregate. Its interface (settled in design review, 01 F5 and 02 F4):

```python
RESOURCE_POOL = "resource_pool"
CAPACITY_BUCKET = "capacity_bucket"

def values(self, family: str) -> Mapping[str, list[dict]]:
    """Site -> rows for every site holding a generation, stale included.
    A site holding none is absent; a loaded empty site maps to []."""
def view(self, site_id: str, family: str) -> ProjectionCacheView:
    """State, identity, value, last error, and last confirmation of one site's family."""
def status(self) -> dict[str, dict[str, ProjectionFamilyStatus]]
async def poll_once(self) -> None          # the poller's cycle; also the first load
async def refresh_site(self, site_id: str, *, families: Iterable[str] | None = None) -> None
async def run(self, *, interval: float, gate, wait) -> None
```

Publication reads `values()`, which deliberately includes stale generations; a source check
reads `view()` and confirms only from a `loaded` generation (D5). (Bare metal's publication
reads `view()` per site instead, stale included, for the generation's identity: D6, as
delivered for bare metal.) An unconfigured site given
to `view` or `refresh_site` raises the kit's `CapacityBindingError`, as
`CapacityRuntime.site_client` does; an unknown family raises `ValueError`. `refresh_site`
never raises for a failed fetch: the cache keeps its last generation as `stale` with its
error and does not advance its last confirmation.

The state runs one operation at a time on a site's family, its version check included (03 F3).
A poll arriving while one is in flight — the poller, the `site-projections` step, the admin
refresh route, a drift check — joins it and returns its result rather than polling again. A
refresh-and-reconcile caller (an inline refresh, D4) waits for the operation in flight and then
fetches, because it reconciles a change it has just made and needs a snapshot taken after that
change; adopting an earlier-started poll's result could miss it. Either way a failed operation
never replaces a confirmation that completed after it began. The fix belongs in core's
`ProjectionCache`, whose `poll_once` today checks the version outside its refresh lock, so
every user of the primitive gains it. Rejected: a kit module-level registry, a process
global that contradicts the instance-scoped loop controller and keeps the module patching
`TESTING.md` rules out; and an instance with a VM module facade, leaving two ways to reach
the state.

### D3. Refreshing every site keeps last-known generations

The state is built once and never replaced, and every refresh updates caches in place; a
site whose fetch fails keeps its last generation as `stale`. VM's admin route
`POST /api/v1/admin/capacity/projections/refresh` is a manual invocation of the poller's
cycle, `poll_once()`, run through the loop controller as the `site-projections` step runs
it: it does not wait for a timer's interval and runs whether or not the loops are held, but
a timer cycle already running finishes first and the route's cycle then polls for itself, so
its answer reflects a change its caller made before asking, and the controller records the
cycle's outcome. It keeps its wire contract and reports honestly (02 F4). A version poll observes every
change a forced snapshot would, because the resource-pool digest covers availability and
views, so the state carries no separate force-refresh operation. Bare metal gains no such
route. This closes the index's unowned item "the admin projection refresh … discards
last-known generations". Retiring the route belongs to `kit-owned-storefront-shell`, where
the question is recorded.

### D4. Every storefront holds both families; a topology error checks both

Every composition holds the resource-pool and capacity-bucket families for every site. A
verified topology-sensitive error triggers one coalesced drift check of every held family,
and never retries the request. Each refresh path belongs to one category (02 F4):

| Operation | Category | Wakes publication |
|---|---|---|
| Poller cycle, `site-projections` step, VM admin refresh route | poll-and-notify | on a resource-pool change |
| Topology drift check | poll-and-notify | on a resource-pool change |
| Inline reconciliation (admin reserve, fulfillment event, failure release) | refresh-and-reconcile | never |
| Capacity-event reconciliation (the event's site's capacity-bucket family; every site's for a full reconcile) | refresh-and-reconcile | never |
| Override write | refresh-and-wake | always, through the override service's hook |

A capacity event's reconciliation judges a fungible listing's availability on its site's capacity
buckets, which move with the event, so it refreshes that family first rather than reconcile over
the last poll's generation; the delta carries no bucket counts, and waiting for the next poll would
leave a reservation's listing open for up to a poll interval (decided 2026-10-16, review 06 F2;
rejected: capacity events advisory until the next poll, which the normative "close-before-reopen
over availability-backed listings" does not allow). A wake never advances a held loop: a held
publication loop stays held, and the wake makes it run promptly once resumed. A failed refresh in any category keeps the site's previous
generation as `stale` with its error and never counts as a confirmation. The compute storefront will eventually pull every
resource pool once for all listing types, so one uniform state is the shape to refactor
from. Rejected: families chosen per composition (bare metal holding resource-pool only),
a parameter that loses its last caller when storefronts merge.

### D5. Bare metal checks generation trust when it reads

Bare-metal publication and the opening recheck run `trusted_bare_metal_projection` on the
held value they read. A refused generation holds the site's listings
(`site_projection_refused`) and makes an opening retryable, as a refused live fetch did.
The state stays domain-neutral and holds whatever generation a site serves. Rejected: a
domain `validate` hook on the shared state, which would derive from the previous
generation instead of holding and would freeze every listing type at that site on one
domain's rule; and a neutral check in the kit, which would interpret opaque
`publication_views`.

**Only a freshly confirmed generation confirms a source check (01 F4 / 02 F1).** A held
generation is in one of four conditions: none held, freshly confirmed, stale, or refused by
the reading domain. Freshly confirmed means `loaded` — the most recent poll succeeded — with a
last confirmation (`fetched_at`) no older than `[capacity].source_confirmation_seconds`, which
defaults to three times `[capacity].poll_interval` when not stated and which a lane or an
operator may widen (03 F1). A `loaded` generation older than that is stale for this purpose,
because a cache only becomes `stale` when a poll fails, and while no poll runs — the loops held
with trading live, or a poller that has exited or hung — it would otherwise stay `loaded`
indefinitely. Publication reads any held generation, stale included, because holding a site's
listings through an outage is its job. A listing-source check — before every seller decision
and every acceptance, in both domains — confirms a listing only when every projection family it
reads is freshly confirmed and accepted by its domain: bare metal's reads the resource-pool
family; VM's reads it and the capacity-bucket family its fungible availability uses (03 F2).
Every other condition refuses as retryable, and an exit is never checked. The bound on the
availability and provenance a source check relies on is therefore the confirmation window, and
an operator holding the loops restores freshness on demand by stepping `site-projections`. This closes VM's existing gap, whose check confirmed from any
held generation including for unbacked listings, which have no admission backstop. Refusing a
backed listing on stale data costs nothing in practice: a reservation that follows cannot
reach a site that cannot be polled. Rejected: accepting unbounded staleness as policy; a
configurable freshness window, a key an operator has no basis to tune; and bounding unbacked
listings only through a new backing-delegate operation. For elapsed time (03 F1), rejected: a
fixed multiple with no setting, which would stall every paused scenario until it steps the
poller; suspending the window while the poller is held, which reopens the gap for exactly the
operator who paused; and no window at all. For a check reading two families (03 F2), rejected:
dropping a stale bucket generation and computing availability from resource rows, which makes
the computation depend on freshness and the rule domain-specific.

### D6. A storefront that cannot publish refuses to start; loop state reaches status

A storefront that derives listings from site projections refuses to start when publishing is
impossible for the whole storefront (01 F2 / 02 F3): no registry to publish to, or a registry
without its authority pin; no enabled settlement mechanism, so no option can ever be built; and
no configured site or a site without exactly one service peer. A storefront that services existing deals only is
not supported. Settlement clauses and bare metal's lease bound are per-pool terms that a pool
override or a pool's hint may supply in place of the storefront-wide defaults, so an empty
`[pricing].settlements` or an absent `[pricing].default_max_duration_seconds` is not a
startup refusal: a pool that resolves no clauses or no lease bound from any tier is held and
reported in the per-site derivation status, as a pool override conflicting with
configuration already is. Each publication loop always runs and catches a failing cycle, as
VM's does. Rejected: requiring storefront-wide defaults, which refuses storefronts whose
terms live in their pools; and proving at startup that some source resolves clauses, which
makes startup depend on site availability.

Both storefronts' system status gains a `lifecycle` section: the loop controller's per-loop
states and publication's last cycle outcome. The kit controller gains an operation each loop
records its cycle's outcome through and a snapshot of states and last outcomes (02 F5):

- the controller's `run_cycle(name)` is the one place a cycle runs, under that loop's lock,
  recording its outcome in a `finally`; a loop registers its step and its interval, and the
  timer the controller starts is a gate, `run_cycle`, wait loop over the same operation, so the
  timer and an operator's step never run a cycle concurrently (03 F3); every VM, bare-metal, and
  API-credit loop moves onto it, replacing bare metal's `publication_lock` and giving VM's
  publication, and every other loop, the serialization it lacks, and the controller keeps no
  other way to run a loop (P1: the API-credit storefront shares the controller, so leaving its
  loops on self-gating tasks would keep a second loop form and the step-and-timer race; rejected,
  scoping the requirement to the compute storefronts and recording the gap); a held loop runs no timer cycles, so a step
  taken while held never waits. The per-site capacity-event pollers that
  `run_capacity_event_pollers` fans out are the one exception in shape: each site's feed
  cursor has its own lock, which the capacity-events step takes per site;
- each invocation, timer or step, records exactly one terminal outcome, including one that
  raised, naming the stage that failed (`compose`, `run`, or `converge`);
- a recorded error carries the exception's type, and its message only when the exception is
  one of the storefront's own configuration or publication errors, whose text names keys and
  reasons rather than values; full detail stays in the log, so a cycle's own outcome carries no
  credential, secret, or other value an unexpected exception's text may hold. (As amended on
  2026-10-18 with the owner, after Section 14's check: status and health do report site errors
  with their text, a site's URL included, for diagnosis -- the projection families'
  `last_error`, and a publication derivation's held site -- since site URLs are not
  sensitive; no credential can appear among them, because a site URL carrying credentials is
  refused when the configuration loads, `SiteAuthorityUrl`.)
- a preview records nothing;
- an exited or cancelled loop stays distinct from a running loop whose last cycle failed.

Bare-metal status also reports the latest per-site derivation summary, as VM's
`publication_derivation` does, so a refused generation and a pool held for missing terms are
visible.

Rejected: starting the bare-metal loop only when configured, with publication reported
unconfigured; and always starting a loop that fails every cycle.

**Decided with the owner, 2026-10-16 (round 05/06 triage):**

- *VM's registry switch is removed* (05 F3). `enable_registry_discovery` let VM start and publish
  nowhere, the unsupported deployment this decision refuses, so VM always publishes to every
  `[registry].urls` entry and checks the registry and its pin unconditionally. A configuration
  stating the key, whatever its value, refuses startup naming it removed, rather than ignoring
  it, so an operator who had turned publication off is not silently switched on. Rejected:
  writing an exemption for the switch into this decision and the delta.
- *Retired keys refuse under their own heading.* The startup refusal names a renamed or removed
  setting under "the storefront states retired settings", apart from "the storefront cannot
  publish", since a stale key is not a reason publication is impossible (05 F10).
- *Each capacity-event site poller records its own outcome* (06 F4). The kit's fan-out keeps
  each site's cycle under that site's cursor lock rather than the controller's, so each site's
  timer cycle reports to a recorder the controller provides under the site's loop name,
  `capacity_events_poller:<site>`, and status reports it; a failure is recorded by type unless
  disclosed, as every cycle's is. The aggregate `capacity-events` step keeps its own outcome, and
  the aggregate loop, which runs no cycle, records none. Rejected: narrowing the
  market-composition requirement to exempt the pollers. As revised on 2026-10-18 (08 F4, F5):
  each site's name is declared as the aggregate loop's child (`declare(name, parent=)`), so once
  the aggregate's task has ended the site reports its `exited` or `cancelled` state and a pause
  no longer waits for it; and the controller issues a recorder (`cycle_recorder`) only for a
  name so declared, never for a loop whose cycles it runs, replacing a `record_cycle` that wrote
  under any name.
- *The development release can start* (06 F1 / 05 F2). The charts' defaults enable no
  settlement mechanism, so a release from them alone is refused, as intended: Alkahest needs a
  chain and wallet a production release supplies. `helm/local-values.yaml`, which
  `make -C helm deploy-local` layers, repeats Bob's agent with Alkahest enabled on the Anvil
  chain the dev-env chart deploys, Bob's development wallet address (Anvil's deterministic
  account 2, its key in the out-of-band `arkhai-bob-runtime` overlay as before), and contact
  exchange with a development contact on a reserved domain. A render test runs the
  storefront's real startup refusal over that render's `storefront.json`, and over the defaults'
  to show it refuses them. Rejected: enabling a mechanism in the chart defaults. As revised on
  2026-10-18 (08 F1, F7):
  - *The local release mounts its address book.* The storefront chart gains a per-agent
    `alkahestAddressBook` (an existing ConfigMap mounted read-only, as the bare-metal chart's),
    and the dev-env chart, whose Anvil state the book describes, carries a copy of
    `kit/alkahest`'s development Anvil address book as a ConfigMap; `helm/local-values.yaml`
    mounts it and both address paths name the mounted file, so Bob's Alkahest listings derive
    their release conditions. The `STOREFRONT_PYTHON` render check derives them over the local
    render, not only the startup refusal. Rejected: the packaged copy's path inside the image's
    virtual environment, and a reserved name the kit resolves.
  - *The storefront chart's agents are keyed by name.* `storefront.agents` is a map from each
    agent's name to its entry rather than a list, because Helm merges maps key by key and
    replaces lists, so an overlay states only what it changes in one agent; a null removes a key
    or an agent. A list is refused by the values schema naming the map. The storefront subchart
    ships no default agent, since Helm cannot remove a subchart's default from a parent's values;
    the umbrella's values declare Bob. The bare-metal chart keeps its one agent's keys at its top
    level (C8). Rejected: a drift guard over the repeated agent, alone or before a separate
    change.

**As delivered for bare metal (Section 13).** Bare metal composes the state and its loops as
VM does, with these choices of its own:

- *The root builds the state and its wake.* `build_runtime_from_configuration` builds one
  `SiteProjectionState` over the sites' aggregate client, with the runtime's `PublicationWake`
  as `on_resource_pool_change`; the runtime holds both, and publication, the opening recheck,
  override status, and health read the state from it and call no site. The wake renews its
  `asyncio.Event` at each timer registration, as VM's `new_publication_wake` does, and an
  accepted override write sets it too.
- *Every loop on `register_loop`, its timer registered at startup.* Steps register when the
  runtime is built, so every route can run one, and timers when the server starts, after the
  first poll, as VM splits them. The poller takes VM's names, `site_projection_poller` on route
  `site-projections`; publication and the poller run their first cycle at once, the sweeps one
  interval later; `publication_lock` is gone, the controller's cycle lock serializing timer
  and step.
- *The loops stop at shutdown* (a divergence: VM's lifespan leaves its loops running until
  the process exits, and its tests stop them with `reset_for_tests`). Bare metal's stop hook
  cancels every timer and awaits its task, so no cycle is left running against a runtime its
  app has uninstalled, a test's lifespan tears down cleanly, and an app started again over the
  same runtime starts its loops afresh. It waits for the loops' tasks only: a publication
  cycle's worker thread stops through the kit's cycle driver on cancellation, which nothing
  here awaits. Whether VM adopts it is an open question below.
- *Disclosed errors* are bare metal's `BareMetalConfigurationError` and a new
  `BareMetalPublicationError` -- a cycle that cannot be composed, naming what is missing (the
  projection state, a registry, the settlement composition), answered as a 503 lifecycle route
  error -- with the capacity and domain-registration errors VM discloses.
- *Publication reads each site's held view*, value and identity together, for every site
  before anything is awaited, because a candidate carries the generation's revision and
  digest and `values()` gives rows alone; a site whose view holds no value is unknown.
- *The confirmation window is resolved once, at composition*
  (`[capacity].source_confirmation_seconds`, else three poll intervals), and carried on the
  runtime as bare metal's other intervals are, where VM reads it at each check; the recheck's
  clock is a runtime seam, as VM's `source_confirmation_clock` is.
- *The publish command loads its own state* with one poll before its cycle, since it composes
  a runtime in its own process until it becomes an API client (C1).

**As delivered for bare metal (Section 14).** Bare metal's system status reports `lifecycle`
in VM's shape (the controller's snapshot, each loop's state and last outcome) and
`publication_derivation`, with these choices of its own:

- *The derivation summary is the cycle report's, per site.* VM's `publication_derivation` names
  VM's own categories (unresolvable pools, regionless pools, infeasible shapes, ...); bare
  metal's reasons are its cycle report's, so each configured site maps to `holds`, `refusals`,
  and `reports`, each entry the report's site-scoped action without its action and site (a
  reason, the pool or Physical Resource where there is one, and its problems or error, a
  site's error text included). A site that derived cleanly is present with empty lists, so
  status tells it from a site no cycle has read; before any cycle the section is empty.
- *Only a cycle records it, and each cycle replaces it.* The publication step clears it as a
  cycle starts, and the cycle records it once its compose stage has read every site, so a
  cycle failing later in `run` or `converge` still reports what it derived and one failing
  before then, composing or reading, reports none; a preview neither clears nor records, as it
  records no outcome. So `publication_derivation` is always the derivation of the cycle whose
  outcome `lifecycle` last reports, or nothing. VM adopts the preview rule (decided with the
  owner, 2026-10-18, after Section 14's check): its dry run derives with `record_reports`
  false, so a preview publishes no report, and logs none of the warnings a changed report
  logs; its real cycles, source checks, and capacity-event reconciliation record as before
  (`arkhai-vms-listings` 0.6.0 threads `record_reports` through `available_compute_slices`,
  `current_available_resource_keys`, and `stale_open_listing_ids`, and returns each site's
  report to a caller through `reports`, which the dry run reads its regionless holds from).
- *A pool resolving no settlement clause is held at compose* (Section 14's check), as one
  resolving no lease bound is: its override's clauses, else `[pricing].settlements`, empty
  holds it as `pool_settlement_clauses_missing`, so the hold reaches the derivation instead of
  surfacing later as a payload refusal.
- *Both status readers receive them*, as VM's one status response carries them to the
  administrator and a site's service-role read alike; pool overrides and obligations waiting
  for an operator stay the administrator's alone.

**C1 as delivered (Section 14).** `bare-metal-storefront publish [--dry-run]
[--storefront-url | -a]` calls `admin_run_lifecycle_cycle("publication")` or
`admin_dry_run_lifecycle_cycle` through the canonical `SyncStorefrontClient`, signing as
`[Identity.principal]` with `ARKHAI_IDENTITY_CREDENTIAL` at `--storefront-url`, else the
configured `base_url`, through one administrator client it shares with `pool-override`
(`admin_cli`). It opens no database and loads no projection: the running storefront's cycle
runs over what its own poller holds. Divergences from VM's `market-storefront publish`: it
prints the cycle's report as JSON, as every other bare-metal command prints its result and as
the command printed it before, rather than VM's table, so a script reads it unchanged; and it
has `--abort-all` too, which seller-closes every open listing (decided with the owner,
2026-10-18 and 2026-10-19), with VM's semantics: through the storefront's seller close route,
and refused beside `--dry-run`, its output the closed listings' IDs as JSON. Bare metal gains
VM's two routes for it: `POST /api/v1/listings/{listing_id}/close`, seller-authenticated
(`close_listing`), and `POST /api/v1/listings/{listing_id}/resume`, administrator-authenticated
(`admin_resume_listing`), which clears the listing's pause and reopens a listing its seller
closed, republishes an open one, and refuses one reconciliation closed with a 409
`listing_closed_by_reconciliation`, as VM's does. Both are built from existing parts: the
capacity-publication kit's `PublicationRuntime.close(..., closed_by="seller")`, `reopen(...,
reopened_by="seller")`, and `publish`, over bare metal's existing `build_publication_runtime`,
`bare_metal_listing_binding`, and `bare_metal_publication_candidate`; core's
`CloseListingResponse` and `PauseListingResponse` and `set_listing_paused`; the route
authentication bare metal's other seller and administrator routes use; and the typed client's
`close_listing`, `resume_listing`, and `list_listings`. The only new bare-metal code is the
route glue (`listing_controls.py`) and a seller-role CLI client beside the administrator one.
The permanent "A seller's close is durable" already states the behaviour, so the delta is
unchanged. As VM's, a close the database cannot take (a lock another writer holds past the busy
timeout) answers 503 `listing_close_incomplete`, "The listing is unchanged; retry the close";
VM's resume has no such answer, so neither has bare metal's. Bare metal also serves VM's
`POST /api/v1/listings/{listing_id}/pause` (administrator, `admin_pause_listing`), over core's
`set_listing_paused`, so resume has a pause to clear: a paused listing stays open and
published, its negotiations refused, and a publication cycle neither clears the pause nor
sends it again (the pause is no publication input in either storefront).

Known limitations, shared with VM: resume loads the listing and then publishes it outside the
publication loop's cycle lock, so a cycle refreshing the same listing in between can leave a
registry holding the older payload until the source changes again, since registry
convergence compares publication status, not payload; and the close's
`listing_close_incomplete` says "unchanged" for any `OperationalError`, including one from
recording the registries' answers after the local close committed, where a retry, which is
idempotent, keeps the seller's close. `-a` is VM's short form of
`--storefront-url`, adopted by both bare-metal commands. A storefront refusal (a cycle it
cannot compose answers 503 naming what is missing) exits 1 with its message, as
`pool-override` does; and a request no storefront answers exits 1 naming the origin it was
sent to and the transport error's type, never a traceback, in both bare-metal commands and in
VM's `publish` and `pool-override`, which adopt it (decided with the owner, 2026-10-18). Each
domain states the rule in its own CLI helper (`admin_cli`, `cli_common`), since neither may
import the other and no kit carries CLI helpers.

**Decided with the owner, 2026-10-18 (round 10 triage, 10 F1).** The durations that read
through the shared type -- every bare-metal interval and timeout its typed settings declare
(`[capacity].poll_interval`, `publication_interval_seconds`, `source_confirmation_seconds`,
`negotiation_timeout_seconds`, `negotiation_watchdog_interval`,
`settlement_servicing_interval_seconds`, `payment_reconciliation_interval`), and VM's
`[capacity].poll_interval` and `source_confirmation_seconds` -- are positive, finite numbers of
seconds that can be applied to an instant without leaving `datetime`'s range: at most the span
from year 1 to the Unix epoch, about 1,969 years, so subtracting one from any instant after 1970
stays after year 1 and adding one to any instant before about 8030 stays before 9999. It is a
representability ceiling, not a policy maximum: a finite window or timeout above it started
cleanly and overflowed where it was applied, the window at the opening recheck and the timeout at
the watchdog's "now minus the timeout". A value below half a microsecond, which a `timedelta`
holds as zero, is refused too, so "positive" holds after conversion. The unstated window, three
poll intervals, is checked as well and refused by the interval's key, since an interval below the
ceiling can derive a window above it: bare metal refuses it when its `[capacity]` section loads,
VM when its startup reads the window. The rule is `kit/config`'s shared `PositiveSeconds`
(D14b's round-10 note says why it lives there). VM's `settlement_servicing_interval_seconds` and
its retention sweep interval were read without it, which this decision left; Section 15 converts
them (owner, 2026-10-19), each refused by its key (`[settlement_servicing_interval_seconds]`,
`[Settlement.contact.retention_sweep_interval_seconds]`), as the API-credit storefront reads its
renamed `settlement_servicing_interval_seconds`. Rejected: having the kit's `freshly_confirmed` treat an unrepresentable window as unconfirmed,
which would turn a configuration mistake into a retryable refusal of every round and need a kit
bump.

**Decided with the owner, 2026-10-19 (Section 15, the controller's loop forms).** Section 15's
plan removed the kit's `start_loop` and the step-only `register_step` "once no caller remains",
but both kept callers by design: `start_loop` was the only way to start the capacity-event
aggregate, the fan-out this decision keeps as the one exception in shape (VM and the API-credit
storefront), and `register_step` registers each loop's step before its timer, which VM (at
import), bare metal (when its runtime is built), and the API-credit storefront (when its
services start) do so every lifecycle route can run a step from the moment it is served. The
controller now has two registration forms and one start:

- `register_loop(name, *, step, interval_seconds, ...)`, a timer loop, as before;
- `register_fan_out(name, *, route, step, preview=None, run, children)`, a loop whose task (`run`)
  a kit runtime owns and which runs independent cycles in declared children. It registers the
  step half as `register_loop` does, and declares each name `children()` returns as the loop's
  child, with this loop as parent, when it registers and again when it starts, so status lists
  every site's poller before its first cycle; a child the task gates later still declares itself
  on use. A name registered as one form is refused as the other, and a running fan-out cannot be
  registered again, as `register_loop` refuses a running loop;
- `start_loops()` starts every registered timer and fan-out that has no task; an ended one keeps
  its handle and stays ended, `clear_loops` covers both, and `keep_registrations=False` forgets
  both.

`start_loop` (and VM's `start_registered_loop` wrapper) is gone. `register_step` stays as the step
half of a registration and runs no loop. VM and the API-credit storefront register their
capacity-event aggregate with `register_fan_out` beside their other loops and no longer start it
in a startup step of its own, so its start moved: VM's from just after the first projection load
to the last startup step with every other loop (no other step runs between them), and the
API-credit storefront's every loop, the sweeps included, to after the credits-service preflight
and the demo-listing seed, where the capacity poller already started (the sweeps' first cycles
are due one interval after their timers start, so only their timers moved). `arkhai-kit-storefront`
0.8.0. Rejected: (a) a fan-out-only `start_fan_out(name, task_factory)` beside `register_step`,
which keeps a second way to start a loop outside registration; (c) removing `register_step` too,
so each storefront registers a loop once with its interval, which would leave VM's routes no step
before startup and rework the registration split Sections 9 and 13 chose; (d) deferring the
removal and keeping `start_loop`.

**API-credit status reports `lifecycle`** (owner, 2026-10-19, Section 15). The API-credit
storefront's system status carries `lifecycle` in VM's and bare metal's shape (core's `LoopStatus`
over the controller's snapshot, keyed by loop name), and becomes the administrator's signed read,
as VM's and bare metal's are: before, it answered unauthenticated and unsigned, so the canonical
client could not read it, and it carries the storefront's principal and every loop's state.
Nothing in the repository read it unauthenticated (the lane's health checks use `/health`).

### D14. Bare-metal configuration follows the VM storefront's conventions

`DEPLOYMENT_AND_CONFIG.md` is correct, so the bare-metal storefront stops reading
application settings from the environment and its chart stops passing them as pod `env`.
Bare metal has never been deployed as a domain, so no compatibility of settings or
Secrets is owed. Accepted scope beyond the original proposal.

- The storefront reads `storefront.toml`, `storefront.json`, and `storefront.secrets.toml`
  through `kit/config`, over a packaged `settings.toml`, as VM does.
  `ARKHAI_IDENTITY_CREDENTIAL` arrives from its own Secret and is never loaded into
  settings.
- **D14a. Shared vocabulary.** A key VM already has is the key: `[Identity]`,
  `[Settlement]`, `[registry]`, `[capacity]`, `[pricing]`, `[negotiation]`, `[Delivery]`,
  `[Wallet]`, `[Chains]`, `base_url`, `db_path`, `negotiation_timeout_seconds`,
  `negotiation_watchdog_interval`. Where bare metal has a clear improvement, VM adopts it.
  A key with no VM counterpart is named for its concept, never the domain. Rejected: a
  `[bare_metal]` namespace, which the merge would have to unwind; and extracting the
  typed configuration models now, which comes later.

  As delivered (Section 11 and its check, decided by the owner's rule to follow VM unless
  bare metal is clearly better): the loader is VM's in shape as well as vocabulary. Its
  environment override layer has VM's prefix, `STOREFRONT_` with `__` between levels: the two
  storefronts never share a process, so one prefix states an override the same way for
  either, and the retired variables' own prefix (`BARE_METAL_STOREFRONT_`), still named in the
  chart and the documentation until Sections 16 and 17, is never read as a setting (rejected:
  a prefix of bare metal's own, which reinterpreted those variables -- a settlement or chains
  JSON string broke loading, and the image's database-path variable overrode `db_path`).
  Typed sections ignore a key they do not name, as VM's loader does, so an older release
  still starts on configuration a newer one wrote (C4's rollback note depends on that);
  refusing a misspelled key is the generated values schema's (D14c, Section 16), not
  startup's (rejected: typed sections refusing unknown keys). The packaged `settings.toml`
  is the one statement of each default: a runtime composed without configuration files, as
  a test composes one, takes its intervals from it. The startup refusal (D6) refuses a site
  bound to no service peer or to several from Section 11, ahead of durable trust, because
  Section 11's site clients take each site's principal from its configured peer.
  `[pricing].settlements` compile when the storefront starts, so a clause that cannot be read
  refuses startup naming the key; an empty list is still not a refusal. The image sets no
  application setting: its database path is the packaged relative `db_path`, under the
  image's working directory, the data volume.
- **D14b. Per-site trust from the site's durable service peer, in both storefronts.** Each
  configured site is bound to exactly one `[Identity.service_peers.<peer>]`; startup refuses a
  site with no peer or more than one. Configuration seeds the peer: once initialized,
  its principals are the durable identity state's, rotated through the two-proof rotation
  route, as "Storefront authorization bindings are durable" requires, and configuration must
  keep covering them. Startup refuses a seeded peer whose configuration no longer names its
  durable primary and every principal active in an overlap ("Startup configuration is stale
  during rotation"), so after a rotation the storefront restarts only once configuration
  names the replacement; a rotation reaches verification when it commits, not at a restart. A site's client verifies
  responses against that peer's currently active principals (`active_principals(now)`),
  obtained at verification time through a provider `kit/site-client` accepts in place of a
  fixed `TrustedIdentitySet` — the same set callbacks are checked against (01 F1). Bare metal
  adopts core's durable service-peer state for its sites. A bare-metal reservation pins its
  site's peer subject; the principal recorded on it is an audit record, so a restart after an
  authorized rotation keeps its reservations. Bare metal has never been deployed outside the
  development cluster, so these schema changes are written as fresh schema with no upgrade or
  backfill logic. VM gains per-site pinning; bare metal gains rotation; site URLs are public configuration as
  VM's are. Bare metal's administrators stay on configuration. As delivered (Section 10 and its
  round 05/06 and round 08 fixes): every client that talks to a site authority -- VM's capacity
  clients and its per-site fulfillment clients alike -- verifies against that site's peer through
  one `ServicePeerTrust` (05 F1; the plan's 10.2 first left the per-site fulfillment clients on
  `[provisioning.identity]`, which this decision does not allow). VM's early lease termination,
  the plumbing `vm-storefront-fulfillment` keeps for a future buyer-requested termination (the
  buyer asks the storefront, which asks the site), goes through the per-site fulfillment client
  to the site the reservation is recorded at, as bare metal's does, so it too verifies against
  that site's peer; it was the last reader of `[provisioning.identity]`, which is retired: the
  storefront refuses to start on it, the values schema and `market-storefront config set` refuse
  it, and the chart's check of the release's provisioning principal is on the site's service peer
  alone (decided with the owner 2026-10-18, 08 F2; rejected: deleting the termination plumbing,
  which the permanent spec keeps). A reload of the trust that fails after a change committed
  never fails or masks the change (05 F4): the trust drops the records it held, which predate
  the change, so every read refuses with 503 from memory and none retries SQLite on the event
  loop, and a background reload retries off the loop, waiting longer after each failure, until
  one succeeds. Its reloads take one lock and read durable state while holding it, so a slower
  reload never installs an older load (decided with the owner 2026-10-18, 08 F6; rejected: a
  stale flag that retried the read on the caller's thread at every verification, which 10.13
  first delivered). Rejected: configuration as the
  response trust set, which splits response and callback trust on every rotation and makes a
  rotation reach responses only through a configuration change and a restart, where durable
  trust reaches them as it commits and needs configuration to name the replacement only before
  the next restart; durable trust for VM only; and a new per-site table renaming VM's keys.

  As delivered for bare metal (Section 12 and its check):
  - *The site binding names the peer, and a reservation pins it.* A bare-metal site binding
    carries its service peer's ID, not a principal, and both of the site's clients verify
    against the trust's provider. A reservation's durable site binding records the peer
    subject, and the principal beside it, the peer's primary when the reservation was made, is
    an audit record never compared. The table is fresh schema (migration 0004 edited in place,
    the owner's rule for bare metal); a database whose table predates the peer column is
    refused at every start by a structural check (migration 0014), naming the reset remedy in
    `docs/bare-metal-seller-quickstart.md`, as migration 0009 refuses the retired listing kind.
    It is a refusal, not an upgrade: the old rows cannot be rebound to a peer without guessing.
  - *Seeding at the server's start, as VM seeds* (revised with the owner, 2026-10-18, after
    Section 14's check). Section 12 seeded at composition, because the in-process `publish`
    read the sites through the trust; once `publish` became an API client, the one command
    composing a runtime, `redeliver-introduction`, reads no site and runs over a database the
    server has seeded. The root builds the trust unseeded, and the server's start hook seeds
    each peer, one at a time so a refusal names it, and loads the trust before the escrow
    backfill and the first projection poll, so no site is called before the trust holds its
    peer.
  - *The service-role status read accepts every configured site's peer* (a divergence found
    in Section 12's check; VM adopts bare metal's rule). The read names no site and returns
    readiness alone, so VM's rule -- exactly one configured peer, else 503 -- answered 503 to
    every site's readiness probe on any multi-site VM storefront. Both storefronts now verify
    it against the union of every configured site's active principals, skipping a site the
    trust cannot answer for, and refuse it as unavailable only when the trust can answer for
    none. A callback names one site and is verified against that site's peer alone, refused
    with the trust's own reason when the site has none.
  - *Bare metal serves VM's identity routes* (rotation, retirement, status), committing through
    the trust. Its administrators are configuration and never a durable subject, so an
    administrator rotation is refused there as not registered.

  **Decided with the owner, 2026-10-18 (round 10 triage, 10 F2).** A site's authority URL is an
  HTTP(S) origin in both storefronts, and VM adopts bare metal's rule, the better one: an `http`
  or `https` scheme, a host, a port (if stated) that parses as a number, and no credentials, query,
  fragment, or path other than `/`, read without surrounding whitespace or a trailing `/`. A
  site's clients join their routes to the URL, so a path became a prefix of every route and
  failed only at the first poll; VM had checked only that a URL was non-empty, and bare metal's
  check, which already refused credentials, a query, and a fragment, accepted a path and a port
  that is not a number. A refusal names the site's key and carries no URL, in its message or its
  exception chain. Both shared rules, this one and the duration (D6's round-10 note), are Pydantic
  annotated types in `kit/config`,
  `SiteAuthorityUrl` and `PositiveSeconds`, each over a plain function. The origin rule's
  placement rests on one rule shared by both storefronts with no dependency from one domain to
  another; the duration's also lets a values schema generated from a typed model carry its bounds,
  which the origin's does not (its JSON schema is a string, with no pattern). Bare metal's
  `[capacity].sites` is a `dict[str, str]`, so the origin rule runs in `parse_site_bindings`,
  through the plain function so the refusal names the site, and a bad URL is refused by key when
  the pod starts, not at `helm install`; VM's untyped `[capacity]` validates each URL through a
  `TypeAdapter`. Rejected: a local copy of the rule in VM, which drifts; and the types staying in
  the bare-metal storefront for VM to import, a dependency between two domains.

  *An established parser, not our own* (owner, 2026-10-18, a follow-up to the round-10 check).
  The origin rule parses the URL with pydantic's `AnyHttpUrl`, which follows the WHATWG URL
  standard through pydantic-core, in place of the hand-written host, port, whitespace, and
  control-character parsing the round's check had first added. The one local rule is the origin
  policy on top of the parsed URL: path `/` or empty, no query, no fragment, no username or
  password; the scheme being `http` or `https` is the parser's. The value handed on is the
  library's normalized origin without its trailing `/` (scheme and host lowercased, an
  international host as punycode, a default port omitted), and the storefronts give that value
  to their site clients. The boundary is parse versus existence: the parser decides syntax, so a
  host the standard accepts but nothing resolves (`-`, `site-a;x`, `%41`, which it reads as `a`)
  is accepted and fails as unreachable at the first poll, and port 0, which the standard allows,
  is accepted. One guard precedes the parse, a check rather than a parser: an ASCII control
  character (U+0000 to U+001F, U+007F) anywhere in the value is refused, because the standard
  would rewrite the URL rather than refuse it -- it drops a tab or newline inside the URL and C0
  controls at its ends, so `http://si<TAB>te` would bind to `http://site`. The guard reads the
  value as stated, its ends included, before anything strips it; a plain surrounding space is
  left for the parser to drop (corrected in round 12, 12 F3: the guard had read the stripped
  value, so a leading tab or a trailing `\n` or `\r\n` was dropped, not refused). Empty credentials
  (`http://@a`, `http://:@a`) are dropped by the parser and accepted as `http://a`, which loses
  nothing. A refusal's reason is built from the parser's error type and fixed text, never its
  message, which keeps the input. Rejected: our own parser, which every edge case the standard
  already settles had to be written and tested again. The owner's standing rule: prefer an
  established parser or validator over writing one, weighed against how heavy the library is to
  import; pydantic is already a `kit/config` dependency, so here the cost is nil.
- **D14c. The values-schema generator moves to `kit/config`.** The generic generator
  (field publicizing, secret refusal, sink typing, render, drift check) leaves
  `market_storefront.values_schema`; each storefront keeps only its section list, passes
  its discovered sinks in so the kit takes no `kit/delivery` dependency, and writes only
  its own chart's schema with its own drift test. Rejected: one definition generated by
  VM and written into the bare-metal chart, because a domain's tooling writing another
  domain's artifact is an architecture violation in spirit even where the import rules
  permit it; and a bare-metal copy of the generator.
- **D14d. Alkahest demands are the mechanism's, for every domain.** A listing's `demands`
  are its advertised Alkahest release conditions. Their derivation from
  `[Settlement.alkahest]` (the recipient arbiter paying the seller wallet by default,
  `oracle_gated`'s trusted-oracle arbiter, `interruptible`'s splitter) moves from VM's
  `publication_terms` into `kit/alkahest`, built with the Alkahest publication option for
  every domain. Each domain's Alkahest seller stage declares the release models it can
  deliver, and startup refuses a configured model the domain cannot (bare metal refuses
  `interruptible`, tied to VM's spot listing shape). The invariant holds where the plan is
  materialized and validated in `kit/alkahest`, independently of any seller policy (02 F2):
  every published Alkahest option has an authorized release condition for its chain; a buyer
  cannot select an absent or different one; a selection matches the advertised arbiter and
  its demand data, so a substituted recipient is refused; the materialized obligation uses
  exactly the authorized condition; and a missing or invalid advertised condition fails
  closed before any obligation is accepted. `escrow_shape_guard` stays as the early,
  explained rejection, and fails closed on a listing advertising none. Tests reproduce
  correction 9 through each domain's seller negotiation runtime and plan materialization
  before the fix and prove it closed. `BARE_METAL_STOREFRONT_DEMANDS` goes. Rejected: dropping
  demands for bare metal (keeps the unchecked arbiter), copying VM's derivation, a configured
  raw list, a guard-only fix, and a separate change for the fix.

  As delivered (Section 6), "built with the Alkahest publication option" is one kit function,
  `market_alkahest.release_conditions`, that each domain's publication calls where it builds
  the listing, not an output of the option builder: VM derives a listing's `demands` into its
  create request before its options are built, and its refresh compares them there, so a
  builder output VM ignored would be a second derivation path. Each domain's input is the
  chains its Alkahest publication names: VM's compiled clauses, which keeps its output
  unchanged; bare metal's Alkahest options as built; and API credits' accepted escrows that
  survive the backing filter, its Alkahest publication form, whether its clauses built them or
  its caller supplied them (an escrow on a chain the storefront does not configure is refused).
  VM can therefore advertise a condition for a chain whose option readiness suppressed; that
  condition authorizes nothing, because no option exists to select. The API-credit storefront
  delivers `recipient` only and bare metal `recipient` and `oracle_gated`; each storefront
  refuses another configured model at startup, naming it, before it opens its database (VM
  and API credits check first in their service composition; bare metal at its settlement
  composition, which precedes its database). A section stating both the oracle-gated and the interruptible model
  refuses startup in every storefront composing Alkahest, VM included, enabled or not, since
  one escrow has one arbiter.

  As delivered (Section 7), and as the owner decided on 2026-10-16 (task 7.6), the invariant is
  enforced inside `kit/alkahest`, so no caller can skip it. `market_alkahest.release_authorization`
  reads what a listing authorizes: a selected condition is kept only when its arbiter and demand
  data equal one the listing advertises on the proposal's chain (addresses compared
  case-insensitively, and replaced by the listing's form), a proposal selecting none takes the
  listing's first condition on the chain, and a listing advertising none there, or demands that
  cannot be read, raise `ReleaseConditionError` (`release_condition_not_authorized`,
  `_not_advertised`, `_unreadable`; `_ambiguous` for a proposal selecting several). The
  proposal's escrow address plays no part, so an unpinned (zero-address) proposal the shape guard
  skips is held all the same. Every kit entry point that encodes an obligation's release
  condition from a proposal takes the listing and authorizes it itself:
  `materialize_escrow_terms_from_proposal` and its payload form,
  `materialize_settlement_plan_from_proposal` and `settlement_plan_payload_from_proposal`,
  `accepted_escrow_artifacts_from_proposal` (which records the authorized proposal as the accepted
  one), and `verify_escrow_for_settlement`, which materializes the expected obligation against
  the listing it is given. Encoding one condition is private to `alkahest.py`, reached only
  through `encode_authorized_release_condition(listing, …)`, so there is no public way to encode
  a condition a listing does not authorize from a proposal. The recipient condition legacy
  verification expects for a thread with no proposal is built by a function private to
  verification. The recipient-arbiter fallback is gone, an `arbiter`
  or `demand` among the escrow's fields is overwritten, an authorized condition the chain's address
  book or codec cannot encode is `_unreadable`, and `accepted_escrow_artifacts_from_proposal`
  raises rather than recording a refusal beside artifacts with no plan. `seller_wallet_address`
  left these signatures, since nothing read it.

  The plan builders' signatures take the listing: VM's Alkahest seller stage builds its proposal
  from the listing entry (`escrow_proposal_from_accepted_entry`, carrying a condition the
  buyer's proposal selects so a substituted one is refused) and binds the listing to its plan
  builder, as its settle path binds the stored listing when it rebuilds the plan; bare metal's
  plan builder receives the listing record; the API-credit storefront's accepted-artifacts builder
  passes its listing. The call-site authorization each domain carried goes, except bare metal's
  at the opening, which pins the authorized proposal on the thread and refuses an unauthorized
  selection at the opening whatever the policy decides. Every refusal is the round's 409 with the
  `release_condition_*` reason, and nothing is recorded. Seller verification re-materializes
  against the listing as stored when it runs, so a listing whose conditions changed after
  acceptance fails it closed; a legacy thread with no proposal is verified against a recipient
  condition paying the seller's wallet, without the listing. VM's refund reads the token and
  amount from the accepted plan's obligation and materializes nothing, so a changed listing does
  not block it. On the buyer side the check is narrower than the seller's. The core buyer's
  orchestration creates the escrow from the seller's accepted escrow terms when the response
  carries them, checking them against nothing here; only the VM buyer's selection path checks the
  seller's plan against the listing first (`validate_selected_escrow_plan`), and the API-credit
  buyer and VM's proposal path do not. Where the response carries no terms, the orchestration
  passes the selected listing to the domain's escrow-terms builder, which materializes the
  accepted proposal under the condition the listing authorizes. A resumed run whose run-log
  records the seller's accepted proposal but no accepted escrow terms has no listing to authorize
  against and refuses by name (`escrow_release_condition_missing`). Rejected: authorization at each
  storefront's acceptance boundary through `authorize_escrow_proposal`, with materialization
  refusing only a proposal selecting no condition, which Section 7 first delivered, because a rule
  each caller must remember is how correction 9 opened: a later acceptance path that skips the
  call is unguarded.

  `validate_selected_escrow_plan` (the VM buyer's check of a seller's plan) compares the demand
  bytes as well as the arbiter, through the chain's address book the buyer configures, and refuses
  a listing advertising no condition. `escrow_shape_guard` rejects a listing advertising no
  condition on the proposal's chain (`release_condition_not_advertised`) and
  `accept_exact_listing` likewise (`exact_listing:release_condition_not_advertised`). The guard
  still passes a proposal carrying no escrow address or the zero placeholder, and a listing
  accepting no escrow; `accept_exact_listing` rejects those as
  `exact_listing:escrow_not_in_accepted_set`, as it did before.

  An empty seller wallet (Section 6's handoff) needs no rule of its own: a recipient condition
  with an empty recipient cannot be encoded, so materialization refuses it as
  `release_condition_unreadable` and no obligation is accepted. Derivation still emits it, so
  such a storefront publishes listings no deal can be accepted on; refusing the empty wallet
  at startup or publication is open for the owner, beside Section 6's oracle-gated startup
  question.

### Consequences and conventions

- **C1. The bare-metal `publish` command is an API client.** It calls the administrator
  `run-cycle` and `dry-run` routes through the canonical `StorefrontClient`, signing as
  the storefront's identity, read with `pool-override`'s from the configuration files.
- **C2. The `site-projections` step is the timer's cycle** in both storefronts:
  `poll_once()` and `status()`.
- **C3. The accepted-generation table is frozen** under `DEPLOYMENT_AND_CONFIG.md`'s rule:
  fresh databases stop creating it, migration `bare-metal-storefront-0011` leaves the chain
  with its ID retired, and nothing reads or writes it. Override status reads
  `values(RESOURCE_POOL)`. Rejected: dropping it by migration, as `0010` did before
  deployment; the documented rule needs no destructive step.
- **C4. Intervals use VM's keys and defaults.** `[capacity].poll_interval = 5`,
  `[capacity].publication_interval_seconds = 30`, `negotiation_watchdog_interval`,
  `negotiation_timeout_seconds`. Settlement servicing uses bare metal's clearer
  `settlement_servicing_interval_seconds`, which VM and the API-credit storefront adopt in place
  of `claims_sweep_interval` (P2: both feed the same kit servicing worker, so one name holds in
  every storefront; the API-credit chart has no generated schema, so its startup refusal is the
  guard there; rejected, leaving the API-credit storefront on the old key). Payment reconciliation, with no VM key, uses
  `payment_reconciliation_interval`. A storefront whose configuration states
  `claims_sweep_interval` refuses to start, naming its replacement, and the generated values
  schema refuses it in an agent's `config`; `DEPLOYMENT_AND_CONFIG.md`'s rollback note says an
  older release ignores the new key and services at its 30-second default (01 F3). Rejected:
  an alias for a transition, which needs a removal owner, and naming the old key while
  ignoring it, which drops a customized cadence silently.

  **Two homes for retired keys** (decided in Section 10, 10.3). A key of the storefront's own
  configuration that it no longer reads is retired in the storefront's catalogue
  (`market_storefront.retired_settings`: the local-inventory keys, the renamed
  `claims_sweep_interval`, the removed `enable_registry_discovery`), which the generated values
  schema refuses in any spelling, `market-storefront config set` refuses to write naming what
  replaces it, and startup refuses for a renamed or removed key (the inventory keys, which nothing
  replaces, do not refuse startup). The chart's hand-written `config.allOf` block holds only the
  chart's own retired values shape, the pre-0.2.0 keys. One catalogue serves the three refusals,
  so they cannot drift (05 F9 found `config set` keeping a third list).
- **C5. Bare-metal status reads held state.** `/health`'s `site_projections` comes from
  `status()` for both families and calls no site.
- **C6. Bare-metal scenarios hold the loops** through an opt-in per-module fixture resumed
  in a finaliser, and step `site-projections` wherever a site changed before stepping
  publication.
- **C7. The capacity-released callback does not refresh projections.** VM refreshes inline
  only where it reconciles inline; bare metal's callback and administrator reserve do not.
- **C8. The bare-metal chart copies the storefront chart's agent shape**, as one agent's
  keys at the top level: `config` rendered unchanged into `storefront.json`, the Secret
  overlay, the credential Secret, `XDG_CONFIG_HOME`, and only release-known derivations.
  It validates no service semantics; the storefront's startup refusal does (D6).

  As delivered (Section 16), with these choices of the chart's own:
  - *Values.* `port`, `service.type`, `identity.credentialSecret`, `secret` (an existing
    Secret's `secretName` and `configKey`, mounted as `storefront.secrets.toml`; the chart
    renders none, so the storefront chart's `createSecret` and `registryAuthToken` have no
    counterpart, bare metal reading no registry write token), `alkahestAddressBook`,
    `config`, persistence, and scheduling. `alkahestAddressBook` stays although 16.2's list
    of values to go named it: the storefront chart's agent gained the same mount in round 08
    (10.20), so the agent shape carries it. The schema's closed top level refuses every
    retired value, naming it.
  - *Derivations: what the release knows, as VM's chart derives them* (amended after
    Section 16's check, following the permanent "A storefront chart passes service
    configuration through"). Always: `port`, a different stated value refused in any
    spelling; `base_url`, the Service's URL (`http://<fullname>:<port>`, bare metal's form,
    no trailing `/`); and `db_path` under `persistence.mountPath`, both only where unstated.
    In an umbrella release, whose `global.registry`/`global.registryIdentity` and
    `global.provisioning`/`global.provisioningIdentity` the chart reads: the internal
    registry's URL as `[registry].urls`, with the operator's chart-level
    `internalRegistryTrust` written under it (required there, checked against the release's
    registry identity, refused beside `registry.urls`), and `[capacity.sites]` as
    `{default: <provisioning URL>}`, each only where `config` states none; every site bound to
    the release's provisioning service must have a role-`service` peer naming
    `global.provisioningIdentity`, which the chart checks and never adds (the spec: "the
    chart MUST NOT add a principal to a trust list"); the umbrella's values state the
    release's development registry trust and that peer for the bare-metal role, as for Bob.
    Installed alone, with no globals, only the first three are derived, and
    `internalRegistryTrust` is refused. A key stated in two spellings is refused at render,
    as VM's chart refuses one. No `provisioning.service_url`: bare metal reads none.
  - *The port is a setting.* Bare metal reads VM's `port` (packaged default 8000), `serve
    --port` overriding it, and the image's command is `serve`: the deployment-state rule lets
    nothing but the configuration directory and the credential travel outside the
    configuration system, and a `--port` argument would.
  - *Service links are off* (`enableServiceLinks: false`), as Section 11's handoff asked:
    Kubernetes would otherwise inject variables for every Service in the namespace, and a
    Service named `storefront…` would land in the `STOREFRONT_` override layer. VM's chart
    adopts it (Section 16's check), its loader reading the same prefix.
  - *The generated definition is the whole document, closed* (a divergence from VM's open
    root, which VM keeps because it reads sections untyped): every setting bare metal reads
    is typed, so the definition is its settings model's, each section's JSON Schema closed
    (`_Section`'s `json_schema_extra`) while the loader still ignores an unknown key (D14a),
    with `[Settlement]` and `[Delivery]` typed by the kits' fragments. No retired keys: bare
    metal had no file configuration before. `[Delivery]`'s own three settings are stated a
    second time beside VM's. Each storefront's test holds its copy's names to the kit's
    `RESERVED_SECTION_KEYS` and its fragments equal to the other chart's committed
    definition, read as a file so neither storefront imports the other; their natural home
    is `kit/delivery`, which both storefronts pin exactly, so moving them is left until that
    kit next changes. Consequence for rollback: the closed definition refuses at render a
    values file stating a key an older chart's schema does not know, so downgrading the
    chart with a newer values file (`helm upgrade` to the older chart with the newer values,
    or with `--reuse-values`) fails until the key is removed; `helm rollback`, which
    restores the older release's own values, is unaffected, and the storefront itself still
    starts on a newer configuration, its loader ignoring the key.
  - *Tier 2* (Validation tiers) runs the storefront's loader, startup refusal, clause
    compilation, and site binding over the example's rendered document through
    `BARE_METAL_STOREFRONT_PYTHON`, and the refusal over the chart defaults': it shows the
    rendered configuration is publishable, not that it starts, since the runtime's own
    composition also needs the signing credential owning the configured principal, the
    overlay's wallet key, a writable database, and chain clients.
- **C9. Compose and the lane mount files**, through a committed development
  `storefront.toml` for bare metal and a secrets file; only bare-metal targets produce
  bare-metal files. As delivered (Section 11): the secrets overlay is committed, a
  well-known development wallet key in `dev-env/identities/bare-metal.storefront.secrets.toml`,
  as VM's `bob.storefront.secrets.toml` is, rather than written by the lane at each run.
- **C10. Reconciled meanings.** Bare metal holds and reports a pool whose effective maximum
  lease duration, resolved through its override and then
  `[pricing].default_max_duration_seconds`, is absent or not positive; VM reads an absent or
  zero value as unlimited (03 F5). Bare metal publishes to every `[registry].urls` entry
  through the runtime's existing fan-out.
- **C11. Settlement and wallet use the shared files.** `[Settlement]` replaces the
  settlement JSON; `[Wallet].address`, `[Chains.<name>]`, and the overlay's wallet key
  replace their variables; the all-or-none Alkahest input rule keeps its refusal.
- **C12. Documentation** named in the proposal's permanent documentation impact.
- **C13. Several storefronts per registry, each in its own Helm release** (owner, 2026-10-19,
  round 12, 12 F1). The provisioning chart and service trust one storefront principal
  (`storefrontIdentity`, whose values schema allows exactly one principal) and call back one storefront
  (`storefront_url`), so a bare-metal storefront beside Bob on the umbrella's provisioning
  service would have its signed requests refused and its capacity-released callbacks sent to
  Bob. Options weighed: (a) a second provisioning instance inside the umbrella for bare
  metal; (b) a multi-storefront provisioning contract -- per-storefront authorization and
  reservation-scoped callbacks -- a separate change; (c) separate releases. The owner chose
  (c): several storefronts per registry is the topology supported and testable today, each
  storefront in its own release of the umbrella with its own provisioning service, publishing
  to one release's registry. Several sites per storefront is in progress (this change's
  per-site state); several storefronts per site is a later goal, which (b) would serve.
  Replacing the umbrella provisioning service's principal or callback with bare metal's was
  rejected: it breaks Bob.

  As delivered (16.7): release 1 is the umbrella as `deploy-local` installs it; release 2,
  `arkhai-bare-metal-seller`, is the same chart under `helm/bare-metal-release-values.yaml`,
  values only: the bare-metal storefront (Anvil account 8, principal, wallet, and
  administrator) and its own provisioning service (Anvil account 9), registry, VM storefront,
  dev-env, contract validation, and the e2e-tests chart disabled; `global.registry.host` names
  release 1's registry Service, whose principal the storefront's `internalRegistryTrust`
  pins, and the chain and Alkahest address book are release 1's dev-env. Release 2 reuses
  release 1's provisioning SSH and runtime Secrets and needs three of its own. One chart change
  (owner-accepted): the umbrella's smoke-test profile (`templates/tests/test-config.yaml`)
  applied its VM-agent requirement, provisioning-to-agent trust check, and agent-derived
  `seller` and `registry` sections whether or not the VM storefront was enabled, which no
  values could satisfy honestly in a release without it; they now apply only while
  `storefront.enabled`, and with the dedicated bare-metal storefront enabled instead the
  profile checks that provisioning trusts that storefront's `Identity.principal`. Release 1
  renders byte for byte as before. A release enabling both storefronts with the bare-metal
  storefront bound to the release's own provisioning service (its derived `default` site, or
  a stated site on that URL) is refused, naming the overlay and `make helm-topology-up`; bound
  only to sites of its own it renders (round 12's check). The bare-metal chart's own umbrella
  render tests and `test-render.sh`'s bare-metal renders therefore render a bare-metal-only
  release. `make helm-topology-up`, `helm-topology-down`, and
  `helm-topology-check` (over `helm/Makefile`'s `topology-*`) install, remove, and test the
  two releases. No end-to-end scenario needs release 2 yet; one that does states it on its
  Makefile target and in its suite module.

  After 16.5's run (owner decision (b), 2026-10-19; 16.8): `topology-up` restarts both
  releases' Deployments after its Helm upgrades -- the registry, then the provisioning
  services, then the storefronts, each `rollout restart` waited on with `rollout status` --
  because local images keep bare tags (a commit-hash tag changes when an image does not and
  can name an image the cluster lacks), so an upgrade leaves each pod template, and its
  pods' image, unchanged. dev-env is not restarted: a new Anvil has none of the release's
  contracts. The generated smoke profile carries what its hooks read and the release states:
  for the internal registry, `registry.authority_id` and `registry.identifier` from
  `global.registryIdentity` (not for a registry the agent names in `registry.urls`, which is
  not the release's); `buyer.wallet_address` from the e2e-tests chart's EIP-191 buyer
  identity; and `seller.wallet_address` from the target agent's `[Wallet].address`.
  `buyer.marketplace_credential` is a key, so no values carry it: the registry chart's
  `tests.credentialProfile` mounts a profile file from a pre-existing Secret into the
  registry smoke pod only, and `helm/local-values.yaml` names
  `arkhai-registry-smoke-credential`, which `topology-check` requires. The umbrella's global
  smoke Secret was not used: it mounts into every smoke pod of both releases and replaces the
  storefront smoke test's selected-agent fallback.

### Owner principles and where they go

- Storefronts converge on one compute storefront whose loops cover every listing type: a
  future `ROADMAP.md` goal, not promoted now.
- The compute storefront pulls every resource pool once for all listing types:
  `storefront-publication` ("Projection-backed listing candidate derivation").
- A storefront's configuration reaches it through its configuration system; a value travels
  outside it only when it controls which configuration is loaded or must be kept from the
  loader, and a chart knows a value only where the deployment needs it for a stated reason.
  This is configuration guidance, held by a compliance check, never a runtime refusal (03 F4):
  `deployment-state`, with the explanation in `DEPLOYMENT_AND_CONFIG.md` beside its pod rule;
  its check is `check-storefront-environment-reads`', which also owns the open question of how
  storefront signing material is resolved.
- A domain's tooling never writes another domain's artifact: `ARCHITECTURE.md`, as
  guidance no check enforces.
- A storefront that cannot publish is not a supported deployment: `storefront-publication`.

## Validation tiers

Chart work is validated in three tiers, as `docs/development/TESTING.md`'s "Chart Render
Tests" separates them (02 F6):

- render tests run `helm template` and need the Helm binary but no cluster;
- a real-loader check loads one rendered `storefront.json` with the bare-metal storefront's own
  configuration loader, as VM's chart test does through `STOREFRONT_PYTHON`, and needs
  neither; the bare-metal chart's plan requires it beside the render assertions, because a
  schema-generated configuration can render and still fail the loader;
- deployment and runtime debugging need a cluster, and run in a local session.

## Open questions

- *Should VM's storefront stop its loops at shutdown, as bare metal's does (D6, as delivered
  for bare metal)?* VM's stop hook clears the container's lifespan state while a loop may
  still be mid-cycle, so a cycle can run on against collaborators the lifespan has dropped;
  the alternative is the kit shell stopping a storefront's loops itself, for every storefront.
  Raised in Section 13; not prescribed by any task, so no task carries it, and it is the
  owner's to decide or defer to `kit-owned-storefront-shell`.

Otherwise none. A mechanical check that storefronts read no application settings from their
environment was decided against in this change and given a change of its own,
`check-storefront-environment-reads`, which carries the inventory taken in design review
(02 §8.1).
