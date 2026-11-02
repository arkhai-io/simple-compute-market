# Payments wire contract source

The schema and conformance vectors are one published contract, vendored together
from arkhai-payments main at `3be127e40820a513c3d4611b3f42371555255fdb`.

- Published schema SHA-256: `380a1a9d9508bf93a0641421760427118782bfa9d429b51aec0571b840188fb7`
- Vendored schema SHA-256: `b7be9fb05b306de5469903ed70c6a821e5129ce757c4d20c9b6cef4e77b32e3a`
- Test-vector SHA-256: `61cfb19e1fb85e12c58484a09f47e89878069e58e44071fb2f8c868bd5c67adf`

The only schema change is its `$id`, replaced by the neutral
`urn:arkhai:payments:wire-contract`. Vectors are byte-identical to the publication.
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
