## ADDED Requirements

### Requirement: Shared parameterized Dynaconf construction

Compute provisioning and e2e settings MUST use a shared lower-layer loader for profile parsing, ordered include resolution, and Dynaconf construction while preserving each consumer's effective prefix, nested separator, defaults, supported dotenv/secrets behavior, missing-file handling, merge precedence, validators, wrappers, and helpers. Unsupported constructor arguments that never affected runtime behavior MUST NOT be promoted into a new compatibility contract.

#### Scenario: Consumer bootstrap preserves documented layered behavior

- **WHEN** the provisioning or e2e composition-root bootstrap receives a controlled configuration-directory, active-profile, layered-file, dotenv/secret, and environment fixture
- **THEN** it produces the documented effective values, adjacent file-layer precedence, dotenv/environment precedence, consumer-specific missing-file behavior, and validation outcome

#### Scenario: Resolver environment remains composition-root policy

- **WHEN** a consumer receives `CONFIG_DIRECTORY` and `ACTIVE_PROFILES` through its process environment
- **THEN** the consumer composition root passes those values explicitly into the shared loader rather than the shared kit reading process globals itself

#### Scenario: Consumer-specific policy remains local

- **WHEN** provisioning applies its typed settings wrapper or e2e applies validators and profile/config-directory helpers
- **THEN** that logic remains in the consumer composition root and is not imported into the shared kit

#### Scenario: Shared loader wheel is installed

- **WHEN** provisioning and e2e install `arkhai-kit-config` from a built wheel
- **THEN** Dynaconf and declared runtime dependencies resolve without repository source paths
