## MODIFIED Requirements

### Requirement: Independently deployable bare-metal seller role
The bare-metal storefront MUST be buildable as a wheel from the repository `.dist` artifact set and as a dedicated image containing its declared domain and shared-role dependencies. It MUST own a writable database distinct from every other storefront, with separate immutable agreement-artifact, fulfillment-lifecycle, and reservation-to-site routing tables. It MUST read its configuration as every storefront does, from `storefront.toml`, `storefront.json`, and the Secret overlay `storefront.secrets.toml`, under the keys the other compute storefront uses for the same concepts. Operator configuration MUST bind every stable site identifier to one exact authority URL and to exactly one service peer, whose durable active principals that site's responses and callbacks are both verified against, while the signer credential remains Secret-injected and diagnostics remain URL/credential-free.

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

### Requirement: A storefront's configuration reaches it through its configuration system

Every configuration value of a storefront MUST be supplied through its configuration system:
its configuration files and its loader's documented override layer. A value MAY be supplied
outside that system only when it controls which configuration is loaded — the configuration
directory and the profiles to layer — or when it must be kept from the loader, as the signing
credential is. A storefront's chart MUST know a configuration value only where the deployment
itself needs it for a stated reason, such as the port its container, probes, and Service share,
and MUST supply outside the configuration system only values of those two kinds. Conformance is
a compliance check of the source and charts, not a runtime refusal: a storefront MUST NOT refuse
to start because a value reached it through its environment, and the loader's override layer
remains available to an operator.

#### Scenario: An operator overrides a setting on a development cluster

- **WHEN** an operator injects a setting through the loader's environment override layer into a
  running deployment and restarts it
- **THEN** the storefront starts and applies the override

#### Scenario: The chart renders a storefront's environment

- **WHEN** the bare-metal chart is rendered
- **THEN** its pod environment carries only the configuration directory and the signing
  credential, and every other value is in a mounted configuration file
