# CLI Query Language Specification

## Purpose

Define the two compact, typed command-line languages used to query market resources and constrain or construct settlement options without leaking mechanism prerequisites into normal marketplace commands.

## Requirements

### Requirement: Common comparison grammar

The resource and settlement DSLs MUST parse space-separated comparisons using `=`, `!=`, `<`, `<=`, `>`, `>=`, `in`, and `notin` over declared boolean, integer, decimal, string, and list values. Comparisons inside one query or clause MUST be implicitly conjunctive. General boolean operators, parentheses, executable expressions, interpolation, and undeclared coercions MUST be rejected with the source position and accepted vocabulary; malformed input MUST NOT be partially applied.

#### Scenario: A query contains several comparisons

- **WHEN** a user supplies `gpu_model=H200 gpu_count>=4 region in [us-east,us-west]`
- **THEN** the parser produces one typed conjunction containing three comparisons in source order

#### Scenario: Unsupported boolean syntax is supplied

- **WHEN** a query contains `or`, parentheses, or another undeclared expression form
- **THEN** parsing fails before discovery, publication, negotiation, or settlement and identifies the unsupported token

### Requirement: Resource queries are filter-spec typed

A resource query MUST resolve field names, operators, value types, missing-value behavior, and aliases against the active registry filter specification. Shared CLI code MUST NOT hardcode VM or other domain field vocabularies. Compilation MUST produce the registry's canonical query parameters and retain the filter-spec identity used for compilation so the existing ETag precondition protects query meaning.

#### Scenario: Declared resource query is compiled

- **WHEN** the active filter specification declares `ram_gb_min` as a lower-bound integer filter and the user supplies `ram_gb>=256`
- **THEN** the compiler emits the declared canonical filter input under that specification and the registry query carries its matching ETag

#### Scenario: Resource field is unknown

- **WHEN** the resource query names a field absent from the active filter specification
- **THEN** the buyer rejects the query before the registry listing request and reports the available declared fields

### Requirement: Settlement clauses are correlated ordered alternatives

Each `--settlement` occurrence MUST form one typed conjunction over one `SettlementOption`. Repeated clauses MUST be evaluated in command order as pre-acceptance alternatives. Every comparison in a clause MUST match the same option; comparisons MUST NOT be satisfied by different options from one listing. Explicit clauses MUST only narrow installed, enabled, mechanism-compatible advertised options and MUST NOT enable a mechanism, invent an option, or authorize post-acceptance failover.

#### Scenario: Two settlement alternatives are supplied

- **WHEN** the buyer supplies a Stripe clause followed by an Alkahest clause and both have compatible advertised matches
- **THEN** selection considers the Stripe clause first and retains the Alkahest clause only as a pre-acceptance alternative

#### Scenario: Predicates occur on different options

- **WHEN** one listing has a Stripe USD option and a separate Alkahest option whose fields collectively but not individually satisfy one clause
- **THEN** the clause does not match that listing

#### Scenario: Accepted mechanism later becomes unavailable

- **WHEN** accepted Terms pin an option selected through a settlement clause and its mechanism later becomes disabled or unready
- **THEN** recovery resumes the pinned obligation without evaluating another clause

### Requirement: Settlement fields have common and mechanism-owned namespaces

The settlement DSL MUST reserve common fields for immutable option identity and mechanism-neutral values, including mechanism, option ID, and asset. A settlement registration MAY contribute typed public projection fields only under its configuration-key namespace, such as `stripe.method` or `alkahest.chain`. Unknown, role-inapplicable, secret, credential, provider-administrator, raw RPC, or non-public fields MUST be rejected. Shared parsing and selection MUST treat contributed values as typed projections and MUST NOT interpret opaque mechanism parameters.

#### Scenario: Qualified Stripe field is used

- **WHEN** a clause contains `mechanism=stripe stripe.method=card`
- **THEN** the Stripe registration validates and projects the public method field while shared selection only evaluates the typed result

#### Scenario: Provider field is requested

- **WHEN** a clause names a Stripe provider ID, credential, webhook value, or authority-administrator field
- **THEN** validation rejects the field without contacting the hosted authority or exposing any provider data

### Requirement: Publication rates are asset-scoped human quantities

A settlement publication clause that sets a rate MUST name its asset and unit and MUST express the rate as a decimal human quantity. The selected mechanism MUST normalize that quantity exactly once to its canonical integer base or minor units without rounding. A missing asset/unit, excessive precision, zero or negative value where unsupported, or one untyped price reused across mechanisms MUST fail before publication. Each mechanism alternative MUST receive its own explicit rate even when their displayed human values are equal.

#### Scenario: Equal displayed rates use different scales

- **WHEN** a seller publishes `2/hour` for USD and separately `2/hour` for a six-decimal token
- **THEN** the Stripe option records 200 minor units and the token option records 2000000 base units without sharing an intermediate `min_price`

#### Scenario: Decimal cannot be represented exactly

- **WHEN** the named asset scale cannot represent the supplied decimal rate without rounding
- **THEN** publication rejects that clause and publishes no option derived from it

### Requirement: Buyer action policy is mechanism neutral

Normal purchase and resume commands MUST accept one `--action` policy with values `open`, `print`, or `fail`. `open` MUST open a returned transient buyer action, `print` MUST display it without opening, and `fail` MUST stop before performing the action while preserving resumable accepted state. The policy MUST apply to any mechanism action and MUST NOT cause an action URL or secret payload to enter durable logs.

#### Scenario: Automated buyer forbids interaction

- **WHEN** a resumed settlement returns a browser action and the buyer selected `--action fail`
- **THEN** the command exits actionably without opening the URL, changing mechanisms, or losing the accepted settlement reference

### Requirement: Explanation is deterministic and sanitized

Discovery and purchase commands MUST support an explanation mode that reports the canonical parsed resource query, settlement clauses, filter-spec identity, predicates pushed to the registry, predicates evaluated locally, ordered survivor counts, selected option identity when any, and stable rejection categories. Explanation MUST be deterministic for the same inputs and listing set, MUST perform no negotiation, publication, settlement, chain, or provider mutation, and MUST NOT expose credentials, transient URLs, private RPC data, or opaque provider payloads.

#### Scenario: Resources exist but settlement is incompatible

- **WHEN** resource filtering leaves listings but no settlement clause matches an installed enabled option
- **THEN** explanation distinguishes resource survivors from settlement rejection and reports sanitized mechanism/asset mismatch counts

### Requirement: Normal commands and mechanism utilities are separate

Normal discovery, buy, resume, reclaim, and publication paths MUST use the resource and settlement DSLs plus mechanism-neutral lifecycle controls. Raw mechanism inspection, setup, and mutation utilities MUST live only under `settlement <mechanism>` command namespaces and MUST NOT add mechanism-specific flags back to normal commands. Legacy convenience filter flags, `--filter name=value`, provider-specific normal-path action flags, legacy settlement overrides, and top-level raw escrow utilities MUST be removed without aliases at the coordinated CLI cutover.

#### Scenario: Buyer needs raw Alkahest inspection

- **WHEN** a buyer invokes an on-chain escrow inspection utility
- **THEN** it is available under the Alkahest settlement namespace and the normal `buy` and `settle` help surfaces contain no raw chain/token override flags
