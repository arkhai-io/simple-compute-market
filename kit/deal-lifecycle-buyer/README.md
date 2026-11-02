# Buyer lifecycle evidence

`market_deal_lifecycle_buyer` owns the buyer's exact-envelope store. The buyer
composition passes a root beside its profile metadata; this kit never reads buyer
configuration. VM and bare-metal CLI negotiation paths compose the store at
`profile_store_path().parent / "evidence"`. Authentication replay expiry does not
remove these records.

## Capture and commitments

Pass `FileEvidenceStore(root).capture` as the injected `capture` callback to the
production negotiation API or a storefront client. Verified incoming envelopes
and the associated signed outgoing request are committed to `evidence.sqlite3`
before the parsed response returns. A failed evidence write prevents commitment.
The store uses transactional updates and restrictive file permissions.

`remember_commitment(negotiation_id, commitment_ref)` records the known reference
and binds it to the most recent kept seller acceptance. A new reference marks the
previous one superseded; its evidence and acceptance binding remain exportable.
The asynchronous `EvidenceStore` port is supported as well. Callers adding local
observations or authority records through `put` supply the producer in the item's
`context`; export computes its digest without reconstructing its body.

## Pruning

`prune_command(store, reader, now=...)` reads every negotiation through the
composition's injected asynchronous reader before considering deletion. The
reader returns a `RetentionObservation` with the accepted adjudication term and
adapter availability, commitment status, delivery end, physical recovery,
complete per-part payouts and complete case closes. A missing boundary, open
case, unpaid part, unavailable read or absent adapter/terms retains evidence.
Running deals cannot age out merely because their latest event is old. An
uncommitted acceptance requires its explicit expiry. Committed deals retain
through the dispute window after the latest of all required boundaries.
Deletion compares the evidence snapshot so a concurrent capture is not removed.

`create_evidence_command_group(store_factory, reader, terms_from_agreement=...)` supplies composable Typer
`prune` and `export` commands. The domain's lifecycle composition supplies the
fresh authority reader; the kit does not invent an offline read or infer payout
from elapsed time. A `prune` command prints deleted IDs and reasons for records it
kept.

## Case export

`export_case(store, negotiation_id, claim=..., requested_outcome=...,
terms_from_agreement=..., commitment_ref=None)` returns the neutral `CasePayload`. The default selects the
one live commitment; an explicit retained reference can select a superseded one.
The bundle includes the exact accepted Agreement bytes, lifecycle terms read
through the composition's `terms_from_agreement(raw_bytes)` projection using the
selected option's accessor, claim, requested outcome and ordered
evidence with producer, signing/observation time, digest, headers and exact body.
A missing acceptance binding or producer fails closed. Export performs no
filing, remedy calculation or payment operation.

The composed command accepts `export NEGOTIATION_ID --claim TEXT
--requested-outcome JSON [--commitment-ref REF]` and emits one JSON bundle with
base64 bodies, not re-serialized originals.

## First use and validation

From the repository root:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist-ci
make -C kit/deal-lifecycle-buyer test
```

The library integration scenario starts an owned loopback HTTP seller with
public deterministic test identities, negotiates through the actual production
transport and reopens the evidence database inside the pre-payment acceptance
callback. It requires no credentials or deployment, and stops its server on all
paths. The export scenario also drives the composed `export` and `prune`
commands. Each scenario owns temporary state; no resident server is needed.
