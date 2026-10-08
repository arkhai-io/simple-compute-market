## ADDED Requirements

### Requirement: The storefront does not select buyer access infrastructure

The VM storefront MUST NOT supply relay configuration with a fulfillment request. It MUST NOT hold a relay address, a relay credential, or a relay's port allocation window in its settings, and it MUST NOT populate them into the request's connectivity metadata.

Which relay serves a host is a durable property of the deployment that owns the host, recorded against the relay that the host's pool references. A storefront naming a relay per request would make a fleet-wide fact depend on a caller's configuration, and would allow two requests against one host to disagree about how that host is reached.

The buyer-facing address and port are returned to the storefront in the fulfillment result. The storefront learns how a VM is reached after it is provisioned rather than dictating it beforehand, and never holds the credential admitting a client to the relay.

#### Scenario: A storefront is configured with legacy relay keys

- **WHEN** a storefront's provisioning settings carry a relay address, domain, or dashboard credential
- **THEN** those settings are not read and no relay configuration is placed in the fulfillment request

#### Scenario: A VM is provisioned through a relay

- **WHEN** a relay-backed fulfillment succeeds
- **THEN** the storefront obtains the buyer's connection address and port from the fulfillment result

#### Scenario: Two requests target one host

- **WHEN** two fulfillment requests are served by the same host
- **THEN** both are reached through the relay referenced by that host's pool, and no request can select a different one
