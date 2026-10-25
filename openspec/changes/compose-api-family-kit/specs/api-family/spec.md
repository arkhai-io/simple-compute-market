## ADDED Requirements

### Requirement: The api family shares one vocabulary and one kit

The `api` family's vocabulary — the purchase shape and key disposition, the
issuance request and result, the fulfillment identity and request digest, the
signed secret-free issuance evidence and portable fulfillment reference, and the
issuance label type with its label-parameterized operations — MUST live once,
in the family vocabulary package under `domains/api`, and every domain selling
prepaid bearer access MUST bind it rather than define or copy its own. The vocabulary MUST
depend only on foundation kits, never on core, a domain, a role, or a
family-kit distribution, and MUST NOT name a sibling domain's label value. No
distribution under `domains/api` MUST import an API-selling domain or a role
executable.

#### Scenario: Two kind literals bind the purchase shape

- **WHEN** the API-credits binding and a binding under a second kind literal
  each construct provision terms for three credits onto a new key
- **THEN** both validate the payload through the vocabulary's one definition,
  differing only in the kind literal each binds

#### Scenario: A family package imports a domain

- **WHEN** the architecture check reads an import of `arkhai_apicredits`, or of
  any later sibling domain's package, from any project under `domains/api`
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
quota-as-capacity composition, the models and in-process migration chain, the
framework-free route services, and the route-declaration adapter, and MUST NOT
construct an application, install authentication, or mount routes. Each
API-selling domain MUST have a service composition root that creates the
application, reads configuration, constructs the authority library's
collaborators, installs the site kit's authentication over the adapted
declarations, mounts the authority's routers and any routes the domain
contributes, and passes the library its issuance label and one validated,
immutable capacity profile — offering mode, seeded pool provider, identity, and
label, deliverable and advertisable modes, backing, and capacity resource type.
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
  route service, and the same service serves the inference storefront's binding

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
