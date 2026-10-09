## ADDED Requirements

### Requirement: Deployable stack per market domain

Every market domain intended for deployment MUST have a stack definition that stands its
services up, following the same topology conventions as the other domains' stacks. A
domain without a stack definition MUST NOT be described as deployable.

#### Scenario: A domain is stood up

- **WHEN** an operator stands up a market domain's services
- **THEN** a stack definition exists for it, following the same conventions as the other
  domains

#### Scenario: A domain's deployment topology changes

- **WHEN** a domain's services are composed differently — for example as an additional
  contract inside another storefront process rather than as its own service
- **THEN** the stack definition reflects the composition actually deployed

### Requirement: Bare-metal buyer ships as a clean wheel contribution

The repository MUST build `arkhai-bare-metal-buyer` as a wheel containing only its buyer
package and entry-point metadata, with internal dependencies consumed from built wheels,
and aggregate distribution, review-scope, installation, and reinitialization targets MUST
include it. The installed buyer MUST address independently configured authenticated
registry and storefront authorities and MUST NOT depend on a co-located seller database,
provisioning socket, container name, compose-only hostname, test credential, or bypass
profile; removing the wheel MUST leave other installed domains starting normally.

#### Scenario: Wheel is installed into a clean environment

- **WHEN** the core buyer, bare-metal domain, required kit and client wheels, and bare-metal buyer wheel are installed from the staged wheelhouse
- **THEN** entry-point discovery registers `bare_metal.v1`, the namespaced CLI imports, and the installed metadata has no undeclared source-checkout dependency

#### Scenario: Buyer wheel is removed

- **WHEN** the bare-metal buyer distribution is uninstalled while the core buyer remains
- **THEN** the bare-metal namespace disappears and other installed domain commands continue to start normally

#### Scenario: Buyer runs outside the seller stack

- **WHEN** the installed buyer is configured with remote registry and storefront authorities and their exact trust pins
- **THEN** discovery, negotiation, settlement, status, access, and teardown use public authenticated APIs exactly as in local deployment, and a production installation with no e2e fixture, mock profile, or source checkout remains runnable without direct database, local provisioner, or unsigned transport access
