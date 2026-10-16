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
reads `view()` and confirms only from a `loaded` generation (D5). An unconfigured site given
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
| Override write | refresh-and-wake | always, through the override service's hook |

A wake never advances a held loop: a held publication loop stays held, and the wake makes it
run promptly once resumed. A failed refresh in any category keeps the site's previous
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
without its authority pin (while VM's `enable_registry_discovery` is true); no enabled
settlement mechanism, so no option can ever be built; and, for bare metal, no configured site
or a site without exactly one service peer. A storefront that services existing deals only is
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
  reasons rather than values; full detail stays in the log, so no credential, secret, or
  private URL reaches status;
- a preview records nothing;
- an exited or cancelled loop stays distinct from a running loop whose last cycle failed.

Bare-metal status also reports the latest per-site derivation summary, as VM's
`publication_derivation` does, so a refused generation and a pool held for missing terms are
visible.

Rejected: starting the bare-metal loop only when configured, with publication reported
unconfigured; and always starting a loop that fails every cycle.

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
- **D14b. Per-site trust from the site's durable service peer, in both storefronts.** Each
  configured site is bound to exactly one `[Identity.service_peers.<peer>]`; startup refuses a
  site with no peer or more than one. Configuration only seeds the peer: once initialized,
  its principals are the durable identity state's, rotated through the two-proof rotation
  route, as "Storefront authorization bindings are durable" requires. A site's client verifies
  responses against that peer's currently active principals (`active_principals(now)`),
  obtained at verification time through a provider `kit/site-client` accepts in place of a
  fixed `TrustedIdentitySet` — the same set callbacks are checked against (01 F1). Bare metal
  adopts core's durable service-peer state for its sites. A bare-metal reservation pins its
  site's peer subject; the principal recorded on it is an audit record, so a restart after an
  authorized rotation keeps its reservations. Bare metal has never been deployed outside the
  development cluster, so these schema changes are written as fresh schema with no upgrade or
  backfill logic. `[provisioning.identity]` remains only for the provisioning service client.
  VM gains per-site pinning; bare metal gains rotation; site URLs are public configuration as
  VM's are. Bare metal's administrators stay on configuration. Rejected: configuration as the
  response trust set, which splits response and callback trust on every rotation and leaves
  bare-metal rotation blocking restarts; durable trust for VM only; and a new per-site table
  renaming VM's keys.
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
- **C9. Compose and the lane mount files**, through a committed development
  `storefront.toml` for bare metal and a secrets file; only bare-metal targets produce
  bare-metal files.
- **C10. Reconciled meanings.** Bare metal holds and reports a pool whose effective maximum
  lease duration, resolved through its override and then
  `[pricing].default_max_duration_seconds`, is absent or not positive; VM reads an absent or
  zero value as unlimited (03 F5). Bare metal publishes to every `[registry].urls` entry
  through the runtime's existing fan-out.
- **C11. Settlement and wallet use the shared files.** `[Settlement]` replaces the
  settlement JSON; `[Wallet].address`, `[Chains.<name>]`, and the overlay's wallet key
  replace their variables; the all-or-none Alkahest input rule keeps its refusal.
- **C12. Documentation** named in the proposal's permanent documentation impact.

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

None. A mechanical check that storefronts read no application settings from their environment
was decided against in this change and given a change of its own,
`check-storefront-environment-reads`, which carries the inventory taken in design review
(02 §8.1).
