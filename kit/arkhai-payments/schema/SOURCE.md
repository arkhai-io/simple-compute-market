# Payments wire contract source

The schema and conformance vectors are one published contract, vendored together
from arkhai-payments main at `3be127e40820a513c3d4611b3f42371555255fdb`.

- Published schema SHA-256: `380a1a9d9508bf93a0641421760427118782bfa9d429b51aec0571b840188fb7`
- Vendored schema SHA-256: `b7be9fb05b306de5469903ed70c6a821e5129ce757c4d20c9b6cef4e77b32e3a`
- Test-vector SHA-256: `61cfb19e1fb85e12c58484a09f47e89878069e58e44071fb2f8c868bd5c67adf`
- Historical `test-vectors/historical-payments.json` SHA-256: `e1a26e4c3fcde9724e5ec9bc606d20bebe49404554eca69a4cb78e4146215631`, a separate raw-framing regression kept beside the current publication and not packaged as a contract resource

The only schema change is its `$id`, replaced by the neutral
`urn:arkhai:payments:wire-contract`. Vectors are byte-identical to the publication; their account IDs and repeated signing seeds are deterministic development fixtures, never operational credentials, and must never be used on a public network.
There is no unpublished payments candidate: all required per-part authorities,
notice/partial-period rules, end rules, extensions and stop-relative holds are
published. Selecting an unavailable proposed contract fails closed, not as a union
with the published models. Mediation is a separate contract, not part of this schema.

## Producer evidence

The publisher's partial-period billing integration evidence records **49 tests /
434 assertions passing against its ledger and persistence**. The cases cover
payer, payee and `chosen` authority stops under all three cut rules, immediate and
scheduled stops, forbidden/missing overrides, delayed-start term ends, and partial
reversals before/after a prorated stop with fee compensation. A later clamped-end
integration run records **50 tests passing**, including zero-reservation approval.
These are producer-reported integration results, not SCM runs or real-HTTP
qualification of chosen/end/reverse. The publisher's independent HTTP encounter
covered fixed payer/payee treatment only; it did not independently drive the
broader chosen/end/reverse cases.

The vendored vectors include signed before/after-start snapshots, term-end and
clamped-approval snapshots, partial reversals while running and after stop, and
same-key payer-stop replay before/after its notice deadline. The stop-retry vectors
are fixed-clock producer fixtures, not a real lost HTTP response. SCM's vector
runner replays those bytes through its shared fixture engine; HTTP lane qualification
and hosted-deployment qualification remain separate.

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

The historical publication remains a separate raw framing regression. Its obsolete
mandates and receipt are refused by current models. Raw JCS transaction identities,
receipt signing bytes and Ed25519 signature, approval commitments and attachment
hashes remain verified. Historical signature verification does not upgrade obsolete
mandates into supported requests. `scripts/check_vectors.py` runs the installed-resource replay and then this check.

## Updating and installed resources

Replace schema and vectors together, restore the neutral `$id`, update the
provenance and hashes here, then run `make generate-models` and `make test` in this
package. The generator copies canonical `schema/` and `test-vectors/` bytes into
`src/market_arkhai_payments/contract_data/` for the one-package wheel. `check-generated`
rejects resource drift as well as model drift; packaged files are generated, never
independently maintained. The installed
`market_arkhai_payments.contracts.get_contract()` API supplies schema/vector bytes,
generated models and publication/hash metadata without sibling checkouts or network
access. Build and client imports never contact the publisher.
