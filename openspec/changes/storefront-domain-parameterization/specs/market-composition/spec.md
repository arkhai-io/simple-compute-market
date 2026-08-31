> Permanent destination: `openspec/specs/market-composition/spec.md`; conceptual rationale also promotes to `docs/development/ARCHITECTURE.md#composition-from-above-and-below`.

## ADDED Requirements

### Requirement: Storefront roots inject one validated domain contract

A domain-owned storefront composition root MUST receive one immutable versioned `MarketDomainContract`, validate it against that executable's supported domain identity and required declared capabilities before constructing role services, repositories, background workers, or the HTTP application, and inject that same contract through every domain-sensitive role boundary. Publication, negotiation, settlement-plan construction, fulfillment dispatch, and persisted domain-artifact normalization MUST NOT discover or replace the contract through module-global state.

#### Scenario: VM storefront starts with its supported contract

- **WHEN** the VM storefront composition root receives a supported `compute.v1` contract with complete codecs and declared storefront, settlement, fulfillment, and compute-provisioning capabilities
- **THEN** startup constructs the app, lifespan container, repository, publication, negotiation, settlement, and fulfillment paths with that same immutable contract before serving requests

#### Scenario: Supplied contract version is unsupported

- **WHEN** the VM storefront root receives a contract whose version is outside the core-supported set
- **THEN** startup fails with the supplied domain identity, supplied version, and supported version information before a repository, background task, route side effect, or publication is created

#### Scenario: Required capability is absent or inconsistent

- **WHEN** the supplied VM contract omits, incompletely implements, or provides without declaration any required codec, storefront, settlement, fulfillment, or compute-provisioning capability
- **THEN** startup fails with the domain identity and incompatible capability before the storefront accepts work

#### Scenario: Supplied identity targets another single-domain executable

- **WHEN** the single-domain VM executable receives a well-formed contract whose stable domain identity is not `compute.v1`
- **THEN** startup rejects it instead of interpreting VM records with the other domain or falling back to the built-in VM contract

### Requirement: Domain injection is a clean composition cutover

After the VM contract is selected at the outermost composition root, every domain-sensitive VM storefront call MUST use the injected value. There MUST be no compatibility accessor, implicit default below the composition root, module-global lookup, or second contract construction path that can select different semantics for the same process.

#### Scenario: Nested role path needs domain semantics

- **WHEN** listing validation, negotiation normalization or policy, accepted-plan derivation, settlement fulfillment, or repository normalization needs a domain codec or capability
- **THEN** it uses the contract supplied by the composition root and cannot resolve a replacement from module state

#### Scenario: Test supplies a compatible contract instance

- **WHEN** a focused test injects a distinct compatible `compute.v1` contract instance
- **THEN** the app state and each constructed domain-sensitive collaborator retain that exact instance rather than reconstructing an equivalent contract

#### Scenario: Core and kit dependency boundaries are inspected

- **WHEN** package imports are checked after parameterization
- **THEN** core and kit packages still import no concrete VM or bare-metal implementation, VM imports no bare-metal composition package, and the bare-metal root remains independently composable

### Requirement: Parameterization preserves external and persisted contracts

Storefront domain parameterization MUST NOT change public listing, negotiation, settlement, fulfillment, identity, configuration, or operator carriers; MUST NOT add a database domain discriminator or migration; and MUST preserve existing listing, negotiation, obligation, fulfillment, and operation identifiers and current Alkahest behavior.

#### Scenario: Existing VM database starts after the cutover

- **WHEN** an existing VM storefront database created by the preceding release is opened with the injected `compute.v1` contract
- **THEN** it requires no schema or data migration and existing records retain their identifiers and interpretation

#### Scenario: Current VM workflow is exercised

- **WHEN** the same listing, negotiation, settlement, and fulfillment inputs are processed before and after parameterization
- **THEN** public responses, persisted canonical values, selected settlement behavior, and side-effect ordering are unchanged

#### Scenario: Rollback is required before multi-domain persistence exists

- **WHEN** operators roll back this change before any dependent multi-domain change writes a domain discriminator
- **THEN** rollback is a code-and-package revert with no data repair or carrier conversion
