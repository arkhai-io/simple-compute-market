## ADDED Requirements

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
