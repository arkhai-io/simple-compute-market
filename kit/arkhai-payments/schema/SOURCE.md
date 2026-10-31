# Payments wire contract source

`payments.schema.json` is the Arkhai payments service's current wire contract. The
service publishes it inside its OpenAPI 3.1 document, and the vendored file is
extracted from that publication. It is identified by content, not by where it was
obtained.

- Vendored schema SHA-256: `5cf22707c0e5c1c1c3ffd398d0a1710e136e719eee841c39323eba837e0ea848`
- Test-vector SHA-256: `e1a26e4c3fcde9724e5ec9bc606d20bebe49404554eca69a4cb78e4146215631`

## How the schema was extracted

The extraction made three changes and nothing else:

- the document's `components.schemas`, 93 definitions, became the schema's `$defs`;
- every reference into `#/components/schemas/` was rewritten to `#/$defs/`;
- the schema was given the neutral `$id` `urn:arkhai:payments:wire-contract` and title.

Everything else is as published. That includes the OpenAPI rendering, which differs in
form from a standalone JSON Schema publication:

- a constant is a one-value `enum`;
- a nullable field is stated as an `allOf` of its type and a type list naming `null`;
- safe-integer maxima are absent.

The generator types a one-value `enum` as a literal, the constraint `const` states.

## Required nullable durations

`OncePart.maxHoldExtension` and `RatePart.maxHoldExtension` are required, and the
service accepts `null` for them. The publication states each as
`allOf: [{$ref: Duration}, {type: [string, null]}]`. That intersection admits no null,
because `Duration` is a string, so a model generated from it as published refuses a
mandate the service accepts.

The vendored schema stays as published. `scripts/generate_models.py` generates from a
normalized copy instead, in which exactly these two properties read
`anyOf: [{$ref: Duration}, {type: null}]`: still required, and either a duration or
null. Generation refuses to run if either property is no longer required or no longer
has the published form, so a corrected publication is reviewed rather than silently
reinterpreted. No other `allOf` is reinterpreted.

`ConnectStatus.connectedAccount` has the same published form. The kit never calls the
onboarding operations that return it, and nothing here establishes what the service
accepts for it, so it is generated as published.

On the wire, a required property keeps its null and an optional property without a
value is omitted. An optional property stated as an explicit `null`, such as a part's
`end`, is normalized the same way: the models accept it, the wire form omits it, and
the transaction ID hashes that normalized mandate, not the raw JSON.
`market_arkhai_payments.canonical.wire_json` produces that form for the approval body,
the transaction ID's JCS, and receipt verification alike, so within the kit they cannot
disagree. The kit's own mandates always state `P0D`, and its buyer check refuses any
other value, null included.

The publication has one defect, kept rather than corrected. `HttpUrl`'s pattern ends in
a leaked regular-expression flag (`$/i`), so it matches no URL. Only the cash, top-up,
onboarding, and billing-portal types use `HttpUrl`, and the kit calls none of them.

## The vectors

`test-vectors/payments.json` is the service's previous vector publication, byte for
byte. Current-wire producer vectors were not supplied with this schema snapshot; the
kit retains the previous publication for canonical framing and uses an explicit SCM
synthetic current-wire fixture.

The previous vectors' mandates and receipt use the previous wire: mandate-level
authorities, and a hold until the transaction stops. The current models refuse both,
and `scripts/check_vectors.py` asserts that refusal.

The check also keeps the vectors as evidence of what does not depend on a part's shape.
Over the raw published JSON it checks:

- each mandate's JCS transaction identity;
- the receipt's signing frame and its Ed25519 signature;
- the attachments' canonical hashes.

The current wire is pinned instead by the kit's own synthetic fixture
(`tests/test_wire_contract.py`). That fixture is a literal approval request written from
this schema and the service's documented normalization of mandate-level authorities into
each part. It is not producer provenance.

## Updating the contract

To update the contract:

1. Replace the schema with a newer publication, extracted the same way.
2. Record its hash above.
3. Regenerate the models with `python scripts/generate_models.py`, run from this package.
   If it refuses the required nullable durations, reconcile the normalization with
   the new publication first.

When current-wire producer vectors are supplied, replace `payments.json` with them,
record their hash, and hold the fixture to them. In the same change, revise
`scripts/check_vectors.py`, whose assertions expect the current models to refuse the
previous vectors, and the README's wording on the previous vectors.

Normal builds and client imports do not access the payments service or the network.
