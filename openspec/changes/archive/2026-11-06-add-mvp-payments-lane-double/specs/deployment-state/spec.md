## ADDED Requirements

### Requirement: A storefront chart trusts a deployment-supplied CA bundle

The storefront and bare-metal storefront charts MUST offer an option that mounts a CA bundle from a deployment-supplied ConfigMap key, or alternatively a Secret key, into the storefront container and derives the agent configuration's `[Settlement.arkhai_payments].ca_bundle_path` from the option's presence, naming the mounted file. The chart MUST refuse a configuration that states a different `ca_bundle_path` while the option is set, MUST refuse the option, naming the section, when the configuration has no `[Settlement.arkhai_payments]` section or an empty one, MUST name no CA itself and supply no default, MUST NOT set `SSL_CERT_FILE`, and MUST render neither the mount nor the setting when the option is unset.

#### Scenario: The option names a ConfigMap key

- **WHEN** a release sets the CA bundle option naming a ConfigMap and key
- **THEN** the storefront container mounts that key, the rendered configuration's `ca_bundle_path` names the mounted file, and no `SSL_CERT_FILE` is set

#### Scenario: The option names a Secret key

- **WHEN** a release sets the CA bundle option naming a Secret and key instead
- **THEN** the storefront container mounts that key and the rendered configuration's `ca_bundle_path` names the mounted file

#### Scenario: The configuration states another bundle path

- **WHEN** a release sets the CA bundle option and its agent configuration states a different `ca_bundle_path`
- **THEN** rendering fails naming both paths

#### Scenario: The option is set without a payments section

- **WHEN** a release sets the CA bundle option and its agent configuration has no `[Settlement.arkhai_payments]` section, or an empty one
- **THEN** rendering fails naming the section, and the chart creates no payments configuration

#### Scenario: The option is unset

- **WHEN** a release leaves the option unset
- **THEN** no bundle is mounted and the chart adds no `ca_bundle_path`

### Requirement: A storefront's secrets reach it through its secret overlay

A storefront's payments key, dispute credentials and wallet key MUST reach it as settings in its secret overlay (`storefront.secrets.toml`, or the API-credit storefront's secret layer), which a deployment supplies from a Secret, never as an environment variable its configuration names and never in a chart's public `config`. The storefront charts MUST offer no option that exposes a payments key as an environment variable, and their values schema MUST refuse in `config`, in any spelling and as null, the payments key `[Settlement.arkhai_payments].api_key`, the variable reference `[Settlement.arkhai_payments].api_key_env`, and every `[[DisputeCredential]]` entry.

#### Scenario: A storefront is configured for payments

- **WHEN** a release configures a storefront for Arkhai payments
- **THEN** its payments key is `[Settlement.arkhai_payments].api_key` in the runtime Secret's overlay, and its pod environment carries no payments variable

#### Scenario: The public configuration states a payments key

- **WHEN** a release's agent `config` states `[Settlement.arkhai_payments].api_key`
- **THEN** the values schema refuses it before anything renders

#### Scenario: The public configuration names a payments key's variable

- **WHEN** a release's agent `config` states `[Settlement.arkhai_payments].api_key_env`
- **THEN** the values schema refuses it before anything renders, and the rest of the payments section is accepted

#### Scenario: The public configuration states a dispute credential

- **WHEN** a release's agent `config` states a `[[DisputeCredential]]` entry, whether with its `api_key`, with an `api_key_env`, or with neither
- **THEN** the values schema refuses it before anything renders: the whole entry, its token included, belongs in the secret overlay

#### Scenario: A storefront offers only payments

- **WHEN** a release configures a storefront with payments and with Wallet, Chains and Alkahest removed and RPC off
- **THEN** the chart renders it with the payments configuration and the CA bundle, and nothing for the removed settings

### Requirement: The local release rehearses a deployment's payments interface

The local Helm release MUST configure payments through the same values a deployment supplies — the agent's payments configuration, the runtime secret overlay and the CA bundle option — and MUST NOT use `development_auth`. Its deploy target MUST enable the payments double's subchart, which release values never enable, once per namespace, and the local deployment MUST supply the seller token in each storefront's runtime secret overlay, the VM storefront's dispute credential for the pinned dispute authority its registry recommends in that storefront's overlay, and the CA ConfigMap from the committed development fixtures by default, through its out-of-band step for local Secrets rather than through chart values. The subchart MUST take its server certificate and key from a named existing Secret when one is given.

#### Scenario: The local release is deployed

- **WHEN** the local deploy target installs the release
- **THEN** the payments double runs, the storefronts are configured for payments through the deployment-facing values, the VM storefront's secret overlay holds its credential for the pinned dispute authority, and no storefront uses development authentication

#### Scenario: A deployment supplies its own TLS

- **WHEN** a release names an existing Secret for the double's server certificate and key
- **THEN** the double serves with that Secret's material rather than the committed files

### Requirement: A storefront checks its payments access from its own container

Each storefront CLI MUST offer `check-payments --account <id>`, which loads the storefront's configuration as the running storefront does, reads the named account's balance through the payments kit with the storefront's own key and configured trust, prints one JSON outcome containing no credential, and exits nonzero naming the failing step: configuration, credential, transport, or the service's refusal code. The storefront charts MUST offer a Helm test that runs it directly, not through the storefront's entrypoint, with the storefront's image, configuration and secrets mounts, identity credential, and CA bundle mount, rendered from the same chart definitions as the storefront Deployment, and without the storefront's data volume, health probes, or network-overlay capabilities and device.

#### Scenario: The storefront can reach its payments service

- **WHEN** an operator or a lane runs `check-payments` for the seller's account in a configured storefront container
- **THEN** it prints an `ok` outcome with the service URL and the account's assets and exits zero

#### Scenario: The storefront does not trust the payments origin

- **WHEN** the storefront's configured CA bundle does not cover the payments service's certificate
- **THEN** the check prints a `failed` outcome naming the transport step and exits nonzero

#### Scenario: The storefront's CA bundle cannot be loaded

- **WHEN** the bundle `ca_bundle_path` names is missing, unreadable, or malformed
- **THEN** the check prints a `failed` outcome naming the configuration step, before any request, and exits nonzero

#### Scenario: A deployment reruns the check

- **WHEN** a deployment runs the storefront chart's Helm test
- **THEN** the check runs with the storefront's image, configuration, secret overlay, credential and CA mount, and mounts no storefront data volume, so it does not depend on where the storefront's volume is attached

### Requirement: A stack's configuration lives in committed files

Every Compose stack the repository runs — each end-to-end lane and the full local stack — MUST take its configuration from committed overlay, profile and secret-overlay files. A Makefile MAY choose which configuration loads, such as the provisioning mode or the runner's profiles, and MUST NOT generate or carry configuration values. A base or domain Compose file MUST carry only values its topology fixes; a deployment's own binds and values MUST be in its overlay, and a base file MUST NOT give a credential or definition document a committed fallback.

#### Scenario: A lane stack is brought up

- **WHEN** a lane target brings its stack up
- **THEN** it names only the lane's Compose files and the run's provisioning mode, and every value the stack reads is in a committed file

#### Scenario: A base stack runs without its overlay

- **WHEN** an operator brings up a base stack file without an overlay binding its credentials
- **THEN** the services that need them refuse to start, and no committed development value is used

### Requirement: The registry reads profile-shaped env files

The registry MUST load, after its default dotenv files, `config-<profile>.env` from `CONFIG_DIRECTORY` for each entry of `ACTIVE_PROFILES` in order, a later file overriding an earlier one and the process environment overriding every file. Its filter specification path MUST be a setting those files can carry, and the filter specification loader MUST resolve its default path from that setting, the packaged specification when it is unset. The registry chart MUST render its settings from its values into a ConfigMap profile mounted under `CONFIG_DIRECTORY`, MUST take secret settings as a profile from a named existing Secret (`secretProfile`), MUST refuse the retired `auth.bootstrapKeySecret` and `auth.adminKeySecret` naming `secretProfile`, and MUST set as container environment only the two resolver variables.

#### Scenario: A lane registry layers a lane profile

- **WHEN** a registry runs with `ACTIVE_PROFILES` naming its own profile and then a lane profile
- **THEN** it takes its identity and descriptor from the first file and the lane's recommended dispute authorities from the second

#### Scenario: A profile selects the filter specification

- **WHEN** a registry's profile names a filter specification path and no `REGISTRY_FILTER_SPEC_PATH` process variable is set
- **THEN** the registry loads and serves that specification, not the packaged default

#### Scenario: The registry chart renders a release

- **WHEN** the registry chart renders a release with a `secretProfile`
- **THEN** the Deployment's environment holds only `CONFIG_DIRECTORY` and `ACTIVE_PROFILES`, the rendered and secret profiles are mounted under the configuration directory, and both are named in `ACTIVE_PROFILES`

#### Scenario: A values file uses a retired key Secret

- **WHEN** a release's registry values set `auth.adminKeySecret` or `auth.bootstrapKeySecret`
- **THEN** rendering fails naming `secretProfile`

## MODIFIED Requirements

### Requirement: A storefront's configuration reaches it through its configuration system

Every configuration value of a storefront MUST be supplied through its configuration system:
its configuration files, its secret overlay, and its loader's documented override layer. A
secret MUST reach it as a setting in its secret overlay, never as an environment variable its
configuration names. A value MAY be supplied outside that system only when it controls which
configuration is loaded — the configuration directory and the profiles to layer — or when it
must be kept from the loader, as the signing credential is. A storefront's chart MUST know a
configuration value only where the deployment itself needs it for a stated reason, such as the
port its container, probes, and Service share, or the CA bundle path it mounts, and MUST supply
outside the configuration system only values of those two kinds. Conformance is a compliance
check of the source and charts, not a runtime refusal: a storefront MUST NOT refuse to start
because a value reached it through its environment, and the loader's override layer remains
available to an operator.

#### Scenario: An operator overrides a setting on a development cluster

- **WHEN** an operator injects a setting through the loader's environment override layer into a
  running deployment and restarts it
- **THEN** the storefront starts and applies the override

#### Scenario: The chart renders a storefront's environment

- **WHEN** the bare-metal chart is rendered, with or without its CA bundle option
- **THEN** its pod environment carries only the configuration directory and the signing
  credential, and every other value, the payments key and CA bundle path included, is in a
  mounted configuration or secret overlay file

### Requirement: Payment credentials stay with their owning process

The Arkhai payments API key MUST reach only its owning buyer or seller process. Outside loopback the payments service origin MUST use HTTPS. Public renderings MUST omit resolved credentials and contain no payment authority, provider, database or worker deployment. The payments lane double is a development fixture, not a payment authority: only the end-to-end lanes and the local release, whose own values enable its subchart, run it, and release values never enable it.

#### Scenario: A non-loopback origin is plain HTTP

- **WHEN** a role's `[Settlement.arkhai_payments]` names an `http://` service origin on a non-loopback host
- **THEN** its configuration is refused, naming the HTTPS requirement

#### Scenario: A release is rendered from release values

- **WHEN** the umbrella chart is rendered without the local release's values
- **THEN** it renders no payments double and no other payment authority

### Requirement: Marketplace deployment config contains consumer data only

Arkhai payment consumers MUST use `[Settlement.arkhai_payments]` for trusted service origin, Ed25519 receipt identity, fee policy, and the owner's API key — a storefront's as `api_key` in its secret overlay, a buyer's as the environment-variable name `api_key_env` its provider reads — and `[[Dispute]]` and `[[DisputeCredential]]` entries for the dispute authorities they offer or accept; registry descriptors may recommend authorities.

#### Scenario: Payments consumer is rendered

- **WHEN** an operator enables Arkhai payments
- **THEN** only consumer policy and credential references enter marketplace public configuration, a storefront's key reaching it in its secret overlay, while the independently operated payments service owns its ledger and provider roles
