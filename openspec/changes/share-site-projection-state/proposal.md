## Why

The two compute storefronts read their sites' resource-pool projections by two routes.
The VM storefront holds each site's projections in a process-global module of its own,
polls them, wakes its publication loop when a site's resource-pool generation changes, and
publishes on a timer. The bare-metal storefront holds nothing: its publication fetches
every site live on each run, its opening recheck fetches the listing's site live on each
opening, and its publication runs only when an operator invokes it.

That difference blocks Goal 7. `unbacked-bare-metal-listings` publishes bare-metal listings
that are never judged against availability, so source reconciliation is the only
reconciliation they get; while bare-metal publication runs only on an operator's command, an
unbacked listing whose pool is withdrawn stays advertised until someone runs it. And because
the recheck fetches live, every bare-metal opening depends on its site being reachable.

Holding projections is the agreed end state for every storefront
(`resolve-compute-family-findings`), and moving VM's projection state into the kit was an
item of `kit-owned-listing-and-fulfillment-lifecycles`, which waits on the storefront shell.
The item needs neither, so it is carved out here as `unbacked-bare-metal-listings`'
prerequisite.

Doing so exposed three further gaps this change also closes. The bare-metal storefront reads
its settings from environment variables and its chart passes them as pod `env`, contrary to
`docs/development/DEPLOYMENT_AND_CONFIG.md`. VM verifies every site's responses against one
shared principal set, contrary to "Storefronts hold an exact principal per site authority",
while bare metal pins per site without a rotation set. And bare-metal listings advertise no
Alkahest release conditions, which leaves the seller's escrow-shape guard accepting a
buyer-chosen arbiter unchecked.

## What Changes

- **Shared projection state.** `kit/capacity-publication` owns per-site projection state: one
  instance per storefront process over its aggregate capacity client, holding both
  projection families for every configured site, with its poller as a lifecycle loop, the
  publication wake on a resource-pool generation change seen by a poll or a drift check,
  per-site refresh and the poller's cycle on demand (VM's admin refresh route), both in place
  and keeping a failing site's last generation, a drift check of every family on a topology
  error, and a per-site status. VM's
  `site_projection_cache` is reduced to VM's `listing_cardinality_mode` explanations and its
  consumers take the injected instance. The `site-projections` step is the timer's cycle.
- **Bare metal on held projections and a loop.** Bare-metal publication derives from the held
  projections, checks generation trust when it reads, runs as a timer-driven loop on the
  storefront's controller (held, stepped, and previewed), and holds a site whose projection is
  not held. The opening recheck reads the held projection. In both domains a listing-source
  check confirms a listing only when every projection family it reads was confirmed by a poll
  within `[capacity].source_confirmation_seconds` (three poll intervals unless stated), so a
  stale or expired one refuses as retryable while publication keeps holding through it. The
  state runs one operation at a time on a site's family, so a failed refresh never overwrites
  a newer confirmation. Override writes refresh the site's
  held projection and wake the loop; override status reads the held projection, and the
  durable accepted-generation table is frozen. The `publish` command becomes an API client.
- **Startup refusal and loop status.** Both storefronts refuse to start when publishing is
  impossible for the whole storefront (no registry or authority pin, no enabled settlement
  mechanism, no site or a site without exactly one service peer). VM no longer has a switch to
  publish to no registry: a configuration stating `enable_registry_discovery`, whatever its
  value, refuses to start naming it removed, as one stating `[provisioning.identity]` does, and
  both refusals are reported under their own heading apart from publication's. Clauses and lease
  bounds stay per-pool terms, a pool resolving none being held and reported (in bare metal, also one with
  no positive maximum lease duration). Both report each loop's state
  and publication's last cycle in system status; the loop controller serializes each loop's
  timer cycle and step through one `run_cycle` boundary, for every storefront's loops, the
  API-credit storefront's included, and records one sanitized outcome per
  cycle. Bare metal also reports its
  per-site derivation summary.
- **Bare-metal configuration on VM's conventions.** The bare-metal storefront reads
  `storefront.toml`, `storefront.json`, and `storefront.secrets.toml` under VM's key
  vocabulary; its chart renders `config` through unchanged with a Secret overlay and a
  generated values schema; Compose and the lane mount files. The values-schema generator
  moves to `kit/config`. Site trust comes from each site's durable service peer in both
  storefronts: responses and callbacks are verified against the same active, rotating
  principals, and bare metal adopts durable service-peer state, written as fresh schema since
  it has never been deployed outside the development cluster. Every client of a site, VM's
  early lease termination included, which goes to the site the reservation is recorded at, so
  VM's shared `[provisioning.identity]` set is retired. A trust reload that fails after an
  identity change leaves the storefront trusting no site, refusing from memory, until a
  background reload succeeds. VM's and the API-credit
  storefront's `claims_sweep_interval` becomes `settlement_servicing_interval_seconds`, and the
  old key refuses startup.
- **A local Helm release that sells.** The chart defaults enable no settlement mechanism, so
  `helm/local-values.yaml`, which `make -C helm deploy-local` layers, enables Alkahest on the
  dev-env chart's Anvil, with that chart's copy of the development address book mounted into
  Bob's pod, and contact exchange. The storefront chart's `agents` becomes a map keyed by agent
  name, so an overlay states only what it changes in one agent; a list is refused naming the
  map, and the subchart ships no default agent.
- **Alkahest release conditions for every domain.** Listing `demands` are derived by
  `kit/alkahest` from `[Settlement.alkahest]` for every domain, each domain declares the
  release models it can deliver, and `kit/alkahest`'s plan materialization uses exactly the
  authorized condition (arbiter and demand data) whatever seller policies run; the escrow-shape
  guard fails closed as the early rejection.

## Capabilities

### Modified Capabilities

- `storefront-publication`: one per-process held projection state read by every publication
  source; publication runs as a controllable loop in each dedicated compute storefront;
  bare-metal recheck, override writes, and override status read held projections; a site
  whose projection is not held holds its listings during a bare-metal cycle; loop state in
  system status; a storefront that cannot publish refuses to start; a listing-source check
  confirms only when every family it reads is confirmed within the source-confirmation window; site responses and callbacks share the
  durable rotating trust set; Alkahest listings advertise their release conditions.
- `market-composition`: per-site projection state is kit-owned and per process; a loop
  records each cycle's outcome with the controller; a loop registers as a timer loop or a
  fan-out, and starting the registered loops is the only way a loop's task starts.
- `api-credits`: the API-credit storefront's system status is the administrator's signed read
  and reports every lifecycle loop.
- `deployment-state`: the bare-metal seller role is configured through mounted files; a
  storefront's configuration reaches it through its configuration system, and only
  meta-configuration and the signing credential travel outside it.
- `negotiation-protocol`: an Alkahest obligation uses exactly the release condition its listing
  authorizes, whatever seller policies run.

### New Capabilities

None.

## Non-Goals

- Unbacked bare-metal supply, which `unbacked-bare-metal-listings` adds on top of this.
- Bare-metal publication inside the combined compute-family storefront, and one loop
  covering several listing types; both belong to the storefront unification that is a
  future roadmap goal.
- The listing lifecycle and fulfillment convergence, which stay with
  `kit-owned-listing-and-fulfillment-lifecycles`.
- Retiring VM's admin projection refresh route, which `kit-owned-storefront-shell` decides.
- Extracting the storefronts' typed configuration models into a kit.
- API credits' publication and projections: its storefront holds no per-site projection state.
  Its loops move onto the controller's cycle boundary and its interval key is renamed, because
  it shares the controller and the servicing worker.
- A pool-override write's live check against the site, which stays live: its requirement is
  that a write is judged against the site's current projection.

## Impact

- `core/storefront`: `ProjectionCache` runs one operation at a time on a family, its version
  check included (D2); `ServicePeerTrust` holds each site's service-peer records in memory for
  response and callback verification, reloading on each identity change and, after a failed
  reload, in the background; `HealthResponse` gains `lifecycle` and its loop models.
- `core/storefront-client`: `HealthResponse.lifecycle`.
- `kit/capacity-publication`: `SiteProjectionState` and its poller; per-site capacity-event
  cycle outcomes reported to the controller.
- `kit/storefront`: per-loop serialization of timer cycle and step, per-cycle outcome
  recording, a status snapshot on the loop controller, and fan-out children: per-site names
  declared under their aggregate loop, which follow its end and alone are issued recorders.
- `kit/site-client`: a provider of a site's active principals in place of a fixed trust set.
- `kit/config`: the values-schema generator.
- `kit/alkahest`: demand derivation, per-domain release-model declaration, and the
  release-condition invariant at plan materialization.
- `kit/policy`: `escrow_shape_guard` fails closed.
- `domains/vms/storefront`: consumers onto the injected state; the step; per-site trust, early
  lease termination routed to the reservation's site, and `[provisioning.identity]` retired;
  startup refusal, the registry switch removed; lifecycle status; the generator's section list
  and retired-settings catalogue; demand derivation removed; the interval key rename.
- `domains/apicredits/storefront`: loops registered with step and interval; the interval key
  rename.
- `domains/bare_metal/storefront`: publication, recheck, overrides, lifecycle steps, server
  startup, status, configuration loading, typed models, CLI commands, a packaged
  `settings.toml`, durable service-peer identity state, and a reservation binding that pins the
  site's peer subject; the accepted-generation table frozen.
- `helm/charts/bare-metal-storefront` and the umbrella: config pass-through, overlay,
  generated schema, render tests. `helm/charts/storefront` (0.3.0) and the umbrella (0.3.0):
  `agents` keyed by name, a per-agent Alkahest address-book mount, the provisioning check on the
  site's service peer, and the retired keys refused; `helm/charts/dev-env`: the Anvil address
  book as a ConfigMap; `helm/local-values.yaml` and the fixtures state only what they change.
- `compose.bare-metal.yml`, `domains/bare_metal/compose.yml`, the root `Makefile`'s
  `e2e-bare-metal-dev-env`, and `e2e-tests/`: file-mounted configuration; bare-metal scenarios
  hold the loops.
- Wire: additive `lifecycle` and derivation sections in system status; bare metal's
  `site_projections` gains the capacity-bucket family. Deployment: VM storefronts must
  configure publication and a service peer per site to start; VM's interval key is renamed, and
  a configuration stating `enable_registry_discovery` or `[provisioning.identity]` refuses to
  start. A storefront chart values file with a list of agents is refused and is rewritten as a
  map, an overlay that replaced Bob setting `bob: null`; `make -C helm deploy-local` deploys a
  Bob selling under Alkahest and contact exchange, given its out-of-band runtime Secret. The
  bare-metal chart's values change shape; bare metal has no deployed release to migrate.
- Chart validation runs in three tiers: render tests (Helm, no cluster), a real-loader check of
  a rendered `storefront.json`, and deployment in a local session with a cluster.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Storefront capacity boundary" and the
      capacity-publication paragraph (bare metal on a loop over held projections; the kit
      owns per-site projection state); kit areas (`kit/config`'s generator, `kit/alkahest`'s
      demand derivation); a domain's tooling never writes another domain's artifact.
- [x] Existing subsystem specification — `storefront-publication`, `market-composition`,
      `deployment-state`, and `negotiation-protocol`, with the companions
      `storefront-publication/architecture.md` ("Projection families", "Reconciliation",
      "Storefront pool overrides", "Unknown sites and inline reconciliation", "Autonomous
      publication") and `market-composition/architecture.md` (the kit's projection state).
- [ ] New subsystem specification
- [ ] No permanent documentation change

Also `docs/development/DEPLOYMENT_AND_CONFIG.md` ("Bare-metal role configuration",
"Per-domain stack composition", "Combined compute-family storefront", the bare-metal
pool-override text, interval keys, VM's startup refusal and per-site trust),
`docs/development/TESTING.md` (the bare-metal loop rows), `docs/bare-metal-seller-quickstart.md`,
and `docs/development/ROADMAP.md` (Goal 4's gap row, Goal 7's current state).

### Knowledge to promote

- Per-site projection state is kit-owned, one instance per process, both families for every
  site, refreshed in place — `openspec/specs/storefront-publication/spec.md`,
  `openspec/specs/market-composition/spec.md`, and `market-composition/architecture.md`.
- Bare-metal publication is a timer loop over held projections, with trust checked on read —
  `openspec/specs/storefront-publication/spec.md` and its companion.
- A storefront that cannot publish refuses to start; loop state is in system status —
  `openspec/specs/storefront-publication/spec.md`.
- Bare-metal configuration follows the storefront file conventions; a storefront's
  configuration reaches it through its configuration system, conformance being a compliance
  check rather than a runtime refusal; site trust comes from each site's service peer
  — `openspec/specs/deployment-state/spec.md` and `DEPLOYMENT_AND_CONFIG.md`.
- Alkahest release conditions are the mechanism's, and an unadvertised one is refused —
  `openspec/specs/storefront-publication/spec.md` and `openspec/specs/negotiation-protocol/spec.md`.
- A domain's tooling never writes another domain's artifact — `ARCHITECTURE.md`.
- Several storefronts per registry is the supported deployment topology, each storefront in its
  own Helm release with its own provisioning service (round 12, `design.md` C13) —
  `DEPLOYMENT_AND_CONFIG.md` and `ARCHITECTURE.md` "Deployment topology".

## Dependencies

- **Carved out of `kit-owned-listing-and-fulfillment-lifecycles`**, which no longer carries
  per-site projection state.
- **Blocks `unbacked-bare-metal-listings`**, whose recheck and source reconciliation rely on
  bare metal holding projections and publishing on a loop.
- **Closes an unowned item** recorded under `publish-multidimensional-listing-shape`: the
  admin projection refresh discarding last-known generations.
- **Hands `kit-owned-storefront-shell`** the question of retiring VM's admin projection
  refresh route.
- **Hands `check-storefront-environment-reads`** the mechanical check of the rule this change
  states in `deployment-state`; that change depends on this one.
- Depends on nothing open: `encapsulate-capacity-backing` (archived 2026-10-14) and
  `kit-owned-storefront-loop-lifecycle` (archived) supply the binding and the loop controller
  it builds on.
