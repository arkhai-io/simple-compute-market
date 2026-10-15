## MODIFIED Requirements

### Requirement: Independently deployable bare-metal seller role
The bare-metal storefront MUST be buildable as a wheel from the repository `.dist` artifact set and as a dedicated image containing its declared domain and shared-role dependencies. It MUST own a writable database distinct from every other storefront, with separate immutable agreement-artifact, fulfillment-lifecycle, and reservation-to-site routing tables. It MUST read its configuration as every storefront does, from `storefront.toml`, `storefront.json`, and the Secret overlay `storefront.secrets.toml`, under the keys the other compute storefront uses for the same concepts. Operator configuration MUST bind every stable site identifier to one exact authority URL and to exactly one service peer whose principals that site's responses and callbacks are verified against, while the signer credential remains Secret-injected and diagnostics remain URL/credential-free.

#### Scenario: Bare-metal storefront package is installed
- **WHEN** the distribution is installed from staged wheels outside the source checkout
- **THEN** the `bare-metal-storefront` entry point and `market.storefront_contributions` hook load without editable sibling packages

#### Scenario: Operator enables only bare-metal
- **WHEN** the bare-metal seller role is enabled and VM storefront is disabled
- **THEN** the role starts with its own persistence and trusted-site configuration without waiting for or referencing a VM storefront

#### Scenario: Operator enables both compute storefronts
- **WHEN** VM and bare-metal seller roles use one provisioning service
- **THEN** they remain separate processes with separate writable storefront databases and explicit public service URLs or gateway paths

#### Scenario: Site configuration is diagnosed
- **WHEN** health or operator status reports configured bare-metal site bindings
- **THEN** it reports stable site IDs and canonical authority principals but no authority URL, signer credential, provider configuration, or private inventory

#### Scenario: A site has no service peer
- **WHEN** the bare-metal storefront starts with a configured site that no service peer is bound to, or that two are
- **THEN** it refuses to start, naming the site

#### Scenario: Helm deploys the one-domain role
- **WHEN** an operator supplies the storefront's public configuration, an existing signer credential Secret, an optional existing Secret overlay, one persistent volume, and a pinned dedicated image to `helm/charts/bare-metal-storefront`
- **THEN** the chart renders the configuration unchanged into `storefront.json`, mounts it and the overlay as files, injects only the credential and the configuration directory through the environment, and renders one unprivileged storefront process with startup, liveness, and readiness probes and no wait or import dependency on the VM storefront

## ADDED Requirements

### Requirement: A storefront reads no application settings from its environment

A storefront MUST read its application settings only through its configuration loader,
from its configuration files and the loader's documented override layer. Outside the
loader it MUST read from its environment only the signing credential and the location of
its configuration directory, and its chart MUST supply nothing else through pod
environment entries.

#### Scenario: A setting is supplied as an environment variable the storefront does not read

- **WHEN** an operator sets a bare-metal publication setting under a retired
  environment-variable name instead of in the storefront's configuration files
- **THEN** the storefront does not read it, and refuses to start for the setting the
  files lack
