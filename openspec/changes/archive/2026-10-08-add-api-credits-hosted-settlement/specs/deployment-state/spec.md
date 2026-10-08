## ADDED Requirements

### Requirement: API-credit hosted deployment is wallet-free and consumer-only

An API-credit buyer/storefront deployment MAY enable `fiat.stripe.v1` with Ed25519 marketplace identities and no wallet/chain settings. It MUST configure only the shared hosted public authority/release pins, exact funding profiles/currency policy, storefront account/condition/evidence resolver, persistent buyer-profile binding, API-credit service/quota inputs, and role-scoped marketplace signer Secrets. It MUST NOT receive Stripe credentials/IDs, stable hosted payer/instrument data in storefront state, raw actions, hosted database/migrations, API bearer secrets in config, or VM/bare-metal provisioning inputs.

#### Scenario: Hosted-only API-credit stack starts

- **WHEN** registry, credits authority, seller, buyer, and hosted authority have exact valid Ed25519/public config and Secret references
- **THEN** listing, negotiation, hosted servicing, issuance, evidence, and API consumption become ready without wallet, chain RPC, physical capacity, or executor config

#### Scenario: Wallet settings are absent

- **WHEN** only hosted settlement is enabled
- **THEN** startup does not derive an EVM address or construct an Alkahest/chain client

### Requirement: API-credit deployment pins independent authorities and artifacts

The deployable composition MUST pin marketplace wheels/image/source/workflow, exact hosted manifest/client/service image/API/schema/migrations/capabilities/source/workflow, credits-service client/service schema/image, portable evidence schema/issuer/resolver, and API-credit domain contract independently. Readiness MUST fail before publication or mutation when any exact identity/capability disagrees. One source commit or mutable tag MUST NOT stand in for another repository or authority.

#### Scenario: Evidence capability does not match hosted resolver

- **WHEN** the API-credit issuer/schema or hosted condition resolver pin differs
- **THEN** the hosted option is unready before publication

#### Scenario: Credits service image is stale

- **WHEN** it cannot enforce the immutable fulfillment/grant and canonical owner contract expected by the storefront
- **THEN** API-credit readiness fails before hosted funding is accepted

### Requirement: API-credit hosted rollout preserves accepted operations

Config/data migration MUST add mechanism-neutral options, canonical owner principals, shared runtime obligations/operations, hosted fulfillment/evidence references, and exact release pins while preserving existing Alkahest listing, escrow, grant, key, quota, credential, and consumption identities. Activation MUST update buyer, storefront, credits service, hosted coordinates, Compose/config, and artifacts as one verified set. Before new hosted publication rollback MAY restore the prior set; after hosted authorization/publication/effect, recovery MUST roll forward without asking old code to interpret new records.

#### Scenario: Existing Alkahest grant is migrated

- **WHEN** deployment upgrades with an accepted or completed API-credit escrow
- **THEN** its escrow UID remains the immutable grant/fulfillment identity and ordinary Alkahest recovery/credential behavior is unchanged

#### Scenario: Migration sees ambiguous key ownership

- **WHEN** a historical owner cannot be represented as one exact canonical principal
- **THEN** migration rolls back rather than guessing an Ed25519/EIP-191 identity or enabling hosted top-up

### Requirement: API-credit role secrets remain separated

Buyer and storefront marketplace signing credentials, credits-service authentication, portable-evidence issuer signing material, hosted authority credentials, and API bearer keys MUST remain separate role-owned secrets. Public principal/config fields contain only public identities and opaque references. A bearer key returned to an authenticated buyer MUST NOT be injected into seller/hosted roles, release artifacts, ConfigMaps, logs, readiness, or evidence.

#### Scenario: API bearer key reaches rendered evidence config

- **WHEN** a value or generated artifact contains a key secret or full bearer credential
- **THEN** schema/canary validation fails and the artifact is not deployed or signed

### Requirement: API-credit Compose path exercises ordinary hosted topology

The repository-owned API-credit Compose/E2E topology MUST run separate registry, credits authority, API-credit storefront, buyer/test driver, and exact hosted authority artifacts over their production APIs and persistent stores. It MUST preserve credits/storefront/hosted state independently across selected restarts, use released wheels/images rather than source-sharing, and route portable evidence through the configured resolver. Protected Stripe credentials remain only in the hosted execution environment.

#### Scenario: Storefront restarts after issuance

- **WHEN** credits grant/evidence committed before marketplace collection
- **THEN** the restarted storefront reads its durable shared runtime state, retrieves the existing grant/evidence, and collects once without rebuilding another service's state
