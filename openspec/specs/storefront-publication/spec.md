# Storefront Publication Specification

## Purpose

Define seller storefront ownership, canonical market identity and service trust, listing publication/reconciliation, and domain-runtime composition.

## Requirements

### Requirement: Hosted publication separates ready funding alternatives

For each VM resource, the storefront MUST build one distinct hosted option for each complete configured clause whose exact funding profile is ready. `card.v1`, `us_bank_transfer.v1`, and `us_ach_debit.v1` MUST remain separate alternatives even when rate, currency, and condition are equal. Deterministic option identity and the accepted plan MUST bind profile, rate, currency, account reference, funds flow, parties, expiry policy, and condition. One profile's blocker MUST NOT suppress another ready hosted profile or Alkahest.

#### Scenario: Three hosted profiles are ready

- **WHEN** one VM listing has complete ready clauses for card, US bank transfer, and ACH
- **THEN** it publishes three distinct hosted options in configured order, each projecting one exact profile

#### Scenario: Push transfer is unready

- **WHEN** bank-transfer readiness fails while card and ACH remain ready
- **THEN** only the push-transfer option is suppressed and the safe blocker identifies its profile without provider data

### Requirement: Hosted accepted plan carries authorization safely

The accepted hosted obligation MUST pin the exact funding profile and deterministic marketplace operation ID. Before materialization the buyer MUST obtain one exact hosted `funding_authorization_ref`; storefront start MAY accept only negotiation ID, obligation ID, and that safe reference. The storefront MUST reload amount, currency, parties, destination account, profile, expiry, and condition from accepted seller state, verify the reference through the hosted client during ordinary materialization, and persist only the safe reference and fingerprint.

Stable payer-profile or instrument refs, Customer/PaymentMethod/mandate data, provider identifiers, raw actions, and buyer automation policy MUST NOT enter negotiation, accepted terms, start requests, storefront SQLite, logs, or evidence.

#### Scenario: Authorization covers another profile

- **WHEN** a start request supplies a funding authorization that does not bind the accepted profile and obligation
- **THEN** materialization fails without creating another authorization or selecting another profile

#### Scenario: Start is retried after acknowledgement loss

- **WHEN** the buyer repeats the exact negotiation, obligation, and funding-authorization reference
- **THEN** storefront and hosted authority converge on the same settlement and operation identities

### Requirement: Legacy hosted card decoding is recovery-only

Already accepted hosted card plans and in-flight marketplace settlement rows MUST retain their immutable option, obligation, operation, and hosted settlement identities through upgrade. A recovery-only decoder MAY interpret their historical `payment_method_types=("card",)` representation, but publication, negotiation, config migration, start, and new plan validation MUST accept only `card.v1` and MUST NOT advertise the legacy representation as an alias.

#### Scenario: Existing card obligation resumes

- **WHEN** restart loads an accepted legacy card plan with a nonterminal hosted operation
- **THEN** it resumes the same settlement and operation identity without republishing, reauthorizing, or rewriting it as a new `card.v1` purchase

#### Scenario: New listing uses legacy card fields

- **WHEN** publication input contains `payment_method_types` or the recovery-only legacy value
- **THEN** validation rejects it and identifies the exact `funding_profile` replacement

### Requirement: Delayed funding does not authorize VM fulfillment

Storefront status MAY project awaiting-payment reason, safe deadline, and transient action metadata for card, push transfer, or ACH. It MUST NOT reserve capacity fulfillment, provision a VM, publish fulfillment evidence, or collect until the hosted authority authoritatively reports the accepted profile funded. Expiry/reclaim MUST re-retrieve current hosted state under the same operation before releasing or refunding.

#### Scenario: ACH is processing

- **WHEN** hosted status reports the accepted ACH obligation pending availability
- **THEN** the storefront persists only safe pending metadata and performs no VM fulfillment or collection

#### Scenario: Funding succeeds at expiry boundary

- **WHEN** a reclaim attempt reaches expiry while provider funding may have completed
- **THEN** authoritative status under the same operation decides funding versus reclaim before capacity or financial action

### Requirement: Seller protocol surface
A storefront MUST expose authenticated listing, negotiation, settlement, identity, health, and operator control surfaces while keeping domain-specific behavior behind injected adapters.

#### Scenario: Buyer settles accepted terms
- **WHEN** the buyer submits a settlement request for an accepted negotiation
- **THEN** the storefront verifies the agreed terms and settlement evidence before scheduling fulfillment

### Requirement: Operator-visible acceptance state
The storefront MUST expose enough operator state to distinguish global negotiation pause from listing state and an empty resource projection from an inventory import failure.

#### Scenario: Storefront is globally paused
- **WHEN** a buyer starts a negotiation while global pause is active
- **THEN** the storefront rejects it with HTTP 503 and a global-pause reason until an authenticated operator resumes the process

#### Scenario: Storefront has no imported resources
- **WHEN** the active storefront database contains no resource rows
- **THEN** system status reports `resource_count` as zero and new negotiations cannot match inventory

### Requirement: Registry publication ownership
A storefront MUST publish, update, close, and reconcile its listings against one or more configured registries using its publisher identity.

#### Scenario: Derived capacity disappears
- **WHEN** authoritative capacity no longer supports a derived listing
- **THEN** reconciliation closes that listing in configured registries without treating stale local state as authority

### Requirement: Canonical storefront market identities

A storefront MUST represent listing ownership, negotiation parties and message senders, accepted terms and settlement plans, heartbeat parties, claim actors, settlement parties, administrator subjects, service-peer bindings, replay reservations, and identity-audit actors as complete canonical principals. Listing, negotiation, obligation, fulfillment, service-peer, and operation identifiers MUST remain stable subjects distinct from the principals authorized to act for them. An explicitly named EVM address inside a tagged chain-mechanism payload MAY identify a chain effect, but it MUST NOT authorize a marketplace action or replace a canonical principal.

#### Scenario: A listing enters negotiation

- **WHEN** a buyer negotiates against a storefront listing
- **THEN** the listing retains its stable listing identity while the listing owner, buyer, seller, message senders, accepted terms, and resulting settlement parties carry their exact scheme-tagged principals

#### Scenario: A chain transfer names an EVM recipient

- **WHEN** an Alkahest or token-transfer payload contains an explicit EVM recipient beside the authenticated marketplace principal
- **THEN** the storefront uses that address only for the selected chain effect and authorizes the request with the complete marketplace principal

### Requirement: Commercial mapping identity
A VM listing's commercial mapping between an authoritative capacity identity and the published listing MUST be its immutable common listing binding. VM publication, reconciliation, close, and reopen MUST NOT read or write `derived_compute_listings`; a closed listing is found again by its candidate's derivation key in the common binding. A domain that still keeps its own mapping table (`derived_bare_metal_listings`) MUST NOT duplicate it as a separate schema. Pricing, settlement terms, and seller policy MUST continue to live on the generic `listings` table, addressed by `listing_id` — no mapping carries commercial fields of its own. Each derivation key MUST include the owning `site_id`, since a pool or resource identifier is only unique within one site, never globally. A derivation key MUST be collision-resistant by construction against any values its constituent fields (`site_id`, `pool_id`, `resource_id`) may take — these are operator-chosen strings with no character restrictions, so a naive delimiter-joined encoding is not sufficient.

#### Scenario: Two sites name a pool identically
- **WHEN** two different sites each have a pool sharing the same operator-chosen `pool_id`
- **THEN** their listing bindings have distinct derivation keys and neither binding is silently overwritten by the other's

#### Scenario: An operator-chosen identifier contains a delimiter character
- **WHEN** a `site_id`, `pool_id`, or `resource_id` value contains a character that would otherwise separate fields in a naively joined key
- **THEN** the resulting derivation key remains distinct from any other combination of values that could produce the same joined string

#### Scenario: Two specific-resource candidates share a pool
- **WHEN** a multi-member pool publishes more than one `specific_resource` candidate, each naming a different physical resource
- **THEN** each candidate's derivation key is resource-keyed and distinct, and binding one candidate does not overwrite another's

#### Scenario: A closed listing's slice becomes publishable again
- **WHEN** a closed VM listing's candidate is derived again with the same derivation identity
- **THEN** the listing bound under that derivation key reopens, rather than a new listing being bound under a colliding key

### Requirement: Site-pinned claim routing
A capacity claim for a capacity-backed listing with a known site mapping MUST be routed to exactly that site, with no fallback to a different site on refusal or error — this applies to every such listing, whether the underlying capacity is fungible (pool-derived) or pinned to a specific physical resource, never only to resource-pinned listings. A capacity-backed listing with no recorded site mapping MAY be routed by placement policy across configured sites. An unbacked listing constructs no capacity claim, so it has no claim to route; refusing claim construction for it is a fail-closed guard against a reservation record with no authority behind it, not a control on what a seller may publish.

#### Scenario: A mapped listing's site would lose to placement policy
- **WHEN** a capacity-backed listing is mapped to one site but placement policy would otherwise prefer a different configured site with more available capacity
- **THEN** the claim is routed only to the listing's mapped site, regardless of what placement policy would have chosen for an unmapped claim

#### Scenario: A mapped site refuses or errors
- **WHEN** a capacity-backed listing's mapped site refuses the claim or the request to that site fails
- **THEN** the claim is not retried against a different configured site

#### Scenario: An unbacked listing is queried for a claim route
- **WHEN** claim construction is attempted for an unbacked listing
- **THEN** no claim is constructed and the attempt is refused

### Requirement: Domain-owned publication and hold hints
A storefront domain MAY interpret a projected pool's `listing_cardinality_mode`, `max_reservation_hold_seconds`, `region`, `sla`, and `pricing` policy tags. `listing_cardinality_mode`'s scope is cardinality: how many listing candidates a pool yields and how each is independently identified. A value describing what is offered, how a deal settles, or whether an admission authority backs the listing is out of scope for this hint and MUST NOT be added to it. Each domain MUST own its accepted `listing_cardinality_mode` values and structural default.

A storefront MUST accept the former `listing_mode` key as a deprecated alias on projection ingestion, resolving it to the same cardinality it names and emitting an operator-visible deprecation notice. Accepting the alias is what prevents a projection produced by an unupgraded site from being silently reclassified to the structural default across version skew. The deprecated alias applies to the projected policy tag a site emits, which is the only spelling an unupgraded peer can send; every other surface naming this hint — the resolver, the durable reconciliation rows, and the operator-facing explanation field — MUST use the settled name alone, so an operator reading why a pool fell back to its structural default is not told about a key the projection no longer carries.

A supplied value the selected domain does not recognize MUST fall back to that domain's structural default with an operator-visible explanation, rather than failing projection ingestion or blocking publication. An absent value MUST fall back to the same default; where a pool has no cardinality question to answer, absence is the encoding and the fallback MUST be silent. The operator-visible explanation is owed for supplied-but-unrecognized values, not for absence. A deprecation notice and a fallback explanation are distinct and MUST remain separately identifiable: the first says a declared value was honored under a key that is going away, the second says a declared value was not usable and a default was substituted, and a pool in both conditions is owed both.

A cooperating storefront MUST treat a valid `max_reservation_hold_seconds` as an advisory upper bound on its own requested reservation-hold TTL — it MUST NOT change what the site ledger itself enforces, and an unresolvable or invalid preference MUST leave the caller's requested TTL unchanged rather than block hold placement.

A `fungible` pool's publishable capacity range is bounded by what a single member can satisfy, never by a sum across members: for a capacity-backed pool, what a single member can currently satisfy, sourced from grouped `site_capacity_buckets` data when it is available; for an unbacked pool, what a single member declares. A `specific_resource` pool publishes one independently identified, independently reservable listing candidate per currently enabled member, regardless of member count. No listing/hold hint's projected value may be persisted into storefront-local storage — a consumer reads it live from the current projection each time it is needed.

`region` has no storefront-side override — a storefront overriding where hardware physically sits would misrepresent a fact, not adjust a policy. `sla` and negotiation-floor pricing policy (per resource family and, within a family, per model) each resolve through a three-tier precedence, highest to lowest: a storefront-specific override on a specific pool; the pool's own declared hint; the storefront's own configured default. `sla`'s middle tier is additionally gated behind a storefront-wide trust setting — a storefront MAY decline to consult a pool's declared SLA at all, independent of whether any specific pool has an override. A resolved `min_price` is only a negotiation floor, and a resolved `default_token_address` is only demand-side policy input; neither constructs a settlement option. Settlement option assets, rates, units, and mechanism inputs come only from complete typed clause lists, with a pool's clauses — from a storefront override on that pool or the pool's own declared hint — replacing the storefront's configured defaults as whole lists. Every term of sale MUST come from a durable source: no command-line argument may supply or replace a settlement clause or a maximum duration, because reconciliation must be able to re-derive every term a listing publishes.

#### Scenario: Listing cardinality mode is absent or invalid
- **WHEN** a projected pool supplies a `listing_cardinality_mode` value unsupported by the selected domain
- **THEN** publication uses the domain's structural default and exposes an operator-visible explanation without failing projection ingestion
- **AND WHEN** a projected pool instead omits the value because no cardinality question applies to it
- **THEN** publication uses the domain's structural default silently, with no operator-visible explanation for the absence

#### Scenario: A projection carries only the deprecated key
- **GIVEN** a site that has not been upgraded emits `listing_mode`
- **WHEN** a storefront ingests that projection
- **THEN** the pool resolves to the cardinality that key names
- **AND** an operator-visible deprecation notice is emitted
- **AND** the pool does not fall back to the structural default

#### Scenario: A fungible pool's members have unequal availability
- **WHEN** a capacity-backed fungible pool's members currently have different available capacity
- **THEN** the storefront publishes candidate slice sizes no larger than the largest currently available single member, not a sum across members

#### Scenario: An unbacked fungible pool's members declare unequal capacity
- **WHEN** an unbacked fungible pool's members declare different quantities
- **THEN** the storefront publishes candidate slice sizes no larger than the largest single member's declared quantity, not a sum across members

#### Scenario: A specific-resource pool has more than one member
- **WHEN** a pool resolves to `specific_resource` and has multiple currently enabled members
- **THEN** the storefront derives one listing candidate per member rather than one pooled candidate

#### Scenario: Hold preference is shorter than storefront policy
- **WHEN** a valid positive `max_reservation_hold_seconds` is lower than the storefront's configured acceptance-hold TTL
- **THEN** the storefront requests no more than the projected preference while live site admission remains authoritative

#### Scenario: A storefront declines to trust a pool's declared SLA
- **WHEN** a storefront has not enabled its SLA trust setting
- **THEN** publication resolves SLA from a per-pool storefront override or the storefront's own default, never from the pool's own declared hint, regardless of whether that pool has one

#### Scenario: A pool supplies negotiation pricing hints
- **WHEN** pricing precedence resolves `min_price` or a token-address policy hint for a listing candidate
- **THEN** the storefront may use those values only for negotiation-floor or demand policy and derives every settlement option exclusively from the effective complete typed clause list

#### Scenario: Terms come only from durable sources
- **WHEN** a publication cycle re-derives an open listing whose pool clauses and configured defaults are unchanged
- **THEN** the listing's settlement options and maximum duration are unchanged, because no term of sale came from a source the cycle cannot re-read

### Requirement: Domain publication capability
A domain that supports seller publication MUST provide its publication source and listing interpretation through the domain contract while registry fan-out remains schema-opaque core orchestration.

#### Scenario: Domain publication plugin is selected
- **WHEN** an operator selects a registered domain source
- **THEN** the core runner invokes it through the publication-source contract and publishes its opaque payloads

#### Scenario: Domain capacity changes
- **WHEN** a domain publication source observes a change in its authoritative inventory or quota
- **THEN** it produces domain listings through its contract and the shared runner publishes or reconciles their opaque payloads

### Requirement: Domain runtime composition
The shared storefront role MUST consume the selected market-domain contract for listing, message, agreed-terms, materialization, receipt, and result codecs plus the lifecycle hooks declared by that domain. A concrete storefront composition MUST supply its implementations explicitly, and generic storefront services MUST NOT import or branch on concrete domains.

#### Scenario: Storefront composition selects a domain
- **WHEN** a VM, bare-metal, or API-credit storefront is assembled
- **THEN** its composition root supplies a validated domain contract used by every shared storefront service that interprets domain behavior

#### Scenario: Domain validation fails
- **WHEN** a domain codec or hook rejects a payload
- **THEN** the storefront surfaces the domain validation failure without coercing it through a different domain or a generic fallback

### Requirement: Complete bare-metal seller lifecycle
A bare-metal storefront MUST validate listing, negotiation-message, agreed-terms, settlement materialization, receipt, and access-result artifacts through its installed domain contract. The listing binding MUST freeze the trusted `site_id`, Physical Resource identity, `bare_metal` offering mode, and contract identity/version; the accepted negotiation MUST copy that binding before persisting domain artifacts. Settlement and fulfillment MUST reload that binding and MUST NOT infer a site, executor, URL, credential, or domain from buyer payload data.

#### Scenario: Buyer accepts a bare-metal listing
- **WHEN** authenticated negotiation accepts valid terms for a trusted listing
- **THEN** the thread persists the canonical buyer and seller principals, exact listing/site/domain binding, agreement payloads, and settlement plan atomically

#### Scenario: Accepted bare-metal agreement is fulfilled
- **WHEN** settlement is verified and the buyer starts fulfillment
- **THEN** the storefront reserves at the recorded site, schedules the accepted Physical Resource, invokes the recorded bare-metal executor, and persists its reservation, settlement-resource, fulfillment, receipt, and result correlations

#### Scenario: Buyer supplies conflicting routing material
- **WHEN** a request or domain artifact asserts a provisioning URL, credential, different site, Physical Resource, machine, or physical-host identity
- **THEN** the storefront rejects the conflict before a state-changing authority call

#### Scenario: Storefront restarts during fulfillment
- **WHEN** a process restarts after reservation, scheduling, begin, result, or teardown acknowledgement
- **THEN** it reloads the same immutable binding and durable lifecycle references rather than reserving, provisioning, or releasing through another site

#### Scenario: Bare-metal result is returned
- **WHEN** the recorded fulfillment succeeds
- **THEN** the storefront normalizes one buyer-safe `BareMetalReceipt` and `BareMetalAccessResult` without returning a private key, provider payload, authority URL, or credential

#### Scenario: Bare-metal lease is torn down
- **WHEN** the buyer requests teardown for the completed fulfillment
- **THEN** the storefront converges teardown through the recorded fulfillment and releases the recorded capacity reservation exactly once only after authoritative teardown success

### Requirement: Storefronts hold an exact principal per site authority
A storefront MUST resolve each site authority's site identifier, URL, and scheme-tagged principal through a registry interface. It MUST verify authority-originated version 2 requests and responses against the exact principal selected by site and route context. The registry MUST NOT use an address-only field, derive a principal from private material, or accept a caller-selected expected principal. Routing and ownership MUST come from the trusted registry binding rather than a counterparty-provided site identity.

#### Scenario: An authority-originated request arrives

- **WHEN** a site authority calls a storefront
- **THEN** the storefront verifies the body-bound request against that site's registered role and principal before route dispatch

#### Scenario: A storefront uses several sites

- **WHEN** a storefront aggregates several site authorities
- **THEN** each site has a separate principal and a principal registered for one site does not authenticate another

#### Scenario: The registry source changes

- **WHEN** site records move from configuration to durable storage
- **THEN** consumers of the registry are unchanged

#### Scenario: A wallet-free site is configured

- **WHEN** a site authority uses an Ed25519 principal
- **THEN** the storefront authenticates it without a wallet, RPC endpoint, chain ID, or EVM private key

#### Scenario: Provisioner reports a conflicting site identity
- **WHEN** a configured provisioning connection reports a `site_id` different from the storefront binding
- **THEN** the storefront retains the configured identity and rejects or ignores the conflicting assertion

### Requirement: Storefront clients verify signed authority responses

A storefront client MUST verify the shared version 2 response signature, configured authority principal, request identity, status, timestamp, and body before accepting a mutation acknowledgement. Unsigned responses, signatures from another principal, body mutations, stale responses, and request-ID mismatches MUST fail closed.

#### Scenario: An authority acknowledges a mutation

- **WHEN** the configured authority returns a valid signed response
- **THEN** the client accepts the response only after every bound field and the exact authority principal verify

#### Scenario: A different authority signs the response

- **WHEN** a valid signer that is not the configured authority signs the same response body
- **THEN** the client rejects the response

### Requirement: Site authority principals rotate with bounded overlap

A storefront MUST require proofs from both the active and replacement principals over the same bounded rotation statement. It MUST accept both only during the recorded overlap and MUST reject the old principal after expiry or explicit retirement.

#### Scenario: Rotation overlap is active

- **WHEN** both principal proofs are valid and the overlap has not ended
- **THEN** either principal authenticates that site authority

#### Scenario: Rotation overlap has ended

- **WHEN** the old principal signs after overlap expiry or retirement
- **THEN** the storefront rejects it

### Requirement: Storefronts cache independent site projections
Individual-resource publication consumes `site_resource_pools`, which carries the physical inventory facts required to create a listing for a specific resource. Capacity-oriented publication consumes vertically grouped `site_capacity_buckets`. Grouped capacity is advisory publication input only and is never an allocation target; authoritative reservation admission remains resource-granular inside the provisioning site authority, which applies each pool provider's host requirement.

A storefront SHALL load the resource-pool and capacity-bucket projections at startup, poll their independent revision-and-digest identities, and replace each cached generation atomically. Refresh failure SHALL retain the last complete generation and mark it stale rather than representing an empty projection. Topology-sensitive authoritative errors MAY trigger one coalesced drift check but SHALL NOT automatically retry a state-changing request.

A storefront implementation MAY additionally support deriving publishable listing candidates from local, non-projection tables as a compatibility or staged-rollout path. Once that implementation's projection-backed candidate derivation has parity with its local-table path, the projection path SHALL be the default; a local-table path, if one still exists, is an explicit opt-in for rollback rather than the default behavior.

#### Scenario: One projection refresh fails
- **WHEN** a storefront cannot refresh one site projection after previously loading a complete generation
- **THEN** it retains that generation as stale without replacing the other independently versioned projection

#### Scenario: Projection-backed derivation has reached parity
- **WHEN** a storefront's projection-backed listing-candidate derivation has parity with any local-table path it retains
- **THEN** the projection path is that storefront's default, with the local-table path available only as an explicit, non-default rollback option

### Requirement: Preflighted hosted VM publication

A VM storefront with hosted settlement enabled MUST preflight the exact signed client/manifest/schema, payer/profile/authorization capabilities, listing account, selected condition resolver, currency/country policy, and each configured funding profile before publishing deterministic separate-charge/transfer options. Each ready clause MUST produce one option containing only account reference, `funds_flow="separate_charges_transfers"`, exact `funding_profile`, lowercase currency/rate, interaction capability, and typed condition descriptor. Failure MUST suppress only the affected hosted profile and MUST NOT prevent ready hosted peers or valid Alkahest publication.

#### Scenario: Hosted preflight fails

- **WHEN** readiness, manifest, account, condition, or selected profile capability cannot be verified
- **THEN** the storefront emits a sanitized profile-specific diagnostic and publishes all independently ready hosted and Alkahest choices

#### Scenario: One bank profile is unsupported

- **WHEN** the verified authority release or policy does not admit one configured bank profile/currency/country combination
- **THEN** that clause publishes no option while ready card or other exact profiles remain

### Requirement: Dedicated hosted settlement routes

Hosted start, status, and reclaim MUST use `/api/v1/settlements`; the legacy `/api/v1/settle/{escrow_uid}` carrier and behavior remain Alkahest-only. Hosted start accepts accepted negotiation and obligation identifiers plus one safe operation-scoped `funding_authorization_ref` only, and reloads buyer, claimant, money, account, exact funding profile, expiry, condition, and provision input from persisted seller state. Status and reclaim MUST never return or accept stable payer/instrument refs or provider data.

#### Scenario: Buyer starts accepted hosted settlement

- **WHEN** the accepted buyer signs a start request containing the two accepted IDs and exact authorization reference
- **THEN** the storefront idempotently registers/materializes that exact plan and returns only opaque state plus optional transient action

### Requirement: Server-authoritative settlement start

`POST /api/v1/settlements` MUST accept only negotiation ID, obligation ID, and one safe funding-authorization reference, reload the accepted plan, and resolve payer, claimant, account, money, profile, expiry, and condition server-side. `GET /api/v1/settlements/{settlement_ref}` MUST return public provider-neutral status, safe reason/deadline, and an optional transient buyer action. Buyer-authorized `POST .../{settlement_ref}/reclaim` MUST enter the shared reclaim lifecycle; internal collection MUST run through the shared claims engine. These routes MUST NOT alias or change `/api/v1/settle/{escrow_uid}`.

#### Scenario: Start request supplies provider or money fields

- **WHEN** a caller attempts to override payer profile, instrument, account, amount, currency, funding profile, condition, or provider parameters
- **THEN** the storefront rejects the request and creates no hosted settlement

#### Scenario: Existing Alkahest settle route is called

- **WHEN** a legacy buyer calls `/api/v1/settle/{escrow_uid}`
- **THEN** response shape, authorization, persistence, and side effects remain unchanged

#### Scenario: Funding authorization is absent

- **WHEN** a new hosted start request omits the operation-scoped authorization reference
- **THEN** the storefront rejects it before materialization rather than asking the seller or authority to choose a payer instrument

### Requirement: Fulfillment precedes hosted financial collection

After authoritative funding, the shared obligation lifecycle MUST reserve `funded → fulfilling`, commit immutable VM fulfillment through the existing domain boundary, and only then submit condition evidence for check/collection. A fulfillment failure MUST leave capacity cleanup ordered after the hosted refund reaches a terminal successful reclaim outcome.

#### Scenario: Provisioning fails after payment
- **WHEN** hosted funding is authoritative but VM fulfillment fails
- **THEN** no transfer occurs, one reclaim/refund is driven to terminal success, and capacity is released only under the existing failure dispatcher ordering

### Requirement: Scheme-neutral storefront authorization

A storefront MUST authenticate publisher, buyer, administrator, and configured service-peer requests through `arkhai.market-request-signature.v2` and MUST authorize complete principals against explicit roles and durable subject bindings selected by route, subject, and site context. Each state-changing proof MUST bind the caller role and principal, method, semantic operation, resource, request ID, timestamp, and canonical body hash. The storefront MUST reserve `(principal, request_id)` durably and atomically before route dispatch, reject changed reuse, and return or resume the recorded outcome for an exact retry without executing a conflicting mutation. It MUST NOT fall back from missing or invalid principal headers to an address in the body, configuration, query, listing, negotiation record, administrator key, or private-key field.

#### Scenario: Body claims the expected buyer address

- **WHEN** a request body names the expected buyer but its proof is missing or belongs to another principal
- **THEN** the storefront rejects the request before negotiation, settlement, fulfillment, or operator state changes

#### Scenario: Provisioning peer uses Ed25519

- **WHEN** an allowlisted Ed25519 service principal submits a valid signed response or callback
- **THEN** the storefront authenticates the configured peer and site binding without requiring an EVM identity

#### Scenario: Exact administrator retry follows a lost acknowledgement

- **WHEN** an administrator re-signs the same semantic mutation with the same principal and request ID after losing the response
- **THEN** the storefront returns or resumes the reserved operation outcome without dispatching a conflicting mutation

#### Scenario: A request ID is reused with changed content

- **WHEN** an authenticated caller reuses its request ID with a different body, role, operation, or resource
- **THEN** the storefront rejects the request before handler dispatch and preserves the first reservation

#### Scenario: Storefront acknowledges an authenticated mutation

- **WHEN** an administrator or configured service peer completes an authenticated mutation
- **THEN** the storefront signs the response over its status, originating request identity, storefront principal, timestamp, and canonical body

### Requirement: Storefront authorization bindings are durable

Each administrator and service peer MUST be a stable storefront-owned subject with one explicit role and one primary canonical principal. A service-peer subject MUST additionally retain its operator-owned site binding. Public configuration MAY seed an uninitialized subject, but after initialization it MUST cover every durably active principal and MUST NOT replace the durable primary principal, change the subject's role or site, overwrite a rotation overlap, or make one principal active for two subjects under the same authority.

#### Scenario: Startup configuration is stale during rotation

- **WHEN** configuration omits a durably active overlap principal or names a different primary principal for an initialized administrator or service peer
- **THEN** storefront startup fails closed instead of overwriting the durable authorization state

#### Scenario: Service peer asserts another site

- **WHEN** an authenticated service peer supplies a `site_id` that differs from its durable subject binding
- **THEN** the storefront rejects the request without changing the peer, routing, capacity, fulfillment, or settlement state

### Requirement: Storefront-owned principals rotate with bounded overlap

A storefront MUST rotate administrator and service-peer subjects only from a registered primary principal through one canonical intent signed by both that principal and its replacement. It MUST apply an identical intent idempotently, bound the overlap duration, preserve primary, overlap, retired, disabled, and audit history, and accept both principals only during the recorded overlap. Retirement MUST name the applied rotation and old principal, and disablement MUST remain distinct from replacement.

#### Scenario: Administrator or service peer begins rotation

- **WHEN** the active and replacement principals provide valid proofs over the same unexpired subject, authority, nonce, and overlap intent
- **THEN** the storefront records the replacement as primary and the old principal as active only for the bounded overlap without changing the stable subject, role, or site

#### Scenario: Retirement names another rotation

- **WHEN** an administrator attempts to retire an old principal with a nonce that does not identify its applied rotation
- **THEN** the storefront rejects retirement and preserves the recorded authorization bindings

### Requirement: Storefront principal is reused without exposing its key

Publication, hosted account ownership, negotiation, and hosted settlement calls MAY use one configured seller principal, but each authority MUST receive only a signer operation or signed proof and MUST enforce its own role binding. Storefront persistence and projections MUST NOT contain the seller's private credential or a Stripe provider identity.

#### Scenario: Storefront publishes a hosted option

- **WHEN** the configured seller principal owns the ready hosted account and signs registry publication
- **THEN** the option contains only the allowed opaque account reference and settlement fields while both authorities bind the same public principal

### Requirement: Storefront identity state migrates atomically

Storefront databases MUST validate and migrate buyer, seller, administrator, service-peer, negotiation-message, heartbeat, claim, settlement, replay, stage-event, and audit identities to canonical principal form in one service-local transaction. Migration MUST preserve listing, negotiation, obligation, fulfillment, service-peer, rotation, and operation identities; prove listing ownership and cross-record party consistency; and retire authoritative address-only identity columns. A malformed or partial principal, ownership conflict, duplicate active binding, missing party relation, or other unsafe population MUST roll back completely.

#### Scenario: Active hosted obligation is migrated

- **WHEN** a storefront with a funded nonterminal obligation upgrades from address-only identity rows
- **THEN** the obligation retains its authoritative lifecycle and operation journal while its parties become canonical `eip191` principals

#### Scenario: Persisted listing ownership conflicts with local identity

- **WHEN** a populated listing cannot be proven to belong to the configured storefront principal and expected storefront URL
- **THEN** the migration aborts without leaving any identity table or embedded event partially converted

### Requirement: Publication derives all ready settlement options

A storefront MUST preflight every enabled installed settlement registration and derive deterministic listing options from every ready mechanism in configured priority order and the seller's validated settlement publication clauses. A clause MUST NOT make a disabled or unready mechanism publishable. One unready mechanism MUST be suppressed with an operator-visible sanitized blocker while ready peers remain publishable. If no enabled ready mechanism has a valid publication clause, publication MUST fail without mutating accepted negotiations or active settlement state.

#### Scenario: Stripe is unready and Alkahest is ready

- **WHEN** both have publication clauses but hosted account readiness is false
- **THEN** the storefront publishes the Alkahest option, omits the Stripe option, and reports the hosted blocker without provider detail

#### Scenario: Readiness returns after publication

- **WHEN** a previously suppressed mechanism becomes ready and its publication clause remains valid
- **THEN** reconciliation may add its deterministic option without changing listing identity or any already accepted Terms

#### Scenario: Clause names a disabled mechanism

- **WHEN** seller publication input names a mechanism whose typed configuration is disabled
- **THEN** publication rejects that clause without using it as an implicit enablement override

### Requirement: Storefront owns seller settlement UX

Seller configuration, readiness, mechanism administration, and publication MUST be exposed through the storefront CLI and generated role config surface. Normal publication MUST derive options from mechanism-neutral settlement clauses and MUST NOT expose provider-, chain-, or escrow-specific flags. Mechanism administration MUST remain under `settlement <mechanism>`. The storefront CLI's publication command MUST run or preview a cycle of the storefront's publication loop through the storefront API rather than deriving or publishing listings itself. A hosted client MAY supply workflow primitives, but a separate provider-specific seller executable or top-level mechanism-specific publication flow MUST NOT be the normal marketplace entry point.

#### Scenario: Seller inspects all settlement mechanisms

- **WHEN** `market-storefront settlement status --json` runs
- **THEN** it returns the common status schema for every installed mechanism in configured order without a listing or financial side effect

#### Scenario: Seller publishes two mechanisms

- **WHEN** normal publication resolves valid Stripe and Alkahest settlement clauses
- **THEN** the storefront derives both through their ready registrations without invoking a mechanism-specific publication command

#### Scenario: Seller runs the publication command

- **WHEN** a seller runs the storefront CLI's publication command
- **THEN** it runs or previews one cycle of the storefront's publication loop through the storefront API, and it reads no storefront database

### Requirement: Publication pricing is explicit per settlement clause

Every priced settlement publication clause MUST contain one asset-scoped decimal rate and unit. The owning mechanism MUST normalize it to canonical integer minor or base units using authoritative asset scale, reject non-exact conversion, and include the normalized rate in deterministic option identity. A resource-level `min_price` or other untyped scalar MUST NOT be reused as the price of more than one mechanism.

#### Scenario: Dual listing uses equal human prices

- **WHEN** a seller explicitly publishes USD 2/hour and six-decimal-token 2/hour clauses for one resource
- **THEN** the resulting options carry 200 and 2000000 canonical units respectively and both display as 2 asset units/hour

#### Scenario: Dual listing omits one mechanism rate

- **WHEN** a resource has one valid mechanism clause and another enabled mechanism has no explicit rate-bearing clause
- **THEN** publication does not infer the missing mechanism's price from the first clause

### Requirement: Per-resource settlement input uses the common clause contract

Configured defaults, pool-declared hints, storefront pool overrides, imported resource records, and reconciliation inputs that describe settlement options MUST parse to the same typed settlement-clause model before option derivation. Unknown fields, conflicting duplicate values, role-inapplicable fields, and malformed rates MUST fail the affected candidate without creating a partially interpreted option.

#### Scenario: Imported resource overrides settlement defaults

- **WHEN** one resource record supplies its own complete settlement clauses
- **THEN** those clauses replace the configured defaults for that resource and are validated through the same grammar and registrations

### Requirement: Publication pricing migration is preview-first and atomic

Storefront publication migration MUST support TOML configuration and resource
CSV inputs through explicit check and write modes. Check mode MUST produce a
deterministic preview without changing the source or creating a backup. Write
mode MUST require a backup, preserve an exact pre-migration copy, validate the
complete proposed document through the current structured clause model and
every selected mechanism's typed publication-input validator, and replace the
source atomically with restrictive permissions. A failed validation or write
MUST leave the source unchanged. Rechecking an already migrated input MUST be
idempotent.

Automatic conversion MUST occur only when one enabled mechanism, its asset
scale, and every legacy pricing input have one complete interpretation.
Dual-mechanism pricing, hidden reserves, per-row legacy pricing, a missing asset
scale, conflicting config and row values, malformed legacy values, and any
other ambiguous population MUST be reported as conflicts without mutation.
Migration MUST NOT guess units, synthesize partial clauses, or reinterpret
`min_price` or `default_token_address` as a settlement rate or asset.

#### Scenario: Operator previews publication migration

- **WHEN** the operator runs check mode against a storefront TOML file or resource CSV
- **THEN** the tool reports the deterministic proposed changes and conflicts while the input bytes and backup set remain unchanged

#### Scenario: Unambiguous publication input is written

- **WHEN** one enabled mechanism and authoritative asset scale make every legacy price unambiguous and the operator requests write with backup
- **THEN** the tool fully validates the typed result, saves the exact original bytes, and atomically installs the restrictive-permission replacement

#### Scenario: Legacy pricing has competing interpretations

- **WHEN** dual mechanisms, hidden reserve pricing, per-row legacy pricing, a missing scale, or conflicting values could produce different clauses
- **THEN** check and write modes report the conflict and neither the source nor any existing backup is changed

#### Scenario: Generated clause fails typed mechanism validation

- **WHEN** a proposed migration contains an unknown field, invalid rate, unsupported asset, or invalid mechanism-owned input
- **THEN** migration fails before backup or mutation rather than persisting a partially validated document

### Requirement: Durable bindings govern multi-domain publication

Every storefront listing MUST have one immutable common mapping binding the listing ID, trusted site, explicit pool or Physical Resource provenance, offering mode, exact domain identity/version, collision-safe derivation identity, and public-safe versioned source envelope. Public `listing_resource.offering_mode` MUST equal the recorded offering mode. The published field, the durable binding, the projected pool declaration, and the capacity claim MUST all name that value `offering_mode`; no surface may use a second name for it. Pricing, settlement clauses, and seller policy remain on the generic listing; secret, provider, credential, SSH, and private result material MUST NOT enter the binding or the published listing.

A seller's published shape is a listing, not an offer. The published shape MUST be named `listing_resource`, and `offer` MUST be reserved for a negotiation message either party sends. No surface may accept a second spelling of the published shape, including a client attribute or a request field that holds it.

#### Scenario: One pool exposes VM and bare-metal modes

- **WHEN** a trusted pool declares both modes and both registered publication sources derive candidates
- **THEN** the storefront creates distinct VM and bare-metal listing/binding identities even when their site-local source identifiers are equal

#### Scenario: One declared mode is withdrawn

- **WHEN** the pool stops declaring one registered offering mode
- **THEN** publication closes only new-work listings for that mode while sibling listings and accepted records retain their original bindings

#### Scenario: Public mode conflicts with the contribution

- **WHEN** a normalized domain listing projects a `offering_mode` different from its registration or durable binding
- **THEN** the listing and binding transaction fails before registry publication or capacity mutation

### Requirement: Trusted listing mappings route to one site

A capacity-backed listing with a durable site mapping MUST route all capacity claims to exactly that configured site and pinned authority. Refusal, outage, missing trust, or mode disagreement at that site MUST fail closed and MUST NOT fan out to another site. An unbacked listing's durable site mapping records its origin and routes no capacity claim.

#### Scenario: A normalized listing disagrees with its binding

- **WHEN** a normalized domain listing projects an `offering_mode` different from its registration or durable binding
- **THEN** publication is refused rather than publishing a listing whose public mode disagrees with its provenance

#### Scenario: A published shape is submitted under the retired key

- **WHEN** a listing is submitted carrying the published shape under `offer_resource` or `offer`
- **THEN** it is rejected rather than accepted under a second spelling

#### Scenario: Another site could satisfy the claim

- **WHEN** the bound site refuses a capacity-backed listing's claim while another configured site has compatible capacity
- **THEN** the storefront reports the bound-site refusal and the other site receives zero calls

#### Scenario: An unbacked listing's origin site is unreachable

- **WHEN** the origin site recorded on an unbacked listing's binding is unreachable
- **THEN** no capacity claim is attempted at it or at any other site

### Requirement: Bare-metal hosted publication intersects all authorities

A bare-metal listing MAY publish exact `fiat.stripe.v1` alternatives only from a complete non-stale trusted selected-site projection with exclusive allocation, SSH capability, hosted authority/account/profile readiness, condition resolver readiness, and compatible offer, funding, fulfillment, and capacity windows. Each ready `card.v1`, `us_bank_transfer.v1`, or `us_ach_debit.v1` profile is a separate deterministic option; one unavailable profile MUST NOT suppress ready alternatives or legacy Alkahest escrows. The option's interaction value MUST be exactly `interactive` or `saved_instrument`; `off_session` is policy behavior, not a wire value, and push bank transfer MUST remain interactive.

#### Scenario: Pending funding cannot extend capacity

- **WHEN** a slow funding profile remains pending at the accepted offer or billable-hold boundary
- **THEN** the old listing cannot be renewed or rebound
- **AND** later availability requires a fresh signed listing and negotiation

### Requirement: API-credit publication composes independent settlement alternatives

A quota-backed `api_credits.v1` listing MUST publish `settlement_options` from
each complete ready hosted clause and `accepted_escrows` from valid Alkahest
entries as independent alternatives. Every hosted option MUST bind the exact
service, quantity pricing basis, canonical seller/claimant, condition,
currency, profile, interaction, account, expiry policy, and rate. One unready
profile MUST suppress only its own option, and hosted-only publication MUST
remain valid with an empty escrow list.

#### Scenario: Quota and three hosted profiles are ready
- **WHEN** card, US bank transfer, and ACH clauses pass readiness for one sellable API-credit resource
- **THEN** the listing exposes three distinct deterministic hosted options alongside any Alkahest escrows

#### Scenario: Hosted clause is incomplete
- **WHEN** its profile, authority, account, condition, or currency readiness fails
- **THEN** only that hosted alternative is omitted and publication emits a safe clause-scoped blocker

### Requirement: A listing's origin site is not its admission authority

Every storefront listing binding MUST record the site the listing originated from
and, separately, whether an admission authority stands behind it. The origin site
is populated for every listing including an unbacked one, because an unbacked
listing is projected from a site like any other.

The durable binding MUST carry an explicit backing discriminator rather than
encoding the category as an absent site or an absent field. The discriminator MUST
be covered by the binding's immutability guarantee so a listing cannot change
category after binding, and a binding written without it MUST be refused rather
than classified by a default.

Publication provenance MUST separate common listing identity — origin site,
offering mode, and source declaration identity — from admission provenance. Only
operations that reserve, commit, release, schedule, or dispatch MUST require the
capacity-backed binding variant; operations that compare, copy, or carry listing
identity MUST accept either.

#### Scenario: An unbacked listing binds

- **WHEN** a storefront publishes a listing derived from a pool declaring no admission authority
- **THEN** the durable binding records the origin site, the offering mode, the source declaration identity, and an explicit unbacked discriminator
- **AND** the binding is otherwise indistinguishable in shape from a capacity-backed listing's

#### Scenario: A binding names no backing

- **WHEN** a writer inserts a listing binding without a backing discriminator
- **THEN** the insert is refused rather than recorded as either value

#### Scenario: A bound listing's backing is changed

- **WHEN** a writer attempts to change a recorded binding's backing discriminator
- **THEN** the change is refused and the binding is unchanged

#### Scenario: An unbacked listing enters a negotiation

- **WHEN** a buyer opens a negotiation against an unbacked listing
- **THEN** the durable listing binding is copied to the negotiation thread with its origin site, offering mode, domain identity, and contract version
- **AND** no step of the negotiation lifecycle refuses the listing for lacking an admission authority

#### Scenario: A capacity operation receives an unbacked listing

- **WHEN** a reservation, commit, release, scheduling, or dispatch operation is attempted for an unbacked listing
- **THEN** the operation is refused before any effect, so no reservation record is created with no authority behind it

### Requirement: Backing is declared by the projected pool

A storefront MUST resolve a listing's backing from the declared value on the
projected pool it derives from, reading that projected tag live at each point of
need and never caching it as storefront-local inventory. The backing discriminator
recorded on a listing's durable binding is derived from that value at publication
and is immutable; it is a storefront fact about a bound listing rather than a cached
copy of a site fact, and the two MUST NOT be conflated. Backing MUST NOT be inferred
from absent capacity data, an empty projection, or a stale generation.

A storefront MUST judge a projection's declarations jointly, per site and per
projection generation. A generation that projects pools, none of which carries either
the backing or the advertisement declaration, comes from a producer that predates them:
every pool in it MUST resolve as capacity-backed with delivery authorization serving
as advertisement authorization, reproducing the contract that applied before the
declarations existed, under one compatibility rule that is logged and reported in
the storefront's system status. That rule is retained until a future change acquires
a reliable signal that no producer relies on it; self-hosted sites may lag without
bound, so no release count is a meaningful removal condition.

In any other generation, a pool whose declarations are absent, malformed, or
violate a cross-declaration rule is unresolvable. An unresolvable pool MUST yield no
new listing candidates, and its existing listings MUST be neither closed nor
refreshed until it resolves, because an unknown declaration is not a withdrawn one.
Each unresolvable pool MUST be reported in the storefront's system status with the
reasons it could not be resolved.

#### Scenario: A producer predates the declarations

- **WHEN** a storefront ingests a site's projection generation in which no pool declares backing or advertisement authorization
- **THEN** every pool resolves as capacity-backed with delivery authorization serving as advertisement authorization
- **AND** the compatibility rule is logged and reported in system status
- **AND** listings previously derived from that site continue to publish unchanged

#### Scenario: A generation projects no pools

- **WHEN** a site's projection generation contains no pools
- **THEN** it is not read under the compatibility rule, and system status does not report the site as an older producer

#### Scenario: A producer omits a declaration for one pool

- **WHEN** a projection generation declares backing and advertisement for some pools and omits them for another it projects
- **THEN** the omitting pool is unresolvable rather than resolving to either value

#### Scenario: A producer emits only one of the two declarations

- **WHEN** a projection generation carries a backing declaration on some pool but no advertisement declaration on any
- **THEN** the generation is not read as an older producer's, and every pool lacking either declaration is unresolvable

#### Scenario: A declared backing value is unrecognized

- **WHEN** a projected pool declares a backing value outside the accepted set
- **THEN** that pool is unresolvable rather than falling back to a structural default

#### Scenario: An unresolvable pool has published listings

- **WHEN** a pool with open listings becomes unresolvable
- **THEN** no new listing is derived from it, its existing listings stay as they are, and system status names the pool and its problems
- **AND** when the pool resolves again its listings are reconciled against the resolved declarations

### Requirement: A listing advertises only a mode its pool authorizes

A listing a storefront derives from a site's resource-pool projection MUST offer only
an offering mode its Resource Pool declares advertisable, whether the listing is
capacity-backed or unbacked. The listing's offering mode continues to resolve from
the frozen contribution registration, and the public offer's mode MUST continue to
equal the recorded offering mode. Bare-metal publication derives its candidates from
the site's capacity snapshot rather than that projection, and reads no pool
declaration.

The pool's delivery authorization MUST continue to be rechecked at reservation,
scheduling, and provider dispatch, and those rechecks apply only to capacity-backed
listings because only they reach those layers.

#### Scenario: A pool authorizes advertisement but not delivery

- **WHEN** an unbacked pool declares a mode advertisable that its provider configuration does not prove deliverable
- **THEN** a listing derived from that pool may offer that mode
- **AND** no reservation, scheduling, or dispatch path is reachable for that listing

#### Scenario: A listing offers a mode its pool does not authorize

- **WHEN** candidate derivation would produce a listing offering a mode its pool does not declare advertisable
- **THEN** the candidate is refused rather than published

### Requirement: A listing's identity is the physical resource it offers

A listing's identity MUST be the physical resource it offers: the supply it draws
from (site, and pool or Physical Resource), what the resource is (offering mode,
resource type and subtype, and categorical attributes), where it is (region), and how
much of it one listing offers (the enumerated quantity and every other declared
dimension the listing publishes). Every other published field — price and pricing
hints, settlement options, maximum duration, and service level — is a term of sale.

A listing commits only to the fields it publishes. A field a listing does not publish
is no commitment. Reconciliation MUST NOT add an identity field to a listing that did
not publish one, because that would make a new commitment under an existing listing
identity.

A change to a term of sale MUST update the listing in place and retain its identity. A
change to an identity field MUST NOT be applied to an existing listing in place. Where
the listing's derivation identity captures the changed field, the existing listing
closes and a newly derived listing is published. Where it does not, the existing
listing MUST close and MUST NOT reopen while its published value differs from its
source, and the refusal MUST be logged naming the source and the differing fields.

Capacity backing is not an identity field under this requirement: it is recorded on
the binding at creation and governed by the backing requirements.

#### Scenario: A term of sale changes

- **WHEN** the price or settlement options behind an open listing change
- **THEN** the listing is updated in place at the storefront and every registry, and retains its listing identity and derivation key

#### Scenario: An identity field outside derivation identity changes

- **WHEN** a declaration behind an open listing changes a published categorical attribute that the listing's derivation identity does not capture
- **THEN** the listing closes and is not reopened while the published value differs from the declaration
- **AND** the refusal is logged naming the declaration and the differing attribute

#### Scenario: A newly published field is absent from an existing listing

- **WHEN** publication begins emitting an identity field that an existing listing did not publish
- **THEN** the existing listing is neither closed nor updated to carry the field, because it made no commitment about it
- **AND** listings published afterwards carry the field

#### Scenario: A pool returns with the opposite backing

- **WHEN** a site's pool is recreated under an existing pool ID with backing opposite to the discriminator on listings bound from it
- **THEN** those listings close and are not reopened, and the refusal is logged naming the pool
- **AND** no replacement listing binds under their derivation identity

### Requirement: Source publication and capacity availability reconcile separately

Source-publication reconciliation MUST apply to every listing regardless of backing:
a removed or disabled source declaration MUST close the listings derived from it, and
a changed source declaration MUST be reflected in what is published according to the
listing identity requirement. A projected pool that declares itself disabled is a
disabled source. Source-publication reconciliation MUST re-derive open listings and
compare them with what is published, so that a change to a term of sale reaches an open
listing.

Every path that reopens a listing MUST apply the same comparison first: a listing whose
published identity differs from its source, or whose binding's backing disagrees with
its source's, MUST NOT be reopened by any path, including one driven by a capacity
event.

Capacity-availability reconciliation and its close-before-reopen sequencing MUST
apply only to capacity-backed listings. An unbacked listing's quantity is bounded by
what its source declares, never by availability, which is what its inexhaustibility
means; it is not an exemption from having its published state follow its
declaration.

An unbacked listing MUST be derived only from the site projection. No
storefront-local table may source its shape or capacity; its storefront-local records
are its listing row and its immutable binding. That prohibition does not exempt it
from source-publication reconciliation.

#### Scenario: An unbacked listing's source declaration is removed

- **WHEN** a capacity resource or pool an unbacked listing derives from is removed or disabled
- **THEN** the published listing closes

#### Scenario: An unbacked source is re-enabled

- **WHEN** a disabled declaration behind closed unbacked listings is enabled again with the same declared shape
- **THEN** those listings reopen under their original listing identities

#### Scenario: A declared shape change alters derivation identity

- **WHEN** a source declaration changes a field the derivation source envelope carries
- **THEN** the existing listing closes and a newly derived listing is published with a different derivation key
- **AND** the original binding row is unmodified

#### Scenario: A pool is disabled at its site

- **WHEN** a projected pool that open listings derive from declares itself disabled
- **THEN** those listings close

#### Scenario: A capacity release would reopen a diverged listing

- **WHEN** a capacity event makes a closed listing's slice available again while a published identity field of that listing still differs from its source
- **THEN** the listing is not reopened and the refusal is logged

#### Scenario: Capacity deltas do not reach an unbacked listing

- **WHEN** capacity-availability reconciliation runs, including after a settlement against an unbacked listing
- **THEN** no unbacked listing is closed, reopened, or resized by it

### Requirement: The seller's inventory guard checks a listing against its own source

Before a seller agrees terms, seller negotiation policy MUST recheck every published
field of the listing that is sourced from its declaration or pool against that
source: the listing's own site and pool or Physical Resource, never a resource
elsewhere. A categorical field MUST equal its source and a quantity MUST fit the
declared capacity. Fields whose authority is the storefront are not rechecked.

Seller policy MUST additionally check that the listing's published quantity is
available only for a capacity-backed listing. For an unbacked listing it MUST NOT
consult availability or contact a site authority.

A declared-match failure MUST be reported with a reason distinct from an availability
failure, so a buyer and an operator can tell a shape the seller no longer declares
from capacity that is temporarily taken.

#### Scenario: An unbacked listing matches its declaration

- **WHEN** a buyer negotiates against an unbacked listing whose published fields match its enabled source declaration
- **THEN** the declared match passes without any availability read or site call

#### Scenario: A declaration no longer supports its listing

- **WHEN** a buyer negotiates against a listing whose source declaration has shrunk below, or been disabled beneath, its published shape
- **THEN** seller policy rejects with a declared-match reason rather than an availability reason

#### Scenario: Matching capacity exists only elsewhere

- **WHEN** a listing's own source no longer supports it but another pool or site holds matching available capacity
- **THEN** seller policy rejects the listing

#### Scenario: A backed listing matches but capacity is taken

- **WHEN** a capacity-backed listing matches its declaration but its published quantity is not available
- **THEN** seller policy rejects with the availability reason

#### Scenario: A fungible listing matches one member

- **WHEN** a buyer negotiates against a listing derived from a fungible pool whose enabled members declare different counts
- **THEN** the declared match passes only if some single enabled member has equal categorical attributes and declares at least the published quantity

#### Scenario: A dry-run evaluation applies the same checks

- **WHEN** a seller evaluates a proposal against a listing without opening a negotiation
- **THEN** the evaluation applies the same declared match and, for a capacity-backed listing only, the same availability check as a negotiation round

### Requirement: A listing's published shape comes from its source declaration

A listing's published compute shape is derived from the shape its source declaration carries,
and a VM listing's is its listing shape; whether it is published is decided against its source
declaration, for capacity-backed and unbacked listings alike.
Nothing in publication verifies that shape against hardware, and this requirement makes no
claim that it does.

Derivation MUST NOT substitute a value for a quantity a declaration does not carry. A
declaration that omits the quantity a domain enumerates listings by (for VM, the quantity its
default shapes are enumerated by) MUST yield no
listing, and the omission MUST be reported to the operator naming the declaration. A
declaration that declares that quantity as zero MUST yield no listing without a
report. A declaration whose quantity is malformed, or a projected member that does not state its
resource kind, MUST be treated as unresolvable and reported:
it yields no new listing and its existing listings are held. In a fungible pool one
unresolvable member holds every listing derived from the pool, because which shapes its
members are feasible for cannot be decided without it; in a specific-resource pool it holds
only its own.

Where a listing is capacity-backed, whether its shape is published additionally follows the
availability its site projects, so a pool's published set moves as capacity is reserved and
released. An unbacked fungible pool's default shapes range up to the largest single
member's declared quantity, never a sum across members, because a reservation would land on
one member. A listing's own quantities never move: availability decides only whether it is
published. An unbacked listing has no availability to bound it and no reservation consumes
it; that difference is carried by the listing's published backing and MUST NOT be encoded a
second time in a separate published field.

#### Scenario: A declaration omits the enumerated quantity

- **WHEN** a source declaration carries no GPU count
- **THEN** no VM listing is derived from it, listings previously derived from it close, and the operator is told which declaration omits it

#### Scenario: A declaration declares zero

- **WHEN** a source declaration declares a GPU count of zero
- **THEN** no VM listing is derived from it and no report is made

#### Scenario: An unbacked listing's published quantity does not move

- **WHEN** any number of buyers settle against an unbacked listing
- **THEN** its published quantity is unchanged, because no reservation consumes it

#### Scenario: A listing's quantities do not follow availability

- **WHEN** reservations consume part of a capacity-backed member from which a listing is
  published, and the member is still feasible for its shape
- **THEN** the listing stays open with its quantities unchanged

### Requirement: A backing change closes and republishes

A listing's backing is fixed for the life of its durable binding. Where the supply
behind a listing moves between backed and unbacked, the existing listing MUST close
and a new listing MUST bind with its own durable identity and its own backing
discriminator.

An implementation MUST NOT attempt an in-place update of a listing's backing, in
either the durable binding or the published payload. Because the pool a listing
derives from carries backing that is itself fixed at creation, a supply move is a
move between pools, and the republished listing's derivation identity differs by
construction.

#### Scenario: Supply moves from unbacked to backed

- **WHEN** the supply behind an unbacked listing is moved to a pool declaring capacity backing
- **THEN** the unbacked listing closes and a new listing binds with a distinct durable identity and a capacity-backed discriminator
- **AND** the original binding row is unmodified

### Requirement: An unbacked listing publishes only settlement options its domain does not fulfil through capacity

A domain that can publish unbacked listings MUST declare in its settlement
composition, for every settlement mechanism it composes, whether settling through that
mechanism delivers through the domain's capacity-backed fulfillment. The declaration
MUST be explicit for each composed mechanism and MUST NOT default. A domain whose
listings are always capacity-backed owes no such declaration.

Publication MUST NOT give an unbacked listing a settlement option whose mechanism its
domain fulfils through capacity. Such options MUST be dropped from an unbacked
candidate with an operator-visible notice naming the pool and the dropped mechanisms.
An unbacked candidate left with no settlement option MUST yield no listing, with the
same notice. Capacity-backed candidates are unaffected.

This is decided by how the domain composes each mechanism, so no pool-level or
listing-level field names a settlement mechanism.

#### Scenario: Every composed mechanism fulfils through capacity

- **WHEN** an unbacked candidate's resolved settlement clauses name only mechanisms its domain fulfils through capacity
- **THEN** no listing is derived from it and an operator notice names the pool and the dropped mechanisms

#### Scenario: One mechanism settles without fulfillment

- **WHEN** an unbacked candidate's resolved clauses name one mechanism its domain fulfils through capacity and one it does not
- **THEN** the listing publishes only the option whose mechanism does not reach capacity-backed fulfillment, and the notice names the dropped mechanism

#### Scenario: A backed candidate names the same mechanisms

- **WHEN** a capacity-backed candidate's resolved clauses name mechanisms its domain fulfils through capacity
- **THEN** every ready option publishes as before

### Requirement: Publication runs as a controllable storefront lifecycle loop

The VM storefront, alone or within the combined compute-family storefront, MUST run
its publication in its own process as a timer-driven lifecycle loop. Bare-metal
publication is operator-invoked and is outside this requirement. Each cycle derives candidates from its configured sources, publishes new
listings, refreshes open listings, closes listings whose source no longer supports
them, holds listings whose source is unresolvable, and reopens listings reconciliation
closed, subject to the listing identity comparison. A change in a site's resource-pool
projection generation MUST wake the loop.

The loop MUST be held by the storefront's lifecycle pause like every other storefront
loop, without affecting trading. While held, an operator MUST be able to run exactly one
cycle — the cycle the timer runs, not an alternate transition — and to preview one: a
preview MUST report every publish, refresh, close, reopen, and hold the cycle would
perform with its reason, MUST apply none of them, and MUST report the same result when
repeated.

The loop MUST publish through the storefront's own services. A publication command
MUST reach the loop only through the storefront's API and MUST NOT read or write the
storefront's database directly.

The loop MUST build only the publication sources of the domains it publishes. A
storefront may register several domains whose publication runs in different places;
each publisher names the domains it builds, and naming one no registration carries
MUST fail before any source is built.

#### Scenario: A site declares new supply

- **WHEN** a site's projection gains an advertisable pool with enabled declarations and the loop is not held
- **THEN** the storefront publishes the derived listings without any operator command

#### Scenario: The loop is held

- **WHEN** the lifecycle loops are held and a site's projection changes
- **THEN** no listing is published, refreshed, closed, or reopened until an operator runs a cycle or resumes the loops

#### Scenario: An operator previews a cycle

- **WHEN** an operator previews a publication cycle twice without an intervening change
- **THEN** both previews report the same planned actions and reasons, and no listing, binding, or registry publication changed

#### Scenario: A storefront registers another domain beside the one its loop publishes

- **WHEN** a storefront registers both the domain its loop publishes and another whose publication runs elsewhere
- **THEN** each cycle builds only the loop's own domain's sources and completes

#### Scenario: An operator runs one cycle while held

- **WHEN** an operator runs one publication cycle while the loops are held
- **THEN** exactly the actions a preview reported are applied and the loops remain held

### Requirement: A seller's close is durable

Every close of a listing MUST record whether its seller or reconciliation closed it,
and a closed listing MUST NOT be recorded without that reason. Reopening a listing
MUST clear it. A later close of a listing its seller closed, by any write, MUST keep
the seller as its reason.

No reconciliation path — a capacity event, the publication loop, or any other — MUST
reopen a listing its seller closed, and publication MUST NOT bind a replacement listing
under that listing's derivation identity. A seller MUST be able to reopen a listing
they closed, after which it is reconciled like any open listing. A seller request to
reopen a listing reconciliation closed MUST be refused with a conflict naming the
reason, because its source does not currently support it.

#### Scenario: A seller closes a listing

- **WHEN** a seller closes an open listing and a later capacity event or publication cycle finds its slice available
- **THEN** the listing stays closed and no replacement listing is published for that slice

#### Scenario: A seller reopens a listing they closed

- **WHEN** a seller resumes a listing they closed
- **THEN** it reopens, its closure reason is cleared, and it is published and reconciled like any open listing

#### Scenario: A seller tries to reopen a reconciliation close

- **WHEN** a seller resumes a listing that reconciliation closed
- **THEN** the request is refused with a conflict naming the closure reason and the listing is unchanged

#### Scenario: Reconciliation closes a listing its seller already closed

- **WHEN** reconciliation writes a close for a listing its seller closed
- **THEN** the listing's closure reason remains the seller, and no later reconciliation reopens it

#### Scenario: A close names no reason

- **WHEN** a writer closes a listing without recording who closed it
- **THEN** the write is refused

### Requirement: Registries converge on each listing's local status

This requirement governs VM publication and API-credit publication; bare-metal
publication is outside it.

For those, a listing's local status is the publication decision and its registries
follow it. A close or reopen MUST change the local listing before any registry is
told, and a local change that fails MUST be reported to its caller with no registry
told — a seller's close is reported as retryable. Each registry's outcome for every
publish, close, and reopen MUST be recorded durably. Every publication pass — each
VM publication cycle and each API-credit capacity reconciliation — MUST then resend,
to each configured registry whose recorded outcome disagrees with its listing's
local status, exactly what that status implies — a close for a closed listing, and
for an open one the listing republished and reopened — and to no other registry. A
registry still unreachable stays recorded as diverged for the next pass.

#### Scenario: A registry misses a close

- **WHEN** a listing closes locally and one of its registries fails the close
- **THEN** the next publication pass sends the close to that registry alone

#### Scenario: A registry misses a reopen

- **WHEN** a listing reopens locally and one registry fails to reopen it
- **THEN** the next publication pass republishes and reopens the listing at that registry alone

#### Scenario: A local close fails

- **WHEN** the local close of a listing fails
- **THEN** no registry is told, and a seller's close is reported as retryable with the listing unchanged

### Requirement: Every VM listing is a listing shape

Every VM listing MUST be a listing shape: a family-grouped capability shape in the VM
domain's vocabulary. Bare-metal and API-credit listings are not listing shapes. A pool's VM
shapes MUST come from exactly one source, in this precedence:

1. The storefront's override for that site and pool, when it states shapes.
2. Otherwise, the pool's own `listing_shapes` hint for the listing's offering mode.
3. Otherwise, the VM domain's default shape generator.

A stated list MUST replace the lower sources as a whole. How many of a shape a pool can serve
MUST be derived from its capacity declarations, and MUST NOT be declared or published.

**The VM default.** The VM domain's default generator MUST yield, for each GPU model among a
pool's enabled members, one shape per GPU count from one to the largest declared GPU count
among that model's members. Each such shape MUST declare the GPU family only. Every VM shape
MUST name a GPU count and a GPU model. A fungible pool MUST publish one listing per feasible
shape. A specific-resource pool MUST publish one listing per member per shape that member is
feasible for.

**Commitment.** A listing MUST publish every quantity and attribute its shape declares,
flattened through the domain's schema, and MUST NOT publish a quantity its shape does not
declare. The capacity claim built from a listing MUST request exactly its shape's quantities.
A listing commits only to what its shape declares. For a dimension its shape omits it makes
no commitment, and what is provisioned for that dimension is the site's to decide.

#### Scenario: A site declares shapes for a pool

- **WHEN** a pool's projected `listing_shapes` hint lists two VM shapes and the storefront
  has no override for that site and pool
- **THEN** the storefront publishes one listing per feasible shape, each carrying its shape's
  GPU count, GPU model, and every other declared quantity, and publishes no default shapes
  for the pool

#### Scenario: The storefront replaces a pool's shapes

- **WHEN** the storefront's override for a site and pool states one shape while the pool's
  hint states two
- **THEN** only the override's shape is published for that pool

#### Scenario: A pool states no shapes

- **WHEN** neither the storefront's override nor the pool's hint states shapes for a pool
  whose enabled members all declare one GPU model
- **THEN** the pool publishes one listing per GPU count its members make feasible, each
  carrying GPU count and model and no other dimension, as its listings did before shapes

#### Scenario: A pool's members declare different GPU models

- **WHEN** a fungible pool without stated shapes holds members declaring two different GPU
  models
- **THEN** the default generator yields each model's GPU counts as separate shapes, and each
  listing names the model of the members that are feasible for it

#### Scenario: A shape omits memory

- **WHEN** a VM shape declares GPU count, GPU model, and vCPU count but no memory family
- **THEN** its listing publishes no `ram_gb`, its capacity claim requests no memory, and any
  memory provisioned for the resulting VM is the site's to decide

#### Scenario: Eight single-GPU VMs from one host

- **WHEN** a fungible pool whose one member declares eight GPUs lists a one-GPU shape
- **THEN** the storefront publishes one listing for that shape, and successive reservations
  against it each reserve one GPU and the shape's other quantities until the member cannot
  admit another

### Requirement: A listing shape is published only where a source member is feasible for it

A shape MUST be publishable only where a member of its source satisfies the capacity claim
its listing would produce under the site authority's exported resource-feasibility
predicate:

- for a fungible pool, some single enabled member;
- for a specific-resource pool, that member.

**Declared and available capacity.**
- Feasibility MUST be judged against the member's declared capacity.
- For a capacity-backed listing the shape MUST additionally be feasible against current
  availability. For a fungible pool that availability is sourced from grouped capacity data
  when it has loaded for the site, and otherwise from the member's own projected
  availability.
- A member whose availability is not reported is unknown rather than empty and MUST be judged
  on its declared capacity.
- An unbacked listing MUST be judged on declared capacity alone.

**Feasibility is not admission.** Publication does not establish that a reservation will be
admitted; the site authority's reservation remains the final admission boundary. A published
listing MAY be refused at reservation for a reason the resource-feasibility predicate does not
evaluate, such as the pool provider's host requirement, holds over the requested lease
window, or a physical-host conflict.

**When no member is feasible.**
- A stated shape that no member is feasible for MUST yield no listing and MUST be reported in
  the storefront's system status, naming the site, the pool, the shape, and what was not
  feasible.
- A default shape that no member is feasible for against declared capacity MUST be reported
  once per pool, naming the claim attribute that no enabled member declares. A default shape
  that fails only against current availability MUST NOT be reported.
- Publication MUST NOT shrink a shape to make it feasible, and MUST NOT substitute another
  source's shapes for a stated list with an infeasible shape.
- A pool whose shape hint the domain cannot read MUST yield no new listing, MUST be reported,
  and its existing listings MUST be held rather than closed.

The seller's inventory guard MUST apply the same feasibility check to a listing's declared
match.

#### Scenario: An override names a model the pool does not have

- **WHEN** a storefront override lists a shape whose GPU model no enabled member of the pool
  declares
- **THEN** no listing is published for that shape and system status reports it, naming the
  model as what was not feasible

#### Scenario: A declaration shrinks beneath a published shape

- **WHEN** a member's declared memory falls below the memory of a shape published from it
  and no other member is feasible for the shape
- **THEN** the listing closes through source reconciliation and the infeasible shape is
  reported

#### Scenario: A backed shape's memory is taken

- **WHEN** a capacity-backed shape's GPUs are free on a member but the member's available
  memory is below the shape's
- **THEN** the shape is not publishable from that member

#### Scenario: A pool's region exists only as a pool hint

- **WHEN** a pool's `region` is stated only in its `region` hint and none of its enabled
  members declares a `region` attribute
- **THEN** the pool publishes no listing, and system status reports once for the pool that no
  member declares the claimed region

#### Scenario: A published listing is refused at reservation

- **WHEN** a listing is published because a member is feasible for its shape, and the site
  refuses the reservation for a reason feasibility does not evaluate
- **THEN** the refusal stands, and publication is not treated as having guaranteed admission

#### Scenario: A pool's shape hint cannot be read

- **WHEN** a pool's `listing_shapes` hint for the VM mode contains a family or field outside
  the VM vocabulary
- **THEN** no new listing is derived from the pool, its existing listings are held, the pool
  does not fall back to the default generator, and system status reports the problem

### Requirement: A VM listing's derivation identity includes its shape

**Identity.**
- Every VM listing's derivation identity MUST include a canonical digest of its shape, taken
  over the family-grouped form rather than the flattened field names, whichever source
  produced the shape.
- Its durable binding MUST record the shape in the current source envelope version.
- A stored listing's derivation identity MUST be read from its binding rather than
  recomputed from its published fields.
- A change to a pool's shapes MUST therefore close listings under a withdrawn shape and
  publish listings under a new one.

**Listings bound before shapes.** A listing bound under the earlier envelope, which carries
no shape, MUST NOT be reopened, and while open MUST close through source reconciliation.

**Seller state carries across.** Before any lifecycle loop runs, the storefront MUST carry a
seller's close and a seller's pause from each such listing to the listing bound for its
equivalent default shape:
- a listing its seller closed MUST have its successor bound closed by its seller and
  unpublished;
- a paused listing MUST have its successor bound paused.

The carry-over MUST be idempotent.

#### Scenario: A shape is edited

- **WHEN** a pool's only listed shape changes its memory from 64 to 96 GiB
- **THEN** the listing for the 64 GiB shape closes and a listing with a distinct derivation
  key is published for the 96 GiB shape, leaving the original binding row unmodified

#### Scenario: A site declares the shape its pool published by default

- **WHEN** a pool publishing a default one-GPU shape gains a `listing_shapes` hint stating
  exactly that shape
- **THEN** the listing keeps its derivation key and is neither closed nor republished

#### Scenario: A storefront upgrades

- **WHEN** a storefront whose listings were bound before shapes starts for the first time
  with shapes
- **THEN** each open earlier listing closes once and a listing for its equivalent shape
  publishes under a shape-bearing derivation key

#### Scenario: A seller-closed listing crosses the upgrade

- **WHEN** a listing its seller closed was bound before shapes
- **THEN** after upgrade the listing for its equivalent default shape is closed by its
  seller, is not published, and no reconciliation reopens it until the seller does

#### Scenario: A paused listing crosses the upgrade

- **WHEN** an open, paused listing was bound before shapes
- **THEN** after upgrade the listing for its equivalent default shape is paused and withheld
  from registries until the seller resumes it

### Requirement: Storefront pool overrides are site-scoped and durable

A storefront's per-pool overrides MUST be stored durably, keyed by site, pool, and offering
mode. Each override belongs to exactly one offering mode and MUST be validated by the market
that serves that mode; a write for a mode no market serves MUST be refused. An override MAY
state its market's commercial terms, settlement clauses, and listing shapes. An override
MUST NOT state region or capacity backing, and its offering mode MUST NOT be defaulted. A field an override leaves unset MUST fall
through to the next precedence tier. Listing shapes and settlement clauses MUST each replace
the lower tier's list as a whole, and an empty shape list or an empty settlement-clause list
MUST be refused.

Within the storefront-override tier, a value in the site-scoped store MUST take precedence
over the home-site legacy override record. While a legacy value is in effect for a pool, the
storefront's system status MUST report it, naming each field whose value came from the legacy
record.

Every listing-derivation path that computes a listing's derivation identity, including
source reconciliation and the inventory guard, MUST resolve the override tier, so that
publication and reconciliation derive the same listings.

An override MUST outlive the projection of its pool. The storefront's system status MUST
report every stored override in exactly one state, judged against the projection its
listings are derived from:

- `inactive` when listings derive from local tables, where no override applies;
- `site_unconfigured` when the storefront does not configure the override's site;
- `unknown` when the site is configured but no projection of it is held;
- `orphaned` when the projection derived from holds no such pool;
- `applied` otherwise.

A site with no projection held MUST NOT make an override `orphaned`, because the pool's
absence is not known. An orphaned override has no effect. When its pool returns, the
override MUST apply again.

#### Scenario: One pool is overridden for two offering modes

- **WHEN** overrides are stored for the same site and pool under two offering modes
- **THEN** each applies only to that mode's listings and is validated by that mode's market

#### Scenario: No market serves the override's mode

- **WHEN** an administrator writes an override for an offering mode no installed market
  serves
- **THEN** the write is refused without contacting the site and nothing is stored

#### Scenario: Two sites name a pool identically

- **WHEN** overrides are stored for pool `gpu` at site `a` and at site `b`
- **THEN** each applies only to listings derived from its own site's pool

#### Scenario: A pool at a non-home site is overridden

- **WHEN** an override states an SLA for a pool at a site other than the storefront's first
  configured site
- **THEN** listings derived from that pool publish the overridden SLA

#### Scenario: An override is deleted over a legacy value

- **WHEN** an override's SLA is deleted for a home-site pool whose legacy override record
  also states an SLA
- **THEN** the legacy SLA applies and system status reports that a legacy value is in effect
  for the pool

#### Scenario: A pool disappears and returns

- **WHEN** a pool with an override leaves its site's projection and later reappears
- **THEN** the override is retained and reported as orphaned while the pool is absent, and
  applies again once the pool is projected

#### Scenario: A site's projection has not loaded

- **WHEN** an override names a configured site whose projection the storefront has never
  loaded
- **THEN** system status reports the override as unknown rather than orphaned, and nothing
  is closed or published for it

#### Scenario: Listings derive from local tables

- **WHEN** a storefront deriving listings from its local tables accepts an override write
  whose pool its site's live projection contains
- **THEN** the override is stored, no listing changes, and system status reports it as
  inactive

#### Scenario: An override shapes a pool's listings

- **WHEN** an override states a shape for a pool and a publication cycle has published it
- **THEN** a later capacity reconciliation derives the same listing and does not close it

### Requirement: Storefront pool overrides are written against the site's live projection

A storefront MUST expose authenticated administrator operations to replace, read, list, and
delete a pool override. They MUST address the site, pool, and offering mode in the request
body or query rather than the path, and MUST bind them into the signed resource with an
unambiguous encoding. Replacement MUST replace the whole record. Deletion MUST be idempotent.

Before accepting a replacement, the storefront MUST refuse:

- a site it has not configured;
- a structurally invalid record, including a shape outside the domain's vocabulary.

It MUST then fetch that site's resource-pool projection live through the site's
authenticated client, not from its cache:

- a pool absent from the live projection MUST be refused;
- an unreachable site, or a response that does not verify, MUST be refused as retryable,
  with a reason distinct from an absent pool;
- a pool present in the live projection MUST be accepted even when its declarations are
  unresolvable.

A shape no member of the live projection is feasible for MUST NOT cause refusal. The
response MUST report feasibility per shape against that live projection and identify the projection generation it
used. After accepting a write, the storefront MUST cause its cached projection of that site
to refresh and its publication loop to run, without writing the live result into the cache
itself. A failed refresh MUST NOT fail the accepted write.

#### Scenario: The pool is unknown to the site

- **WHEN** an administrator writes an override for a pool the site's live projection does
  not contain, while the storefront's cached projection still lists it
- **THEN** the write is refused and nothing is stored

#### Scenario: The site is unreachable

- **WHEN** an administrator writes an override while the named site cannot be reached
- **THEN** the write is refused as retryable, naming the site as unavailable rather than the
  pool as unknown

#### Scenario: An override's shape is feasible nowhere

- **WHEN** an administrator writes an override whose only shape no member of the live
  projection is feasible for
- **THEN** the override is stored, the response reports the shape as infeasible, and
  the next publication cycle publishes no listing for it

#### Scenario: A shape outside the vocabulary

- **WHEN** an administrator writes an override whose shape names a family or field the
  domain does not define
- **THEN** the write is refused without contacting the site

### Requirement: A site whose projection is not held holds its listings

A storefront that derives listings from site projections MUST treat a configured site whose
resource-pool projection holds no value as unknown, not empty: every listing derived from
that site MUST be held, neither closed nor refreshed, until the site's projection holds a
value. Such a storefront MUST NOT derive listings from its local tables because no site's
projection is held.

#### Scenario: The storefront starts while a site is unreachable

- **WHEN** a storefront with open listings from a site restarts while that site cannot be
  reached, and a publication cycle runs
- **THEN** those listings stay open, and none is closed as having lost its source

#### Scenario: No site's projection is held

- **WHEN** no configured site's projection holds a value and a publication cycle runs
- **THEN** no listing is derived from the storefront's local tables and no listing is
  closed

#### Scenario: The site returns

- **WHEN** the unknown site's projection loads
- **THEN** its listings are reconciled against it as usual

### Requirement: An operation that changes a site's capacity reconciles against that site's current projection

A storefront operation that changes a site's capacity and reconciles listings inline (an
administrator reservation, a fulfillment event, or a failure action that releases capacity)
MUST refresh its cached projection of that site before reconciling. It MUST reconcile
against the same projection publication derives from, never against local tables where
listings derive from projections. Its response MUST report the listings its own change
closed or reopened.

The refresh belongs to the operation: it MUST NOT start or advance any background loop. A
failed refresh MUST NOT fail the operation; reconciliation then uses the last generation
the storefront holds.

#### Scenario: A reservation makes a larger listing infeasible

- **WHEN** an administrator reserves two of a member's four GPUs while the storefront's
  loops are paused
- **THEN** the reservation's response reports the listings whose shapes no longer fit as
  closed, and keeps open those that still fit

#### Scenario: A later reservation does not report an earlier one's closes

- **WHEN** a second reservation at the same site follows the first
- **THEN** its response reports only listings its own reservation made infeasible, and none
  the first reservation already closed

## Evidence

- Canonical listing, negotiation, settlement, fulfillment, and stage-log principals: `core/storefront/tests/unit/test_identity_migrations.py`, `test_settle_identity_models.py`, `test_sqlite_client_escrow_fulfillment_identity.py`, and `test_stage_log_identity.py`.
- Version 2 body binding, durable replay classification, exact-retry outcome recovery, and signed responses: `core/storefront/tests/unit/test_auth.py`, `domains/vms/storefront/tests/unit/test_service_peer_identity.py`, and `domains/vms/storefront/tests/integration/test_admin_api.py`.
- Durable administrator/service-peer ownership and two-proof rotation lifecycle: `core/storefront/tests/unit/test_identity_authority.py`, `test_identity_lifecycle.py`, and `domains/vms/storefront/tests/unit/test_identity_dispatch.py`.
- Transactional storefront principal migration, conflict rejection, and legacy-column retirement: `core/storefront/tests/unit/test_identity_migrations.py`.
- Projection-backed candidate derivation defaults on once at parity with a retained local-table path: `domains/vms/storefront/tests/unit/test_config_loader.py::test_settings_toml_provides_baseline_defaults` and `test_use_site_projection_for_listings_can_still_be_disabled_explicitly`.
- Generic publication source, runner, and plugin discovery: `core/storefront/tests/unit/test_publication_sources.py`, `test_publication_runner.py`, and `test_publication_plugins.py`.
- Registry fan-out and publication persistence: `core/storefront/tests/unit/test_registry_publication.py` and `domains/vms/storefront/tests/unit/test_publications_wiring.py`.
- Domain-runtime bundle and VM wiring: `core/storefront/tests/unit/test_domain_runtime.py` and `domains/vms/storefront/tests/unit/test_domain_runtime_wiring.py`.
- Global pause state: `domains/vms/storefront/tests/unit/test_order_pause_state.py` and `tests/integration/test_admin_api.py`.
- Resource-count diagnosis: `domains/vms/storefront/src/market_storefront/services/system_service.py` and `e2e-tests/tests/smoke/test_storefront_smoke.py`.
- Site-scoped derivation keys and collision resistance (VM and bare-metal): `domains/vms/storefront/tests/unit/test_reconciler.py`; a bare-metal listing is keyed by the common binding's derivation key, whose source identity includes the pool: `domains/bare_metal/tests/test_storefront_publication.py` and `domains/bare_metal/storefront/tests/test_publication_cycle.py`.
- Site-pinned claim routing, including the collision case placement policy would otherwise choose wrongly: `core/storefront/tests/unit/test_aggregation.py`. Mapped-listing routing reached through the real admin, negotiation-hold, and settlement/fulfillment entry points: `domains/vms/storefront/tests/integration/test_admin_api.py`, `domains/vms/storefront/tests/unit/test_two_phase_reserve.py`, and `domains/vms/storefront/tests/unit/test_settlement_jobs.py`.
- Domain-owned listing-cardinality resolution, bucket-sourced fungible candidates, multi-member specific-resource derivation, the resource-keyed derivation-key collision fix, and the live (never persisted) hold-preference cap: `domains/vms/storefront/tests/unit/test_reconciler.py`, `domains/vms/storefront/tests/unit/test_listing_cardinality_mode.py`, `domains/vms/storefront/tests/unit/test_sync_negotiation_hold_cap.py`, `domains/vms/storefront/tests/unit/test_remote_capacity_client.py`, and `domains/bare_metal/storefront/tests/test_publication_cycle.py`.
- Region/SLA hint resolution (including SLA's storefront-wide trust gate) and negotiation-floor pricing-policy precedence: `domains/vms/storefront/tests/unit/test_pool_descriptors.py`, `domains/vms/storefront/tests/unit/test_pricing_resolution.py`, `domains/vms/storefront/tests/unit/test_reconciler.py`, and `domains/vms/storefront/tests/unit/test_cli_publish_helpers.py::TestPoolHintResolutionSettings`.
- Structured publication defaults/imports and preview-first, typed, backed-up atomic migration with ambiguity refusal: `domains/vms/storefront/tests/unit/test_config_loader.py`, `test_resource_csv_importer.py`, and `test_publication_migration.py`.
- Complete bare-metal seller composition, immutable listing/thread binding, selected-site lifecycle, result redaction, restart, and contribution wiring: `domains/bare_metal/storefront/tests/test_http_negotiation.py`, `test_persistence.py`, `test_fulfillment_service.py`, `test_site_clients.py`, `test_domain_runtime.py`, and `test_app_composition.py`.
- Every VM listing is a listing shape — the override, hint, and default-generator sources, per-model default shapes, and publishing exactly the declared quantities: `domains/vms/storefront/tests/unit/test_reconciler.py` (`TestListingShapes`, `TestStorefrontOverrideTier`), `domains/vms/domain/tests/test_shape_generation.py`, `test_storefront_adapter.py`, and `domains/vms/storefront/tests/integration/test_publication_loop.py`. A shape's declared quantities, not pool defaults, size the VM: `provisioning/compute/service/tests/unit/services/test_ansible_fulfillment_provider.py`.
- Shape feasibility agrees with the site ledger on declared and available capacity, members, and buckets: `domains/vms/storefront/tests/integration/test_shape_feasibility.py`.
- Shape-bearing derivation identity and the seller-state carry-over across it, reported through system status: `domains/vms/storefront/tests/integration/test_listing_identity_carryover.py` and `test_publication_loop.py`.
- Storefront pool overrides — the kit's store, reader, write check, status, and signed-resource contract: `kit/pool-overrides/tests/unit/` and `kit/pool-overrides/tests/integration/`; through the storefront app and its typed clients, including a non-home site, refused writes, commercial terms reaching a listing, and the legacy tier: `domains/vms/storefront/tests/integration/test_pool_overrides_api.py`; the VM vocabulary: `domains/vms/storefront/tests/unit/test_vm_pool_override_contribution.py`; the administrator contract: `domains/vms/storefront/tests/unit/test_identity_dispatch.py`.
- A site whose projection is not held holds its listings, and an empty projection derives nothing: `domains/vms/storefront/tests/integration/test_reconciler_projection.py` and `test_pool_overrides_api.py`.
- An operation that changes a site's capacity refreshes that site before reconciling inline: `domains/vms/storefront/tests/integration/test_pool_overrides_api.py` and `e2e-tests/tests/e2e/roles/scenarios/vms/test_compute_dynamic_listings.py`.
- Listing shapes end to end — a stated shape discovered by a memory query, reserved at its declared quantities, and replaced through a storefront override: `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`.

- Common multi-domain listing bindings, collision-safe derivation, frozen publication sources, and exact public mode: `core/storefront/tests/integration/test_domain_binding_migrations.py`, `core/storefront/tests/unit/test_publication_runner.py`, `test_publication_plugins.py`, and `domains/vms/storefront/tests/unit/test_publication_wiring.py`.
- Publication through the storefront app — the loop's cycle, dry run, and pause; unbacked and backed derivation; refresh, close, hold, and reopen; the two-domain registry; backed-only capacity events; publish-then-negotiate; round zero's inventory guard; and each registry's outcome and convergence: `domains/vms/storefront/tests/integration/test_publication_loop.py`, with the app in `domains/vms/storefront/tests/publication_app.py`.
- Joint per-generation reading of pool declarations, including the older-producer rule and an empty generation: `kit/resource-pools/tests/unit/test_site_declarations.py`. The projection's shape on both sides of the site boundary: `kit/site-client/src/market_site_client/fixtures/resource_pools.py`, validated in `provisioning/compute/service/tests/integration/test_capacity_api.py` and built by the storefront's publication tests.
- Listing identity, the reconciliation comparison, and availability reconciliation of backed listings only: `domains/vms/storefront/tests/unit/test_listing_comparison.py` and `test_reconciler.py`.
- Unbacked listings publish only options their domain does not fulfil through capacity: `domains/vms/storefront/tests/unit/test_unbacked_settlement_options.py` and `test_settlement_composition.py`.
- Each publisher builds only its named contributions: `core/storefront/tests/unit/test_publication_plugins.py` and `domains/vms/storefront/tests/unit/test_publication_wiring.py`.
- Durable seller close, kept by every later write: `core/storefront/tests/integration/test_listing_closure.py`, `kit/capacity-publication/tests/unit/test_publication.py`, `domains/apicredits/storefront/tests/integration/test_publish_reconcile.py`, and `domains/bare_metal/storefront/tests/test_publication_cycle.py`.
- Registry convergence: `core/storefront/tests/integration/test_listing_closure.py`, `kit/capacity-publication/tests/unit/test_registry_convergence.py`, and `domains/apicredits/storefront/tests/unit/test_capacity_reconcile_converges.py`.
- Loop controls from either client variant: `domains/vms/storefront/tests/unit/test_lifecycle_client_parity.py`.

The installed bare-metal contribution supplies an independently runnable seller composition. Shared shells consume that contribution and the common immutable binding and lifecycle contexts; they do not replace the domain-owned codecs, seller policy, provisioning adapters, or fulfillment hook.
