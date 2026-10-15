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
consumer. Its operations: `view(site, family)`, `values(family)` (held sites only, `[]`
an authoritative empty), `status()`, `poll_once()` (the timer's cycle, also the first
load), `refresh_site(site, families=None)` (never raises), `refresh_all()`, and
`run(interval, gate, wait)`. Its constructor installs each site's topology-error handler
and takes an `on_resource_pool_change` callback, the publication wake. Tests build their
own instance over a fake aggregate. Rejected: a kit module-level registry, a process
global that contradicts the instance-scoped loop controller and keeps the module patching
`TESTING.md` rules out; and an instance with a VM module facade, leaving two ways to reach
the state.

### D3. Refreshing every site keeps last-known generations

`refresh_all()` force-refreshes every cache in place; a site whose fetch fails keeps its
last generation as `stale`. VM's admin route `POST /api/v1/admin/capacity/projections/refresh`
keeps its wire contract and reports honestly. Bare metal gains no such route. This
closes the index's unowned item "the admin projection refresh … discards last-known
generations". Retiring the route belongs to `kit-owned-storefront-shell`, where the
question is recorded.

### D4. Every storefront holds both families; a topology error checks both

Every composition holds the resource-pool and capacity-bucket families for every site. A
verified topology-sensitive error triggers one coalesced drift check of every held family,
and never retries the request. A resource-pool identity change observed by the poller or
a drift check fires `on_resource_pool_change`; refreshes an operation runs itself (inline
reconciliation, an admin refresh) do not, and an accepted override write wakes
publication through its own hook. The compute storefront will eventually pull every
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

### D6. A storefront that cannot publish refuses to start; loop state reaches status

Both storefronts refuse to start unless publication is configured: bare metal requires
`[registry].urls` with matching `[registry.authorities]`, a non-empty
`[pricing].settlements`, a positive `[pricing].default_max_duration_seconds`, a settlement
composition, and at least one `[capacity.sites]` entry with exactly one service peer; VM
requires a non-empty `[pricing].settlements` and, while `enable_registry_discovery` is
true, registries. A storefront that services existing deals only is not supported. Each
publication loop then always runs and catches a failing cycle, as VM's does.

Both storefronts' system status gains a `lifecycle` section: the loop controller's
per-loop states and publication's last cycle outcome (finish time, outcome, error). The
kit controller gains an operation a loop records each cycle's outcome through and a
snapshot of states and last outcomes; the timer and the `run-cycle` step record through
the same call. Bare-metal status also reports the latest per-site derivation summary, as
VM's `publication_derivation` does, so a refused generation is visible.

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
- **D14b. Per-site trust from the site's service peer, in both storefronts.** A site's
  client trusts the principals of the one `[Identity.service_peers.<peer>]` bound to its
  `site_id`, the same set its callbacks are checked against. Startup refuses a site with
  no peer or more than one. `[provisioning.identity]` remains only for the provisioning
  service client. VM gains per-site pinning, bare metal gains rotation sets, and site URLs
  are public configuration as VM's are. Rejected: VM's shared set unchanged (a regression
  for bare metal), and a new per-site table renaming VM's keys.
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
  `interruptible`, tied to VM's spot listing shape). `escrow_shape_guard` fails closed: a
  proposal naming a demand against a listing advertising none is rejected. A test
  reproduces correction 9 before the fix and proves it closed. `BARE_METAL_STOREFRONT_DEMANDS`
  goes. Rejected: dropping demands for bare metal (keeps the unchecked arbiter), copying
  VM's derivation, a configured raw list, and a separate change for the fix.

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
  `settlement_servicing_interval_seconds`, which VM adopts in place of
  `claims_sweep_interval`. Payment reconciliation, with no VM key, uses
  `payment_reconciliation_interval`.
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
- **C10. Reconciled meanings.** Bare metal refuses a zero or absent
  `default_max_duration_seconds`, which VM reads as unlimited. Bare metal publishes to
  every `[registry].urls` entry through the runtime's existing fan-out.
- **C11. Settlement and wallet use the shared files.** `[Settlement]` replaces the
  settlement JSON; `[Wallet].address`, `[Chains.<name>]`, and the overlay's wallet key
  replace their variables; the all-or-none Alkahest input rule keeps its refusal.
- **C12. Documentation** named in the proposal's permanent documentation impact.

### Owner principles and where they go

- Storefronts converge on one compute storefront whose loops cover every listing type: a
  future `ROADMAP.md` goal, not promoted now.
- The compute storefront pulls every resource pool once for all listing types:
  `storefront-publication` ("Projection-backed listing candidate derivation").
- A storefront never reads application settings from its environment: already in
  `DEPLOYMENT_AND_CONFIG.md`; stated normatively in `deployment-state`.
- A domain's tooling never writes another domain's artifact: `ARCHITECTURE.md`, as
  guidance no check enforces.
- A storefront that cannot publish is not a supported deployment: `storefront-publication`.

## Validation constraint

Helm rendering, chart deployment, and their debugging need an environment with Helm and a
cluster; the cloud sessions this change is designed in have neither. Chart work is
validated in a local session.

## Open questions

1. **A mechanical check for environment reads.** Whether this change adds a compliance
   target, beside `make check-architecture`, that refuses a storefront package reading
   application settings directly from the environment (allowing the configuration
   loader, `ARKHAI_IDENTITY_CREDENTIAL`, and `XDG_CONFIG_HOME`). Revisit at the start of
   planning, before any task prescribes one; the API-credit storefront's own reads must
   be inventoried first, since a repository-wide check would either cover or exempt it.
