# Storefront Publication Specification

## Purpose

Define seller storefront ownership, canonical market identity and service trust, listing publication/reconciliation, and domain-runtime composition.

## Requirements

### Requirement: Seller protocol surface
A storefront MUST expose authenticated listing, negotiation, settlement, identity, health, and operator control surfaces while keeping domain-specific behavior behind injected adapters.

A settlement request MUST name the accepted negotiation and carry only what negotiation did not settle, such as the buyer's settlement-effect address. It MUST NOT restate a negotiated term, such as the buyer's access key or the settlement chain; the storefront reads those from the accepted negotiation, and MUST refuse a request that carries one. This holds in every domain.

#### Scenario: Buyer settles accepted terms
- **WHEN** the buyer submits a settlement request for an accepted negotiation
- **THEN** the storefront verifies the agreed terms and settlement evidence before scheduling fulfillment

#### Scenario: A settlement request restates a negotiated term
- **WHEN** a buyer's settlement request carries an SSH public key or a chain name, matching the accepted terms or not
- **THEN** the storefront refuses it before any settlement lookup

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
A VM or bare-metal listing's commercial mapping between an authoritative capacity identity and the published listing MUST be its immutable common listing binding. VM and bare-metal publication, reconciliation, close, and reopen MUST NOT read or write a domain-owned mapping table (`derived_compute_listings`, `derived_bare_metal_listings`); a closed listing is found again by its candidate's derivation key in the common binding. A bare-metal listing's derivation key MUST include its pool, so a Physical Resource moved to another pool derives a new listing and its old listing closes as a withdrawn source. Pricing, settlement terms, and seller policy MUST continue to live on the generic `listings` table, addressed by `listing_id` — no mapping carries commercial fields of its own. Each derivation key MUST include the owning `site_id`, since a pool or resource identifier is only unique within one site, never globally. A derivation key MUST be collision-resistant by construction against any values its constituent fields (`site_id`, `pool_id`, `resource_id`) may take — these are operator-chosen strings with no character restrictions, so a naive delimiter-joined encoding is not sufficient.

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

#### Scenario: A Physical Resource moves to another pool
- **GIVEN** an open bare-metal listing bound under a Physical Resource's pool
- **WHEN** the site projects that Physical Resource under a different pool that admits bare metal, and the operator runs bare-metal publication
- **THEN** the listing closes as a withdrawn source and a new listing publishes under the new pool's binding

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

`region` has no storefront-side override — a storefront overriding where hardware physically sits would misrepresent a fact, not adjust a policy. `sla` and per-family rates (per capacity family and, for a family the domain prices per attribute value, per that value) each resolve through a three-tier precedence, highest to lowest: a storefront-specific override on a specific pool; the pool's own declared hint; the storefront's own configured default. `sla`'s middle tier is additionally gated behind a storefront-wide trust setting — a storefront MAY decline to consult a pool's declared SLA at all, independent of whether any specific pool has an override. The negotiation floor applied to a listing whose settlement option advertises no rate is the storefront's configured default alone: it is not resolved per pool or per model, and it constructs no settlement option. A pool hint or storefront override that still states the retired `min_price` or `token` pricing keys MUST remain readable; neither key is read, and the storefront MUST report them as retired rather than holding the pool. Settlement option assets, rates, units, and mechanism inputs come only from complete typed clause lists, with a pool's clauses — from a storefront override on that pool or the pool's own declared hint — replacing the storefront's configured defaults as whole lists. Every term of sale MUST come from a durable source: no command-line argument may supply or replace a settlement clause or a maximum duration, because reconciliation must be able to re-derive every term a listing publishes.

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
- **WHEN** a pool's pricing hint or a stored storefront override states `min_price` or `token`
- **THEN** neither value is read, the pool's listings are neither held nor refused for it, and system status reports the retired keys
- **AND** every settlement option derives exclusively from the effective complete typed clause list and, for a shape-priced listing, its resolved family rates

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

Publication and negotiation MAY use one configured seller principal. Each marketplace authority MUST receive only a signer operation or signed proof and enforce its own role binding. Arkhai payment calls use separate owner-scoped account credentials. Storefront persistence and projections MUST NOT contain the seller's private credential or a Stripe provider identity.

#### Scenario: Storefront publishes a payment option

- **WHEN** the seller publishes `arkhai.payments.v1`
- **THEN** the option carries only public payee and payment policy while marketplace proof and payment credentials remain separate

### Requirement: Storefront identity state migrates atomically

Storefront databases MUST validate and migrate buyer, seller, administrator, service-peer, negotiation-message, heartbeat, claim, settlement, replay, stage-event, and audit identities to canonical principal form in one service-local transaction. Migration MUST preserve listing, negotiation, obligation, fulfillment, service-peer, rotation, and operation identities; prove listing ownership and cross-record party consistency; and retire authoritative address-only identity columns. A malformed or partial principal, ownership conflict, duplicate active binding, missing party relation, or other unsafe population MUST roll back completely.

#### Scenario: Active escrow obligation is migrated

- **WHEN** a storefront with a funded nonterminal obligation upgrades from address-only identity rows
- **THEN** the obligation retains its authoritative lifecycle and operation journal while its parties become canonical `eip191` principals

#### Scenario: Persisted listing ownership conflicts with local identity

- **WHEN** a populated listing cannot be proven to belong to the configured storefront principal and expected storefront URL
- **THEN** the migration aborts without leaving any identity table or embedded event partially converted

### Requirement: Publication derives all ready settlement options

A storefront MUST preflight every enabled installed settlement registration and derive deterministic listing options from every ready mechanism in configured priority order and the seller's validated settlement publication clauses. A clause MUST NOT make a disabled or unready mechanism publishable. One unready mechanism MUST be suppressed with an operator-visible sanitized blocker while ready peers remain publishable. If no enabled ready mechanism has a valid publication clause, publication MUST fail without mutating accepted negotiations or active settlement state.

#### Scenario: Arkhai payments is unready and Alkahest is ready

- **WHEN** both have publication clauses but payments configuration is unready
- **THEN** the storefront publishes the Alkahest option, omits the Arkhai payment option, and reports the mechanism blocker without provider detail

#### Scenario: Readiness returns after publication

- **WHEN** a previously suppressed mechanism becomes ready and its publication clause remains valid
- **THEN** reconciliation may add its deterministic option without changing listing identity or any already accepted Terms

#### Scenario: Clause names a disabled mechanism

- **WHEN** seller publication input names a mechanism whose typed configuration is disabled
- **THEN** publication rejects that clause without using it as an implicit enablement override

### Requirement: Storefront owns seller settlement UX

Seller configuration, readiness, mechanism administration, and publication MUST be exposed through the storefront CLI and generated role config surface. Normal publication MUST derive options from mechanism-neutral settlement clauses and MUST NOT expose provider-, chain-, or escrow-specific flags. Mechanism administration MUST remain under `settlement <mechanism>`. The storefront CLI's publication command MUST run or preview a cycle of the storefront's publication loop through the storefront API rather than deriving or publishing listings itself. A mechanism kit MAY supply workflow primitives, but a separate provider-specific seller executable or top-level mechanism-specific publication flow MUST NOT be the normal marketplace entry point.

#### Scenario: Seller inspects all settlement mechanisms

- **WHEN** `market-storefront settlement status --json` runs
- **THEN** it returns the common status schema for every installed mechanism in configured order without a listing or financial side effect

#### Scenario: Seller publishes two mechanisms

- **WHEN** normal publication resolves valid Arkhai payment and Alkahest settlement clauses
- **THEN** the storefront derives both through their ready registrations without invoking a mechanism-specific publication command

#### Scenario: Seller runs the publication command

- **WHEN** a seller runs the storefront CLI's publication command
- **THEN** it runs or previews one cycle of the storefront's publication loop through the storefront API, and it reads no storefront database

### Requirement: Publication pricing is explicit per settlement clause

Every priced settlement publication clause MUST carry one asset-scoped decimal rate and unit: stated on the clause for a flat-priced listing, or composed for a shape-priced listing from the listing's own shape and its family rates in that clause's asset. The owning mechanism MUST normalize the rate to canonical integer minor or base units using authoritative asset scale, with exact arithmetic whatever the rate's number of significant digits, MUST reject a conversion that is not a whole number of units or exceeds `2**256 - 1`, and MUST include the normalized rate in deterministic option identity. A resource-level `min_price` or other untyped scalar MUST NOT be reused as the price of more than one mechanism, and a family rate in one asset MUST NOT price a clause in another.

#### Scenario: Dual listing uses equal human prices

- **WHEN** a seller explicitly publishes USD 2/hour and six-decimal-token 2/hour clauses for one resource
- **THEN** the resulting options carry 200 and 2000000 canonical units respectively and both display as 2 asset units/hour

#### Scenario: Dual listing omits one mechanism rate

- **WHEN** a resource has one valid mechanism clause and another enabled mechanism has no explicit rate-bearing clause
- **THEN** publication does not infer the missing mechanism's price from the first clause

#### Scenario: A rate has more significant digits than a fixed-precision context holds

- **WHEN** a clause's rate, stated or composed, has more than 28 significant digits and is not a whole number of the asset's base units
- **THEN** the mechanism refuses it rather than rounding it into an apparently exact value

#### Scenario: A shape-priced clause's asset has rates for some families only

- **WHEN** a shape-priced listing has a clause in an asset in which only some of the families its shape names have rates
- **THEN** that clause's rate is composed from those families alone, and no rate is taken from another asset's family rates

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

### Requirement: Payment publication discloses mandate policy

VM, bare-metal, and API-credit storefronts supporting `arkhai.payments.v1` MUST publish ready payment clauses as independent `settlement_options` beside supported Alkahest alternatives. Every option MUST bind asset, rates, payee account, hold window, and agreement-deposit setting. No Stripe funding profile or provider object MAY enter an option.

#### Scenario: A payment clause is ready

- **WHEN** a resource has a complete ready Arkhai payment clause and supported Alkahest terms
- **THEN** publication exposes distinct choices with independent rates and deterministic option IDs

#### Scenario: Payment policy is incomplete

- **WHEN** a clause lacks required payee, asset, window, or deposit policy
- **THEN** publication rejects it without inferring values from an Alkahest price or mutating accepted deals

### Requirement: Domain payment publication respects domain capacity

Bare-metal payment publication MUST require a non-stale selected-site projection with exclusive allocation and supported SSH access; API-credit publication MUST use sellable quota for the named service. Pending payment MUST NOT renew an accepted capacity hold or select another site.

#### Scenario: A bare-metal site projection is stale

- **WHEN** a bare-metal storefront's selected-site projection is stale
- **THEN** it publishes no payment option for that site until a fresh projection shows exclusive allocation and supported SSH access

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
equal the recorded offering mode. VM and bare-metal publication both derive their
listings from that projection, and each resolves every pool it derives from through
the shared site declaration reader: a pool that does not declare the listing's mode
advertisable, or that declares itself disabled, yields no listing, and a pool whose
declarations do not resolve holds the listings derived from it — neither published,
closed, nor refreshed.

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

#### Scenario: A pool stops advertising bare metal

- **GIVEN** an open bare-metal listing derived from a pool
- **WHEN** that pool no longer declares `bare_metal` advertisable, or declares itself
  disabled, and the operator runs bare-metal publication
- **THEN** the listing closes as a withdrawn source

#### Scenario: A bare-metal pool's declarations do not resolve

- **GIVEN** a bare-metal listing derived from a pool
- **WHEN** a later projection generation leaves that pool unresolvable
- **THEN** the listing is neither closed nor refreshed until the pool resolves

### Requirement: An unbacked pool yields no bare-metal listing

Every bare-metal listing is capacity-backed. Bare-metal publication MUST derive no
listing from a Physical Resource whose pool declares itself unbacked, and MUST report
each such pool to the operator by name, because a listing derived from it could only
publish a backing its pool contradicts.

#### Scenario: An unbacked pool advertises bare metal

- **WHEN** a pool that declares itself unbacked advertises `bare_metal`
- **THEN** bare-metal publication derives no listing from it
- **AND** the operator is told which pool was refused and why

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

This requirement governs VM, API-credit, and bare-metal publication.

For those, a listing's local status is the publication decision and its registries
follow it. A new listing MUST be recorded locally, with its durable binding, before any
registry is told of it, so no registry can hold a listing the storefront has no record
of. A close or reopen MUST change the local listing before any registry is told, and a
local change that fails MUST be reported to its caller with no registry told — a
seller's close is reported as retryable. Each registry's outcome for every publish,
close, and reopen MUST be recorded durably. Every publication pass — each VM
publication cycle, each API-credit capacity reconciliation, and each run of the
bare-metal publication command — MUST then resend, to each configured registry whose
recorded outcome disagrees with its listing's local status, exactly what that status
implies — a close for a closed listing, and for an open one the listing republished and
reopened — and to no other registry. A registry still unreachable stays recorded as
diverged for the next pass.

#### Scenario: A registry misses a close

- **WHEN** a listing closes locally and one of its registries fails the close
- **THEN** the next publication pass sends the close to that registry alone

#### Scenario: A registry misses a reopen

- **WHEN** a listing reopens locally and one registry fails to reopen it
- **THEN** the next publication pass republishes and reopens the listing at that registry alone

#### Scenario: A local close fails

- **WHEN** the local close of a listing fails
- **THEN** no registry is told, and a seller's close is reported as retryable with the listing unchanged

#### Scenario: A new listing's local record fails

- **WHEN** publication derives a new listing and recording it locally fails
- **THEN** no registry is told of the listing

#### Scenario: A bare-metal registry that missed a close is repaired by the next run

- **GIVEN** a bare-metal listing closed locally whose registry close failed
- **WHEN** the operator runs bare-metal publication again
- **THEN** the close is resent to that registry, and to no other

### Requirement: Every VM listing is a listing shape

Every VM listing MUST be a listing shape: a family-grouped capability shape in the compute
family's vocabulary. A bare-metal listing's shape is derived from its Physical Resource's
declaration rather than chosen, and is governed by the bare-metal requirements below. API-credit
listings are not listing shapes. A pool's VM
shapes MUST come from exactly one source, in this precedence:

1. The storefront's override for that site and pool, when it states shapes.
2. Otherwise, the pool's own `listing_shapes` hint for the listing's offering mode.
3. Otherwise, the VM domain's default shape generator.

A stated list MUST replace the lower sources as a whole. How many of a shape a pool can serve
MUST be derived from its capacity declarations, and MUST NOT be declared or published.

**The VM default.** The VM domain's default generator MUST yield, for each GPU model among a
pool's enabled members, one shape per GPU count from one to the largest declared GPU count
among that model's members. Each such shape MUST declare the GPU family only. Every VM shape
MUST name a GPU count and a GPU model. A fungible VM pool MUST publish one listing per
feasible shape. A specific-resource VM pool MUST publish one listing per member per shape that
member is feasible for.

**Commitment.** A VM listing MUST publish every quantity and attribute its shape declares,
flattened through the domain's schema, and MUST NOT publish a quantity its shape does not
declare. The capacity claim built from a VM listing MUST request exactly its shape's
quantities. A VM listing commits only to what its shape declares. For a dimension its shape
omits it makes no commitment, and what is provisioned for that dimension is the site's to
decide. A bare-metal listing commits differently: it sells one whole unit held exclusively,
and its shape describes what that unit contains (see "A bare-metal listing sells one whole
unit").

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
- a structurally invalid record, including a shape outside the domain's vocabulary;
- asking rates its domain cannot read, judged exactly as publication reads them, so an
  accepted write never later holds the pool.

It MUST then fetch that site's resource-pool projection live through the site's
authenticated client, not from its cache:

- a pool absent from the live projection MUST be refused;
- an unreachable site, or a response that does not verify, MUST be refused as retryable,
  with a reason distinct from an absent pool;
- a pool present in the live projection MUST be accepted even when its declarations are
  unresolvable.

A shape no member of the live projection is feasible for MUST NOT cause refusal. The
response MUST report feasibility per shape against that live projection and identify the projection generation it
used. After accepting a write, a storefront that caches site projections MUST cause its
cached projection of that site to refresh, without writing the live result into the cache
itself, and a storefront that runs a publication loop MUST cause it to run. A failed refresh
MUST NOT fail the accepted write. A storefront whose publication is operator-invoked applies
an accepted write at its next publication run.

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

#### Scenario: An override states a rate its domain cannot read

- **WHEN** an administrator writes an override whose asking rate names a shape outside
  the domain's vocabulary, a period this version does not accept, or a shape another
  entry already prices
- **THEN** the write is refused without contacting the site

#### Scenario: A bare-metal override is accepted between runs

- **WHEN** an administrator writes an override for a bare-metal pool while no publication
  run is in progress
- **THEN** the write is stored and reported without starting a run, and the next
  operator-invoked run publishes under it

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

#### Scenario: A bare-metal site is unreachable during a publication run

- **GIVEN** open bare-metal listings derived from a site
- **WHEN** the operator runs bare-metal publication while that site's projection cannot be
  fetched
- **THEN** those listings stay open and unchanged, and the run reports the site as unknown
- **AND** every other configured site is reconciled as usual

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

### Requirement: A bare-metal listing's shape is derived from its declaration

Every bare-metal listing MUST carry a family-grouped capability shape derived from the
capacity declaration of the Physical Resource it offers, through the compute-family schema
and the shared capability-shape utility:

- its quantities MUST be the declared capacity dimensions other than `units`;
- its attributes MUST be the declared attributes the schema names;
- no other declared attribute is shape input.

A declaration that cannot be read this way MUST be treated as unresolvable: it yields no new
listing, its existing listing is held, and the publication run reports it naming the
declaration. That covers:

- a capacity dimension outside the schema;
- a quantity that is not a positive integer;
- a missing GPU count or GPU model;
- a `units` dimension other than exactly one.

Publication-only data the site copies into the bare-metal view MUST NOT be a source of shape
fields.

A bare-metal listing MUST NOT read a pool's `listing_shapes` hint. A pool stating one for
bare metal MUST be reported as not applicable.

#### Scenario: A Physical Resource declares its hardware

- **WHEN** a Physical Resource declares capacity `{units: 1, gpu_count: 8, ram_gb: 2048}` and
  the attribute `gpu_model: H200`
- **THEN** its listing's shape is `{gpu: {count: 8, model: H200}, memory: {gib: 2048}}`

#### Scenario: Two Physical Resources declare the same dimensions

- **WHEN** two Physical Resources in one pool declare identical dimensions
- **THEN** each publishes its own listing, and both listings carry the same shape

#### Scenario: A declaration names no GPU model

- **WHEN** a Physical Resource declares a GPU count but no `gpu_model` attribute
- **THEN** no listing is derived from it, any listing previously derived from it is held,
  and the run names the declaration and the missing field

#### Scenario: Hardware stated only for publication

- **WHEN** a declaration states its GPU model only inside its bare-metal publication
  configuration
- **THEN** that value is not published, the declaration is unresolvable for its missing
  model, and the run reports the ignored publication field

### Requirement: A bare-metal listing publishes its shape where the compute schema reads it

A bare-metal listing MUST publish its shape's quantities and attributes as top-level fields
of the listing resource under the compute family's flat names, so that the compute
registry schema's dimension filters evaluate bare-metal listings as they evaluate VM
listings.

It MUST publish `region` from its pool's `region` hint. A pool with no non-empty string
region hint MUST be held: its resources yield no new listing, its existing listings are
neither closed nor refreshed, and the run reports the pool.

A bare-metal listing MUST NOT publish its hardware in a nested mapping beside the top-level
fields.

#### Scenario: A buyer filters compute supply by GPU model

- **WHEN** a buyer queries a compute registry for a GPU model that a published bare-metal
  listing's Physical Resource declares
- **THEN** the bare-metal listing is returned

#### Scenario: A buyer filters by GPU count

- **WHEN** a buyer queries a compute registry for listings with at least eight GPUs
- **THEN** a bare-metal listing whose Physical Resource declares eight GPUs is returned

#### Scenario: A pool states no region

- **WHEN** a pool advertising bare metal carries no region hint
- **THEN** no bare-metal listing is published from it and the run reports the pool

### Requirement: A bare-metal listing's derivation identity includes its shape

A bare-metal listing's derivation identity MUST be its site, pool, Physical Resource, and a
canonical digest of its shape taken over the family-grouped form, and its durable binding
MUST record the shape digest. A Physical Resource anchors at most one open listing at a time.
A change to its declared shape MUST close its listing and publish a listing under a new
derivation key, leaving the original binding unmodified.

A listing bound under a derivation identity that carries no shape digest matches no
candidate, and MUST close through source reconciliation. It MUST NOT be reopened.

#### Scenario: A declared dimension is corrected

- **WHEN** a Physical Resource behind an open listing changes its declared memory from
  1024 to 2048
- **THEN** that listing closes and a listing with a distinct derivation key publishes for
  the new shape

#### Scenario: A storefront upgrades

- **WHEN** a bare-metal storefront whose listings were bound without a shape digest runs
  publication
- **THEN** each such open listing closes as a withdrawn source and a listing for the same
  Physical Resource publishes under a shape-bearing derivation key in the same run

### Requirement: A bare-metal listing sells one whole unit

A bare-metal listing MUST be held by exclusive allocation of one unit of its Physical
Resource. Its capacity claim MUST request exactly one `units` and MUST carry its shape's
attributes, so that admission matches the published attributes. Its shape's quantities
describe what that unit contains, and MUST NOT be requested dimension by dimension.

The claimed attributes MUST come from the storefront's trusted record of the accepted
listing, never from buyer input.

#### Scenario: A declaration changes model after acceptance

- **WHEN** a buyer accepts a bare-metal listing published with `gpu_model: H200`, and its
  Physical Resource's declaration is changed to another model before reservation
- **THEN** the site refuses the reservation

### Requirement: Bare-metal opening rechecks its listing against its source

Before a bare-metal seller agrees terms, the storefront MUST re-derive the listing's shape
and region from its own site's live resource-pool projection, at its bound pool and
Physical Resource. It MUST refuse with a declared-match reason when any of these hold:

- the shape digest differs from the binding's;
- the region differs from the published region;
- the Physical Resource is absent or disabled.

It MUST refuse as retryable when the site cannot be reached or does not verify.

#### Scenario: A declaration shrinks beneath its listing

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose Physical Resource now
  declares fewer GPUs than it published
- **THEN** the opening is refused with a declared-match reason

### Requirement: A listing's asking rate is declared per shape

A compute listing MAY publish the rate its seller is asking for the listing's shape,
as an `asking_rate` object on the published listing resource carrying `amount`,
`asset`, and `period`. The rate prices one listing shape: listings of different
shapes from the same pool carry independently declared rates, and a rate MUST NOT be
decomposed per capacity dimension.

The rate MUST resolve through this precedence, highest first:

1. The storefront's site-scoped pool override for the listing's site, pool, and
   offering mode, when it states asking rates.
2. Otherwise, the `asking_rates` declaration on the Resource Pool the listing derives
   from, read from the site's projection.
3. Otherwise, no asking rate.

Each tier states rates as a list of entries, each naming the capability shape it
prices. An entry applies to the listing whose shape has the same canonical digest.
An override's list MUST replace the pool's list as a whole; an empty override list
MUST be accepted and MUST mean that no listing of that pool publishes an asking rate.
An override is available for a pool at any site the storefront publishes for.

No storefront configuration default MAY supply an asking rate. Every published rate
is either the declaration of the listing's origin pool or an explicit override for
that site and pool, so a storefront publishing for several seller sites never
advertises its own blanket price as another site's.

A listing whose shape no applicable entry prices MUST publish normally with no
asking rate. An entry naming a shape the pool does not publish has no effect and MUST
be reported in the storefront's system status.

A storefront MUST publish only a complete rate: all three fields present, `amount`
exact positive decimal text without an exponent, `asset` a trimmed non-empty opaque
identifier, and `period` a unit this version accepts, which is `hour` alone.

The asking rate MUST NOT participate in any shape digest or derivation identity.

#### Scenario: A pool prices each of its shapes

- **WHEN** a pool publishes a 1-GPU and an 8-GPU shape and declares a rate for each
- **THEN** each listing publishes the rate declared for its own shape

#### Scenario: A shape is priced nowhere

- **WHEN** a pool publishes a shape that neither its declaration nor an override prices
- **THEN** that listing publishes normally with no asking rate

#### Scenario: The storefront overrides a remote site's rate

- **WHEN** the storefront's override for a pool at a site other than its first
  configured site states an asking rate for one of the pool's shapes
- **THEN** that listing publishes the override's rate and not the pool's declaration

#### Scenario: The storefront withholds every rate

- **WHEN** the storefront's override for a pool states an empty asking-rate list
- **THEN** no listing of that pool publishes an asking rate, whatever the pool declares

#### Scenario: A storefront configures pricing defaults

- **WHEN** a pool declares no asking rates, no override states any, and the storefront
  configures negotiation-floor or settlement defaults
- **THEN** no listing of that pool publishes an asking rate

### Requirement: A malformed asking-rate declaration holds its pool

A pool `asking_rates` declaration or an override's asking rates that the storefront
cannot read MUST hold every listing of that pool — neither published, closed, nor
refreshed — and MUST be reported in the storefront's system status. It is unreadable
when an entry's shape is outside the offering mode's vocabulary, when two entries
price the same shape, or when any entry's amount, asset, or period is invalid.

An unreadable declaration MUST NOT fall through to a lower tier or to no rate. An
absent declaration and a malformed one are different: falling through would silently
drop a price the seller believes they advertised. A declaration stated as `null`,
for the whole `asking_rates` key or for one offering mode, is malformed, not absent.

#### Scenario: A declaration names an unknown shape field

- **WHEN** a pool's asking-rate entry names a shape field the offering mode does not
  define
- **THEN** that pool's listings are held and the storefront reports the declaration
  unreadable

#### Scenario: A rate uses an unsupported period

- **WHEN** a declaration or override quotes a rate per a period other than `hour`
- **THEN** that pool's listings are held rather than published with or without the rate

#### Scenario: A declaration is stated as null

- **WHEN** a pool states `asking_rates` as `null`, or states `null` for the listing's
  offering mode
- **THEN** that pool's listings are held rather than published without a rate

#### Scenario: Two entries price one shape

- **WHEN** two entries in one list name shapes with the same canonical digest
- **THEN** that pool's listings are held rather than either rate being chosen

### Requirement: The asking rate is a listing attribute, not a settlement option rate

No settlement option, escrow term, or accepted obligation MAY be constructed from a
published asking rate, and an agreed amount MUST remain absent rather than zero until
one is negotiated. This constrains what the system builds from the number, not how
far a buyer should trust it: like every published field, an asking rate is a seller
assertion, and nothing in the marketplace verifies any of them.

A listing MAY publish an asking rate and also advertise a rate inside a settlement
carrier — an accepted escrow's rate slots or a settlement option's rates. The two
MUST be treated as independent carriers: a mechanism rate governs what the runtime
constructs for that mechanism, and the asking rate governs nothing. They MUST NOT be
required to agree, and where they disagree neither corrects the other.

Neither may be derived from the other. A storefront MUST NOT populate an asking rate
from a rate advertised in a settlement carrier, and MUST NOT write an asking rate
into a settlement option, escrow term, or obligation. Deriving it in either direction
would make the field's provenance unreadable, and it is undefinable for a listing
advertising escrows in several assets.

A storefront MAY derive an asking rate from a seller's negotiation-side rate
structure where the seller's declared policy says so, once such a structure exists;
the structure does not replace, subsume, or reinterpret the published asking rate.

A listing whose only settlement option is under a mechanism declining scalar
participation carries no mechanism rate. Such a listing MUST still be able to publish
an asking rate. Asking rates MUST be available to backed and unbacked listings alike.

#### Scenario: A deal is agreed against a listing carrying an asking rate

- **WHEN** a negotiation concludes against a listing publishing an asking rate
- **THEN** the agreed amount comes from the negotiation
- **AND** the published asking rate does not constrain or supply it

#### Scenario: A listing carries both an asking rate and an escrow rate

- **WHEN** publication builds a candidate whose shape has an asking rate and whose
  settlement configuration advertises escrow rates
- **THEN** both appear in the published listing
- **AND** the asking rate is not populated from, reconciled against, or written into
  any settlement carrier

#### Scenario: The two published rates disagree

- **WHEN** a listing's asking rate differs from the rate advertised in its settlement
  carrier
- **THEN** publication is not refused on that ground

#### Scenario: A rateless mechanism carries a declared asking rate

- **WHEN** a listing's only settlement option is under a mechanism declining scalar
  participation and its shape has an asking rate
- **THEN** the listing publishes the asking rate and the option remains rateless

### Requirement: An asking-rate change refreshes the listing in place

An asking rate is a term of sale under the requirement that a listing's identity is
the physical resource it offers. Changing the amount, asset, or period that applies
to a listing MUST refresh the listing in place at the storefront and every registry,
retaining its identity and derivation key. Removing the rate that applies to a
listing MUST refresh it without an asking rate; it remains discoverable and becomes
absent from rate-bounded queries.

A rate change MUST NOT close a listing and publish it under a new identity.

#### Scenario: A seller changes a declared rate

- **WHEN** the rate declared for a published shape changes
- **THEN** the listing is refreshed carrying the new rate under its existing identity

#### Scenario: A seller removes a declared rate

- **WHEN** the entry pricing a published shape is removed
- **THEN** the listing is refreshed without an asking rate
- **AND** it remains discoverable while absent from rate-bounded queries

#### Scenario: The storefront overrides a declared rate

- **WHEN** an override starts stating a different rate for a shape the pool already
  prices
- **THEN** the listing is refreshed carrying the override's rate under its existing
  identity

### Requirement: Bare metal joins the site-scoped pool-override store

A bare-metal storefront MUST contribute a market vocabulary for the `bare_metal` offering
mode to the site-scoped pool-override store, and MUST serve the same authenticated
administrator operations, through the same signed-resource contract, as every storefront
that serves overrides.

The bare-metal vocabulary is:

- settlement clauses;
- the terms `min_duration_seconds` and `max_duration_seconds`;
- asking rates, resolved as every compute listing's asking rate is.

A bare-metal override MUST NOT state listing shapes. An override's settlement clauses
replace the storefront's configured publication clauses for that site's pool as a
whole. Each of its duration bounds replaces its configured counterpart independently,
as configuration overlays do, and the effective pair a listing would publish MUST be
ordered. A write whose minimum exceeds the effective maximum MUST be refused. Because
configuration can change after a write, publication MUST also check the effective
pair, holding the pool's listings and reporting the conflict rather than publishing
an unordered pair or failing the run.

A bare-metal storefront's command line MUST offer the same replace, read, list, and delete
operations through its administrator API, with the offering mode never defaulted, and MUST
NOT read or write its database to do so.

A stored bare-metal override that cannot be read MUST hold its pool's listings, neither
publishing, closing, nor refreshing them, and MUST be reported; configuration MUST NOT speak
for a pool whose override exists but cannot be read.

A bare-metal storefront MUST record durably, for each site, the last resource-pool projection
generation a publication run accepted, whichever process ran it, and its override status MUST
be judged against that generation. A site with no recorded generation is `unknown`.

#### Scenario: A bare-metal override is written

- **WHEN** an operator writes an override for a pool at a configured site in the
  `bare_metal` offering mode
- **THEN** bare metal validates it, and it applies only to that site's pool's bare-metal
  listings

#### Scenario: A bare-metal override states a shape

- **WHEN** an operator writes a `bare_metal` override that states listing shapes
- **THEN** the write is refused without contacting the site

#### Scenario: An operator writes a bare-metal override from the command line

- **WHEN** an operator runs the bare-metal storefront's override command with a record for
  the `bare_metal` mode
- **THEN** the command sends it through the administrator API, which checks it against
  the site's live projection, and prints the stored override

#### Scenario: An override minimum exceeds the configured maximum

- **WHEN** an operator writes a bare-metal override stating only a minimum duration
  above the storefront's configured maximum
- **THEN** the write is refused, naming the effective maximum

#### Scenario: Configuration falls below an accepted override

- **WHEN** an override's minimum was accepted and the configured maximum is later set
  below it
- **THEN** the next publication run holds that pool's listings and reports the
  conflict

#### Scenario: A stored bare-metal override cannot be read

- **WHEN** a publication run finds a stored override for a pool that cannot be decoded
  or read in the bare-metal vocabulary
- **THEN** the pool's listings are held rather than published under configured terms,
  and the run reports why

#### Scenario: Publication runs from the command

- **WHEN** an operator runs `bare-metal-storefront publish` in its own process and the run
  accepts a site's generation holding the override's pool
- **THEN** the running storefront reports the override as applied

#### Scenario: Status before the first run

- **WHEN** a bare-metal storefront reports override status before any publication run has
  accepted a generation for the override's site, including after a restart that follows
  no run
- **THEN** the override is reported as unknown

### Requirement: Shape-resolvable commercial rates

A storefront MUST let a seller state a rate per unit per time unit for each capacity family
its domain's pricing projection names, in an asset, under the family it prices, in one nesting
shared by the configured default, the pool's pricing hint, and the storefront's pool override.
The domain's pricing projection MUST name, for each priced family, the one quantity it is priced
by and, where the family is priced per attribute value, that attribute; which families are keyed
MUST NOT be inferred from the schema. Within one family, a tier's rate list MUST replace lower
tiers' lists as a whole, and each family MUST resolve independently of the others. A family rate
MUST be positive decimal text; a zero rate MUST be refused.

A VM listing for which any family resolves a non-empty rate list is **shape-priced**: each of its
settlement clauses names mechanism, asset, and mechanism input, and for each clause whose
mechanism negotiates a scalar amount the storefront composes the clause's rate by evaluating the
listing's own shape against the family rates in that clause's asset. A clause whose mechanism
declines the scalar is published rateless in either mode. Otherwise the listing is
**flat-priced**: a clause's own rate is the listing's rate whatever its shape, and a stated flat
rate MUST NOT be reinterpreted as a rate for any one family.

A family the listing's shape does not name MUST NOT contribute to its price. A family its shape
names with no rate in a clause's asset MUST contribute nothing to that clause's price, and the
storefront MUST report it as included without a rate; no family is required to have a rate. A
candidate MUST be refused, with a reason naming the asset, when a scalar-negotiating clause's
composed rate is zero, so that no listing is published or negotiated free; and, with a reason, when
a shape-priced clause also states its own rate.

#### Scenario: A configuration states no family rates

- **WHEN** a storefront's tiers resolve no family rates for any listing and every clause rate
  converts exactly
- **THEN** every listing is flat-priced and publishes the same settlement options, with the same
  option identities, as a storefront without family-rate support

#### Scenario: A shape-priced listing composes its rate

- **WHEN** a listing of two H100 GPUs, sixteen vCPUs, and 128 GiB of memory resolves rates of 80 per
  card-hour, 0.5 per vCPU-hour, and 0.05 per GiB-hour in one asset
- **THEN** its clause in that asset publishes a rate of 174.4 per hour

#### Scenario: A family without a rate is not charged

- **WHEN** a shape-priced listing's shape names 64 GiB of memory and no tier states a memory rate in
  a clause's asset
- **THEN** that clause's rate is composed from the other families' rates, the listing publishes,
  and the storefront reports memory as included without a rate in that asset

#### Scenario: A listing would be free in an asset

- **WHEN** no family a shape-priced listing's shape names has a rate in a scalar clause's asset
- **THEN** the candidate is refused with a reason naming the asset, and nothing is posted to a
  registry

#### Scenario: Rates resolve from different tiers per family

- **WHEN** one family's rates are stated by a storefront override and another's are available only
  as a configured default
- **THEN** each family resolves independently from its own highest available tier

#### Scenario: A shape omits a family the seller prices

- **WHEN** a shape-priced listing's shape omits a family for which rates resolve
- **THEN** that family contributes nothing to the listing's price

#### Scenario: A shape-priced clause states its own rate

- **WHEN** a shape-priced listing's clause also states a rate
- **THEN** the candidate is refused with a reason, and neither source is chosen silently

#### Scenario: A published asking rate is present

- **WHEN** a listing also publishes a listing-level asking rate
- **THEN** that asking rate is neither read as a family rate nor reinterpreted as one, and no
  family rate is read as the asking rate

### Requirement: An unreadable family rate holds its pool

A family rate list that a tier states and the storefront cannot read MUST NOT be treated as absent:
the pool MUST be held, so its listings keep their last-published terms and nothing is published or
refreshed from it until the rate is readable. The storefront MUST report, per held pool, the tier,
family, and problem in the derivation report its system status serves. A malformed family rate in
the storefront's own configured defaults MUST prevent the storefront from starting.

#### Scenario: A pool hint states an unreadable rate

- **WHEN** a pool's hint states a memory rate the storefront cannot read and the storefront's
  configured default states a memory rate
- **THEN** the pool is held rather than priced from the configured default, its open listings keep
  their last-published terms, and system status names the hint, the family, and the problem

#### Scenario: A configured default states an unreadable rate

- **WHEN** the storefront's configured defaults state a family rate that cannot be read
- **THEN** the storefront refuses to start, naming the setting

### Requirement: Price aggregation is replaceable

Deriving a price from a shape and one asset's family rates MUST occur behind a replaceable
aggregation interface that the domain selects; operator configuration MUST NOT select it. The
interface MUST return an exact price in the asset's display units per time unit, computed without
binary floating point and without rounding. Converting that price to base units is the consumer's
step, under the consumer's stated rule. No consumer of a price MAY reconstruct or assume a total by
combining individual family rates and quantities directly, and evaluation MUST be callable outside
the negotiation path.

#### Scenario: A domain selects a different aggregation

- **WHEN** a domain selects a different price aggregation
- **THEN** prices change accordingly with no change to negotiation, publication, or settlement
  code paths

#### Scenario: A consumer needs a shape's price

- **WHEN** any component needs the price of a shape
- **THEN** it obtains it through the aggregation interface rather than by multiplying a family's
  rate by its quantity

#### Scenario: A price has more significant digits than a fixed-precision context holds

- **WHEN** family rates and quantities produce a price with more than 28 significant digits
- **THEN** the aggregation returns that price exactly

### Requirement: A shape-priced listing records the rates that could price a revised shape

A shape-priced listing MUST record, on the storefront's generic listing record, every family's
resolved rate list for the listing — including families its own shape omits — and the storefront's
listing read MUST return it; a flat-priced listing records none. The record is a term of sale: a
change MUST refresh the listing in place, and the record MUST NOT be hashed into the listing's
identity, its shape digest, or any settlement option's identity. A settlement option's identity
MUST continue to cover its rates, so a change that alters a listing's composed rate changes that
option's identity while the listing's identity is unchanged. Publication to a registry MUST carry
each settlement option's composed rate for the listing's own shape and MUST NOT depend on the
registry keeping any listing field it does not already keep.

#### Scenario: A family rate changes

- **WHEN** a shape-priced listing's composed rate changes while its shape and source do not
- **THEN** the listing keeps its identity, its options carry the new composed rate under new
  option identities, and its storefront listing read returns the new rates

#### Scenario: A rate changes for a family the listing's shape omits

- **WHEN** a GPU-only shape-priced listing's resolved memory rate changes
- **THEN** the listing is refreshed in place with the new recorded rate, and its composed rate and
  option identities are unchanged

#### Scenario: A listing is published to a registry

- **WHEN** a shape-priced listing is published
- **THEN** the registry receives the listing's settlement options with their composed rates in the
  existing option fields, and no additional listing-level field

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
- Every VM listing is a listing shape — the override, hint, and default-generator sources, per-model default shapes, and publishing exactly the declared quantities: `domains/vms/storefront/tests/unit/test_reconciler.py` (`TestListingShapes`, `TestStorefrontOverrideTier`), `domains/vms/domain/tests/test_shape_generation.py`, `test_storefront_adapter.py`, and `domains/vms/storefront/tests/integration/test_publication_loop.py`. A shape's declared quantities, not pool defaults, size the VM: `domains/vms/provisioning/adapter/tests/unit/test_vm_fulfillment_plan.py` (`TestSizingPrecedence`).
- Shape feasibility agrees with the site ledger on declared and available capacity, members, and buckets: `domains/vms/storefront/tests/integration/test_shape_feasibility.py`.
- Shape-bearing derivation identity and the seller-state carry-over across it, reported through system status: `domains/vms/storefront/tests/integration/test_listing_identity_carryover.py` and `test_publication_loop.py`.
- Storefront pool overrides — the kit's store, reader, write check, status, and signed-resource contract: `kit/pool-overrides/tests/unit/` and `kit/pool-overrides/tests/integration/`; through the storefront app and its typed clients, including a non-home site, refused writes, commercial terms reaching a listing, and the legacy tier: `domains/vms/storefront/tests/integration/test_pool_overrides_api.py`; the VM vocabulary: `domains/vms/storefront/tests/unit/test_vm_pool_override_contribution.py`; the administrator contract: `domains/vms/storefront/tests/unit/test_identity_dispatch.py`.
- A site whose projection is not held holds its listings, and an empty projection derives nothing: `domains/vms/storefront/tests/integration/test_reconciler_projection.py` and `test_pool_overrides_api.py`.
- An operation that changes a site's capacity refreshes that site before reconciling inline: `domains/vms/storefront/tests/integration/test_pool_overrides_api.py` and `e2e-tests/tests/e2e/roles/scenarios/vms/test_compute_dynamic_listings.py`.
- Asking rates through each storefront app and its typed clients — declared and override rates reaching the listing a buyer reads, an empty override withholding a rate, in-place refresh, independence from settlement rates, each seller site's rate reaching only its own listing, and holds on an unreadable declaration or a bound conflict: `domains/vms/storefront/tests/integration/test_pool_overrides_api.py` and `domains/bare_metal/storefront/tests/test_http_publication_rates.py`; resolution and the edge matrix: `kit/resource-pools/tests/unit/test_asking_rates.py`, `domains/vms/storefront/tests/integration/test_reconciler_projection.py`, and `domains/bare_metal/storefront/tests/test_publication_cycle.py`; across running services: `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_publication.py` (stages 05b–05d).
- Bare metal's pool overrides — the route service, the administrator routes and their refusals, override status against the durable accepted-generation record, effective lease bounds, and the command: `kit/pool-overrides/tests/unit/test_route_service.py`, `domains/bare_metal/storefront/tests/test_pool_overrides_api.py`, `test_pool_override_terms.py`, `test_publication_cycle.py`, `test_pool_override_cli.py`, and `test_runtime_environment.py`.
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
- Bare-metal shape derivation and its holds: `domains/bare_metal/tests/test_shapes.py`, `test_storefront_publication.py`, and `test_publication.py`; the published flat fields against the compute schema, `test_schema.py`.
- Bare-metal publication with shape-bearing identity, successors, region holds, and reports: `domains/bare_metal/storefront/tests/test_publication_cycle.py` and `test_persistence.py`; system evidence in `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_publication.py`, stages 03b and 06.
- The whole-unit claim and its admission by the site's own matcher: `domains/bare_metal/storefront/tests/test_claims.py`, `test_fulfillment_service.py`, and `test_http_settlement.py`.
- The bare-metal opening recheck: `domains/bare_metal/tests/test_inventory_guard.py` and `domains/bare_metal/storefront/tests/test_http_negotiation.py`, through the canonical client.
- A settlement request restates no negotiated term: `domains/vms/storefront/tests/unit/test_settlement_start_authority.py`, `domains/vms/buyer/tests/test_vm_settlement_helpers.py`, `core/storefront-client/tests/test_negotiate_new_payload.py`, and `domains/bare_metal/storefront/tests/test_http_settlement.py`.

The installed bare-metal contribution supplies an independently runnable seller composition. Shared shells consume that contribution and the common immutable binding and lifecycle contexts; they do not replace the domain-owned codecs, seller policy, provisioning adapters, or fulfillment hook.
