## ADDED Requirements

### Requirement: API credits composes the api family kit

The API-credits domain MUST compose the `api` family's vocabulary and kit for
every concern the kit owns — the purchase shape, issuance models and digests,
issuance evidence, the authority's key service and ledger, the storefront's
issuance and settlement composition, the negotiation adapters, the quota listing
binding and publication, the buyer flows, the mechanism stages, and the bearer
gate — and MUST retain no domain-local implementation of any of them. Its
runtime behaviour — wire shapes, authentication roles and operation names,
refusal status codes and error bodies, digests, database schema and migration
history, environment prefixes and settings keys, and its service's distribution
name, image, entry point, and version response — MUST be unchanged by that
composition, each held to a recorded baseline. The retirement of the
`arkhai-apicredits-middleware` distribution is a package and import break, not a
behaviour change, and every repository consumer of it MUST migrate to the gate
library in the same change.

#### Scenario: A grant issued before the kit is read after it

- **WHEN** the family authority, composed by the API-credits service root, reads
  a grant and its request digest written by the pre-kit service
- **THEN** it recomputes the same fulfillment identity and digest and accepts an
  exact retry without a second grant

#### Scenario: A baseline is diffed

- **WHEN** a slice lands and the recorded baselines — route surface and OpenAPI
  document, authentication roles and operation names, refusal status codes and
  error bodies, environment variables and settings keys, schema and migration
  history, version response — are diffed against the service and storefront
- **THEN** every diff is empty

#### Scenario: Upgrade and rollback against a retained database

- **WHEN** the kit-composed service image starts over a copy of a pre-kit
  database, and the pre-kit image then starts over a database the kit-composed
  image has written
- **THEN** both start, serve the same routes, and read every row, so upgrade
  and rollback are each a change of image and configuration against the
  retained database

#### Scenario: A domain-local copy is sought

- **WHEN** the API-credits packages are searched for an issuance client, a
  digest function, a key service, a settlement stage, or a gate of their own
- **THEN** none is found; each is imported from a `domains/api` distribution

#### Scenario: A middleware consumer is sought

- **WHEN** the repository is searched for `apicredits_middleware` or
  `arkhai-apicredits-middleware`
- **THEN** no consumer remains; the sample app, the service's integration
  tests, the conformance runner, the READMEs, the cookbook, the workflows, and
  the Makefiles name the gate library
