# api-family Specification

## Purpose

The `api` market family: the vocabulary and kit every domain selling prepaid
bearer access to an HTTP API composes — the purchase shape, issuance and its
digests, issuance evidence, the authority's key service and ledger, the
storefront's issuance and settlement composition, the buyer flows, the
mechanism stages, the bearer gate, and the gateway in front of a service — and
the contributions through which a domain composes them. See the [architecture companion](architecture.md).

## Requirements

### Requirement: The api family shares one vocabulary and one kit

The `api` family's vocabulary — the purchase shape and key disposition, the
issuance request and result, the fulfillment identity and request digest, the
signed secret-free issuance evidence and portable fulfillment reference, and the
issuance label type with its label-parameterized operations — MUST live once,
in the family vocabulary package under `kit/api`, and every domain selling
prepaid bearer access MUST bind it rather than define or copy its own. The vocabulary MUST
depend only on foundation kits, never on core, a domain, a role, or a
family-kit distribution, and MUST NOT name a sibling domain's label value. Every
distribution under `kit/api` MUST import no API-selling domain and no
role, except through an edge recorded as an exception row in
`docs/development/ARCHITECTURE.toml`;
[Current limits](architecture.md#current-limits) lists those edges.

#### Scenario: Two kind literals bind the purchase shape

- **WHEN** the API-credits binding and a binding under a second kind literal
  each construct provision terms for three credits onto a new key
- **THEN** both validate the payload through the vocabulary's one definition,
  differing only in the kind literal each binds

#### Scenario: A family package imports a domain

- **WHEN** the architecture check reads an import of `arkhai_apicredits`, or of
  any later sibling domain's package, from any project under `kit/api`
- **THEN** the check fails naming the import, and no exception row excuses it

#### Scenario: A label value is sought in the vocabulary

- **WHEN** the vocabulary package is searched for `api-credits` or `inference`
- **THEN** neither appears; each is passed in by its domain

### Requirement: Family kit distributions exist only where a rule forces them

The family kit MUST be split into distributions only where the scope rule, the
route-contract pattern, or dependency weight requires it: a `contracts` package
for wire models and plain-data route declarations, a `client` package for the
typed client, one library per market side — authority, selling, buying — whose
dependencies the other sides do not need, one library for the bearer gate, and
one library per settlement mechanism and market side carrying that mechanism's
name. Dependencies among them MUST be acyclic: a side-and-mechanism library
depends on its side's library and its mechanism kit; the side libraries depend
on the vocabulary and, where they use them, on `contracts`, and only `selling`
and `buying` may depend on `client`;
`client` depends on `contracts`; the gate depends on no family distribution.

#### Scenario: A buyer plugin is installed

- **WHEN** a domain's buyer plugin and its dependencies are installed
- **THEN** the environment contains the buying library and its mechanism
  libraries, and no capacity publication, storefront shell, selling-side stage,
  or SQLAlchemy model from the selling or authority libraries

#### Scenario: An Alkahest-only storefront is installed

- **WHEN** a storefront composes only the `alkahest.v1` stage entry
- **THEN** its environment contains `selling` and the selling-side Alkahest
  library, and neither payments library nor any buying-side library

#### Scenario: The authority's dependencies are read

- **WHEN** the authority library's declared and imported dependencies are read
- **THEN** the family client is not among them

### Requirement: Route declarations are plain data adapted by the authority

The family `contracts` package MUST declare each authority route as plain data —
method, path pattern, signed operation name, admitted roles, and the path
segment naming the bound resource — and MUST NOT depend on the site kit. The
authority library MUST provide the adapter from those declarations to the site
kit's route contracts, each domain's service root MUST invoke it where it
installs the site kit's authentication middleware, and the typed client MUST
sign each request from the same declaration, so client, server, and
authentication cannot disagree.

#### Scenario: A route's roles are read on both sides

- **WHEN** the typed client signs a consume request and the authority's
  authentication admits it
- **THEN** both read the operation name and admitted roles from the one
  declaration, and the contracts package imports no site-kit module

### Requirement: Issuance digests are label-parameterized and byte-identical

The vocabulary's request digest, fulfillment identity, evidence digest, and
portable fulfillment reference MUST take the issuance label as an argument and
MUST produce, for the label `api-credits`, exactly the bytes the API-credits
domain produced before composing the kit. The authority MUST compute those
values through the vocabulary's functions and MUST NOT keep an implementation
of its own.

#### Scenario: The API-credits pins are replayed

- **WHEN** the pinned regression inputs are digested through the vocabulary with
  the label `api-credits`
- **THEN** every recorded request digest, fulfillment identity, evidence digest,
  and attestation shape matches byte for byte

#### Scenario: Two labels digest the same request

- **WHEN** one issuance request is digested under `api-credits` and under
  `inference`
- **THEN** the two digests differ, and each authority accepts only its own

### Requirement: A domain contributes through one typed bundle per side

The selling library MUST define a frozen selling bundle and the buying library
a frozen buying bundle, each typed against the packages its fields reference.
A storefront composition root MUST hand the selling library one bundle naming
the domain's issuance label, kind literals and schema identity, listing schema
and publication mapping, issuance projection, optional publication guards,
optional acceptance hook, optional delivery public-result extension, and
consumption rule; a buyer plugin MUST hand the buying library a bundle naming
its schema identity, filters, rendering, and commands. The kit MUST treat every
optional field's absence as valid and MUST NOT discover or import a domain to
obtain a contribution.

#### Scenario: A domain omits every optional contribution

- **WHEN** the API-credits storefront composes the selling library with no
  guard, no acceptance hook, and no public-result extension
- **THEN** publication, acceptance, and delivery run with the kit's defaults and
  no placeholder implementation is supplied

#### Scenario: A domain extends the public result

- **WHEN** a storefront's bundle supplies a public-result extension and a
  delivery completes
- **THEN** the delivery's public result carries the extension beside the
  connection payload and never the bearer secret

### Requirement: The issuance projection reads the accepted listing

The selling bundle's issuance projection MUST map the listing as accepted and
pinned to the negotiation thread to the authority's issuance command's named
service identity and quota resource, and the selling library MUST combine them
with the accepted terms' quantity and key target into that command; neither
MUST read a listing changed since acceptance. The selling library MUST record
the listing as accepted with the negotiation, immutably, before the
negotiation's success is recorded, and MUST settle and issue from that
record, refusing a negotiation that has none or is asked for
another listing; only a negotiation accepted before recording existed, whose
thread is unbound, MAY issue from the stored listing. For a quota-backed
domain the selling library MUST refuse, before publication and again before
acceptance, a listing that names no quota resource, and before acceptance a
listing whose quota resource differs from the one its durable binding records.
The selling library MUST read no domain field name of its own.

#### Scenario: A listing is republished after acceptance

- **WHEN** a seller republishes a listing with a new service identity after a
  buyer's acceptance against the old one
- **THEN** the issuance command for that acceptance carries the identity the
  buyer accepted

#### Scenario: A listing's service changes in place after acceptance

- **WHEN** a listing's service identity or endpoint changes after a buyer's
  acceptance while its quota resource stays the same
- **THEN** the issuance command and the delivered connection payload carry
  the service and endpoint recorded at acceptance

#### Scenario: An Agreement names another listing than its negotiation

- **WHEN** the accepted Agreement's listing differs from the listing its
  negotiation thread names
- **THEN** settlement is refused under every mechanism before any evidence is
  recorded or any credit issued

#### Scenario: An issuance result answers another request

- **WHEN** the authority's signed issuance result differs from the submitted
  request in its fulfillment identity, request digest, negotiation, owner,
  service, quota resource, quantity, or key target
- **THEN** no credential is stored and no fulfilled progress is recorded

#### Scenario: A quota-backed listing names no resource

- **WHEN** a domain's publication mapping yields a listing with no quota
  resource under a quota-backed profile
- **THEN** publication is refused naming the listing, and an acceptance against
  such a listing is refused before any issuance

#### Scenario: A listing's quota resource no longer matches its binding

- **WHEN** a listing's stored resource names a quota resource other than the
  one its durable binding recorded at creation
- **THEN** the source check before every seller decision and acceptance
  refuses the listing as a declared mismatch

### Requirement: A delivery's public record is safe and final

The selling library MUST refuse an issuance result that does not answer the
submitted request, recording no credential and no fulfilled progress. A
public-result extension MUST receive the issuance result without its bearer
secret, and the selling library MUST refuse, before any continuation attests or
records the delivery, an extension that is not plain data, that names a field
the delivery already publishes or keeps private, or that carries the bearer
secret anywhere. Issuance progress that reaches `ready` or `failed` MUST NOT
change afterwards.

#### Scenario: An extension carries the secret

- **WHEN** a domain's public-result extension returns the bearer secret nested
  inside another value
- **THEN** the delivery is refused before attestation and no public or private
  result is recorded

#### Scenario: A stale write reaches finished progress

- **WHEN** a delivery whose progress is `ready` receives a `provisioning` or
  `failed` write
- **THEN** the write is refused and the recorded progress is unchanged

### Requirement: A mechanism's selling-side behaviour lives in its distribution

Each selling-side mechanism distribution MUST provide its seller stage with every
collaborator injected, and through that stage its negotiation step, timer loops,
startup steps, health checks, and configuration checks. The selling library and a
domain's storefront composition MUST hold none of these; a storefront MUST register
exactly what the stages its table composes contribute.

#### Scenario: An Alkahest-only storefront starts

- **WHEN** a storefront's seller table composes only the escrow stage
- **THEN** no payment reconciliation loop is registered, and the escrow backfill runs
  at startup

#### Scenario: A payments-only storefront starts

- **WHEN** a storefront's seller table composes only the payment stage
- **THEN** no escrow backfill runs, and payment reconciliation is registered while
  payments is serviced

### Requirement: Escrow delivery is retried without repeating an effect

Under the escrow mechanism, an issuance whose outcome is unknown MUST stay open and be
re-driven under the same fulfillment identity, keeping its capacity hold; an issued
grant MUST be compensated only after a definite refusal or a definite non-submission of
its attestation. The attestation's submission MUST be recorded before it is submitted,
and an unknown outcome, or a recorded submission with no reference, MUST park the
obligation for an operator with the delivered credential stored privately.

#### Scenario: Issuance times out

- **WHEN** an issuance times out, answers a retryable server error, or loses its
  response after the authority committed
- **THEN** no failure policy runs, the hold stays, and the re-drive issues under the
  same fulfillment identity and request digest

#### Scenario: The process stops after submitting the attestation

- **WHEN** the attestation's submission was recorded and submitted, and the process
  stopped before its reference was recorded
- **THEN** the next attempt does not submit, the obligation waits for an operator, and
  the grant stands

#### Scenario: The attestation's outcome is unknown

- **WHEN** the chain's answer to the attestation is lost
- **THEN** the obligation waits for an operator, the buyer's credential is readable
  from its private result, and no re-drive submits again

### Requirement: Accepted deals are serviced after their mechanism stops publishing

A storefront MUST build the servicing client of every mechanism its configuration
names, enabled for publication or not, so obligations accepted under a mechanism are
serviced after it is disabled and the storefront restarts. A disabled section whose
client cannot be built MUST NOT stop startup.

#### Scenario: A mechanism is disabled after acceptance

- **WHEN** an obligation is accepted under the escrow, the escrow is disabled, and the
  storefront restarts
- **THEN** the restarted storefront's servicing worker checks and collects it

### Requirement: Each domain composes the authority kit in its own service root

The authority library MUST own the key service, the prepaid ledger, the
quota-as-capacity composition, the models and migration chain, the
framework-free route services, and the route-declaration adapter, and MUST NOT
construct an application, install authentication, or mount routes. Each
API-selling domain MUST have a service composition root that creates the
application, reads configuration, constructs the authority library's
collaborators, installs the site kit's authentication over the adapted
declarations, mounts the authority's routers and any routes the domain
contributes, and passes the library its issuance label and one validated,
immutable capacity profile — offering mode, seeded pool provider, identity, and
label, deliverable and advertisable modes, and backing.
The authority library MUST read every such value from the profile and MUST name
no domain's value itself. Deployments of different domains MUST NOT share a
database or key namespace.

#### Scenario: The API-credits root composes the kit

- **WHEN** the API-credits service starts
- **THEN** its distribution name, image, entry point, version response, routes,
  and authentication are unchanged, and every authority behaviour is served by
  the authority library under the `api-credits` label and the API-credits
  capacity profile

#### Scenario: A reservation under another offering mode

- **WHEN** a root passes a profile whose offering mode is `inference` and a
  reservation names `inference`
- **THEN** the authority admits it, and a reservation naming `api_credits` is
  refused under that profile

#### Scenario: A domain contributes a route

- **WHEN** a domain's service root mounts a router its own package supplies
  beside the authority's routers
- **THEN** the route is served behind the same authentication, resolves to
  exactly one declaration, and the authority library is unchanged

### Requirement: The bearer gate is one published family package

The bearer gate — the framework-neutral gate, its ASGI adapter, its
configuration, its verify-and-consume client, and its optional identity
signing — MUST live in one family library whose runtime dependencies are httpx
alone, with the identity kit as an optional extra, depending on no other family
distribution and parameterized by environment prefix and label. Its local
spelling of the routes it calls — methods, paths, signed operation names,
request and response fields, and error codes — MUST be held equal to the
`contracts` package's declarations by a test that is a development dependency
only. The Python gate MUST remain the reference implementation that replays the
cross-language conformance trace. The gate MUST be published under its own
distribution name, and the repository MUST NOT publish a second distribution
carrying the same code under another name.

#### Scenario: The gate's spelling drifts

- **WHEN** a route's operation name or error code changes in `contracts` and
  not in the gate
- **THEN** the parity test fails naming the route, while the gate's runtime
  dependencies remain httpx alone

#### Scenario: The published packages are listed

- **WHEN** the published-packages table and the publish workflow are read
- **THEN** the gate library appears once, under its own name, and no
  API-credits-named middleware distribution appears

#### Scenario: The conformance trace is replayed

- **WHEN** the Python conformance runner replays the recorded session against
  the relocated gate
- **THEN** every step's decision, error code, purchase pointer, and
  collaborator call counts match the trace

### Requirement: A gate's cached verification answers only for the secret that earned it

Every bearer gate — the Python reference and the TypeScript and Rust gates that
replay the same conformance trace — MAY cache a verification, and a cached
verification MUST authorize only the exact secret that earned it, compared by a
fingerprint of the secret rather than by the key identifier, which any bearer
header carries. A secret the gate has not cached MUST be verified with the
authority. A refusal of a secret other than the cached one MUST NOT evict the
cached credential. Verifications MUST install in the order they started, by a
ticket the gate issues, so an answer from a verification that started earlier
never replaces one that started later.

#### Scenario: A second secret presents a cached key identifier

- **WHEN** a request carries a key identifier the gate has cached with a
  different secret
- **THEN** the gate verifies the presented secret with the authority, and a
  refusal leaves the cached credential in place

#### Scenario: Two verifications of one secret overlap

- **WHEN** a verification that started earlier answers after one that started
  later
- **THEN** the gate keeps the later verification's answer

#### Scenario: Every gate replays the trace

- **WHEN** the Python, TypeScript, and Rust conformance runners replay the
  recorded session
- **THEN** each asserts the secret every verification sends, and each gate's
  own tests hold its verifications to ticket order

### Requirement: Route services are kit-owned and bindings are composition-owned

Each route the selling or authority library serves MUST have a framework-free
route service in that library that validates and performs the route and reports
refusals as errors carrying a status code, and an HTTP binding in the
composition that mounts it — a domain's storefront or a domain's service root.
A binding MUST hold no business logic beyond mapping the route to its service
and its error to a response.

#### Scenario: A storefront binds the negotiate route

- **WHEN** the API-credits storefront mounts its negotiate route
- **THEN** the controller delegates every decision to the selling library's
  route service, and the same service would serve any other domain's binding
  unchanged

### Requirement: A storefront's authentication verifies what was sent and records every outcome

The storefront authentication the selling library binds MUST verify each
role's signature over the request body as the caller sent it, never over a
re-serialization that drops or adds fields, and MUST record every
authenticated outcome — administrator, buyer, and seller alike — so an exact
retry of a mutation replays the recorded outcome whether or not its replay
lease has lapsed.

#### Scenario: A client states an optional field as null

- **WHEN** a buyer signs and sends a continuation whose optional fields are
  stated as null, and another sends one leaving them out
- **THEN** both verify, and each is dispatched once

#### Scenario: A seller retries a mutation after its lease

- **WHEN** a seller's close is dispatched and the same signed request is sent
  again after the replay lease has lapsed
- **THEN** the recorded outcome is answered and the close does not run again

### Requirement: A configuration refusal names the composing storefront's key

The selling library MUST read no configuration itself; a refusal for a setting
it needs — the pricing floor, the capacity sites — MUST name the setting as the
composing storefront passed it, in that storefront's own spelling.

#### Scenario: A configuration refusal names the storefront's key

- **WHEN** a negotiation needs the pricing floor and the storefront's
  configuration states none, or states one that is not decimal text
- **THEN** the refusal names the floor setting as that storefront's
  configuration spells it, which the storefront passed to the selling library,
  and the library read no configuration itself

### Requirement: An opening is recorded in one transaction

The selling library MUST record a negotiation's opening — the thread, its
opening message, its listing's binding, and its purchase terms — in one
transaction, through the negotiation runtime's opening unit of work, so a
failure in any of those writes leaves none of them and no continuation finds a
bound thread without the terms it validates against.

#### Scenario: The opening's last write fails

- **WHEN** the thread, its opening message, and its binding have been written
  and the purchase-terms write fails
- **THEN** the opening is refused and the database holds no thread, message,
  binding, or terms for the negotiation

### Requirement: The purchase shape admits two key dispositions and an exact quantity

The family vocabulary's purchase shape MUST admit exactly two key dispositions:
a new key naming no `key_id`, and an existing key naming a non-blank `key_id`.
Its `quantity` MUST be a strict integer of at least one, and constructing a
purchase MUST NOT convert or truncate the quantity it is given. Every domain that
binds the shape inherits these refusals unchanged.

#### Scenario: A malformed key disposition is received

- **WHEN** provision terms under any bound kind carry a new key with a `key_id`,
  or an existing key whose `key_id` is empty or whitespace
- **THEN** validation refuses the terms

#### Scenario: A quantity is not an exact integer

- **WHEN** provision terms carry a quantity of `true`, `"5"`, `1.0`, or `1.5`,
  or a purchase is constructed with a quantity of `1.5`
- **THEN** validation refuses it rather than coercing or truncating it

### Requirement: A gateway in front of a model server is one family library

The family MUST provide one gateway library that fronts an OpenAI-style model
server behind the bearer gate. It consumes one family-owned offering value
— the service name it admits, the key scope it enforces, a default
per-request charge, the purchase pointer, the upstream and its credential
reference, and the current canonical terms as verification input — which the
composing domain's executable projects from its own validated listing; the library MUST import no domain and MUST NOT
read a listing itself. It reads the request's `model` and refuses one the
offering does not serve before any charge; it verifies the key against the
offering's scope, calls a per-request verification hook with the offering's
current canonical terms and the key's accepted terms payload and digest as
verification returned them, which admits everything until a proof format is
configured, and only then charges the key's verified charge, or the
offering's default when verification returns none, and forwards; it replaces
the buyer's credential with the deployment's own upstream credential,
forwards streamed responses as they arrive, and lists only the served model.

#### Scenario: Two domains front model servers

- **WHEN** the inference gateway executable and an API-credits composition each
  wrap a model server with the library
- **THEN** both refuse an unlisted model uncharged, charge an admitted request
  once, and stream, differing only in the values each root supplies

#### Scenario: A domain is imported by the library

- **WHEN** the architecture check reads an import of a domain package from the
  gateway library
- **THEN** the check fails naming the import

#### Scenario: The seller reprices after a sale

- **WHEN** a key was issued under a listing charging one credit per request,
  the seller republishes the listing at ten, and the gateway is restarted
- **THEN** requests on that key are charged one credit, a key issued after the
  republication is charged ten, and a top-up of the first key from the
  repriced listing is refused

### Requirement: The gate verifies and charges in separable steps

The bearer gate MUST expose key verification separately from the charge, with
the same authority exchanges and cached state as its single authorize
operation, so a composition can run a check between a verified key and its
charge without charging a request it then refuses.

#### Scenario: A check between verification and charge refuses

- **WHEN** a composition verifies a key, runs its own check, and refuses
- **THEN** the key's balance is unchanged and the authority saw only the
  verification

### Requirement: The gate settles an authority refusal by what it refused

A refusal of the key itself — revoked, out of scope, or unknown — MUST deny
the key from then on as its verification would, whether it came from a single
charge or a batch, and MUST NOT be reported as exhausted credit. A refusal of
the key's credit MUST be answered `402` by the gate itself only for a
configured recheck window, after which the next request is charged at the
authority, so a key topped up meanwhile is admitted without waiting for its
verification to expire.

A refusal is an answer naming its reason: a `4xx` with an error code, or a
batch item with a reason. A refusal other than of the key or its credit — such
as `scope_required` — is of the gate's own call: the request MUST be denied
`502` with that code, and neither the key's balance nor its credit touched. A
consume answered with no result and no refusal — a `5xx`, an unreadable body,
or no answer at all — MUST be denied `503 credits_unavailable`, with no purchase
pointer, leaving the key neither exhausted nor its estimate lowered; the key's
charges MUST then be made at the authority until it answers for the key again,
since its balance may already include the unanswered charge.
A verification with no readable answer — a transport error, a `5xx`, an
unreadable body, a field not of its declared type, or an answer that cannot be
authenticated as the authority's — MUST be denied `503
credits_unavailable` and recorded nowhere, so it neither invalidates a good
key nor admits a refused one.

#### Scenario: A batch reports the key revoked

- **WHEN** a batch settles with the authority answering one of its items
  `key_revoked`
- **THEN** the key's next request is denied `403 key_revoked`, not `402`

#### Scenario: A key exhausted and then topped up

- **WHEN** the authority refuses a key for insufficient credit and the key is
  topped up before its verification expires
- **THEN** requests inside the recheck window are denied `402` without an
  authority call, and the first request after it is charged and admitted

#### Scenario: A consume goes unanswered

- **WHEN** the authority answers a consume `503` with no named refusal
- **THEN** the request is denied `503 credits_unavailable` without a purchase
  pointer, and the key's next request is charged at the authority even though
  its estimate would admit it optimistically

### Requirement: The gate charges a key in the order it admitted the key's requests

A charge the gate sends to the authority synchronously MUST reach it after
every charge of the same key admitted before it and still queued, so a request
already served is never refused for credit a later charge took. When those
older charges go unanswered, or the authority cannot be reached, the
synchronous charge MUST be refused `503 batch_unavailable` without being
consumed. Closing the gate MUST wait for every charge in progress, batched or
synchronous, including another close; offer the queued charges in each key's
admission order, draining no further a key whose answer is lost; and raise the
charges left unsettled rather than return as though they were settled. Once
closed,
the gate MUST refuse verification and charging `503 gate_closed` without
calling the authority.

#### Scenario: A queued charge and a later synchronous charge share the last credit

- **WHEN** a key with 10 credits has a 6-credit charge queued and a second
  6-credit request falls below the low-balance threshold
- **THEN** the queued charge is settled first, and the second request is
  denied `402`

#### Scenario: A synchronous charge arrives while the gate closes

- **WHEN** a charge is being consumed synchronously while the gate closes
- **THEN** closing returns only after the authority has answered it

#### Scenario: A batch answer is lost while the gate closes

- **WHEN** the authority's answer to a batch offered while closing is lost
- **THEN** closing sends no later charge of that key and raises the key's
  charges as unsettled, each with its idempotency key

#### Scenario: A request finishes verifying after the gate has closed

- **WHEN** a request's verification completes after closing has returned
- **THEN** its charge is refused `503 gate_closed` and the authority is not
  called

### Requirement: The public-result extension receives the delivery's settlement context

The selling library MUST call a domain's public-result extension with the
accepted listing resource, the secret-free issuance result, and a delivery
context naming the agreed settlement mechanism and the settlement stage's
reference, so a domain whose public record is the family's materialization can
build it from the extension's inputs alone. A domain that supplies no
extension MUST see no change to its delivery.

#### Scenario: A domain builds its materialization in the extension

- **WHEN** a storefront's bundle supplies a public-result extension and a
  delivery completes from verified Alkahest evidence
- **THEN** the extension receives the mechanism and the escrow uid beside the
  listing and the result, and the public result carries what it returns

#### Scenario: API credits delivers without an extension

- **WHEN** the API-credits storefront, which supplies no extension, completes
  a delivery
- **THEN** its public result is byte-identical to the result before the
  context existed

### Requirement: The issuance subject may carry accepted terms

The family issuance subject MAY carry the accepted terms as canonical JSON,
their digest, and a per-request charge, which the domain's projection reads
from the accepted listing; the charge is an integer from one to `2^53 - 1`,
the canonical JSON integer domain, within the range the authority can
consume. When present, the digest and charge MUST enter the issuance request
digest and the signed evidence, the authority MUST verify the
digest against the payload and record all three in a table of its own beside
the grant, leaving the grant table's columns unchanged, and `verify` MUST
return the key's pinned terms, digest, and charge; when absent, they MUST be
omitted rather than serialised as null, so digests, evidence, and `verify`
are byte-identical to their form before the fields existed.

#### Scenario: API credits issues without terms

- **WHEN** an API-credits issuance request, which sets neither value, is
  digested and its key verified
- **THEN** the digest, the evidence, and the verify response match the
  recorded pins byte for byte

#### Scenario: The migrate command creates the terms table

- **WHEN** an authority's migrate command runs against a database its chain
  built before the terms table's migration was appended
- **THEN** the appended migration creates the terms table and is recorded, the
  grant table's columns are unchanged, and existing grants read as unpinned

#### Scenario: The application start only checks

- **WHEN** an authority application starts against a database that lacks the
  terms table's migration
- **THEN** it issues no DDL and refuses the database as behind, naming its
  migrate command and the pending migration

#### Scenario: An image without the terms migration meets a migrated database

- **WHEN** an authority image whose chain lacks the terms table's migration is
  started, or its migrate command run, against a database recording it
- **THEN** the database is refused as ahead, naming the unknown migration, and
  nothing is applied

#### Scenario: Metering reads the accepted card

- **WHEN** a later consumer prices a request against a grant issued with
  accepted terms
- **THEN** the authority supplies the grant's full accepted terms, verified
  against their digest, without consulting the storefront

### Requirement: A key is scoped to its first grant

The authority MUST bind a key to the service, resource, and accepted terms
digest of the grant that created it and MUST refuse an existing-key issuance
whose service, resource, or terms differ, naming the refusal, so a key's one
balance is only ever spent on what every one of its grants bought, at the
charge each was bought at. `verify`, `consume`, and each batched consume item
MAY carry the caller's expected service and resource; when present, the
authority MUST refuse a key whose first grant's scope differs, uncharged, with
a named status, and when absent it MUST behave as before the fields existed. A
gate with a configured scope MUST send it on every one of these calls, and
MUST NOT admit a charge on a verification the authority has since refused.

#### Scenario: A key is topped up from another listing

- **WHEN** a buyer who holds a key issued for one listing purchases onto that
  key from a listing with a different service or resource
- **THEN** issuance is refused naming the key's scope, no grant is recorded,
  and the key's balance is unchanged

#### Scenario: A key is presented at another offering's gateway

- **WHEN** a funded key issued for one service and resource is presented to a
  gateway whose offering names another, under the same authority
- **THEN** the authority refuses the verification by scope, the gateway
  answers `403`, the model server receives nothing, and the key's balance is
  unchanged

### Requirement: A delivered credential names the service it was bought for

The buying library MUST show a delivered credential's service name, taken from
the delivery's connection details, beside its key and base URL under the
domain's own label, and MUST record it with the credential's other non-secret
fields.

#### Scenario: A purchase delivers a key

- **WHEN** a settlement delivers a key whose connection details name its
  service
- **THEN** the buyer is shown the key, the base URL, and the service name under
  the domain's label, and the run log records the name but not the secret
