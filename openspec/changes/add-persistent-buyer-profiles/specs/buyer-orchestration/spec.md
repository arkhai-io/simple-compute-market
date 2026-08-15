## ADDED Requirements

### Requirement: Core owns the buyer profile command surface

The core `market` CLI MUST expose profile create, import, list, show, select, rotate, retire, and delete commands independently of any market-domain plugin. Commands MUST use the shared marketplace identity profile and credential-provider contracts and MUST return only public metadata and redacted credential references. Domain plugins MUST NOT register competing profile or raw identity management commands.

#### Scenario: Core starts without a domain plugin

- **WHEN** no buyer domain plugin is installed
- **THEN** profile lifecycle commands remain available and operate without importing a domain package

#### Scenario: Profile command fails to resolve a secret

- **WHEN** the exact configured credential provider is unavailable
- **THEN** the command fails with the provider and bounded reference context but emits no secret value and attempts no fallback

### Requirement: Fresh runs use the selected profile primary signer

Every fresh buyer run that performs authenticated marketplace work MUST resolve the currently selected active profile, load its primary credential through the exact configured provider, derive and compare the signer principal, and inject that signer into core orchestration and the selected domain plugin. The run MUST durably record the stable local profile ID, exact canonical public principal, and signature-contract version before an authenticated mutation. A missing selection, unavailable credential, principal mismatch, retired profile, or malformed store MUST fail before discovery-authenticated mutation, negotiation, or settlement.

#### Scenario: Selected profile uses Ed25519

- **WHEN** a fresh VM or API-credit run starts with an active selected Ed25519 profile
- **THEN** the same resolved signer is injected through core and domain orchestration and no wallet, chain, or raw private-key field is required

#### Scenario: Credential no longer matches metadata

- **WHEN** the exact provider returns a credential whose derived principal differs from the selected profile primary principal
- **THEN** the run fails before authenticated work and does not rewrite the profile or choose another signer

### Requirement: Every buyer domain consumes the shared resolver

Every shipped buyer domain/plugin MUST receive signer and profile context through the core-owned resolver contract. A domain MUST NOT parse `[Identity]`, read a keyring/file/environment secret directly, infer an identity from a wallet, or define another provider precedence layer. Shared conformance MUST prove the same selected-profile and recorded-principal behavior for each shipped domain.

#### Scenario: Two domains use one selected profile

- **WHEN** VM and API-credit buyer commands run under the same selected local profile
- **THEN** both receive the exact same canonical primary signer through the core boundary while retaining domain-owned terms and result behavior

#### Scenario: Plugin attempts legacy resolution

- **WHEN** a plugin configuration contains direct identity or raw secret fields after cutover
- **THEN** validation rejects them with the explicit import path rather than letting the plugin bypass the core resolver

### Requirement: Legacy identity configuration is import-only

After cutover, buyer runtime configuration MUST reject legacy `[Identity]`, raw private-key, seed, mnemonic, and implicit wallet-derived marketplace identity fields. The only supported transition from legacy identity configuration MUST be the explicit profile import command, which validates the complete candidate before mutation. Runtime MUST NOT preserve old/new precedence, hidden aliases, environment-name compatibility, or automatic first-run import.

#### Scenario: Legacy identity remains in buyer config

- **WHEN** a normal buy, settle, resume, or profile-independent diagnostic command loads a buyer configuration containing removed direct identity fields
- **THEN** validation reports the explicit import/removal action and no authenticated mutation runs

#### Scenario: Import preview fails

- **WHEN** explicit import finds a duplicate, conflict, missing credential, or principal mismatch
- **THEN** it reports the failure without modifying the profile store or legacy file

## MODIFIED Requirements

### Requirement: Identity-first buyer orchestration

The core buyer role MUST resolve one marketplace signer from the selected persistent buyer profile for every fresh run and MUST receive or resolve the exact recorded historical signer for recovery. That signer MUST be injected for discovery-authenticated actions, negotiation, storefront settlement, heartbeat, and recovery. The signer-provided buyer identity MUST be the exact canonical `{scheme, identifier}` principal; identifier equality under a different scheme, profile ID, hosted payer binding, credential reference, or provider resource MUST NOT authorize the buyer. Core orchestration MUST resolve wallet and chain settings only when the selected domain or settlement adapter declares an EVM effect, and it MUST NOT name or pass private-key strings through schema-opaque orchestration.

#### Scenario: Buyer chooses hosted fiat

- **WHEN** an Ed25519 buyer profile selects a compatible `fiat.stripe.v1` option
- **THEN** core negotiation and settlement use that profile signer while wallet, chain, RPC, token-balance, and gas checks are not invoked

#### Scenario: Buyer chooses Alkahest

- **WHEN** the selected obligation requires an Alkahest transaction
- **THEN** the Alkahest adapter separately resolves and validates its EVM wallet and chain inputs before the chain effect

#### Scenario: No buyer profile is selected

- **WHEN** a fresh authenticated buyer command starts without an active selected profile
- **THEN** core fails before domain dispatch or authenticated effects and directs the user to create, import, or select a profile

### Requirement: Buyer recovery binds public principal

Buyer run logs MUST persist the stable local profile ID, exact canonical `{scheme, identifier}` public principal, signature-contract version, settlement obligation and operation identities, and domain state needed to resume, but MUST NOT persist credential locators that reveal secrets or private signing material. A recovery command MUST ignore the profile currently selected for fresh runs, load the recorded profile and exact recorded principal, and resolve that retained signer from profile history. It MUST fail closed unless the resolved signer matches the recorded principal or a completed protocol-authorized recovery transition explicitly permits the replacement.

#### Scenario: Another signer resumes a run

- **WHEN** a valid signer whose principal is not authorized for the recorded buyer attempts recovery
- **THEN** the buyer refuses to continue or submit a settlement mutation

#### Scenario: Selected profile changed after the run

- **WHEN** the user selects another profile after a run records its buyer principal
- **THEN** `buy --from` or `settle --from` resolves the recorded profile/principal history and does not use the newly selected signer

#### Scenario: Recorded predecessor was retained

- **WHEN** profile rotation promoted a replacement but the run records the predecessor
- **THEN** recovery loads the retained predecessor credential and preserves the original run and operation identities

### Requirement: Buyer config template is role-appropriate

Generated buyer configuration MUST contain XDG/profile-store selection inputs and shared `[Settlement]` vocabulary while omitting direct `[Identity]` secrets, raw credential values, seller-only hosted account, authority administration, onboarding, publication, and provider fields. A headless template MAY contain an approved credential-provider kind and bounded secret reference, but MUST NOT contain the resolved seed, private key, or environment value. Mechanism-specific buyer constraints MAY appear only in the owning typed subsection.

#### Scenario: Fiat-only buyer initializes configuration

- **WHEN** the user generates an Ed25519 hosted-fiat buyer config
- **THEN** the output directs profile creation or import and contains settlement preference inputs but no private identity, wallet/chains, or seller account configuration

#### Scenario: Headless buyer template is generated

- **WHEN** an operator selects the strict file or explicit environment credential provider
- **THEN** generated output contains only the provider kind and secret reference with owner-only placement guidance
