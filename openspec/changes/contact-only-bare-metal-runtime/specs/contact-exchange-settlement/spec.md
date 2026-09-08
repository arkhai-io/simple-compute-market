## ADDED Requirements

### Requirement: Bare-metal contact-only environment composition

The bare-metal environment factory SHALL derive introduction-only operation from
its enabled settlement composition. When only `contact-exchange.v1` is enabled,
it SHALL require no site binding, capacity or fulfillment client, wallet, chain,
hosted authority, or delivery sink. Health SHALL mark physical checks as not
applicable and SHALL report incomplete contact configuration as unavailable.
Physical settlement composition SHALL continue to require trusted sites.

#### Scenario: Wallet-free contact-only startup

- **WHEN** a seller supplies its Ed25519 identity, admin identities, public URL,
  database path, and ready contact-only settlement configuration
- **THEN** the ordinary server starts without constructing physical or financial
  clients, and without fabricating a trusted site

#### Scenario: Incomplete contact configuration

- **WHEN** the contact-only seller has no configured contact payload or profile
- **THEN** health is degraded rather than claiming introduction readiness

### Requirement: Unbacked bare-metal contact admission

An unbacked bare-metal listing SHALL contain only canonical rateless
`contact-exchange.v1` options with asset `introduction`, no physical option facts,
no accepted escrows, and exactly `access_methods: [none]`. Its negotiation SHALL
refuse physical access terms or financial mechanisms. Machine and host labels
in this listing SHALL NOT confer site or provisioning authority.

#### Scenario: An unbacked offer is accepted

- **WHEN** an authenticated buyer selects the exact advertised contact option
  with `bare_metal.v1` non-access terms
- **THEN** acceptance persists no contact data; a separate signed introduction
  start persists both contacts and context and completes the existing obligation

#### Scenario: A physical or financial offer is unbacked

- **WHEN** an operator attempts to persist physical provenance without a site,
  physical access, or a financial settlement option on an unbacked listing
- **THEN** admission fails before writing the listing

### Requirement: Amountless buyer negotiation is explicit

The shared buyer SHALL represent an amountless invocation with absent opening
price and bound, and require exact advertised rateless option semantics. It SHALL
preserve absent monetary amounts and reject a monetary proposal or obligation.
Priced invocations SHALL retain monetary comparisons and missing-amount refusal.
The bare-metal introduction command SHALL pass the complete validated selected
contact option and absent price inputs, not a fictitious zero price.

#### Scenario: Real buyer transport accepts an introduction

- **WHEN** the introduction command selects its validated rateless option
- **THEN** the signed accepted plan is validated against the option, parties,
  expiration, asset, and absent amount before contact sharing starts

#### Scenario: A seller adds money to an amountless acceptance

- **WHEN** an amountless invocation receives a monetary proposal or obligation
- **THEN** the buyer refuses it rather than comparing against a fabricated zero

### Requirement: Opt-in immutable synthetic offer publication

The packaged bare-metal storefront SHALL load a strict, bounded file of up to
five explicit synthetic introduction offers only when requested through
`publish-contacts --offers` or `BARE_METAL_STOREFRONT_CONTACT_OFFERS_PATH`.
The complete file, signed registry schema, public profile notice, and existing-ID
conflicts SHALL be validated before any remote write. Each new typed local
listing and its immutable public intent SHALL be durable before publication.

Public discovery SHALL use the existing flat `vms.compute/1` schema with explicit
GPU, region, CPU, RAM and disk fields while retaining `bare_metal.v1` identity.
Options SHALL come from the existing contact settlement composition with empty
rates and escrows; public offers SHALL contain no configured private contact.
All offers and public terms SHALL identify synthetic data and disclaim supply,
payment and provisioning. No physical or outbound delivery sink is applicable.

#### Scenario: Registry acknowledgement is lost

- **WHEN** a signed registry upsert commits but its acknowledgement is lost
- **THEN** bounded retries and later startup reconciliation use the same IDs
- **AND** the registry converges without duplicates, while failures report the
  confirmed count and explicitly uncertain remote outcome

#### Scenario: Operator content or local lifecycle changes

- **WHEN** an existing loader ID has changed public intent or is closed or paused
- **THEN** reconciliation refuses it without rewriting accepted artifacts or
  reopening it; absent IDs trigger no deletion
- **AND** regenerated timestamps and private contact changes alone do not alter
  public intent or already-revealed contacts

#### Scenario: Startup publication cannot authenticate

- **WHEN** registry write-key admission or independent response-trust validation
  fails during opt-in publication
- **THEN** startup fails before HTTP serving rather than claiming publication
  success, without exposing the key or contact payload

### Requirement: Contact publication deployment inputs

The existing bare-metal chart SHALL support an opt-in existing offer ConfigMap,
registry authority/principal pins and a separate existing API-key Secret. It SHALL
omit site authority for file publication, retain a single-writer Recreate/PVC
lifecycle, and reject Alkahest or ephemeral storage in this mode. The packaged
CLI and actual Dockerfile SHALL be covered by a non-pushing CI image-build gate.
An added gate SHALL NOT be treated as evidence of a built or deployed image.

#### Scenario: Synthetic publication is configured in the chart

- **WHEN** `contactOffers` references an existing offer ConfigMap and registry
  trust/API-key inputs with persistent storage and Alkahest disabled
- **THEN** the chart mounts the offer and key files, omits the site environment
  input, and retains one replica with Recreate and a persistent volume
- **AND** this render does not establish image execution or deployment

### Requirement: Accepted introductions are resolvable before consent

New contact acceptances SHALL commit the immutable accepted settlement plan and
its existing obligation bookkeeping atomically. Bookkeeping SHALL remain pending,
without contact data, mechanism invocation, materialization, fulfillment binding,
resource reservation or completion. A failure in either persistence step SHALL
roll back both. Re-registration SHALL preserve any existing lifecycle state.

#### Scenario: Authorized read before start and after restart

- **WHEN** an accepted buyer or seller signs a read for the registered obligation
  before explicit contact sharing, including after a process restart
- **THEN** the seller returns request-bound signed `409` with detail
  `introduction has not been started`, using the existing introduction protocol
- **AND** no contact payload or settlement operation is persisted by acceptance
  or by the pending read

#### Scenario: Pending response authenticity is invalid

- **WHEN** the response signature, body, status, principal, method, operation,
  resource or request identity is altered
- **THEN** authenticated response verification refuses it
- **AND** unknown, nonparty or unauthenticated requests never receive authorized
  pending semantics; unsigned refusals retain their HTTP response bodies

#### Scenario: Older accepted plan lacks obligation bookkeeping

- **WHEN** only the older accepted plan exists and a read supplies its opaque
  obligation reference without the negotiation identity
- **THEN** it remains unresolved with `404`; no scan or backfill fabricates lookup
- **AND** ordinary explicit start with the known negotiation ID remains available
  under the existing authorization and consent rules

### Requirement: Literal configured contacts stay out of public artifacts

Contact-kit and the offer loader SHALL check decoded public string keys and values
for literal configured contacts before admitting public artifacts. They SHALL
share the same representation-level check without inferring other private data.

#### Scenario: A configured contact requires JSON escaping

- **WHEN** a configured contact value occurs literally in any decoded public
  string key or value, including nested option terms, Unicode, quotation marks,
  backslashes or embedded newlines
- **THEN** contact-kit refuses contaminated profiles, options and accepted
  obligations using the same decoded-string check
- **AND** the loader refuses the complete offer file before local immutable
  intent or registry writes, including when the contaminated offer is last
- **AND** this protection remains literal and case-sensitive; it does not infer
  unconfigured private data or normalize transformed or encoded values
