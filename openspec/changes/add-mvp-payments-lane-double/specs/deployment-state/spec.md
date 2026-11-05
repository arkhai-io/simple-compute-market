## ADDED Requirements

### Requirement: A storefront chart trusts a deployment-supplied CA bundle

The storefront and bare-metal storefront charts MUST offer an option that mounts a CA bundle from a deployment-supplied ConfigMap key, or alternatively a Secret key, into the storefront container and sets `SSL_CERT_FILE` to it. The chart MUST name no CA itself and supply no default, and MUST render neither the mount nor the variable when the option is unset.

#### Scenario: The option names a ConfigMap key

- **WHEN** a release sets the CA bundle option naming a ConfigMap and key
- **THEN** the storefront container mounts that key and its `SSL_CERT_FILE` names the mounted file

#### Scenario: The option names a Secret key

- **WHEN** a release sets the CA bundle option naming a Secret and key instead
- **THEN** the storefront container mounts that key and its `SSL_CERT_FILE` names the mounted file

#### Scenario: The option is unset

- **WHEN** a release leaves the option unset
- **THEN** no bundle is mounted and `SSL_CERT_FILE` is not set

### Requirement: A storefront chart injects the payments key from a deployment Secret

The storefront and bare-metal storefront charts MUST offer an option naming a Secret and key that holds the storefront's payments API key, and MUST expose it to the storefront container under the environment variable the agent configuration's `[Settlement.arkhai_payments].api_key_env` names. The chart MUST refuse the option when the configuration names no `api_key_env`, and MUST render no variable when the option is unset.

#### Scenario: The key option is set

- **WHEN** a release names a Secret and key for the payments key and the agent configuration sets `api_key_env`
- **THEN** the storefront container's environment has that variable from that Secret key

#### Scenario: The configuration names no key variable

- **WHEN** a release sets the key option but the agent configuration has no `api_key_env`
- **THEN** rendering fails naming the missing setting

#### Scenario: A storefront offers only payments

- **WHEN** a release configures a storefront with payments and with Wallet, Chains and Alkahest removed and RPC off
- **THEN** the chart renders it with the payments configuration, the CA bundle and the key variable, and nothing for the removed settings

### Requirement: The local release rehearses a deployment's payments interface

The local Helm release MUST configure payments through the same values a deployment supplies — the agent's payments configuration, the payments key Secret and the CA bundle ConfigMap — and MUST NOT use `development_auth`. Its deploy target MUST enable the payments double's subchart, which release values never enable, once per namespace, and the local deployment MUST supply the key Secret and CA ConfigMap from the committed development fixtures by default, through its out-of-band step for local Secrets rather than through chart values. The subchart MUST take its server certificate and key from a named existing Secret when one is given.

#### Scenario: The local release is deployed

- **WHEN** the local deploy target installs the release
- **THEN** the payments double runs, the storefronts are configured for payments through the deployment-facing options, and no storefront uses development authentication

#### Scenario: A deployment supplies its own TLS

- **WHEN** a release names an existing Secret for the double's server certificate and key
- **THEN** the double serves with that Secret's material rather than the committed files

### Requirement: A storefront checks its payments access from its own container

Each storefront CLI MUST offer `check-payments --account <id>`, which loads the storefront's configuration as the running storefront does, reads the named account's balance through the payments kit with the storefront's own credential and trust, prints one JSON outcome containing no credential, and exits nonzero naming the failing step: configuration, credential, transport, or the service's refusal code. The storefront charts MUST offer a Helm test that runs it directly, not through the storefront's entrypoint, with the storefront's image, configuration and secrets mounts, identity credential, CA bundle mount and `SSL_CERT_FILE`, and payments-key variable, rendered from the same chart definitions as the storefront Deployment, and without the storefront's data volume, health probes, or network-overlay capabilities and device.

#### Scenario: The storefront can reach its payments service

- **WHEN** an operator or a lane runs `check-payments` for the seller's account in a configured storefront container
- **THEN** it prints an `ok` outcome with the service URL and the account's assets and exits zero

#### Scenario: The storefront does not trust the payments origin

- **WHEN** the storefront's CA bundle does not cover the payments service's certificate
- **THEN** the check prints a `failed` outcome naming the transport step and exits nonzero

#### Scenario: A deployment reruns the check

- **WHEN** a deployment runs the storefront chart's Helm test
- **THEN** the check runs with the storefront's image, configuration, credential, CA mount and key variable, and mounts no storefront data volume, so it does not depend on where the storefront's volume is attached
