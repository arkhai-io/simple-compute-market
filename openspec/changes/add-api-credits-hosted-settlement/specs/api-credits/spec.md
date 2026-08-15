## ADDED Requirements

### Requirement: API-credit listings expose independent settlement alternatives

An `api_credits.v1` listing MUST carry mechanism-neutral `settlement_options` independently from legacy `accepted_escrows`. Each option MUST bind the listed service and quota resource, seller principal, exact mechanism/profile, condition, currency, per-credit-unit rate, and expiry policy. Hosted options MUST use `fiat.stripe.v1` with one exact profile; Alkahest options MUST retain their accepted-escrow semantics. No option MAY be synthesized from another mechanism or profile.

#### Scenario: Seller publishes hosted and Alkahest choices

- **WHEN** the quota resource is available and both mechanisms have complete ready clauses
- **THEN** the listing contains independently identifiable hosted settlement options and accepted Alkahest escrows without treating either as fallback for the other

#### Scenario: Hosted option is incomplete

- **WHEN** its account, condition, profile, currency/rate, claimant, or readiness is absent or mismatched
- **THEN** that option is not published while independently valid alternatives remain

### Requirement: Hosted funding gates exact-once credit issuance

A hosted API-credit obligation MUST bind accepted service, quantity, key mode and optional key ID, canonical buyer and claimant principals, exact amount/currency/profile, account, expiry, condition, marketplace operation ID, and funding authorization. The storefront MUST create no quota hold, key, grant, top-up, credential result, or issuance evidence until the hosted authority reports that exact obligation authoritatively funded.

Once funded, issuance MUST use the immutable settlement obligation/fulfillment identity as its unique grant key. Restart and exact retry MUST converge on one quota commitment, one new key or one existing-key top-up, one secret-bearing buyer result, and one public secret-free receipt. Checkout completion, bank instructions, ACH processing, webhook arrival, and provider identifiers MUST NOT authorize issuance.

#### Scenario: Bank transfer is awaiting funds

- **WHEN** the hosted authority returns instructions or pending attributable funding
- **THEN** the storefront issues no credits and retains the exact resumable obligation

#### Scenario: Restart follows issuance acknowledgement loss

- **WHEN** the credits authority committed the grant but the storefront did not record completion
- **THEN** retry with the same immutable fulfillment identity retrieves/converges on the same grant without reserving quota or increasing balance twice

### Requirement: Portable issuance evidence is signed and secret-free

Successful hosted issuance MUST publish one signed portable evidence object retrievable by the configured condition resolver. Its canonical body MUST bind domain/version, service and quota resource, quantity, key mode and resulting public key ID, canonical buyer and claimant principals, settlement obligation/fulfillment identity, issuance success, timestamp, issuer identity, schema/capability version, and digest. It MUST NOT contain the API bearer secret, hosted payer/instrument/provider data, action material, or private credits-service state.

The hosted condition MUST accept only an unexpired, correctly signed object whose exact obligation, parties, service, quantity, key ownership, and issuance identity match. Evidence publication and retrieval MUST be idempotent; a changed body under the same identity MUST conflict. Only satisfied authoritative evidence MAY enable collection.

#### Scenario: New-key issuance succeeds

- **WHEN** the exact funded obligation creates a key and commits its grant
- **THEN** the buyer may retrieve credentials through the authenticated storefront while the condition resolver receives only signed public key ownership and issuance evidence

#### Scenario: Evidence names another buyer

- **WHEN** a signed evidence object does not bind the accepted canonical buyer or owned existing key
- **THEN** condition evaluation fails without collection or disclosure of the bearer secret

### Requirement: Failed issuance preserves hosted reclaim safety

If authoritative funding succeeds but credits issuance has not committed, the storefront MUST retry the exact issuance until success, declared terminal failure, or accepted expiry. A terminal failed issuance MUST publish no satisfied evidence and MUST remain eligible for hosted reclaim after expiry when the shared runtime confirms no fulfillment success, satisfied evaluation, or collection reservation. A pre-collection hosted funding return MUST block issuance and collection. A post-collection loss MUST remain a hosted incident and MUST NOT revoke consumed credits or rewrite completed issuance.

#### Scenario: Credits authority rejects issuance before expiry

- **WHEN** an authoritative ownership or quota check fails without committing a grant
- **THEN** no satisfied evidence or collection is produced and the obligation may reclaim under the accepted deadline

#### Scenario: ACH loss appears after collection

- **WHEN** hosted authority reports a post-collection return/loss after credits were issued and collected
- **THEN** completed issuance and consumption history remain immutable while the financial authority owns incident recovery

### Requirement: Hosted API-credit identity is wallet-free and role-separated

Marketplace buyer/storefront principals, hosted payer ownership, API-key ownership, and bearer authentication MUST remain distinct identities. A canonical Ed25519 buyer principal MAY negotiate, authorize, receive a new key, and top up its existing key with no wallet or chain configuration. Existing-key issuance MUST recheck canonical owner at the credits authority; another principal MUST be rejected even if it presents the key ID or funds the hosted obligation. Bearer secret possession authorizes API use only and MUST NOT authorize marketplace purchase or top-up.

#### Scenario: Same profile tops up its key

- **WHEN** the canonical owner uses the same persistent buyer profile to fund an accepted existing-key obligation
- **THEN** the credits authority adds the exact quantity once and does not rotate or expose the existing bearer secret

#### Scenario: Another principal funds a top-up

- **WHEN** accepted hosted funding names a buyer who does not own the requested key
- **THEN** authoritative issuance fails without changing balance, quota, key ownership, or settlement evidence

## MODIFIED Requirements

### Requirement: Versioned API-credits vocabulary

The API-credits domain MUST validate listings, round-zero provision intent, negotiated terms, settlement selection, materialization, receipts, and fulfillment results against the `api_credits.v1` domain contract. A listing MUST carry `settlement_options` and `accepted_escrows` as independent typed alternatives. Provision intent MUST use version `1`, request a positive integer quantity, and select either a new key or an existing key identified by `key_id`. Accepted terms MUST pin one exact advertised settlement selection and canonical buyer/seller principals.

#### Scenario: Invalid provision intent is received

- **WHEN** provision intent has another kind or version, a quantity below one, or existing-key mode without `key_id`
- **THEN** the domain rejects it before policy or settlement processing

#### Scenario: Settlement choice is not advertised

- **WHEN** terms select an option/escrow identity absent from the trusted listing or change its mechanism/profile/condition/parties
- **THEN** the domain rejects it before funding authorization or issuance

### Requirement: Quantity-scaled pricing

API-credits negotiation MUST interpret an advertised accepted-escrow or settlement-option rate as a per-credit-unit rate and compute the scalar reference payment as quantity multiplied by that exact rate in payment base units. Seller policy and materialized obligation MUST use the same quantity-scaled amount and currency. A hidden-reserve listing MUST have an operator-configured minimum price before it can accept an offer. Overflow, fractional base units, changed currency, or disagreement between accepted terms and selected option MUST fail.

#### Scenario: Buyer requests several credits

- **WHEN** a buyer requests three credits from a listing whose accepted unit rate is 100 base units
- **THEN** buyer and seller policy use 300 base units as the scalar reference payment

#### Scenario: Materialization amount differs

- **WHEN** a hosted authorization or settlement plan does not equal accepted quantity multiplied by unit rate
- **THEN** materialization fails before financial or issuance side effects

### Requirement: Advisory negotiation checks and authoritative issuance

Negotiation-time quota and key checks MUST be advisory guards over captured views. Existing-key negotiation MUST reject known revoked keys, keys owned by another canonical marketplace principal, and unavailable keys while allowing an active unowned key to receive an open top-up only where current domain policy permits. Issuance MUST recheck key status and canonical ownership at the credits service and MUST commit a live quota hold or atomically reserve fresh quota before granting credits. Marketplace principal comparison MUST use full canonical scheme and identifier and MUST NOT coerce an Ed25519 principal into a wallet address.

#### Scenario: Captured quota cannot satisfy the request

- **WHEN** the captured availability is two units and the buyer requests three
- **THEN** negotiation rejects the request without placing a quota hold

#### Scenario: Negotiation view is stale at issuance

- **WHEN** accepted terms reach issuance after their hold expired or key state changed
- **THEN** the credits service repeats authoritative quota and key checks before changing the balance

#### Scenario: Ownership scheme differs

- **WHEN** an Ed25519 buyer and an EIP-191 key owner have equal-looking identifier text
- **THEN** they remain different canonical principals and the top-up is rejected

### Requirement: Idempotent credit issuance

The credits service MUST own API-key hashes, balances, grants, and consumption records. A new key MUST be derived through the issuance operation, store only a hash of its bearer secret, and bind the full canonical buyer principal when supplied. A credit grant MUST be unique by immutable settlement obligation/fulfillment identity; historical Alkahest rows MAY retain `escrow_uid` as that identity. Retrying the same issuance MUST NOT grant credits or reserve quota twice. Changed service, quantity, key mode/key ID, owner, or settlement identity under an existing grant identity MUST conflict. A retry for an unused newly issued key MAY rotate and return a replacement secret, but a retry after use MUST NOT reveal a bearer secret.

#### Scenario: Issuance is retried

- **WHEN** the same immutable fulfillment identity is issued more than once with an identical request
- **THEN** balance and quota change only once while any replacement secret follows the unused-key rule

#### Scenario: Grant identity is reused with another quantity

- **WHEN** a retry changes the requested credits or target key under the same fulfillment identity
- **THEN** the authority returns conflict and performs no additional grant

### Requirement: Verified settlement fulfillment

The API-credits storefront MUST verify the accepted mechanism-specific settlement state before creating an issuance job. For hosted settlement, only authoritative funded state for the exact profile/authorization MAY reserve fulfillment; for Alkahest, the existing verified evidence boundary remains unchanged. A successful job MUST persist the immutable fulfillment reference and buyer credentials, while public fulfillment results and portable evidence MUST omit the bearer secret. If downstream Alkahest fulfillment fails after issuance, the storefront MUST attempt the existing compensating balance adjustment and revoke a key newly created by that failed operation. Hosted issuance is itself the domain fulfillment: failure before its commit remains reclaimable and no speculative compensation may claim that a hosted financial effect was reversed.

#### Scenario: Settlement evidence is invalid

- **WHEN** accepted settlement state/evidence fails mechanism-specific verification
- **THEN** the storefront creates neither an issuance settlement row nor a credit grant

#### Scenario: New-key issuance succeeds

- **WHEN** verified settlement produces a successful issuance job
- **THEN** the storefront persists credentials for authenticated buyer retrieval and exposes a secret-free public result and portable fulfillment reference

#### Scenario: Hosted issuance fails before grant commit

- **WHEN** funding is authoritative but the credits service makes no quota/key/grant change
- **THEN** the storefront publishes no satisfied evidence, performs no collection, and preserves eligible reclaim recovery
