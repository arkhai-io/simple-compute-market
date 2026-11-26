# Design — the site ledger reads pools through an injected port

## Context

`docs/development/ARCHITECTURE.md`'s kit areas place `kit/site` and
`kit/resource-pools` side by side as authority capabilities that build on foundation
capabilities only. The site ledger does not: `kit/site/src/market_site/ledger.py`
imports the pool authority and its contracts package and reads `ResourcePool` rows in
its decision session for four facts:

- **Existence**, at registration (`register_declaration_in_session`), refusing a
  declaration naming a pool the site does not have.
- **Enabled and delivers the requested offering mode**, at probe, reserve, resize and
  the rebind recheck (`_pool_declares_mode`, through the contracts package's
  `pool_delivers_offering_mode`).
- **The pool's provider** (`_pool_provider`), which the ledger feeds with its injected
  `HostRequirement` into `declaration_has_usable_host`.
- **Whether the pool declares any deliverable mode** (`_pool_delivers`), in the offered
  read, judging a missing or unparseable pool as delivering so the host rule fails
  closed.

Beside `ResourcePool`, the ledger imports `DeliverableHosts`, `HostRequirement` and
`declaration_has_usable_host` from `market_resource_pools.host_requirement`, and
`declared_deliverable_modes` and `pool_delivers_offering_mode` from
`market_resource_pools_contracts`. `make check-architecture` cannot see the edge — both
kits have empty scope and it forms no cycle — and `kit/site` has had no boundary test of
its own since the repository check subsumed it.

The default-pool fallback this change was first opened to retire is already gone: since
`marketplace-v0.3.0` the ledger reads a declaration with no pool as belonging to no pool
(`_log_poolless_declaration`), as `site-capacity`'s "Operator-administered capacity
declarations" requires.

`renewable-compute-lease-deadlines` depends on this change: it adds the pool's effective
delivery deadline at commit as a further fact through the port.

Two read-only modules also remain in the authority rather than its contracts package,
`site_declarations.py` and `asking_rates.py`, so every reader of a site's pool
declarations — the VM, bare-metal and API-credit storefronts and `arkhai_vms_listings` —
installs the authority, SQLAlchemy and PyYAML for a function that imports neither.
`docs/guidance/repository/package-layers.md`, "Where the current tree diverges", records
both divergences against this change.

The deployment record read for this design is the release tags; the newest is
`marketplace-v0.4.0`.

## Decisions

### D1 — Remove the edge through an injected port rather than sanction it

The site ledger receives pool facts from its composition root through a port `kit/site`
defines, and `kit/site` imports nothing from the pool capability.

The deciding consideration is that this direction complies with the layering guidance:
a kit-to-kit edge the kit-area order forbids is removed, by moving code or injecting a
port, rather than sanctioned by amending the order. It also gives the site's pool facts
one interface the composition answers, which matters for the next fact: the delivery
deadline `renewable-compute-lease-deadlines` adds resolves from a pool tag, a provider's
default and a composition switch, which only the composition knows.

*Rejected.* Sanctioning the edge — amending `ARCHITECTURE.md` to allow
`kit/site → kit/resource-pools` one way and forbidding the reverse — is the least code,
but retires the rule that authorities build on foundation only and leaves every new
fact half a row read and half an injected value, as the host requirement is today.
Deferring leaves `renewable-compute-lease-deadlines` either adding a fifth row read,
which `ARCHITECTURE.md` forbids while the edge stands, or waiting. An earlier argument
for the port — that API credits would no longer need a pool table — does not hold: its
pool row feeds its resource-pool projection and its storefront (D3).

### D2 — The pool authority stays a repository-wide kit

`kit/resource-pools` keeps an empty scope. It is provider-neutral: it stores `provider`
as an opaque string and validates configuration through the `PoolConfigHandler`
protocol, playbooks live in the domain adapters and the service's configuration, API
credits — a domain with no family — runs a pool through it, and `kit/fulfillment`, a
repository-wide kit whose specification forbids depending on the compute family kit,
depends on it. It passes `family-kits.md`'s first placement test, "Outside the family".
`ARCHITECTURE.md`'s statement that the authority is compute-family knowledge is
corrected, and no scope divergence is recorded for it.

*Rejected.* A compute family-kit distribution would put `kit/fulfillment` and both
API-credit packages out of scope — two new findings to fix one — and add
`align-package-paths-with-layers` as a prerequisite. Splitting the host-requirement
module under compute is not separable: `kit/site` and `kit/fulfillment` both use its
protocol and predicate (D5). Leaving the claim in place keeps a permanent document
describing the authority as something it is not.

A future pool behaviour that is intrinsically compute belongs to a provider's handler or
to the compute family kit, never to `kit/resource-pools`.

### D3 — API credits keeps its pool table and composes the real reader

The API-credit service keeps `resource_pools`, its startup seed of the `default` pool,
and `load_pool_directory`, which feeds the pool's metadata into the site's resource-pool
projection; the API-credit storefront resolves its listing's advertisement and backing
from that projection. Its composition root passes `ResourcePoolFacts()` with no host
requirement, so no pool needs a host and its admission stays host-agnostic.

*Rejected.* A static single-pool reader with the table dropped would leave the
projection and the storefront without the pool's declarations, and dropping a deployed
table is a non-additive schema change.

### D4 — The port reads one pool's facts in the caller's session, as structural values

`kit/site` defines two protocols in `market_site/pool_facts.py`:

```python
class PoolFacts(Protocol):
    @property
    def exists(self) -> bool: ...
    @property
    def enabled(self) -> bool: ...
    @property
    def deliverable_modes(self) -> frozenset[str] | None: ...  # None: unreadable
    @property
    def needs_host(self) -> bool: ...

class PoolFactsReader(Protocol):
    def pool_facts(self, db: Session, pool_id: str) -> PoolFacts: ...
```

`kit/resource-pools` implements them in `market_resource_pools/pool_facts.py` with its
own frozen dataclass, `StoredPoolFacts`, and `ResourcePoolFacts`, which takes the
composition's `HostRequirement` and resolves the pool's provider into `needs_host`. It
imports nothing from `market_site`; the provisioning service, a composition root
importing both, holds the test that confirms the implementation satisfies the port. A
port's returned
values are structural for the same reason its methods are: a concrete class owned by
`kit/site` would make the implementation import `market_site`, recreating the edge in
reverse.

The ledger uses the facts as follows:

| Decision | Facts |
|---|---|
| Registration | `exists`; otherwise `UnknownPoolError` |
| Probe, reserve, resize, rebind | `enabled` and the requested mode in `deliverable_modes`; then the usable-host predicate with `needs_host`, judged backed |
| Offered read | backed when `deliverable_modes is None or bool(deliverable_modes)`; then the predicate with `needs_host` |

A missing pool is reported `exists=False`, `enabled=False`, `deliverable_modes=None`,
with `needs_host` true exactly when a requirement is supplied, which keeps today's
missing-provider rule and the offered read's fail-closed judgement. An unreadable
deliverable declaration refuses admission rather than raising; startup and every write
already refuse such a pool, so the case is unreachable.

Every operation takes the caller's session: admission reads pool facts inside the
transaction that creates the reservation, under the ledger's serialization and its
`BEGIN IMMEDIATE`, so a pool's deliverable set cannot narrow between the check and the
reservation. The ledger reads each pool once per decision, as it caches today.

The ledger loses its `host_requirement` argument and takes a required `pool_facts`
argument. `kit/site` drops both `arkhai-kit-resource-pools` and
`arkhai-kit-resource-pools-contracts`.

The conformance is a runtime test in the provisioning service's unit tests, settled in
the triage of the design review (10 F2), since no type checker runs over these packages
and that root builds the ledger through dependency-injection providers no checker relates
to the constructor. The test asserts that every member `typing.get_protocol_members`
returns for `PoolFacts` is a field of `StoredPoolFacts`, and that `ResourcePoolFacts`
has `pool_facts` with `PoolFactsReader`'s parameters. A later fact adds a member to
`PoolFacts` and a field to `StoredPoolFacts` in the change that introduces it; an
implementation lacking it fails that test. `renewable-compute-lease-deadlines` adds
`delivery_deadline_seconds` this way, with its switch and provider defaults configured on
`ResourcePoolFacts`. *Rejected (10 F2):* a static conformance witness checked by mypy in
a required suite gives the guarantee as a type error, but brings a type checker into
packages that run none, a decision larger than this change.

*Rejected.* One method per fact keeps each caller's intent at its call site but moves
the site's admission rules — enabled and declared, fail-closed — into the implementation,
and reads per fact rather than per pool. A raw row view (provider, enabled, policy tags)
is the smallest diff but keeps `kit/site` interpreting tags through the contracts
package, keeps the host requirement injected into the ledger, and would need the
deadline's switch and defaults injected separately. A concrete `PoolFacts` class, a
per-composition adapter (two copies of one mapping), and handing the implementation the
class to construct were rejected as the representation of the value.

### D5 — The site owns the deliverable-hosts report and the usable-host predicate

`kit/site` defines, in `market_site/deliverable_hosts.py`, the `DeliverableHosts`
protocol and the predicate, taking the pool's need for a host as a boolean:

```python
def declaration_has_usable_host(
    host_id: str | None, *, needs_host: bool, backed: bool,
    deliverable: frozenset[str] | None,
) -> bool: ...
```

Its behaviour is unchanged: usable when the pool needs no host or is unbacked;
otherwise the declaration must name a host, and that host must be in the report when one
is supplied. `kit/resource-pools` keeps `HostRequirement` and `pool_needs_host`, which
its `ResourcePoolFacts` and `kit/fulfillment`'s scheduler apply. The scheduler and
`scheduling_persistence.py` take the protocol and the predicate from `market_site`, as
does `compute_provisioning`'s `RelayDeliverableHosts`. This is the shape of
`CapacityReleaseGuard`: a narrow interface the lower layer defines and consumes, without
naming the upper one.

*Rejected.* Moving the module into the contracts package would strip its `Session` type
and keep `kit/site` depending on contracts, and a session-scoped in-process protocol is
not an API contract. A new foundation kit would cost a distribution for about a hundred
lines and put a provider mapping in the foundation area. Redefining the protocol in
`kit/site` while the predicate stayed would leave two copies of one rule.

### D6 — The declaration and asking-rate readers move into the contracts package

`site_declarations.py` and `asking_rates.py` move from `kit/resource-pools` into
`kit/resource-pools-contracts`, beside the `listing_terms` and `capacity_bounds`
resolvers it already holds; both import only the standard library and the contracts
package, within its allowlist. The authority does not re-export them. The VM, bare-metal
and API-credit storefronts and `arkhai_vms_listings` import them from contracts and drop
`arkhai-kit-resource-pools` from their runtime dependencies, keeping it in their `dev`
group only where tests seed pool rows. `host_requirement.py` stays with the authority as
its provider mapping (D5). `package-layers.md` loses both pool divergences.

*Rejected.* A separate change would cost a design, reviews, validation and closeout for a
mechanical move. Leaving the modules would strand the recorded divergence without an
owner.

### D7 — `capacity_buckets.pool_id` stays nullable

No migration is built. A stored declaration with no pool stays inert as `site-capacity`
already requires: it is not projected, admitted against, or moved, and the ledger logs
it. `marketplace-v0.2.29` wrote declarations with an optional pool, so a deployment whose
rows date from it may hold such rows; their reading is current, specified behaviour, not
a compatibility path. The ledger skips a poolless row before consulting the port.

*Rejected.* Backfilling `default` reverses the specified rule, and points at a missing
pool on every provisioning site, whose seed declares `vm-default` and
`bare-metal-default`. Deleting the rows, or refusing the migration while any exists,
spends a non-additive table rebuild in both service chains, and data loss or an operator
upgrade step, on a state already inert.

*Revisit when* a writer of `capacity_buckets` other than the ledger appears, so that the
database itself must refuse a poolless row.

### D8 — `DEFAULT_POOL_ID` stays in the pool authority

It stays in `market_resource_pools.db` for the API-credit service's seed and the tests
that seed that pool. The ledger never needed it, and nothing outside the pool capability
reads it.

### D9 — The ledger requires its reader; `kit/site`'s tests use their own double

`pool_facts` has no default, so a composition cannot omit it and no permissive reader
exists in production code. `kit/site`'s tests use a double in their own conftest — a
mapping from pool id to a test record — as they already use a fake `DeliverableHosts`
report. Tests in `kit/fulfillment`, the provisioning service, the storefronts and API
credits pass the real `ResourcePoolFacts` over the pool rows they seed.

*Rejected.* A permissive default reader in `kit/site` is exactly what could leak into a
composition.

### D10 — Two boundary tests guard the edge

`kit/site/tests/unit/test_import_boundaries.py` forbids `market_resource_pools` and
`market_resource_pools_contracts` in `kit/site/src`, and
`kit/resource-pools/tests/unit/test_import_boundaries.py` forbids `market_site`, since
nothing else would catch a reverse edge once the forward one is gone: the repository
check cannot see the kit-area order, and acyclicity fails only once both directions
exist. No `ARCHITECTURE.toml` row is added; the edge is invisible to the layer and scope
rules.

### D11 — Implementation cadence

One round of two sessions, reviewed together, then closeout:

1. **The contracts split (D6):** move the two modules and their unit tests, switch the
   four readers' imports, move test-only dependencies to `dev`, bump versions, relock.
   `arkhai-kit-resource-pools-contracts` takes a minor bump (to 0.5.0) and
   `arkhai-kit-resource-pools` one (to 0.11.0) that also covers what session 2 adds to
   it. The VM and bare-metal storefronts and `arkhai_vms_listings` raise
   `arkhai-kit-resource-pools-contracts` to that version, and the API-credit storefront
   adds the dependency at it.
2. **The port (D3, D4, D5, D9, D10):** the two `kit/site` modules, `ResourcePoolFacts`
   and its tests, the ledger rewired, fulfillment's and the relay report's imports, both
   composition roots, every test constructing the ledger, both boundary tests, the
   conformance test (D4), and `kit/site/pyproject.toml` dropping both pool
   distributions. `arkhai-kit-site` takes a minor bump (to 0.15.0); `kit/fulfillment`
   and `provisioning/compute` raise their `arkhai-kit-site` floor to it, and the
   provisioning service and the API-credit service raise both `arkhai-kit-site` and
   `arkhai-kit-resource-pools`, for `ResourcePoolFacts`.

Each consumer raises its lower bound to the first version exporting what it now imports,
as `versioning.md`, "Before 1.0.0", asks (10 F3); the versions named are those the
pre-1.0 rule gives, confirmed against `make check-version-bumps`. The sessions touch
disjoint code, and the split is mechanical, so one review reads both.

## Open questions

None.
