## ADDED Requirements

### Requirement: The pool authority answers the site's pool facts

Resource-pool management SHALL supply a reader satisfying the site authority's pool-facts
port without importing the site authority. Given the caller's session and a pool
identifier, it SHALL report whether the pool exists, whether it is enabled, its declared
deliverable offering modes or that they are unreadable, and whether declarations in the
pool need a host, resolved from the pool's provider and the host requirement its
composition supplies. With no host requirement supplied, no pool SHALL need a host; with
one supplied, a provider it does not name SHALL need one.

#### Scenario: A pool whose provider needs a host

- **GIVEN** a composition supplying a host requirement in which the pool's provider
  needs a host
- **WHEN** the site reads the pool's facts
- **THEN** the pool is reported existing, with its enablement and deliverable modes, and
  as needing a host

#### Scenario: A composition supplying no host requirement

- **WHEN** a composition supplying no host requirement reads a pool's facts
- **THEN** the pool is reported as needing no host

#### Scenario: A pool identifier with no stored pool

- **WHEN** the site reads the facts of a pool identifier no stored pool has
- **THEN** the pool is reported as not existing, not enabled, with unreadable deliverable
  modes, and as needing a host exactly when a host requirement is supplied

## MODIFIED Requirements

### Requirement: The pool wire contract and client are thin distributions

The resource-pool capability MUST own its pool wire models and pool route contracts in a
contracts distribution that depends on no persistence or web-framework package, and its
typed client in a separate client distribution depending only on those contracts. The
client MUST offer async and sync variants with identical operations over any transport
that provides authenticated requests, so it depends on no compute-provisioning package. The
pool authority imports its models from the contracts distribution, and the provisioning
service that hosts the pool routes assembles the capability's route contracts into its
table without owning them. The reader of a site's projected pool declarations and the
asking-rate resolution MUST live in the contracts distribution, so a consumer that only
reads a site's pools installs no pool authority.

#### Scenario: An operator administers pools

- **WHEN** an operator creates or updates a pool through the resource-pool client
- **THEN** the client signs the request from the resource-pool route contracts, and the
  operator's environment installs neither SQLAlchemy nor the compute provisioning kit

#### Scenario: A compute domain hosts no pool model

- **WHEN** the compute provisioning contracts distribution is inspected
- **THEN** it declares no resource-pool model or pool route contract

#### Scenario: A storefront reads a site's pool declarations

- **WHEN** a storefront resolves a site's projected pool declarations and asking rates
- **THEN** it does so through the contracts distribution, and its runtime dependencies
  include neither the pool authority nor SQLAlchemy through it
