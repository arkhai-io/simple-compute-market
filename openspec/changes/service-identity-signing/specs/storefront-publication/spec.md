## ADDED Requirements

### Requirement: Storefronts hold a registry of site identities

A storefront MUST hold, for each site authority it uses, a record of that site's
identifier, its address, and its scheme-tagged identity, and MUST verify
authority-originated calls against that identity. The identity MUST be expressed in the
repository's scheme-tagged identity vocabulary rather than as a scheme-specific field, so
a later scheme carries its own identifier form. The registry MUST be reached through an
interface rather than read directly from configuration, so its source can change without
changing its consumers.

#### Scenario: An authority-originated call arrives

- **WHEN** a site authority calls a storefront
- **THEN** the storefront verifies the call against that site's registered identity, and
  rejects a call it cannot attribute to a registered site

#### Scenario: A storefront uses several sites

- **WHEN** a storefront aggregates several site authorities
- **THEN** it holds a separate identity for each, and an identity registered for one site
  does not authenticate another

#### Scenario: The registry's source changes

- **WHEN** site records move from configuration to durable storage
- **THEN** consumers of the registry are unchanged

#### Scenario: A scheme other than the default is registered

- **WHEN** a site's identity uses a different identity scheme
- **THEN** the registry stores that scheme's own identifier form without a
  scheme-specific field being added
