## MODIFIED Requirements

### Requirement: API credits composes the api family kit

The API-credits domain MUST compose the `api` family's vocabulary and kit for
every concern the kit owns — the purchase shape, issuance models and digests,
issuance evidence, the authority's key service and ledger, the storefront's
issuance and settlement composition, the negotiation adapters, the quota listing
binding and publication, the buyer flows, the mechanism stages, and the bearer
gate — and MUST retain no domain-local implementation of any of them. Its
runtime behaviour — wire shapes, authentication roles and operation names,
refusal status codes and error bodies, digests, database schema, environment
prefixes and settings keys, and its service's distribution name, image, entry
point, and version response — MUST each be held to a recorded baseline. Its
service and storefront databases MUST be built by the family libraries'
migration chains through `apicredits-service-migrate` and
`apicredits-storefront-migrate`, which adopt a database marketplace 0.3.0 ran
on, and any other non-empty database those chains did not build MUST be
refused. The retirement of the
`arkhai-apicredits-middleware` Python distribution is a package and import
break, not a behaviour change, and every repository consumer of it MUST import
the gate library instead.

#### Scenario: A baseline is diffed

- **WHEN** the service or storefront changes and the recorded baselines — route surface and OpenAPI
  document, authentication roles and operation names, refusal status codes and
  error bodies, environment variables and settings keys, schema, version
  response — are diffed against the service and storefront
- **THEN** every diff is empty

#### Scenario: A database the chain did not build

- **WHEN** a migrate command or an application startup meets a non-empty
  database its chain did not build and marketplace 0.3.0 did not run on
- **THEN** it is refused as unsupported, naming the command, and nothing is
  applied

#### Scenario: A domain-local copy is sought

- **WHEN** the API-credits packages are searched for an issuance client, a
  digest function, a key service, a settlement stage, or a gate of their own
- **THEN** none is found; each is imported from a `domains/api` distribution

#### Scenario: A middleware consumer is sought

- **WHEN** the repository is searched for the `apicredits_middleware` Python
  package or the `arkhai-apicredits-middleware` Python distribution
- **THEN** no consumer remains; the sample app, the service's integration
  tests, the Python conformance runner, the READMEs, the cookbook, the
  workflows, and the Makefiles name the gate library, while the TypeScript and
  Rust gates under `domains/api/gate-ports/` keep their own package
  names
