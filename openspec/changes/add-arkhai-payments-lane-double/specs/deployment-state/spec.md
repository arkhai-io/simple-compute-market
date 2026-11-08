## MODIFIED Requirements

### Requirement: Payment credentials stay with their owning process

The Arkhai payments API key MUST reach only its owning buyer or seller process. Outside loopback the payments service origin MUST use HTTPS. Public renderings MUST omit resolved credentials and contain no payment authority, provider, database or worker deployment. The payments and mediation lane doubles are development fixtures, not payment or dispute authorities: only the end-to-end lanes and the local release, whose own values enable their subcharts, run them, and release values never enable them.

#### Scenario: A non-loopback origin is plain HTTP

- **WHEN** a role's `[Settlement.arkhai_payments]` names an `http://` service origin on a non-loopback host
- **THEN** its configuration is refused, naming the HTTPS requirement

#### Scenario: A release is rendered from release values

- **WHEN** the umbrella chart is rendered without the local release's values
- **THEN** it renders no payments double, no mediation double and no other payment or dispute authority

### Requirement: The local release rehearses a deployment's payments interface

The local Helm release MUST configure payments through the same values a deployment supplies — the agent's payments configuration, the runtime secret overlay and the CA bundle option — and MUST NOT use `development_auth`. Its deploy target MUST enable the payments double's and the mediation double's subcharts, which release values never enable, once per namespace, and the local deployment MUST supply the seller token in each storefront's runtime secret overlay, the VM storefront's dispute credential for the mediation double its registry recommends in that storefront's overlay, with its `ca_bundle_path` naming the file the chart mounts the CA bundle as, and the CA ConfigMap from the committed development fixtures by default, through its out-of-band step for local Secrets rather than through chart values. Each double's subchart MUST take its server certificate and key from a named existing Secret when one is given.

#### Scenario: The local release is deployed

- **WHEN** the local deploy target installs the release
- **THEN** the payments double and the mediation double run, the storefronts are configured for payments through the deployment-facing values, the VM storefront's secret overlay holds its credential for the mediation double with the chart's CA file as its `ca_bundle_path`, and no storefront uses development authentication

#### Scenario: A deployment supplies its own TLS

- **WHEN** a release names an existing Secret for a double's server certificate and key
- **THEN** that double serves with that Secret's material rather than the committed files

#### Scenario: The copied dispute credential names the chart's CA file

- **WHEN** the local deployment's out-of-band step copies the VM storefront's dispute credential from its Compose secret overlay
- **THEN** the copy's `ca_bundle_path` is the file the storefront chart mounts the CA bundle as, not the Compose stack's path
