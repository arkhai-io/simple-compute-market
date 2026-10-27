# Design

## Context

### What exists

API credits is one domain spread over five distributions, with nothing shared
beneath it. The domain library (`arkhai_apicredits`, about 2,800 source lines)
holds the listing schema, provision terms, negotiation guards, the storefront's
typed authority client with its issuance models and digests, mechanism-neutral
issuance from verified evidence, signed issuance evidence, and the payments
clause validators. The service (`apicredits_service`, about 2,200) holds the
key service, its SQLAlchemy models and hand-rolled migrations, its route
contracts, controllers, and app assembly; it embeds the site and resource-pool
kits and models quota as capacity in the site ledger. The storefront
(`apicredits_storefront`, about 8,500) composes negotiation, settlement, quota
listing binding and publication, issuance evidence persistence, lifecycle loops
with per-cycle outcomes, nine routers, the two seller settlement stages, the
publish-from-quota route's contract and typed clients, which already follow the
route-contract pattern, and the startup refusal of retired or unreadable
settings. The buyer plugin
(`arkhai_apicredits_buyer`, about 3,700) holds the buy, negotiate, settle, and
listing flows and the two buyer stages. The published middleware
(`apicredits_middleware`, about 1,200) is the bearer gate, httpx-only with the
identity kit as an optional extra, and the reference implementation of the
cross-language conformance trace under `domains/apicredits/middleware/conformance/`.

Three facts the proposal did not record, found in the code:

- The issuance digest is already implemented twice. The storefront client and
  the service's wire models each spell the same four schema strings and the
  digest domain. The kit does not introduce a mirror; it removes one.
- The authority is also a capacity authority. Quota is a reservation in the
  embedded site ledger, both domains' listings bind to a quota resource in a
  pool, and the service's migrations include the pool and reservation tables.
- Storefront logic lives in the controllers and composition modules, not behind
  framework-free route services. The negotiate controller alone is 289 lines.

One storefront router, the issuance-evidence read, is referenced nowhere and is
never mounted.

### What the inference copy measured

The campaign's earlier plan copied these roles into the inference domain and
extracted a kit afterwards. The copy was carried as far as the storefront and
the authority: about 12,500 copied source lines against fewer than 300 new
ones — a model-card listing builder, a guard refusing rate cards the stack
cannot charge, and a materialization pinning the rate card at acceptance — all
three beside the copy rather than inside it. The shared part is the whole
machinery. The copied pull requests were withdrawn unmerged; the three modules,
the development seed, and the startup refusal of a foreign settlement mechanism
are the inference contribution this design has to admit.

### What governs the design

`docs/development/ARCHITECTURE.md` is a mandate, and its "Package and
dependency layers" and "Family kits" sections decide most of what follows. Each
decision below names the rule that decides it. Where the documents leave a
choice, the decision says so and records the owner's.

## Goals / Non-Goals

**Goals.** One `api` family whose vocabulary and kit every domain selling
prepaid bearer access composes; API credits refactored onto it with its behaviour, wire, digests, and
data unchanged, proven by pinned bytes; a contribution surface the inference
domain fills with its three modules and wiring; the duplicate digest removed.

**Non-Goals.** Any change to an API-credits digest, wire shape, database row,
or observable behaviour. Any inference role, stack, or scenario. Metering,
holds, or usage capture. A TypeScript or Rust gate change beyond what relocating
the Python reference requires and the verify-cache fixes D10 records. A ledger-free access distribution, deferred under
"Open Questions".

## Decisions

### D1. The family is `api`, rooted at `domains/api`

Credits is one way to pay for API access; a domain selling access by
subscription or by invoice would still publish a listing, issue a credential,
and gate requests on it. The family is named for what is sold, and API credits
joins it now: `ARCHITECTURE.toml` gains a `[[families]]` row (`name = "api"`,
`directory = "domains/api"`, `vocabulary = "arkhai-api"`) and the `apicredits`
domain row gains `family = "api"`; the inference domain joins when its campaign
composes the kit.

The kit lives under the family directory. The scope rule reads scope from the
path: "a package under a family's directory [is scoped] to that family", and the
check classifies any project whose first two path segments are the family
directory that way. Compute's kit sits under `provisioning/` only as a tracked
divergence: each of its five packages carries an override row reading "outside
the family's directory", owned by `align-package-paths-with-layers`. The rules
prescribe `domains/api/`, so no override row is written.

**Rejected:** a function-named top-level directory beside `provisioning/`. It
would need the same override rows compute carries, for a package created after
the rule existed.

### D2. The distributions are the ones the rules force, and no more

`ARCHITECTURE.md` licenses exactly three reasons to split a family's code into
more than one distribution, and each of the eleven packages below exists for
one of them.

| Project | Package | Layer, kind | Exists because |
|---|---|---|---|
| `domains/api` | `arkhai_api` | specialization, library | a family vocabulary package "own[s] no authority or persistence, and never depend[s] on a family kit" |
| `domains/api/contracts` | `arkhai_api_contracts` | specialization, contracts | the route-contract pattern: the owning package owns wire models and the route contract, and a `client` may depend only on `contracts`, core, and the identity kit |
| `domains/api/client` | `arkhai_api_client` | specialization, client | the same pattern: a thin client "so a caller does not install the capability's service code to call it", and "the server never depends on its own client" |
| `domains/api/authority` | `arkhai_api_authority` | specialization, library | dependency weight: SQLAlchemy and the site and pool kits, which no storefront or buyer needs |
| `domains/api/selling` | `arkhai_api_selling` | specialization, library | dependency weight: the negotiation runtime, capacity publication, the storefront kit, and the core storefront, which no authority or buyer needs |
| `domains/api/buying` | `arkhai_api_buying` | specialization, library | dependency weight: the buyer core and its configuration, which no storefront or authority needs |
| `domains/api/gate` | `arkhai_api_gate` | specialization, library | dependency weight: embedded in third-party applications, httpx-only, identity optional |
| `domains/api/selling-alkahest` | `arkhai_api_selling_alkahest` | specialization, library, mechanism `alkahest` | the scope rule: "a specialization that knows a mechanism carries the mechanism in its name"; the side split, because a buyer must not install selling code |
| `domains/api/selling-arkhai-payments` | `arkhai_api_selling_arkhai_payments` | specialization, library, mechanism `arkhai-payments` | the same |
| `domains/api/buying-alkahest` | `arkhai_api_buying_alkahest` | specialization, library, mechanism `alkahest` | the same, for the buyer side |
| `domains/api/buying-arkhai-payments` | `arkhai_api_buying_arkhai_payments` | specialization, library, mechanism `arkhai-payments` | the same |

Dependencies among them point one way and are acyclic, as the family-kit
section requires: `contracts` → vocabulary; `client` → `contracts`;
`authority` → vocabulary and `contracts`, never `client`, so "the server never
depends on its own client"; `selling` → vocabulary, `contracts`, and `client`;
`buying` → vocabulary, and no further family package, since a buyer never calls
the authority and decodes a delivery through its domain's market contract; each `selling-<mechanism>` → `selling` and its mechanism kit;
each `buying-<mechanism>` → `buying` and its mechanism kit; `gate` → nothing
in the family. Nothing under `domains/api/` imports `arkhai_apicredits`, a later
sibling domain's package, or any role executable. The existing API-credits service
project stays, as a composition root over `authority`; the inference service
is the stack change's.

`selling`'s dependency on the core storefront is a layer divergence of the
shape the storefront kit, capacity publication, and the VM and bare-metal
vocabularies already carry, since the core storefront is a composition. It is
recorded as an exception row owned by `kit-owned-storefront-auth-and-persistence`,
whose carve-out of the core storefront's hook shapes and registry into
`kit/storefront-contracts` retires it with the others. The alternative, keeping
every module that touches the core storefront in each domain's storefront,
would leave the binding, persistence, and route services domain-local, which
D7 and D11 exist to prevent.

The buying side has the same shape. `buying`, `buying-alkahest`, and
`buying-arkhai-payments` build on the buyer role's orchestration, negotiation
client, run log, configuration resolution, and settlement policy, and the
buyer role, `arkhai-core-buyer`, is a composition, so each depends upward on
it. The three edges are recorded as temporary `layer` exception rows owned by
`kit-owned-buyer-orchestration`, which moves that machinery below the
composition boundary into a kit, migrates the three libraries, and deletes the
rows. The alternative, keeping the flows in each domain's buyer plugin, would
leave them domain-local, which D7 exists to prevent; moving the buyer role's
machinery here would change every domain's buyer, outside this change's
boundary. No existing change retires the edges:
`align-package-paths-with-layers` only moves the role's path, and
`buyers-use-the-storefront-client` only replaces its storefront call helpers.

`selling` and `buying` are named for the side of the market each serves. They
cannot carry their roles' names: `storefront`, `buyer`, `service`, and `app`
are the role words the check reads as "executable", and these are libraries.

**Rejected:** a base distribution for issuance and keys plus a `credits`
distribution for the ledger. The rule permits a split only where a consumer
"would otherwise install dependencies [it does] not use"; both consumers use
the ledger, and the ledger adds no dependency the authority kit lacks. Deferred
with its trigger under "Open Questions". **Rejected:** one kit distribution for
all three sides, which would install the storefront's publication machinery on
every buyer's machine. **Rejected:** one distribution per mechanism holding
both sides' stages: it would depend on both `selling` and `buying` and undo the
side split for every installer. **Rejected:** mechanism stages inside `selling`
and `buying` under an override row granting the mechanisms, which is the shape
of the divergence the domain library carries today; "no new dependency of the
same shape should be added while one stands".

### D3. The vocabulary holds the shared semantics that need no core

A family vocabulary package "depends only on foundation kits, never on a
domain, a role, or core". `arkhai_api` therefore holds, with pydantic and the
identity kit as its only dependencies:

- the purchase shape and key disposition: a positive integer quantity of
  credits onto a new key or an existing key named by `key_id`, with its payload
  validation, parameterized by the binding domain's kind literal;
- the issuance request and result models, the deterministic fulfillment
  identity, and the issuance request digest, each taking an issuance label;
- the signed, secret-free issuance evidence body, its signing, verification,
  digest, encoding, and the portable fulfillment reference, likewise labelled;
- the issuance label type and the label-parameterized operations above.

The issuance and evidence parts are reusable by any domain that delivers a
bearer credential; the purchase shape is prepaid, since it buys a quantity of
credits, so the vocabulary as a whole is bound by prepaid bearer-access domains
until the ledger-free split under "Open Questions" separates the two. The
concrete labels are not vocabulary: `api-credits` and `inference` are each
domain's contribution, so the family package never names a sibling. The
message, terms, materialization, receipt, and result carriers extend core
schemas, so they cannot be vocabulary either; `contracts` provides them as base
classes each domain binds to its kind literal. They cannot live in `selling`:
a domain's codecs bind them, and its buyer plugin installs those codecs, so a
buyer would install `selling` and the storefront machinery beneath it, which
the side split exists to prevent. `contracts` may depend on core, and both
sides already install it. Neither contribution bundle is
vocabulary, for the same reason: both are typed against core, storefront, and
runtime packages. The API-credits terms module becomes a one-line binding of
the vocabulary's shape, and a test binding under a second kind literal proves
the shape carries no API-credits assumption, which is the "third domain" test
applied early. The inference domain binds the same shape when its own campaign
composes the kit; nothing here touches it.

### D4. Contracts are plain data, and the client signs from them

`contracts` holds the family's wire models — the authority's issuance request
and response, consume, verify, adjust, key, grant, and usage shapes, and the
negotiation and delivery carriers D3 places here — and the route contract
as plain data: for each route its method, path pattern, signed operation name,
admitted roles, and the path segment naming the bound resource. That is the
form `kit/resource-pools-contracts` uses, "so a client needs only this package
to sign a pool request and a service hosting the pool authority assembles the
same declarations into the table its request authentication reads". The
`contracts` kind allowlist admits core, the identity kit, the shape kits, and
the family vocabulary, and the site kit is none of those, so the declarations
cannot be the site kit's contract objects. `authority` provides the adapter from
those declarations to `SiteRouteContract` objects, and each domain's service
root invokes it where it installs the site kit's `SiteAuthMiddleware`, so
resource extraction, role admission, and exact-retry semantics stay where they
are, fed by the same declarations. `client` holds the typed sync and async
clients. Each derives a request's method, path, operation, and signed
resource from the shared route declarations, so request authentication and
the client cannot disagree; signs its requests and verifies the authority's
signed responses itself; and owns its httpx transport's lifecycle. Neither
depends on the site client's `authenticated_request` abstraction: the
client stays a thin standalone package over `contracts`, the identity kit,
and httpx, and coupling it to the site client would add a dependency with
no architectural gain. The service's own duplicate models and digest helpers are
deleted; it imports the vocabulary's functions, so client and server recompute
the same bytes from one implementation.

**Rejected:** `contracts` depending on the site kit under an exception row. A
new divergence of a kind the rules say not to add, and every client installer
would pull the site authority.

### D5. The mechanism stages live in side-split, mechanism-named distributions

Each domain role still "MUST declare one immutable table from canonical
mechanism ID to domain-owned stage", and that table stays in the domain's
storefront and buyer compositions, as the wiring it is. The entries move, split
by side: `selling-alkahest` holds the seller Alkahest stage and the accepted
escrow artifacts; `selling-arkhai-payments` holds the seller payments stage,
the receipt-gated issuance service, and the payments clause validators;
`buying-alkahest` holds the buyer Alkahest stage, escrow selection, and the
escrow client helpers; `buying-arkhai-payments` holds the buyer payments stage
and payer selection. Each stage takes its collaborators — the delivery
callable, the evidence repository, the private-result repository, the capacity
runtime — as constructor arguments, where today the seller stages read the
storefront's container and settings modules; "instance wiring ... belong[s] in
the composition root". An Alkahest-only storefront installs `selling` and
`selling-alkahest` and nothing else from the mechanism set.

The VM domain is the precedent for the principle, not the packaging: its
seller Alkahest codec is its own distribution, `arkhai-vms-settlement`, and its
buyer Alkahest code lives inside the buyer plugin, with no runtime edge between
them. A buyer-side library is new here because two domains' buyers share it.

### D6. Each domain composes the authority kit in its own service root

`authority` is a library: it owns the key service and the prepaid ledger, the
quota-as-capacity composition over the site and resource-pool kits, the SQLAlchemy models and the in-process migration chain, the
framework-free route services for every authority route, the adapter from
`contracts`'s plain declarations to the site kit's contract objects, and the
runtime initialization that ensures the profile's pool exists. It produces no
application. The pool seed moves out of the migration chain into that
initialization, because "config-driven operational seeding belongs in runtime
initialization; migrations may seed only deterministic system rows required to
satisfy a new schema constraint", the rule `seed-default-pool-at-runtime`
applies to the compute provisioning service's seed.
"Instance wiring, process lifecycle, route mounting, and aggregation of
contributions belong in the composition root", and a function that creates the
app, installs authentication, and mounts routers is composition wherever it is
called from.

Each domain's service is that root. `domains/apicredits/service` stays, with
its distribution name, image, entry point, and version response unchanged,
and shrinks to about a hundred lines: read configuration, construct the
authority kit's collaborators, install the site kit's authentication over the
adapted declarations, mount the authority's routers and any routes the domain
contributes, and run the migration chain. The inference service root is
created the same way by the inference campaign's stack change, and the
inference-only routes its metering change adds are mounted by that root with a
plain import the architecture check can see. The architecture document already treats the
storefront executables as "domain-owned composition roots"; this applies the
same shape to the authority.

The root passes the authority kit two things beside its signer, trusted
principals, database, and key namespace. The issuance label. And one validated,
immutable **capacity profile** carrying the offering mode, the seeded pool's
provider, identity, and label, its deliverable and advertisable modes, and its
backing — the values the service hard-codes as `api_credits` today in its pool
seed and its reservation check. The kit reads every such value from the profile
and names none itself. The profile carries no capacity resource type: the
ledger does not filter reservations by type, and a resource's type is what its
registration states (pre-closeout review 08 F3).

**Rejected:** one family service at `domains/api/service` deployed per domain.
A family composition root may not import a domain, so a domain's contributions
could reach it only through a new plugin group discovered at startup; that
costs a sanctioned group, discovery code, an image installing both domains, a
changed version response, and a topology change on upgrade, and the two
domains never run in one process, so the shared image buys nothing.
**Rejected:** `authority` exposing a completed app builder, for the reason
above.

### D7. A domain contributes through one typed bundle per side

"Domains define the values, codecs, hooks, and registrations a family kit
consumes; composition roots select and assemble those contributions", and a
family kit "never discovers or imports its domains". `selling` defines
`SellingContributions`, which each storefront's container fills and passes to
it; `buying` defines `BuyingContributions` for the buyer plugin. Each lives in
the library whose types it is written against, so neither is typed as `Any`
and neither is vocabulary. Entry points stay for the role executables only: the
plugin groups are for packages "imported by nobody", and a storefront imports
its own domain.

| Field | API credits supplies | Inference supplies, when its campaign composes the kit |
|---|---|---|
| issuance label | `api-credits` | `inference` |
| kind literals and schema identity | `api_credits.v1`, `api_credits` | `inference.v1`, `inference` |
| offering mode, contribution identifier, table prefix | `api_credits`, `apicredits`, `api_credit` | its stack change's design decides |
| listing schema and publication mapping from a quota resource | the named-service listing | the model-card listing |
| publication guards | none | the request-priced guard |
| negotiation-time terms checks | the quota and key guards, from `selling` | the same |
| acceptance hook | none | pin the rate card |
| issuance projection | service from `service_name`, resource from `resource_id` | its stack change's design decides; see "Open Questions" |
| delivery public-result extension | none | the materialization, beside the connection payload, never the secret |
| consumption rule | a fixed amount per request, configured at the gate | the same until metering |
| buyer filters and rendering | service name | model card fields |

The **issuance projection** is the field the first review found missing. The
domain's projection maps a listing's resource to the issuance command's
service identity, its quota resource, and the endpoint returned beside the key;
`selling` adds the quantity and key target from the accepted terms, which are
the vocabulary's purchase shape and the same for every domain, so the one
projection also serves publication, where there are no terms. Together they
form the authority's issuance command. It reads the listing as accepted and
pinned to the thread, never a listing republished since, so a seller cannot
change what a settled purchase issues. For a quota-backed domain `selling`
refuses a listing with no quota resource before publication and again before
acceptance, since the authority cannot reserve against nothing; the inference
model card's `resource_id` is optional today and becomes required by that
guard. `selling` keeps no field-name assumption of its own: it reads a listing
only through the projection. The public connection payload a delivery returns
(`kind`, `service_name`, `base_url`, `key_id`, `quantity`) is the family's
delivery shape, filled from the projected subject, and keeps those keys because
the recorded API-credits results carry them.

"Pinned to the thread" is a record of the listing as accepted. Before the
runtime records the negotiation's success, `selling` binds the thread to its
listing's durable binding, which core does once per thread, and writes the
listing, narrowed to the domain's listing schema, to core's immutable
per-negotiation artifact table under a `listing` slot. Settlement verifies the
payment and issues from that record, never from the stored listing, so a listing whose service or
endpoint changes in place after acceptance, under the same quota resource,
still issues what the buyer accepted. Recording binds the thread, so an
unbound thread was accepted before acceptances were recorded, and reads the
stored listing as before; a bound thread without a record, or asked for
another listing than the one it accepted, is refused. API-credit
threads are opened unbound today, though the negotiation protocol has a thread
copy its listing's binding at opening; binding them at opening is section 6's
(task 6.5), and recording at acceptance does not depend on it. The record lives in the existing artifact table
because a new table or column would change the schema baseline (D9), and the
Agreement's `listing_hash` cannot stand in for it: it covers the whole stored
row, status and timestamps included, which change after acceptance. The `listing`
slot is new core API, so `arkhai-core-storefront` becomes 0.16.0; the
capacity-publication kit pins the core storefront exactly, so the bump carries
through it (0.10.2) to the four packages that pin it exactly and to the VM
storefront's exact pin on the bare-metal storefront. That cascade is versioning
fallout of the slot, not new behaviour in those packages. The source check
before every acceptance also refuses a listing whose projected quota resource
differs from the one its immutable binding records.

The consumption rule is the rule's kind, a fixed amount per request: the amount
is the gate's setting, which the storefront does not read, and adding a
storefront setting would change the configuration baseline. The bundle names
the offering mode, contribution identifier, and table prefix the storefront's
binding, registration, and tables are keyed by; the settlement-evidence and
listing-source envelope kinds and the private-credentials reference are spelled
from the kind literal and the prefix, which reproduces the recorded API-credits
names. A storefront holds its bundle wherever its stages, services, and
persistence can read it without an import cycle; the API-credits storefront
holds it in `container.py`.

The negotiation, publication, and lifecycle that `selling` owns read the
bundle the same way. The opening guard registers under a name spelled from the
kind's stem (`api_credits_round_zero_guard`), and the quota and key guards under
their family names, so a configured chain resolves each as before; a listing is
the domain's when its resource validates as the listing schema, and the quota
guard reads its resource through the projection. The refusal codes are the
family's, shared with the authority's issuance re-check, except the one that
spelled the domain, which the table prefix spells (`api_credit_quantity_unavailable`).
Refusal messages name what is sold through the bundle's `refusal_noun`, which
API credits sets to `API-credit`, so its error bodies are byte-identical to
those it served before the kit. A listing's amount rate is the one `amount`
rate its selected option or escrow states, in a per-credit unit; two, or one in
another unit, are refused, and the configured floor applies only where none is
stated. The domain's publication guards run wherever a listing publishes: at
creation, on an administrator's resume, on a reconciliation reopen, where a
refused listing stays closed, and on a registry divergence repair, which runs
the publication hook on the stored listing it would republish and leaves one
the hook refuses unrepaired. Escrow handling is injected rather than imported,
since `selling` knows no mechanism: the opening guard's escrow
canonicalization, an `EscrowAcceptance` that offers and accepts an escrow, and
the mechanism a listing's accepted escrows publish under with their release
conditions. A mechanism's timer loops and startup steps are contributed to
`selling`'s lifecycle as registrations (`ContributedLoop`, startup steps), never
named by it. Each selling-side mechanism distribution's stage supplies them, with
its negotiation step, health checks, configuration checks, and servicing, and a
storefront registers what the stages its table composes contribute, so the
storefront names a mechanism only where it selects one. Reconciliation reads every listing by the core store's keyset over
`(created_at, listing_id)`, which no write changes, so a pass visits each
listing once. A thread takes its listing's binding when it opens, and the
opening is one transaction: the negotiation runtime's `open_negotiation` hook
hands the storefront's persistence the thread, its opening message, and the
opening record together, in place of its own separate writes, and `selling`
runs them with the thread's purchase terms through the core client's
`open_negotiation`, one connection and one commit, so a failed write leaves no
thread, message, binding, or terms. VM and bare metal keep the runtime's
separate writes until their own change adopts the hook.

`selling` reads no configuration itself, so a refusal for a missing or
malformed setting names the key the composing storefront passes:
`RoundSettings.floor_key` for the pricing floor and `read_capacity_sites`'s
`sites_key` for the capacity sites, both dotted keys the refusal brackets as
the storefront's own file spells them. API credits passes
`pricing.default_min_price` and `capacity.sites`, so its three pricing
refusals — an unconfigured floor, and a floor that is not a number, twice —
name `[pricing].default_min_price`, where they once named
`[seller.pricing].default_min_price`, a key no storefront spells. They reach
the wire from a continuation round, which the negotiate route serves 404 as
`{"detail": <message>}`; at opening the runtime answers any missing floor as
`offer_unfulfillable: no_floor_price` before the message is served. No
baseline records them, and no other body changes.

`buying` reads its bundle and the plugin's stage table the same way. The
bundle names the registry schema whose filter spec types the buyer's resource
queries, with an example query for the commands' help; the buyer's filters are
that spec's, so the bundle carries no filter vocabulary of its own. Every step
that differs by mechanism is a method of the stage the selected or accepted
option names: selection and negotiation pricing, the acceptance check, a
deal's enrichment, the rows describing a listing's settlement terms, a buy
session opened for each buy (resources resolved once registries are known,
the settings missing when unavailable, explicit price scaling, the proposal,
run-log fields, the settle call), resumption from a run-log, the command-line
options it reads, and the per-chain configuration the negotiation guards read.
A command's options are the union of its stages' and reach only the stages, so
no option value enters policy parameters, and run-log fields carry no
credential. At most one stage supplies the escrow codec core's negotiation
client carries. A mechanism's configuration is its stage's: the payments stage
is given the table holding the payer account, and the Alkahest stage resolves
the buyer's wallet and chains, each injectable.

Every field a domain may omit is optional in the bundle, so API credits
supplies no placeholder. Each caller — both storefronts, each service root,
each gate, each buyer plugin — composes through its bundle, its capacity
profile, and configuration alone.

### D8. The digest label is a parameter, and the pins come first

The issuance request digest, fulfillment identity, evidence digest, and
portable reference each embed schema strings that today spell API credits. The
vocabulary's functions take the label, and the API-credits binding passes
`api-credits` with its exact existing strings. Before anything moves, a
regression suite under `domains/apicredits/tests/` records, for a fixed input
set, the request digest, the fulfillment identity, the evidence digest, and the
signed attestation shapes the domain produces today; every later slice runs it,
and a difference is a blocking defect. The suite is the change's first
implementation task.

### D9. The compatibility promise is proven at its full width

The pins prove the bytes. The proposal also promises unchanged wire shapes,
authentication, database rows, migration identifiers, environment prefixes, and
observable behaviour, so the same first task records a baseline for each and
every slice diffs against it:

- the route surface: every route's method, path, and the OpenAPI document the
  service and storefront serve;
- authentication: each route's admitted roles and signed operation name, and
  the status code and error body of each refusal;
- configuration: every environment variable and settings key each process
  reads, by prefix;
- schema: the tables, columns, and indexes each database holds, and the
  recorded migration history;
- the version response, which names the unchanged API-credits distribution.

Because the API-credits service keeps its distribution, image, and entry
point, each baseline is held to a diff of zero rather than an allowlist of
accepted differences.

### D10. The gate is the published middleware, relocated under its own name

`domains/api/gate` holds the bearer gate: the framework-neutral `TokenGate`,
the ASGI adapter, the configuration, the httpx verify-and-consume client, and
the identity-v2 signing with the identity kit as an optional extra, exactly as
today, parameterized by environment prefix and label. It depends on no family
package: its runtime dependency is httpx alone, as the published package's
contract requires, so its small wire contract — the verify and consume routes,
their operation names, their fields and error codes — stays local, as it does
now. That is a second spelling of part of the route contract, so a dev-only
test compares the gate's spelling against `contracts`'s plain declarations and
fails on any difference; the published gate gains no dependency from it. The
conformance trace stays at `domains/apicredits/middleware/conformance/`, owned
by `sign-multi-language-credits-middleware`, and the Python runner replays it
against the relocated gate.

`arkhai-apicredits-middleware` is retired. This is a package and import break,
not a behaviour change, and the proposal lists every repository consumer that
migrates to `arkhai_api_gate`: the sample app and its tests, the service's
integration tests, the conformance runner, the three middleware READMEs, the
cookbook, the identities README, the publish and test workflows, and the root
and domains Makefiles. The gate takes the middleware's row in the
published-packages table and the workflow, with a one-time PyPI setup that is a
maintainer's. There are no third-party sellers installing the package today,
and sellers are expected to take the pre-built images, so the old name has
nothing to protect.

Section 9's review found that the gate trusted a cached key identifier for any
secret that presented it. The cache now answers only for the exact secret that
earned it, compared by fingerprint; a refusal of another secret leaves it in
place; and verifications install by ticket, in the order they started, since
two clock reads can return the same value. The TypeScript and Rust gates had
the same defect, and at the owner's direction their fixes and the conformance
steps asserting each verification's secret ride this change's branch, outside
its original non-goal; `sign-multi-language-credits-middleware` keeps outbound
signing and the fixture's home. The `api-family` delta states the invariants
for every gate.

**Rejected:** `gate` depending on `contracts` for one spelling of the routes;
it would make pydantic and the identity kit hard dependencies of a package
whose contract is httpx-only. **Rejected:** keeping
`arkhai-apicredits-middleware` as a thin re-export of the gate. The releasing
guide permits that form, but it exists only to protect installs nobody has.

### D11. Route services in the kit, bindings in the compositions

The route-contract pattern splits a route into wire models, a route contract, a
typed client, a framework-free route service, and an HTTP binding that
"belongs to whatever composes the process". `selling` and `authority` own the
route services; each domain's storefront and each domain's service root own
the bindings. The unmounted issuance-evidence router is dropped, not moved.

The storefront's route services are `selling`'s `route_services`: one class
per router — listings, negotiate, negotiations, settle, system — over
providers of the collaborators the storefront resolves in its lifespan, each
refusing with `RouteRefusal(status_code, detail)` and importing no web
framework. The settle service reads the seller stage table from the
settlement composition it is given, so the library holds no table of its own.
A controller authenticates, calls its service, and serves the refusal as the
response; the API-credits controllers stay the class-based views they were,
because the recorded OpenAPI document carries the class in each route's name
and operation identifier. Authentication is `selling`'s `auth`:
`StorefrontAuth` verifies administrators, buyers, and the seller and signs
every response over the storefront's replay store, signer, administrators, and
principal, each read when a request runs. It verifies every role over the
request body as sent, which is what each client signs, so a client that states
an optional field as null and one that leaves it out both verify; and it binds
every role's authenticated request to its response, so each outcome is
recorded and an exact retry replays it after the reservation's lease as before. It is the library's one
framework-facing module, since it reads the request and wraps the response,
and the storefront kit already builds the FastAPI application every storefront
runs. Persistence is `selling`'s `StorefrontSQLiteClient`: the core client
plus the family's settlement tables under the bundle's prefix, its migration
identifiers unchanged, and the purchase-terms table under the family name
`credit_deal_terms`, since the terms are the vocabulary's shape and the
API-credits schema baseline fixes the name. The storefront's composition holds
the one client over its configured database and constructs each service once,
in `container.py`.

### D12. What API credits keeps

Its listing resource schema and kind literals; the meaning of `service_name`;
its issuance projection and its fixed per-request amount, supplied as
contributions; its environment prefixes and settings; its settlement tables in
both compositions; its storefront controllers and its service root as
bindings; its compose files, seed, and development identities; its service
distribution, image, and entry point. Its domain library shrinks to the listing
schema, the kind bindings, and the bundle values, and its override row in
`ARCHITECTURE.toml` is retired, because the mechanism codecs that earned it
move to the mechanism distributions.

"Its seed" is the seed's values: the quota, listing, and escrow settings under
`[seed]` that API credits configures and passes in. The code that registers the
seeded quota and publishes the seeded listing is the family's, in `selling`,
since any quota-backed domain of the family seeds the same way.

### D13. Slices, each leaving no copy behind

"Every domain that implemented it MUST compose the kit implementation in the
same change, every obsolete domain-local implementation MUST be removed." Each
slice therefore deletes the API-credits implementation it replaces, and no
slice leaves a copy for a later one. Planning fixes the sections; the order the
dependencies impose is: the pins and the compatibility baselines; vocabulary
and `contracts`, with both domains binding the purchase shape; `client`, with
the service composing the shared digest and deleting its duplicate;
`authority`, with the API-credits service root composing it and passing its
capacity profile; `selling`, with the storefront's route services and
bindings; the two selling-side mechanism distributions; `gate`, retiring the
old distribution and migrating its consumers; `buying` and the two buying-side
mechanism distributions. Each slice is one to two thousand lines, leaves API
credits green on its suites, its compatibility baselines, and its end-to-end
lane, and keeps `make check-packaging` green.

### D14. Compatibility

Wire shapes, digests, database rows, migration identifiers, environment
prefixes, the API-credits service's distribution, image, entry point, and
version response do not change, and the baselines above hold each to a diff of
zero. The gate publishes as `arkhai-api-gate`, and the
`arkhai-apicredits-middleware` distribution is no longer published, which is
the one package break and is listed as such. The API-credits distributions
keep their names and bump versions as their contents shrink. They are not
import-compatibility boundaries before 1.0: as implementations move into the
family packages, their Python module and symbol surfaces shrink under minor
version bumps, as the versioning policy permits, while runtime behaviour,
wire, digests, data, configuration, and the retained service and package
identities stay compatible. No database reset
is required, and the service's in-process migration chain is unchanged.
`ARCHITECTURE.toml` gains the family row and the `family` attribute on the
API-credits row, loses the domain library's override row, and needs no override
row for any new project, because every path reads as intended. It gains four
exception rows, each a `layer` row naming a library's dependency on a role
composition (D2): `arkhai-api-selling` on `arkhai-core-storefront`, owned by
`kit-owned-storefront-auth-and-persistence`; and `arkhai-api-buying`,
`arkhai-api-buying-alkahest`, and `arkhai-api-buying-arkhai-payments` on
`arkhai-core-buyer`, temporary and owned by `kit-owned-buyer-orchestration`. This
change introduces the rows and owns none of them. The
inference row gains its attribute when that domain's campaign composes the kit.

## Implementation notes

What implementation settled beneath the decisions above, kept here when the task
notes were compressed.

- **D2, D11.** `selling`'s `auth` is a third copy of the storefront v2
  authentication beside VM's and bare metal's, until
  `kit-owned-storefront-auth-and-persistence` consolidates them. At the owner's
  decision, the `selling` exception row's reason names each import it excuses
  and no destination, because the owning change's design has settled none.
  `selling`'s `arkhai-kit-resource-pools` dependency is planned, and the pool
  declaration reader's placement is a divergence `ARCHITECTURE.md` already
  names. The storefront's binding tests patch module functions because core
  fixes the fulfillment hook's signature.
- **D3.** `IssuanceLabel` carries a separate `fulfillment_id_prefix`, since the
  recorded API-credits prefix, `api-credit-fulfillment.v1`, is singular and no
  rule derives it from `api-credits`. The bound carriers are cached
  `create_model` subclasses: equal kinds or labels give one class, and a class
  statement inside the factory cannot name the base it shadows. Their generic
  class names change only pydantic titles, reprs, and error headers, which no
  recorded document names. `IssuanceRequest` keeps the service's field order and
  docstring because the served OpenAPI document carries both.
- **D4.** `contracts` re-exports the vocabulary's label and result model, so the
  client, whose kind allowlist admits `contracts` and the identity kit, reads
  every wire model from one package; widening the allowlist was declined. The
  client validates an outgoing issuance request under its own label, so another
  label's command never reaches the authority, and owns one HTTP client for its
  lifetime with `close()`, since a client per call would close a transport its
  caller supplied.
- **D5.** `selling-alkahest` imports no core-storefront module — the stage-event
  log and the escrow backfill are injected — so it needs no exception row; the
  settle and refund payload checks sit in `selling` beside the route services
  for the same reason. `SELLER_STAGES` lives in the storefront's `container.py`,
  because the stages' loops feed `STOREFRONT_LOOPS` there. A section services
  the deals accepted under it whether or not it publishes. Saving the credential
  before submitting the attestation was tried and withdrawn: a restart after
  submitting re-issued and rotated the secret while the row kept the dead one,
  and the secret was readable while the attestation was in flight. A typed
  bundle per library, or one constructor argument per collaborator, was
  declined for the stages, because the collaborators exist only once the
  lifespan runs and either would duplicate the composition behind providers.
- **D6.** `AuthorityRouteService` is one class because every route shares the
  one key-service collaborator. `key_prefix` is required, so two roots never
  share a namespace by omission. A foreign offering mode is refused only at the
  site ledger's admission, as undeclared by the seeded pool, since the key
  service always claims the profile's own mode.
- **D7.** The `result_mismatch` check does not compare the reservation, because
  the authority may replace an expired hold under the same grant. Guards
  register in `market_policy`'s process-wide registry, keyed by name, so one
  process composes one domain's guards. On a registry divergence repair the
  capacity-publication kit republishes without the publication hook, and VM's
  hook expects a typed payload, so `selling` wraps the store for `load_listing`
  to run the hook on the object the kit will send; a repair hook every domain
  can use is that kit's to add. The buyer's run-log credential copy was
  deferred to `keep-buyer-credentials-private` because no buyer had a private
  store and the run log was the only durable copy of a once-issued secret; the
  Alkahest option flags to `derive-buyer-settlement-inputs` because a private
  key on the command line reaches shell history and process inspection, and
  removing the flags changes a documented interface.
- **D9.** The rollback probes run behind the shared-secret gate, since no
  credential file can be mounted from inside the test container. The
  storefront's authentication baseline observes each route's operation and
  resource from an unsigned probe through an outermost test middleware, rather
  than transcribing them.
- **D10.** The gate keeps a SHA-256 fingerprint of the secret and matches it in
  constant time; an answer installs only if its verification started after the
  cached one's, ordered by a strictly increasing ticket because a monotonic
  clock can return one value twice. The window the ordering defect reopened
  never outlived the old answer's own TTL, so it bounded staleness rather than
  bypassing verification. The gate parses leniently, so the service suites hold
  only the response fields some test asserts.

## Risks / Trade-offs

- **Refactoring a live domain.** Mitigated by the pins, the compatibility
  baselines, each slice's suites and lane, and the rule that a slice leaves
  API credits green. The pipeline was meant to run on every push; the change
  was worked from a fork without push access to the main repository, so it
  never ran (11.8), and the API-credit lane is tracked in the index's Goal 4
  unowned work.
- **Eleven projects where there were five.** Each exists for a rule the
  documents state; the cost is lock files and the aggregate test target, which
  `make check-packaging` and "Aggregate kit tests cover every kit" hold.
- **Stages refactored to injection.** The seller stages read composition state
  today; moving them to constructor arguments changes their tests, not their
  behaviour, and the pins cover the bytes they produce.
- **Two spellings of the gate's routes.** Accepted so the published gate stays
  httpx-only; held equal by the dev-only parity test.

## Open Questions

- **A ledger-free access distribution.** Splitting `authority` into issuance
  and ledger halves is deferred until a sibling domain sells access without a
  prepaid balance — by subscription, by invoice, or free with a rate limit.
  The trigger is that domain's proposal; the rule that permits the split is
  dependency weight, which such a consumer would create. Until then the
  family's composability claim is scoped to prepaid bearer access.
- **Inference's issuance projection values.** Which stable value enters the
  digested service identity, `model_id` or `served_model_name`, and whether the
  endpoint is delivery metadata or nothing in issuance, are the inference
  domain's choices and belong to the design of the inference campaign's stack
  change.
  The review of this design recommends one explicitly named model identity and
  a required `resource_id`; the projection's interface here already requires
  the resource.
- **The TypeScript and Rust gates.** They replay the same conformance trace
  and are unaffected by the Python relocation; whether they adopt a family
  name is `sign-multi-language-credits-middleware`'s.

## Migration Plan

No data migration. Each slice is a code relocation proven by the pins and the
baselines; a deployment upgrades by installing the new wheels or the rebuilt
API-credits images, whose names, entry points, and Compose topology are
unchanged. Two directions are tested against a copy of a pre-kit database:
the kit image over the pre-kit database proves upgrade compatibility, and the
pre-kit image over a database the kit image has written proves rollback
compatibility. Rollback of any slice is therefore the previous image and
configuration against the retained database; no slice writes a row an earlier
version cannot read.
