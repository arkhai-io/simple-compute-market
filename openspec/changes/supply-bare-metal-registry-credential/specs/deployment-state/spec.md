## MODIFIED Requirements

### Requirement: Independently deployable bare-metal seller role
The bare-metal storefront MUST be buildable as a wheel from the repository `.dist` artifact set and as a dedicated image containing its declared domain and shared-role dependencies. It MUST own a writable database distinct from every other storefront, with separate immutable agreement-artifact, fulfillment-lifecycle, and reservation-to-site routing tables. Operator configuration MUST bind every stable site identifier to one exact authority URL and canonical principal, while signer credentials and complete routing records remain Secret-injected and diagnostics remain URL/credential-free.

The dedicated chart MUST accept a public registry URL, authority, and bounded principal trust set together, and an optional existing Secret reference for its publication bearer. It MUST NOT accept a plaintext registry bearer in public values or render credential material into a ConfigMap or chart-managed Secret. An unconfigured registry MUST render no registry environment variables; a configured registry without a bearer reference MUST omit only the API-key environment variable.

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

#### Scenario: Helm deploys the one-domain role
- **WHEN** an operator supplies public seller identity, existing signer and site-binding Secret references, one persistent volume, and a pinned dedicated image to `helm/charts/bare-metal-storefront`
- **THEN** the chart renders one unprivileged storefront process with startup, liveness, and readiness probes and no wait or import dependency on the VM storefront

#### Scenario: Helm configures authenticated bare-metal publication
- **WHEN** an operator supplies complete registry trust and an existing API-key Secret reference
- **THEN** the pod receives the public registry settings and an API-key `secretKeyRef`, without any credential value in rendered manifests
