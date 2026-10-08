## ADDED Requirements

### Requirement: Domain payment publication respects domain capacity

Bare-metal payment publication MUST require a non-stale selected-site projection with exclusive allocation and supported SSH access; API-credit publication MUST use sellable quota for the named service. Pending payment MUST NOT renew an accepted capacity hold or select another site.

#### Scenario: A bare-metal site projection is stale

- **WHEN** a bare-metal storefront's selected-site projection is stale
- **THEN** it publishes no payment option for that site until a fresh projection shows exclusive allocation and supported SSH access

### Requirement: Payment publication discloses mandate policy

VM, bare-metal, and API-credit storefronts supporting `arkhai.payments.v1` MUST publish ready payment clauses as independent `settlement_options` beside supported Alkahest alternatives. Every option MUST bind asset, rates, payee account, hold window, and agreement-deposit setting. No Stripe funding profile or provider object MAY enter an option.

#### Scenario: A payment clause is ready

- **WHEN** a resource has a complete ready Arkhai payment clause and supported Alkahest terms
- **THEN** publication exposes distinct choices with independent rates and deterministic option IDs

#### Scenario: Payment policy is incomplete

- **WHEN** a clause lacks required payee, asset, window, or deposit policy
- **THEN** publication rejects it without inferring values from an Alkahest price or mutating accepted deals

## MODIFIED Requirements

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

### Requirement: Storefront identity state migrates atomically

Storefront databases MUST validate and migrate buyer, seller, administrator, service-peer, negotiation-message, heartbeat, claim, settlement, replay, stage-event, and audit identities to canonical principal form in one service-local transaction. Migration MUST preserve listing, negotiation, obligation, fulfillment, service-peer, rotation, and operation identities; prove listing ownership and cross-record party consistency; and retire authoritative address-only identity columns. A malformed or partial principal, ownership conflict, duplicate active binding, missing party relation, or other unsafe population MUST roll back completely.

#### Scenario: Active escrow obligation is migrated

- **WHEN** a storefront with a funded nonterminal obligation upgrades from address-only identity rows
- **THEN** the obligation retains its authoritative lifecycle and operation journal while its parties become canonical `eip191` principals

#### Scenario: Persisted listing ownership conflicts with local identity

- **WHEN** a populated listing cannot be proven to belong to the configured storefront principal and expected storefront URL
- **THEN** the migration aborts without leaving any identity table or embedded event partially converted

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

### Requirement: Storefront principal is reused without exposing its key

Publication and negotiation MAY use one configured seller principal. Each marketplace authority MUST receive only a signer operation or signed proof and enforce its own role binding. Arkhai payment calls use separate owner-scoped account credentials. Storefront persistence and projections MUST NOT contain the seller's private credential or a Stripe provider identity.

#### Scenario: Storefront publishes a payment option

- **WHEN** the seller publishes `arkhai.payments.v1`
- **THEN** the option carries only public payee and payment policy while marketplace proof and payment credentials remain separate

## REMOVED Requirements

### Requirement: API-credit publication composes independent settlement alternatives

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Bare-metal hosted publication intersects all authorities

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Dedicated hosted settlement routes

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Delayed funding does not authorize VM fulfillment

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Fulfillment precedes hosted financial collection

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Hosted accepted plan carries authorization safely

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Hosted publication separates ready funding alternatives

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Legacy hosted card decoding is recovery-only

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Preflighted hosted VM publication

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Server-authoritative settlement start

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.
