## ADDED Requirements

### Requirement: Whole-host storefront chain configuration is rendered or absent

Deployment of the whole-host storefront MUST render chain endpoint
configuration and a signing-key reference when Alkahest settlement is enabled,
and MUST render neither, nor a seller address, when it is disabled. The signing
key MUST arrive by Secret reference and MUST NOT be rendered as a literal value.
A chain whose deployed contract addresses are not published MUST be able to
reference a mounted address configuration file, and the mounted location and the
configured path MUST agree.

Enabling settlement without chain configuration, without a signing-key Secret
reference, or with an address mount whose Secret is unnamed MUST fail the render
rather than produce a role that starts and cannot settle.

#### Scenario: Hosted-only role is rendered

- **WHEN** Alkahest is disabled
- **THEN** no chain, wallet or seller-address configuration is present

#### Scenario: Alkahest is enabled without chain configuration

- **WHEN** settlement is enabled but no chain endpoint is configured
- **THEN** the render fails

### Requirement: Whole-host publication carries a registry write credential when one is configured

A registry that gates writes resolves a bearer credential in addition to the
per-request seller signature. Deployment of the whole-host storefront MUST
therefore be able to supply a write-scoped registry API key to publication, and
MUST supply it by Secret reference, never as a literal value. The credential is
optional: where none is configured the deployment MUST render no credential
environment. The publication client treats an unset or empty credential as
absent and sends no bearer header. The credential MUST NOT replace or relax
the signature the registry verifies on top of it. A registry's administrative
credential is a separate secret for that registry's own administrative routes
and is not this value.

The credential is sent verbatim as an HTTP bearer value, so it MUST be one line
of printable US-ASCII. A configured credential that is not MUST be refused
before any request is attempted, with a diagnostic that names the constraint and
never the value.

The publication command MUST report the round and MUST exit non-zero when the
round contains a failed candidate, so an operator step that checks only the exit
status cannot record a round that published nothing as a success. A candidate failure caused by a registry call MUST be reported only by
exception type and, where available, HTTP status: the request
URL, the request headers and the response body are request material and MUST NOT
appear in the round the operator records.

#### Scenario: The registry gates writes

- **WHEN** the storefront is rendered with a registry API-key Secret named
- **THEN** publication's credential environment is bound to exactly that Secret
  reference and no key material is rendered

#### Scenario: The registry publishes openly

- **WHEN** no registry API-key Secret is named
- **THEN** no credential environment is rendered and publication carries its
  request signatures only

#### Scenario: The configured credential cannot be sent as a header

- **WHEN** the configured credential carries a line break or other character an
  HTTP header value may not hold
- **THEN** the client refuses it before any request, and the refusal does not
  repeat the value

#### Scenario: A registry call fails against a configured credential

- **WHEN** a publication call fails, whether the transport rejects the request
  or the registry rejects the credential
- **THEN** the failed candidate records the exception type and, where there is
  one, the HTTP status, and records no header, URL or response body

#### Scenario: A candidate fails to publish

- **WHEN** a publication round returns a failed candidate
- **THEN** the command prints the round and exits non-zero

### Requirement: Provisioning host trust is pinned by deployment, not by image configuration

The provisioning deployment MAY pin the SSH host keys its playbooks accept.
Where pinning is enabled, the render MUST mount an operator-managed
`known_hosts` Secret read-only into the serving container and MUST set the
executing environment so that strict host-key checking and that mounted file
take effect together: neither checking without the file, nor the file without
checking. The environment is the authority because a configuration file shipped
in the image is outranked by it, so the deployment MUST NOT depend on the
image's own Ansible configuration for this decision. The Secret MUST be
referenced, never rendered as literal key material, and its contents remain
operator-owned; the chart does not generate, rotate, or validate pins.

Enabling pinning without a Secret reference MUST fail the render rather than
produce a role that starts and refuses every host. Where pinning is disabled,
the render MUST carry no host-trust environment and no pin mount, leaving the
image's existing defaults in force.

#### Scenario: Pinning is enabled

- **WHEN** the provisioning chart is rendered with host-key pinning enabled and
  an existing `known_hosts` Secret named
- **THEN** the serving container mounts that Secret read-only at the configured
  file location and its environment enables strict checking against exactly that
  file

#### Scenario: Pinning is enabled without a Secret reference

- **WHEN** host-key pinning is enabled but no Secret is named
- **THEN** the render fails

#### Scenario: Pinning is left disabled

- **WHEN** the provisioning chart is rendered with default values
- **THEN** no host-trust environment and no pin volume are present
