# Payments wire contract source

The standalone `payments.schema.json` and current producer vectors are selected by
content, without importing the payments service implementation or reading it at
build or import time.

| Publication | SHA-256 |
|---|---|
| Original standalone schema | `380a1a9d9508bf93a0641421760427118782bfa9d429b51aec0571b840188fb7` |
| Vendored standalone schema | `b7be9fb05b306de5469903ed70c6a821e5129ce757c4d20c9b6cef4e77b32e3a` |
| Current `test-vectors/payments.json` | `61cfb19e1fb85e12c58484a09f47e89878069e58e44071fb2f8c868bd5c67adf` |
| Historical `test-vectors/historical-payments.json` | `e1a26e4c3fcde9724e5ec9bc606d20bebe49404554eca69a4cb78e4146215631` |

The only transformation of the standalone schema replaces the top-level `$id`
string with `urn:arkhai:payments:wire-contract`. All other bytes, including
formatting, remain unchanged. Its 95 definitions retain the published constraints.
Both vector files are byte-for-byte publications. Their account IDs and repeated
signing seeds are deterministic development fixtures, never operational credentials;
they must never be used on a public network.

## Required nullable durations and optional values

`OncePart.maxHoldExtension` and `RatePart.maxHoldExtension` are required unions of
`Duration` and null. The generator checks those exact shapes and required status,
and preserves those definitions unchanged. A changed nullable contract stops
generation for review.

On the wire, a required property keeps its null and an optional property without a
value is omitted. An optional property stated as an explicit `null`, such as a
part's `end` or a receipt part's `rate`, is normalized the same way, though the
schema does not allow that null: the models accept it, the wire form omits it, and
the transaction ID hashes that normalized mandate, not the raw JSON. Receipts and
snapshots parse the same way, and a receipt signature is verified against the
normalized body. An inserted null changes no value the kit then checks or stores,
because the kit computes transaction identity and verifies receipt signatures over
the parsed model's canonical JSON, not over received bytes. Conversely, a body the
service signed with such a null in it would not verify.
`market_arkhai_payments.canonical.wire_json` produces that form for approval bodies,
transaction JCS and receipt verification. The kit derives `P0D` and its buyer policy
refuses other maximum hold extensions, including null.

The standalone publication also includes effective snapshot ends, nonnegative
snapshot and receipt gross amounts, safe-integer numeric maxima and a valid HTTP
URL pattern. `DealCommitment` is a reference to `Sha256Hex`; generation may retain
both root wrappers, so comparisons use their JSON value rather than a wrapper.

For generation only, `Balance.available.propertyNames` is dereferenced from
`Asset` to that definition's identical string and pattern constraints. The pinned
generator otherwise emits unhashable Pydantic root models as dictionary keys.
This preserves asset validation while using plain string keys. The vendored
schema stays unchanged, and generation refuses an unexpected map-key reference.
The generator emits its inline constrained key as `constr(pattern=...)`; the wrapper
checks that sole call's exact constraint and renders the equivalent
`Annotated[str, Field(pattern=...)]` so the generated file also passes static typing.
Unexpected output count, argument shape or pattern stops generation.

## Conformance evidence

`scripts/check_vectors.py` checks current mandates and approvals through the strict
models, preserving required nulls and canonical transaction identities. It checks
the four producer signed snapshots and every snapshot in the two published event
scenarios: model round trips, snapshot signing frames and signatures, embedded
receipt signatures, transaction bindings, and event/request shapes. It checks
attachment canonical hashes and sizes, and approval agreement commitments.
These are producer data checks, not execution of the external event reducer.

The historical publication remains a separate raw framing regression. Its obsolete
mandates and receipt are refused by current models. Raw JCS transaction identities,
receipt signing bytes and Ed25519 signature, approval commitments and attachment
hashes remain verified. Historical signature verification does not upgrade obsolete
mandates into supported requests.

The independent synthetic approval fixture and nullable tests additionally pin
marketplace mandate derivation, omitted optionals, approval transport bodies,
transaction IDs and receipt verification. Local conformance does not establish the
shapes of every live service response or prove provider funding, cash operations
or physical fulfillment. Verify exact selected-server responses and retained
historical receipt signatures before deploying affected consumers.

## Updating the contract

1. Select a standalone schema and producer vectors and inspect them for public
   suitability. Keep historical raw-signature fixtures separately.
2. Record original hashes, exact neutral-identifier transformations and vendored
   hashes here.
3. Run `python scripts/generate_models.py` with the package's pinned generator.
   Reconcile any required-nullable guard failure against the new publication.
4. Run `python scripts/generate_models.py --check`, `python scripts/check_vectors.py`,
   the package tests and typing checks. Review generated shape changes and verify
   exact-server compatibility before consumer rollout.

Normal builds and client imports do not access the payments service or the network.
