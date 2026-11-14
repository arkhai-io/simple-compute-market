---
tags: [repository, configuration]
---

# Storefront publication configuration

What a storefront's configuration does to its publication: what it refuses at
startup, how it starts while its dependencies are unreachable, what its system
status reports, and the terms, shapes, and per-pool overrides its listings publish.
The rules these apply are
[`configuration.md`](../../../docs/guidance/engineering/configuration.md) and
[`deployment.md`](../../../docs/guidance/engineering/deployment.md); a storefront's
settlement mechanisms are
[`settlement-configuration`'s](../settlement-configuration/configuration.md), and
its site bindings [`site-capacity`'s](../site-capacity/configuration.md).

## A storefront that cannot publish refuses to start

The VM and bare-metal
storefronts derive their listings from site projections, and each refuses to start,
naming every problem, when publishing is impossible for the whole storefront:
`[registry].urls` is empty, or a registry lacks its `[registry.authorities]` pin; no
`[Settlement]` mechanism is enabled, or the root does not resolve; `[capacity.sites]`
is empty, a site is bound to no `[Identity.service_peers]` peer or to several, or a
site's URL is not an HTTP(S) origin. The bare-metal storefront also refuses a
`[registry.authorities]` pin or a `[registry.auth]` token naming a URL that is not among
`[registry].urls`, and two tokens naming one registry once normalized, naming the table
and the URL and never the token. The refusal runs before the storefront opens its
database or builds a signer, so it leaves no database file and starts no loop.
Missing storefront-wide terms are not a refusal: an empty `[pricing].settlements` or
an absent `[pricing].default_max_duration_seconds` leaves the terms to each pool's
override or hint. A pool that resolves no lease bound is held and reported in system
status's `publication_derivation`; a candidate whose pool resolves no settlement
clause is refused as `no_settlement_option`, and its open listing is closed through
reconciliation and reopened under the same identity once a clause resolves (see
[Storefront listing shapes and pool overrides](#storefront-listing-shapes-and-pool-overrides)).
Retired settings are refused under their own
heading, apart from these, since a stale key is not a reason publication is
impossible. A storefront that only services deals already accepted is not a supported
deployment. A storefront chart cannot check any of this, which is why each chart's
render tests run the storefront's own refusal over a rendered `storefront.json`.

## A storefront starts with its dependencies unreachable

None waits for its
registry, chain, site, or credits service
([`deployment.md`, "A deployment does not wait on a service's dependencies"](../../../docs/guidance/engineering/deployment.md#a-deployment-does-not-wait-on-a-services-dependencies)).
The VM storefront's
`[seller.provisioning]` and the API-credit storefront's `credits` sections have no
reachability preflight: their removed `fail_on_unreachable` and `preflight_timeout`
keys are retired settings, refused at startup and, for VM, by the values schema and
`market-storefront config set`. A storefront started with its registry unreachable
reports the registry check unreachable and itself `degraded`, and its publication
cycle still completes, each listing it could not publish recording
`registry_not_converged` until a later cycle publishes it. One started with its site
unreachable holds no projection of that site, so its cycle holds the site's listings
and closes none, and its fulfillment and settlement calls to the site fail
retryably. API credits' configured seed listing is created by its `listing-seed`
loop step, which waits while the credits service cannot be reached or a mechanism
its clauses use is unknown, and gives up, logging once, on a configuration failure.

## Durations are positive seconds

The typed durations — bare metal's intervals and
timeouts (`[capacity].poll_interval`, `[capacity].publication_interval_seconds`,
`[capacity].source_confirmation_seconds`, `negotiation_timeout_seconds`,
`negotiation_watchdog_interval`, `settlement_servicing_interval_seconds`,
`payment_reconciliation_interval`), VM's `[capacity].poll_interval`,
`[capacity].source_confirmation_seconds`, `settlement_servicing_interval_seconds`, and
contact retention's `retention_sweep_interval_seconds`, and the API-credit
storefront's `settlement_servicing_interval_seconds`, `[capacity].poll_interval`, and
watchdog and payment-reconciliation intervals — are positive, finite numbers of
seconds that can be applied to an instant without leaving `datetime`'s range: at most
the span from year 1 to the Unix epoch, about 1,969 years, and at least a
microsecond. A value outside that is refused by its key when the storefront starts.
`[capacity].source_confirmation_seconds` is how old a site's last successful
projection poll may be for a listing-source check to confirm a listing against it;
unstated, it is three poll intervals, and a poll interval whose derived window could
not be represented is refused by the interval's key. A storefront whose loops are held
while it trades refuses sources older than the window as retryable, until an operator
steps `site-projections`; the end-to-end lanes and the local Helm release widen it to
an hour, a development value.

## The settlement servicing interval

VM's and the API-credit storefront's servicing
sweep reads `settlement_servicing_interval_seconds` (30 by default), as bare metal's
does; a configuration still stating `claims_sweep_interval` refuses startup, naming
its replacement. The API-credit storefront has no chart, so its startup refusal is the
only guard there. It also refuses, by key and before its signer or database, capacity
sites whose authorities are not valid principals and a capacity poll interval that is
not positive seconds.

## System status

Each storefront's system status reports its lifecycle loops as
`lifecycle`: each loop's state and last cycle's outcome, a failure's stage and error
type, and its message only for the storefront's own configuration and publication
errors. Each also reports `settlement`, every composed mechanism's readiness as its
registration projects it — `mechanism`, `ready`, and each blocker's `code` and
`kind` — with Alkahest's carrying each chain's last probe result and when it was
taken (`chain_probe`); and `status` is `degraded`, rather than `ok`, while a check
such as the registry's fails, the process itself still serving. The VM and
bare-metal storefronts also report each site's projection families and its
`publication_derivation`, in one shape for both: per site, the `holds`, `refusals`,
and `reports` the last real publication cycle made, each entry a reason code with
the pool or Physical Resource it concerns and any detail. Only a publication cycle
records it — a preview, a listing-source check, and capacity-event reconciliation
do not — so a configured site no cycle has derived since start is absent, and a site
present with empty lists derived cleanly. The storefront logs each entry as a
warning when it first appears and at info when it clears, and never logs a standing
entry again or a preview, so a condition that lasts many cycles is logged once. A
cycle that cannot read a site at all records a hold naming no pool, and the site's
other entries from the last cycle that read it stand beside that hold until a cycle
reads the site again. The API-credit storefront's status is the
administrator's signed read (`admin_system_status`), as VM's and bare metal's are;
`/health` stays unauthenticated and is a process check.

## Listing bindings and storefront-wide terms of sale

Each listing binding records its capacity backing, and each closed listing records
whether its seller or reconciliation closed it. Both columns are enforced by
triggers: the required-backing insert trigger
`storefront_listing_binding_backing_required`, and the two closure-reason triggers
`listing_closed_by_consistent_insert` and `listing_closed_by_consistent_update`.
A registry that publishes the backing field keeps it; an older reader ignores it.

The combined storefront's publication loop publishes VM; bare-metal publication
runs in the dedicated bare-metal storefront's own loop. Storefront-wide terms of sale are configuration — `[pricing].settlements` and the per-model
`[pricing.defaults.gpu.<model>].settlements`, `default_max_duration_seconds`, and
the family rates `[pricing.defaults.gpu.<model>].rates` and
`[pricing.defaults.<family>].rates` (see
[Storefront listing shapes and pool overrides](#storefront-listing-shapes-and-pool-overrides))
— beneath each pool's own `pricing` declaration and the storefront's
per-pool overrides. `[pricing].default_min_price` is the negotiation floor for a
selected settlement option that advertises no rate, in base units per hour as
decimal text; a fractional number is refused when a negotiation first needs it.
The storefront refuses to start with a configured family rate it cannot read.
`default_token_address` and per-model `min_price` and `token` configure nothing; the
storefront names any it finds at startup. A change to any of them reaches open listings on the next publication
cycle; `market-storefront publish` runs or previews that cycle and takes no terms
of its own.

## Storefront listing shapes and pool overrides

A VM storefront publishes one listing per shape a pool offers. Beyond a pool's
own `listing_shapes`, the storefront operator may state its own terms for one
pool at one site, in one offering mode, through the administrator API or
`market-storefront pool-override` (`set --file`, `get`, `list`, and `delete`,
with `--mode` never defaulted). An override states listing shapes, settlement
clauses, asking rates, and the market's terms (for VM: `sla`,
`max_duration_seconds`, and `pricing` family rates); it cannot state region or
capacity backing. A write stating the retired `min_price` or `token` is refused; a
stored override that still carries them keeps applying its other terms, and
system status names the retired keys.

- **Family rates price a listing by its shape.** A rate is stated per capacity
  family in the pricing hint's nesting —
  `pricing: {gpu: {H100: {rates: [...]}}, cpu: {rates: [...]}, memory: {rates: [...]}, storage: {rates: [...]}}`
  — each entry an `asset`, a positive decimal-text `rate` per unit of the family
  (per card, vCPU, or GiB), and a time unit `per`. The same nesting serves a pool's
  `pricing` hint, an override's `pricing` term, and the storefront's
  `[pricing.defaults]`; each family resolves from its own highest tier, whose list
  replaces lower tiers' whole. A listing for which any family resolves rates is
  shape-priced: its settlement clauses state no `rate`, and each clause's rate is
  the listing's shape priced at the family rates in that clause's asset. A family
  without a rate is not charged, and system status lists it per asset; a listing
  whose rate would be zero in a clause's asset is refused. Without family rates a
  clause's own `rate` is the listing's rate, whatever its shape. The provisioning
  service refuses a pool write whose rate lists are malformed; a rate the storefront
  still cannot read holds the pool's listings at their last-published terms and is
  named, with its tier and family, in system status.

- **Asking rates are declared per shape.** A pool states them in its
  `asking_rates` policy tag, keyed by offering mode, each entry naming the shape
  it prices with an `amount` (positive decimal text, no exponent), an `asset`,
  and a `period` (`hour`). A listing publishes the rate for its own shape, or
  none. An override's `asking_rates` replace the pool's list whole; an empty list
  withholds every rate. No storefront setting supplies a rate. A declaration or
  override the storefront cannot read holds that pool's listings and is named in
  system status, as is a rate for a shape the pool does not publish. A changed or
  withdrawn rate refreshes the listing in place.

- **A stated shape may bound what an agreed shape states.** In a pool's
  `listing_shapes` or an override's, any quantity field may take a constraint
  mapping in place of its scalar, holding `offer`, `min`, `max`, or any of them:

  ```yaml
  listing_shapes:
    vm:
      - gpu:    { model: H100, count: { offer: 1, min: 1, max: 4 } }
        cpu:    { count: 16 }
        memory: { gib: { max: 512 } }
  ```

  The listing publishes each field's `offer` (here one GPU, 16 vCPUs, and no
  memory); `min` and `max` bound only what an agreed shape may state, and are never
  published. A plain scalar is shorthand for an `offer`, and an `offer` alone says
  nothing about negotiability: write a fixed value with `min` and `max` equal to it.
  Each value is a positive integer, `min` is not above `max`, an `offer` lies within
  its own range, a mapping states at least one key, and any other key is refused.
  Constraints apply to quantities only; `gpu.count` and `gpu.model` are required
  together, so a shape that states a `gpu` family always gives `gpu.count` an
  `offer`. Changing only a range keeps the listing's identity.

- **The storefront's configured default fills unconstrained bounds.**
  `[admissibility.defaults.vm]` in the VM storefront's settings uses the same family
  nesting and field syntax, without `offer`:

  ```toml
  [admissibility.defaults.vm.gpu]
  count = { min = 1, max = 16 }

  [admissibility.defaults.vm.memory]
  gib = { max = 512 }
  ```

  For each field's `min` and `max`, a stated shape's own bound wins, including a
  wider one, and a bound it does not state is the default's. An override's shapes
  replace the hint's whole and do not inherit its constraints. Generated shapes
  take the default alone, so the default generator yields only the GPU counts it
  admits. `settings.toml` ships none, and absent and an empty table both mean no
  default. A malformed table — an unknown key, `min` above `max`, an `offer`, or a
  constraint on a field that is not a quantity or is undefined — stops the
  storefront at startup, naming each problem as `admissibility.defaults.vm.<path>`. The default is parsed
  once at startup, so a change takes effect on restart.

- **Publication never advertises an offer the policy excludes.** A stated shape
  whose `offer` falls outside its resolved range is not published, and an open
  listing for it closes. Base shapes are read first: a base shape that cannot be
  read, including one whose required field is given a constraint mapping with no
  `offer`, holds the whole pool. Once every base shape reads, a listing whose policy
  cannot be computed — a constraint on a field that is not a quantity, on an
  undefined field, or with an unknown key; bounds that merge to an empty range; or
  one base shape stated twice with different constraints — closes alone, and the
  pool's other listings publish. System status reports the inadmissible offers and
  the uncomputable policies under each site's `publication_derivation` `reports`,
  as `listing_shape_inadmissible` and `shape_constraints_unusable` entries whose
  `findings` name the tier, path, and problem, each tier's conflicting value, or
  each conflicting entry.

- **Writes refuse what they can check.** The provisioning service refuses a pool
  write whose constraint mappings are malformed or that states one base shape twice
  with different constraints, naming each entry; identical entries are accepted, and
  whether a field may carry a constraint is left to the storefront, which never
  judges a pool's shapes against its configured default at write. An override write
  is refused, without a site call and leaving the stored override unchanged, when a
  shape's base shape or constraints cannot be read, its list states one base shape
  with different constraints, or a shape resolves to an empty range against the
  configured default or leaves its `offer` inadmissible.

- **A write needs its site reachable.** It is checked against the site's live
  projection: a pool the site does not project is refused, an unreachable or
  unverifiable site is refused as retryable, and a shape no member is feasible for
  is accepted and reported, because it then publishes nothing.
- **System status reports each override's state:** `applied`, `orphaned` while
  its pool is absent, `unknown` while its site's projection is not loaded, or
  `site_unconfigured`.
- **An override is the only storefront tier.** Each term it states replaces the
  pool's own hint for that term; a term it omits resolves from the hint, then
  from the storefront's configured defaults. The storefront holds no other
  per-pool record.
- **A site whose projection is not loaded holds its listings.** They are neither
  closed nor refreshed until it loads, so a storefront restarting while a site is
  unreachable does not delist that site. Listings derive only from site
  projections; nothing local stands in for one. A site decommissioned without
  closing its listings leaves them advertised until an operator closes them.
- **A candidate with no settlement option yields no listing.** In VM and bare metal
  alike, a candidate whose payload carries no settlement option and no accepted
  escrow is refused and recorded under its site's `publication_derivation`
  `refusals`, with its pool and Physical Resource. Its admissible clauses are its
  pool override's, else the configured ones, after admissibility for its backing
  (an unbacked listing publishes only options its domain does not fulfil through
  capacity). When the candidate's listing is open, each mechanism of those clauses
  is judged by its readiness blockers' `kind` (see
  [`settlement-configuration`'s "An Alkahest section that cannot settle makes Alkahest unready"](../settlement-configuration/configuration.md#an-alkahest-section-that-cannot-settle-makes-alkahest-unready)
  and [System status](#system-status)):
  - every mechanism ruled out by configuration — no clause, a contact-only option
    whose origin has no contact, or any configuration blocker — refuses it as
    `no_settlement_option` and closes the listing through reconciliation; it
    reopens under the same identity on the first cycle whose payload builds again;
  - any mechanism whose every blocker is reachability — its chain or service
    unreachable, or not yet probed since start — holds the listing on its
    last-published terms as `settlement_mechanism_unknown`, a hold, and it
    negotiates as before; with no open listing that is a refusal;
  - any other payload failure is refused as `payload_unbuildable`, its text the
    entry's `error`, and leaves an open listing as it is.

  A mechanism outside the candidate's admissible clauses is not judged, so an
  outage on a mechanism the listing could never publish neither holds nor closes
  it.
- **A clause naming a disabled mechanism is dropped wherever it is stated.** A
  settlement clause is read in full before its mechanism's enablement is judged,
  so a malformed clause — including a stated `mechanism_input` that is not a
  mapping — is a payload failure that leaves its listing as it is. A readable
  clause whose mechanism's section is absent or disabled is dropped and rules that
  mechanism out, whether a pool's hint, an override, or `[pricing].settlements`
  states it, so a listing it alone priced closes as `no_settlement_option`.
  `market-storefront config migrate --scope settlement|publication` validates its result
  through the same reading, so it accepts a configuration whose clause names a
  disabled mechanism, as the storefront starts with one; disabling a mechanism is a
  deliberate operator act.
- **A region is the pool's alone.** A pool stating no `region` is held as
  `pool_region_missing`: it publishes nothing new and leaves its open listings
  unrefreshed.

Constraints are additive: every shape stated without them is valid, and with no
constraint and no configured default publication is unchanged. Sites and storefronts
are upgraded together. A constraint written before a storefront can read constraints
makes that pool's hint unreadable to it, which holds the pool. To roll back to a
release without constraints, first remove every constraint mapping from pool hints
and stored overrides: a constraint left
in place makes the older storefront hold the pool, and the older provisioning service
refuse any write that keeps it. The contract between a storefront and the
provisioning service it calls is the
[compute provisioning contract](../compute-provisioning-contract/spec.md), and the
major every party accepts is
[its configuration](../compute-provisioning-contract/configuration.md).

Listing shapes are fail-forward. Every VM listing's identity includes its shape, so
a storefront's first publication cycle on a release with shapes, from one without,
closes each listing and publishes its successor once; a seller's close and pause
carry to the successor, and system status reports the carry-over.

A bare-metal storefront serves the same administrator operations, through
`bare-metal-storefront pool-override` (`set --file`, `get`, `list`, `delete`,
with `--mode` never defaulted). The command calls the administrator API, never
the database. It signs as the storefront itself, as `[Identity.principal]` from
the configuration files the server reads with `ARKHAI_IDENTITY_CREDENTIAL`, so
that principal must be one of `[Identity.administrators]`. It connects to
`--storefront-url` (`-a`), else the configured `base_url`. `bare-metal-storefront
publish` signs and connects the same way, running one publication cycle, or with
`--dry-run` previewing one, and printing the cycle's report as JSON; with
`--abort-all` it closes every open listing as its seller, refused beside
`--dry-run`. A storefront refusal exits 1 with its message, and a request no
storefront answers exits 1 naming the origin it was sent to and the transport
error's type.

- **A bare-metal override states no shapes.** It states settlement clauses, which
  replace `[pricing].settlements` for that pool whole; asking rates; and the terms
  `min_duration_seconds` and `max_duration_seconds`.
- **Each lease bound replaces its configured counterpart on its own.** The pair a
  listing would publish must still be ordered: a minimum above the effective
  maximum (the override's, else `[pricing].default_max_duration_seconds`) is
  refused at the write. If configuration later falls below an accepted minimum,
  the next publication cycle holds that pool as `pool_override_terms_conflict`
  rather than publishing; raise the maximum or correct the override. A pool for
  which neither the override nor configuration states a positive maximum is held
  as `pool_lease_bound_missing`. A pool resolving no settlement clause is not
  held: its candidates have no settlement option, as "A candidate with no
  settlement option yields no listing" above describes.
- **A machine the site builds no view for is reported, and its listing held.** The
  site projects a declaration from which it cannot build a bare-metal view — a
  backed one naming no host, no access methods, or no `physical_host_id`, a missing
  or invalid `allocation_mode`, a private-looking capacity or capability key —
  without the view, and with the reason in its `publication_view_problems`. The
  storefront reports it as `publication_view_unbuildable` with those problems and
  refuses openings against it; an open listing of it is held, neither closed nor
  refreshed, until the declaration is corrected, while a disabled declaration or a
  pool that stops admitting bare metal still closes it.
- **A write takes effect at once.** An accepted write refreshes the site's held
  projections and wakes the publication loop.
- **Status is judged against the held projection.** An override's status reads
  the resource-pool projection the storefront holds for its site; until the
  storefront holds one, including just after a restart, its overrides read
  `unknown`.
