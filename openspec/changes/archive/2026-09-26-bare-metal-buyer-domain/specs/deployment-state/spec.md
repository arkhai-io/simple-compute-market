## ADDED Requirements

### Requirement: Bare-metal buyer ships as a clean wheel contribution

The repository MUST build `arkhai-bare-metal-buyer` as a platform-appropriate wheel containing only its buyer package and entry-point metadata, with all internal dependencies consumed from built wheels. Aggregate domain/root distribution targets, review-scope resolution, installation, and reinitialization MUST include that artifact and MUST explicitly upgrade/reinstall it when changed. The wheel MUST contribute to the core `market` executable and MUST NOT ship a competing buyer executable, embed source-tree paths, bundle seller/provisioner implementations, or rely on editable sibling installs.

#### Scenario: Wheel is installed into a clean environment

- **WHEN** the core buyer, bare-metal domain, required kit/client wheels, and bare-metal buyer wheel are installed from the staged wheelhouse
- **THEN** entry-point discovery registers `bare_metal.v1`, the namespaced CLI imports, and the installed metadata has no undeclared source checkout dependency

#### Scenario: Buyer wheel is removed

- **WHEN** the bare-metal buyer distribution is uninstalled while the core buyer remains
- **THEN** the bare-metal namespace disappears and generic/other installed domain commands continue to start normally

#### Scenario: Reinitialization follows a buyer change

- **WHEN** the bare-metal buyer package or an internal dependency changes
- **THEN** the repository reinit target rebuilds prerequisites and force-upgrades the staged wheels before any smoke or integration command runs

### Requirement: Buyer configuration separates public routing, profile identity, access input, and mechanism secrets

Bare-metal buyer configuration MUST use the common buyer configuration hierarchy and declare only registry/storefront trust, domain defaults, settlement mechanism selection, and safe access preferences as ordinary configuration. Persistent marketplace signer selection MUST come from the shared buyer profile store. An SSH private key, marketplace signing credential, wallet key, hosted credential, password, bearer token, action URL, or retrieved access response MUST NOT appear in generated TOML, ConfigMaps, release manifests, images, example files, or run logs. SSH public-key file selection MAY be configured, but the private key path/value MUST not be inferred, copied, or persisted by the marketplace.

#### Scenario: Hosted-only Ed25519 profile is initialized

- **WHEN** a buyer selects an Ed25519 profile and enables only `fiat.stripe.v1` for a bare-metal purchase
- **THEN** initialization and runtime succeed with wallet, RPC, chain ID, deployed-address, and EVM private-key settings absent

#### Scenario: Alkahest is selected

- **WHEN** the exact accepted option uses `alkahest.v1`
- **THEN** only the Alkahest registration requires and validates its explicit wallet/chain configuration without changing marketplace profile ownership

#### Scenario: Generated configuration is inspected

- **WHEN** templates, Compose/Helm values, release inputs, diagnostics, and examples are rendered
- **THEN** they contain no raw signing, SSH private, wallet, hosted, action, or access credentials and use approved secret/profile references where a secret is required

### Requirement: Buyer deployment does not invent a seller topology

Local and release deployment support MAY install the buyer beside registry/storefront services for demonstration, but the buyer MUST address independently configured authenticated authorities and MUST NOT depend on a co-located seller database, provisioning socket, container name, compose-only hostname, test credential, or bypass profile. Disabling the buyer plugin MUST not affect seller, registry, site, or provisioning service startup.

#### Scenario: Buyer runs outside the seller stack

- **WHEN** the installed buyer is configured with remote registry/storefront authorities and their exact trust pins
- **THEN** discovery, negotiation, settlement, status, access, and teardown use public authenticated APIs exactly as in local deployment

#### Scenario: Test stack wiring is absent

- **WHEN** a production installation contains no e2e fixtures, mock profile, or source checkout
- **THEN** the buyer remains runnable and does not fall back to direct database, local provisioner, or unsigned transport access
