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

## Authority selection

The foundation's `market_deal_lifecycle.selection.AuthoritySelection` is a
resource-free option-preference callback. The composition passes registry-local
resolved `DisputeEntry` lists and installed `TermContext` capabilities. It checks
the full authority identity and params, installed interface, advertised payment
mechanism and lifecycle timing/capability rules before commitment. Unknown
mechanisms cannot carry lifecycle terms. A missing authority list refuses hosted
options with the diagnostic naming local entries and registry opt-in.

VM and API-credit policies inject it into `BuyerSettlementPolicy`; bare-metal
validates its explicit option ID through the same helper. Core receives only a
callback returning a rank or refusal, not a lifecycle implementation. Mechanism
and explicit clause priority remain primary; authority preference precedes the
option-ID tie-break within them, including across listings. Compatibility and
explanation callers pass the listing so another registry's recommendations never
broaden admission. Exact params equality is the conservative default; there is no
interface-specific relaxation.

The VM buyer's committed `examples/authority_selection.py` exercises this path
without a wallet, registry connection, service credential or deployment.

## Buyer half

`BuyerLifecycle` receives a resolver for immutable `BuyerDeal` projections from
retained Agreements, payment/dispute adapter tables, an `OperationStore` and a
signed `BuyerPeer`. `FileEvidenceStore` also implements the atomic operation
store; reopening it retains the same-key/content guard across process restarts.
The operation guard is retained even when evidence becomes eligible for pruning.
The generic kit imports neither a mechanism nor a dispute implementation.

`submit(command)` dispatches payment commands only to the payment adapter and
`dispute`, `delivery_end` intents and `append` only to the Agreement's dispute
adapter. The returned outcome is the counterpart's unchanged answer, including
mixed per-part protection, pending results and unknown lost responses. No local
clock closes a filing window and no requested remedy is applied locally.
`append(...)` asks the dispute adapter to package the supplied evidence; callers
never manufacture interface-specific append JSON. Free-form filing requests are
built by the owning dispute adapter and carried as an `InterfaceRequest` payload.

After a potentially recorded filing the half sends a stable-key courtesy hint.
An optional asynchronous `observe_hint(message, outcome)` receives its separate
acknowledgement; an unavailable storefront never changes the filing's outcome.
`read(id)` merges the buyer's direct payment events/open extensions with the
Agreement authority's cases/dispute events and the signed storefront's delivery
view. It ignores the storefront's financial interpretation. With no payment
adapter the authority view is explicitly rejected, naming the mechanism, but the
delivery view remains available. `commit(message)` checks the retained reference
before sending the peer message. Canonical surrender and outage journaling are
separate from filing a delivery-end intent. A lost surrender response is retried
under the original key before fixing a case claim; a transient loss does not
commit the buyer to contested observation time. When the acknowledgement selects
an earlier non-surrender end, the half skips automatic payer filing.

Reproduce the injected first-use journey after rebuilding wheels:

```sh
make -C kit/deal-lifecycle-buyer build reinit
(cd kit/deal-lifecycle-buyer && uv run --find-links ../../.dist python examples/first_use.py)
```

The example owns and removes a temporary database. It exercises the buyer half,
not deployed authority or lifecycle-route behavior.

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
