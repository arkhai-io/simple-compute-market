## ADDED Requirements

### Requirement: Shared parameterized Dynaconf construction

Compute provisioning and e2e settings MUST use a shared lower-layer loader for profile parsing, ordered include resolution, and Dynaconf construction while preserving each consumer's prefix, nested separator, defaults, dotenv/secrets behavior, missing-file handling, merge precedence, validators, wrappers, and helpers.

#### Scenario: Consumer loads equivalent configuration

- **WHEN** current and shared-loader implementations receive the same provisioning or e2e profile/environment fixture
- **THEN** they produce equivalent nested values, source precedence, missing-file behavior, and validation outcome

#### Scenario: Consumer-specific policy remains local

- **WHEN** provisioning applies its typed settings wrapper or e2e applies validators and profile/config-directory helpers
- **THEN** that logic remains in the consumer composition root and is not imported into the shared kit

#### Scenario: Shared loader wheel is installed

- **WHEN** provisioning and e2e install `arkhai-kit-config` from a built wheel
- **THEN** Dynaconf and declared runtime dependencies resolve without repository source paths
