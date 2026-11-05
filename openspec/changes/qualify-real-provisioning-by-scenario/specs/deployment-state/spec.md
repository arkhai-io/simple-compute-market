## ADDED Requirements

### Requirement: A storefront chart trusts a deployment-supplied CA bundle

The storefront and bare-metal storefront charts MUST offer an option that mounts a
CA bundle from a deployment-supplied Secret or ConfigMap key into the storefront
container and sets `SSL_CERT_FILE` to it. The chart MUST name no CA itself, and MUST
render neither the mount nor the variable when the option is unset. The payments kit's
transport rule is unchanged: an HTTPS origin, including a cluster-service origin, is
accepted, and plain HTTP outside loopback is refused.

#### Scenario: The option is set

- **WHEN** a release sets the CA bundle option naming a Secret key
- **THEN** the storefront container mounts that key and its `SSL_CERT_FILE` names the
  mounted file

#### Scenario: The option is unset

- **WHEN** a release leaves the option unset
- **THEN** no bundle is mounted and `SSL_CERT_FILE` is not set

#### Scenario: A cluster-service payments origin

- **WHEN** payments are configured with `https://<service>.<namespace>.svc.cluster.local`
- **THEN** the kit accepts the origin, and refuses the same origin over plain HTTP
