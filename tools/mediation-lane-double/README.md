# Mediation lane double

An HTTPS double of an `arkhai.mediation.v1` dispute authority, run beside the
payments double in every end-to-end lane. It reproduces the authority's API
mechanics against the mediation kit's vendored contract and takes every decision
the authority would make from a rule a scenario installs, the way mock
provisioning takes a job's outcome. It never re-implements the authority's
decision logic. It is a lane collaborator: it imports the mediation and payments
kits and the lane doubles' control contract, and nothing imports it.

## What it serves

The authority's routes, authenticated by bearer token and validated against the
vendored contract:

- `POST /cases` files a case under an `Idempotency-Key`. The double reads the
  transaction's signed snapshot from the payments double as the authority's own
  account, refuses a filer who is neither party (`filer_not_party`) and an
  Agreement whose JCS SHA-256 is not the receipt's `deal`
  (`agreement_hash_mismatch`), each a `rejected` filing that reserves no case,
  extends nothing and makes the Agreement known to no reader, and sends `extend`
  for each part. A part payments extends is reported `held` with its
  extension's event sequence. Only payments' nothing-held refusal,
  `hold_not_extendable`, reports a part `not_held`, its reason read from the part's
  signed amounts: `paid_out` when any money was released, otherwise `reversed` when
  any was reversed or refunded, otherwise `nothing_held`. Any other refusal, and
  any transport failure, answers the filing `error` with `protection_incomplete`,
  and a retry under the same key completes it. A case whose every part is not held
  is dismissed with `nothing_held`, as the contract dismisses one automatically.
- `POST /append` records evidence from either party, and concurrence only from the
  payee (`mandate.to`); a closed case refuses an append.
- `GET /cases/{case_ref}` answers a party with the case.
- `GET /record` pages the signed per-Agreement record after a cursor. An Agreement
  is known from its first filing the double admits, so a party reading one with no case gets an
  empty page; an unknown Agreement and a reader who is no party get the same
  `404 invalid_request`.
- `GET /respondent` lists the open cases a party did not file and has not
  answered with an append, in filing order.
- An exact retry under the same key returns the original answer; the same key with
  another request answers `idempotency_conflict`. A filing left
  `protection_incomplete` keeps its case reference under its key, bound to that
  filing, so its retry re-sends the same extends and another filing under the key
  is a conflict.

Records are signed with the fixture's record key and dated by the double's
perceived clock.

## What a rule decides

A rule (`POST /test/rules`) matches a call's `operation` (`file`, `append`,
`case`, `record`, `respondent`), its case's `filer` (`payer` or `payee`), its
claim's `kind` and `cause`, and its `transaction`, and takes one action:

- a refusal with a published mediation error code, on any operation, for a call
  past authentication, validation and the party and case checks;
- a filing answer, `pending`, `error` or `rejected`, given in place of filing and
  not remembered under its key, so a retry once the rule is gone files for real (a
  `pending` answer's case reference is the one that filing then takes);
- a ruling `{basis, delivery_end, effects, close}` for the case a matching filing
  or append reaches;
- a transport fault, *drop after commit* or *unavailable* (`match: {}`).

A rule that could never act is refused at install: a match value no call can have
(a `filer` or `cause` other than `payer` or `payee`, a `kind` other than
`delivery_end` or `effects`, a `transaction` that is no transaction id), a filing
answer on any operation but `file`, a ruling on any but `file` or `append`, and a
`record` or `respondent` read matched on anything but its operation, since such a
read names no case. A rule whose action a call's operation cannot take is passed
over for that call.

A ruling is recorded in the signed record with its effects `prepared`, then each
effect is applied as one payment event carrying the case reference and the
effect's id, `<case_ref>:<ruling>:<n>`, under a key stable within the Agreement.
The event is fixed when it is first sent, so every resend is the same request,
and payments answers one it already took with the event it stored. Case
references carry a prefix unique to the process, so a restarted double never
reuses a request id the payments double already answered. A ruling stopped
part-way stays recorded as its ruled entry left it, its unapplied effects
`prepared`. Only per-part `reverse` effects are applied (see "Deviation from its
producer"). A delivery end is recorded as applied with the ruling, since it is read from the
record and never sent to payments. With `close`, the case's own extensions are
lifted and the case closes with every effect `applied`; without it, a second
ruled entry attests the effects applied, when the first left any `prepared`, and
the case stays open. A rule's `pause_before_effects` holds the ruling before any
effect, its delivery end included, until the rule is resumed (`POST /test/rules/{id}/resume`):
the ruled entry then records the delivery end `prepared`. The marketplace's
watch records an end from a delivery-end effect whatever its applied state, so
the gate holds the delivery end only in this double's record, and a scenario
steps no storefront servicing while a ruling waits at its gate. A payments failure, a refusal or a lost
answer alike, stops the application where it is, the case `applying` and waiting
on its rule; resuming the rule continues it without applying an effect twice.

An operator's decision (`POST /test/cases/{case_ref}/decide`) rules an open case in
the same shape. Repeating the ruling a case is applying continues it, past its gate
or from where payments stopped it, whether or not its rule is still installed;
another ruling there is `422 invalid_request`. `POST /test/cases/{case_ref}/close`
closes an open case without a ruling once its extensions are lifted, answering
`502 payments_unavailable` when payments does not lift them. A case applying a
ruling is refused, `409 case_applying`, and keeps its extensions: the contract's
closed entry is final only once every effect is applied and the case's
extensions are lifted, and it has no state for an abandoned effect. Resuming the
rule or repeating the ruling completes the application.

## Deviation from its producer

With no matching rule nothing is ever ruled: a case is filed, its parts are
protected, appends are recorded, and a case with nothing held is dismissed. A
`delivery_end` claim that a payee files, or concurs in, which the authority would
rule mechanically, is ruled only when a rule says so. The double verifies the
filed Agreement's binding to its payment, the authority's admission rule, but no
concurrence signature or mechanical guard, which are the marketplace's
verification and the authority's decision logic; the mediation kit proves the
marketplace's own verification against the producer's vectors. A rule
may program only `reverse` effects, and a rule naming another is refused at
install. A `stop` and a `penalty` act on rate parts — a stop schedules or applies a
part's stop under its partial-period rule, and a penalty reverses earned amounts
still held, across parts in mandate order — and no lane running this double runs a
rate part, so neither is applied untested; an `award` is not executable on
`arkhai.payments.v1`, as the contract states.
To know which party files before the app runs, so that a rule naming the filer can
drop a filing's response, the fault classifier reads an unseen transaction's
parties from payments. The transport-fault middleware runs the classifier on a
worker thread, so the control and health routes keep answering while that read
waits.

## What its results establish

A lane result against the double proves the marketplace's filing, answering,
observation, end service and display of a ruling over the authority's real
mechanics: authentication, idempotency, the signed record and its cursors,
protection by real extensions at the payments double, and the effects of a ruling
reaching payments. It establishes nothing about a remedy's arithmetic, which stays
qualified by the producer's ruling traces, nor about a hosted authority's
availability or policy.

## Controls and clock

The lane doubles' control routes, from `tools/lane-double-controls`, under
`/test/` on the API port and authenticated by the fixture's control token: rules
with their matched and waiting counts, resume, decide, close, the case listing by
transaction, the perceived clock's advance and reset, and status, which reports
the perceived now and the SHA-256 of each installed contract resource. Control
routes and `/health` are never faulted.

## Fixtures

`fixtures/authority.toml` holds, as public development values never for a public
network: the authority's identity (origin `https://mediation-double:8443`, account
`00000000-0000-4000-8000-0000000000d1`, and the record key its committed seed
yields, which the double checks at start), the buyer's and seller's tokens by their
payments accounts, the authority account's token at the payments double, and the
control token.

## Running it

The image (`make build-mediation-lane-double` in `tools/`, or the root's
`make build-tools`) carries the
fixture, the lane CA and its `mediation-double` leaf, and the leaf key its build
generates, and reaches the payments double at `https://payments-double:8443` under
the lane CA. Outside the image, `MEDIATION_LANE_DOUBLE_FIXTURES`,
`MEDIATION_LANE_DOUBLE_TLS` (a directory holding `double.pem`, `double.key.pem` and
`lane-ca.pem`), `MEDIATION_LANE_DOUBLE_PAYMENTS_URL`, `MEDIATION_LANE_DOUBLE_HOST`
and `MEDIATION_LANE_DOUBLE_PORT` say where to find them; then
`python -m mediation_lane_double`.

`make test` runs the unit and application integration suite: the kit's real
`MediationClient` against the app in process, with the payments kit's
`FakePaymentsClient` over its shared engine as the payments peer and one clock for
both, and the transport faults under uvicorn on loopback.
