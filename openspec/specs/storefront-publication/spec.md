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
A storefront's derived-listing mapping (`derived_compute_listings`, `derived_bare_metal_listings`) is the commercial-mapping table between an authoritative physical or capacity identity and a published listing; it MUST NOT be duplicated as a separate schema. Pricing, settlement terms, and seller policy MUST continue to live on the generic `listings` table, addressed by `listing_id` — the mapping row carries no commercial fields of its own. Each mapping row's derivation key MUST include the owning `site_id`, since a pool or resource identifier is only unique within one site, never globally. A derivation key MUST be collision-resistant by construction against any values its constituent fields (`site_id`, `pool_id`, `resource_id`) may take — these are operator-chosen strings with no character restrictions, so a naive delimiter-joined encoding is not sufficient.

#### Scenario: Two sites name a pool identically
- **WHEN** two different sites each have a pool sharing the same operator-chosen `pool_id`
- **THEN** their derived-listing mapping rows have distinct derivation keys and neither row's mapping is silently overwritten by the other's

#### Scenario: An operator-chosen identifier contains a delimiter character
- **WHEN** a `site_id`, `pool_id`, or `resource_id` value contains a character that would otherwise separate fields in a naively joined key
- **THEN** the resulting derivation key remains distinct from any other combination of values that could produce the same joined string

#### Scenario: Two specific-resource candidates share a pool
- **WHEN** a multi-member pool publishes more than one `specific_resource` candidate, each naming a different physical resource
- **THEN** each candidate's derivation key is resource-keyed and distinct, and recording one candidate's mapping does not overwrite another's

### Requirement: Site-pinned claim routing
A capacity claim for a listing with a known site mapping MUST be routed to exactly that site, with no fallback to a different site on refusal or error — this applies to every listing with a site mapping, whether the underlying capacity is fungible (pool-derived) or pinned to a specific physical resource, never only to resource-pinned listings. A listing with no recorded site mapping MAY be routed by placement policy across configured sites.

#### Scenario: A mapped listing's site would lose to placement policy
- **WHEN** a listing is mapped to one site but placement policy would otherwise prefer a different configured site with more available capacity
- **THEN** the claim is routed only to the listing's mapped site, regardless of what placement policy would have chosen for an unmapped claim

#### Scenario: A mapped site refuses or errors
- **WHEN** a listing's mapped site refuses the claim or the request to that site fails
- **THEN** the claim is not retried against a different configured site

### Requirement: Domain-owned publication and hold hints
A storefront domain MAY interpret a projected pool's `listing_mode`, `max_reservation_hold_seconds`, `region`, `sla`, and `pricing` policy tags. Each domain MUST own its accepted `listing_mode` values and structural default; an absent or unrecognized value MUST fall back to that default with an operator-visible explanation rather than failing projection ingestion or blocking publication. A cooperating storefront MUST treat a valid `max_reservation_hold_seconds` as an advisory upper bound on its own requested reservation-hold TTL — it MUST NOT change what the site ledger itself enforces, and an unresolvable or invalid preference MUST leave the caller's requested TTL unchanged rather than block hold placement.

A `fungible` pool's publishable capacity range is bounded by what a single member can currently satisfy, never by a sum across members, and MUST be sourced from grouped `site_capacity_buckets` data when it is available; a `specific_resource` pool publishes one independently identified, independently reservable listing candidate per currently enabled member, regardless of member count. No listing/hold hint's projected value may be persisted into storefront-local storage — a consumer reads it live from the current projection each time it is needed.

`region` has no storefront-side override — a storefront overriding where hardware physically sits would misrepresent a fact, not adjust a policy. `sla` and negotiation-floor pricing policy (per resource family and, within a family, per model) each resolve through a three-tier precedence, highest to lowest: a storefront-specific override on a specific pool; the pool's own declared hint; the storefront's own configured default. `sla`'s middle tier is additionally gated behind a storefront-wide trust setting — a storefront MAY decline to consult a pool's declared SLA at all, independent of whether any specific pool has an override. A resolved `min_price` is only a negotiation floor, and a resolved `default_token_address` is only demand-side policy input; neither constructs a settlement option. Settlement option assets, rates, units, and mechanism inputs come only from complete typed clause lists, with resource clauses replacing command clauses and command clauses replacing configured defaults as whole lists.

#### Scenario: Listing mode is absent or invalid
- **WHEN** a projected pool omits `listing_mode` or supplies a value unsupported by the selected domain
- **THEN** publication uses the domain's structural default and exposes an operator-visible explanation without failing projection ingestion

#### Scenario: A fungible pool's members have unequal availability
- **WHEN** a fungible pool's members currently have different available capacity
- **THEN** the storefront publishes candidate slice sizes no larger than the largest currently available single member, not a sum across members

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

#### Scenario: Current storefront composition selects a domain
- **WHEN** a VM or API-credit storefront is assembled
- **THEN** its composition root supplies a validated domain contract used by every shared storefront service that interprets domain behavior

#### Scenario: Domain validation fails
- **WHEN** a domain codec or hook rejects a payload
- **THEN** the storefront surfaces the domain validation failure without coercing it through a different domain or a generic fallback

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
Individual-resource publication consumes `site_resource_pools`, which carries the physical inventory facts required to create a listing for a specific resource. Capacity-oriented publication consumes vertically grouped `site_capacity_buckets`. Grouped capacity is advisory publication input only and is never an allocation target; authoritative reservation admission remains host-granular inside the provisioning site authority.

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

Seller configuration, readiness, mechanism administration, and publication MUST be exposed through the storefront CLI and generated role config surface. Normal publication MUST accept mechanism-neutral settlement clauses and MUST NOT expose provider-, chain-, or escrow-specific flags. Mechanism administration MUST remain under `settlement <mechanism>`. A hosted client MAY supply workflow primitives, but a separate provider-specific seller executable or top-level mechanism-specific publication flow MUST NOT be the normal marketplace entry point.

#### Scenario: Seller inspects all settlement mechanisms

- **WHEN** `market-storefront settlement status --json` runs
- **THEN** it returns the common status schema for every installed mechanism in configured order without a listing or financial side effect

#### Scenario: Seller publishes two mechanisms

- **WHEN** normal publication receives valid Stripe and Alkahest settlement clauses
- **THEN** the storefront derives both through their ready registrations without invoking a mechanism-specific publication command

### Requirement: Publication pricing is explicit per settlement clause

Every priced settlement publication clause MUST contain one asset-scoped decimal rate and unit. The owning mechanism MUST normalize it to canonical integer minor or base units using authoritative asset scale, reject non-exact conversion, and include the normalized rate in deterministic option identity. A resource-level `min_price` or other untyped scalar MUST NOT be reused as the price of more than one mechanism.

#### Scenario: Dual listing uses equal human prices

- **WHEN** a seller explicitly publishes USD 2/hour and six-decimal-token 2/hour clauses for one resource
- **THEN** the resulting options carry 200 and 2000000 canonical units respectively and both display as 2 asset units/hour

#### Scenario: Dual listing omits one mechanism rate

- **WHEN** a resource has one valid mechanism clause and another enabled mechanism has no explicit rate-bearing clause
- **THEN** publication does not infer the missing mechanism's price from the first clause

### Requirement: Per-resource settlement input uses the common clause contract

Command defaults, imported resource records, and reconciliation inputs that describe settlement options MUST parse to the same typed settlement-clause model before option derivation. Unknown fields, conflicting duplicate values, role-inapplicable fields, and malformed rates MUST fail the affected candidate without creating a partially interpreted option.

#### Scenario: Imported resource overrides settlement defaults

- **WHEN** one resource record supplies its own complete settlement clauses
- **THEN** those clauses replace the command-level defaults for that resource and are validated through the same grammar and registrations

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

Every storefront listing MUST have one immutable common mapping binding the listing ID, trusted site, explicit pool or Physical Resource provenance, offering mode, exact domain identity/version, collision-safe derivation identity, and public-safe versioned source envelope. Public `offer_resource.virtualization_type` MUST equal the recorded offering mode. Pricing, settlement clauses, and seller policy remain on the generic listing; secret, provider, credential, SSH, and private result material MUST NOT enter the binding or public offer.

#### Scenario: One pool exposes VM and bare-metal modes

- **WHEN** a trusted pool declares both modes and both registered publication sources derive candidates
- **THEN** the storefront creates distinct VM and bare-metal listing/binding identities even when their site-local source identifiers are equal

#### Scenario: One declared mode is withdrawn

- **WHEN** the pool stops declaring one registered offering mode
- **THEN** publication closes only new-work listings for that mode while sibling listings and accepted records retain their original bindings

#### Scenario: Public mode conflicts with the contribution

- **WHEN** a normalized domain listing projects a `virtualization_type` different from its registration or durable binding
- **THEN** the listing and binding transaction fails before registry publication or capacity mutation

### Requirement: Trusted listing mappings route to one site

A listing with a durable site mapping MUST route all capacity claims to exactly that configured site and pinned authority. Refusal, outage, missing trust, or mode disagreement at that site MUST fail closed and MUST NOT fan out to another site.

#### Scenario: Another site could satisfy the claim

- **WHEN** the bound site refuses a listing claim while another configured site has compatible capacity
- **THEN** the storefront reports the bound-site refusal and the other site receives zero calls

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
- Site-scoped derivation keys and collision resistance (VM and bare-metal): `domains/vms/storefront/tests/unit/test_reconciler.py`, `domains/bare_metal/tests/test_publication.py`, and `domains/bare_metal/tests/test_storefront_publication.py`.
- Site-pinned claim routing, including the collision case placement policy would otherwise choose wrongly: `core/storefront/tests/unit/test_aggregation.py`. Mapped-listing routing reached through the real admin, negotiation-hold, and settlement/fulfillment entry points: `domains/vms/storefront/tests/integration/test_admin_api.py`, `domains/vms/storefront/tests/unit/test_two_phase_reserve.py`, and `domains/vms/storefront/tests/unit/test_settlement_jobs.py`.
- Domain-owned listing-mode resolution, bucket-sourced fungible candidates, multi-member specific-resource derivation, the resource-keyed derivation-key collision fix, and the live (never persisted) hold-preference cap: `domains/vms/storefront/tests/unit/test_reconciler.py`, `domains/vms/storefront/tests/unit/test_listing_mode.py`, `domains/vms/storefront/tests/unit/test_sync_negotiation_hold_cap.py`, `domains/vms/storefront/tests/unit/test_remote_capacity_client.py`, and `domains/bare_metal/storefront/tests/test_publication.py`.
- Region/SLA hint resolution (including SLA's storefront-wide trust gate) and negotiation-floor pricing-policy precedence: `domains/vms/storefront/tests/unit/test_pool_descriptors.py`, `domains/vms/storefront/tests/unit/test_pricing_resolution.py`, `domains/vms/storefront/tests/unit/test_reconciler.py`, and `domains/vms/storefront/tests/unit/test_cli_publish_helpers.py::TestPoolHintResolutionSettings`.
- Structured publication defaults/imports and preview-first, typed, backed-up atomic migration with ambiguity refusal: `domains/vms/storefront/tests/unit/test_config_loader.py`, `test_resource_csv_importer.py`, and `test_publication_migration.py`.

- Common multi-domain listing bindings, collision-safe derivation, frozen publication sources, and exact public mode: `core/storefront/tests/unit/test_domain_binding_migrations.py`, `test_publication_runner.py`, `test_publication_plugins.py`, and `domains/vms/storefront/tests/unit/test_publication_wiring.py`.
Complete runnable bare-metal servicing remains gated on its producer contribution; the common shell does not substitute a fulfillment hook.
