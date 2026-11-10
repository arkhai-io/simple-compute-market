# Design: in-lane payment and mediation doubles

## Context

Facts the decisions rest on:

- **The payments double exists.** `add-mvp-payments-lane-double` (archived
  2026-11-06) built `tools/payments-lane-double`: an HTTPS service at
  `https://payments-double:8443` over the payments kit's clock-injected
  `PaymentsAuthority` engine, mirroring the payments service's API, run by the VM,
  bare-metal and API-credit lanes (`compose.payments-double.yml`) and the local Helm
  release. Callers trust its committed lane CA through `ca_bundle_path`; a lane marks
  the target its own (`PAYMENTS.LANE_OWNED`), so an unready double fails setup. Its
  suite and specification claim only the once-only surface, though the engine serves
  rate parts, stops, holds, `extend` and `lift`. Its clock is wall time injected into
  the engine (`PaymentsDouble(clock=wall_clock)`), and the engine evaluates due state
  lazily on each read; nothing runs in the background.
- **No lane runs a dispute authority.** The lanes' registries recommend a fixture
  authority at `https://dispute.invalid` whose record key has no private half and
  whose account has no token at the payments double
  (the payments double's `fixtures/dispute-authority.toml`, retired by this
  change). The VM payment
  scenario's operator-end case and refund stages skip on a blank
  `MEDIATION.SERVICE_URL` (`e2e-tests/tests/e2e/roles/helpers/mediation.py`), and the
  bare-metal buyer's teardown files a `delivery_end` case that reaches nobody and
  records `Unknown`.
- **Both contracts are published and vendored.** `kit/arkhai-payments/schema/SOURCE.md`
  states that no unpublished payments candidate exists; `kit/arkhai-mediation`'s
  `publication.json` is published with the `delivery_end`, `concurrence` and
  `respondent` capabilities. Both kits expose their resources from installed wheels.
- **Mediation has a kit, and its fakes decide nothing.** `kit/arkhai-mediation` holds
  the client, the dispute adapter, `MediationContractFake` and `RulingTraceFake`; the
  fakes take injected answers and compute no remedy. The producer publishes fourteen
  ruling traces over fixed Agreements.
- **SCM files no revision.** The dispute adapter refuses a revised `delivery_end`
  filing with "repair required", and the published interface has no linked-revision
  mapping.
- **SCM's mediation client cannot trust a private CA.** `MediationClient` builds its
  HTTP client with default verification and `[[DisputeCredential]]` has no CA
  setting; no process sets `SSL_CERT_FILE`.
- **Every transport failure is one failure to SCM.** `PaymentsClient` turns any
  `httpx.RequestError` into `PaymentsTransportError`, and `MediationClient` any
  `httpx.TransportError` into `MediationTransportError`: a refused connection and a
  response abandoned mid-way are indistinguishable.
- **The end-to-end discipline.** `TESTING.md`, "The discipline every scenario
  follows": a scenario is a deterministic sequence of state changes; it holds the
  loops it depends on, advances one side effect at a time and waits only on effects of
  its own requests or instants the Agreement fixes. Mock provisioning is the
  precedent for programming a collaborator's outcomes: a scenario installs a
  when→then rule, may hold a job at the rule's gate, and deletes or resumes its rules.

## Goals and acceptance boundary

- A mediation double beside the payments double in every lane, with the dispute
  authority's real API mechanics and scenario-programmed decisions.
- Typed, deterministic controls on both doubles, including transport faults and a
  perceived clock.
- The payments double claiming the rate and hold surface its engine serves.
- The VM payment scenario's case stages and the bare-metal filing running against
  the mediation double, and six VM-lane controls scenarios, each on its own deal,
  proving the lane's dispute wiring, every other control proven by its double's suite.
- The release wheelhouse carrying no distribution only tests depend on.
- The mediation double in the local Helm release beside the payments double, as a
  subchart of the umbrella chart, with a Helm test checking the VM storefront's
  mediation configuration from its own container.

**Non-goals:** a rules engine reproducing the dispute authority's or the payments
service's decisions; contract modes; a production guard on fixture identities;
storefront- or site-side clock control; rate scenarios in lanes (convergence owns
them once spot derives rate parts); payment scenarios in Helm validation
(`helm-e2e-pipeline-parity`); moving the lane collaborators out of the umbrella chart
(`separate-lane-infrastructure-chart`); live, hosted-ledger or adjudication evidence.

## Decisions

### D1. The mediation double answers from programmed rules

The mediation double reproduces the dispute authority's API mechanics and takes
every decision the authority would make as a scenario-programmed answer, the way
mock provisioning takes a job's outcome. It never re-implements the authority's
decision logic.

**Real mechanics:** routes, bearer authentication, schema validation against the
vendored contract, idempotency and conflict answers, the filing's admission checks
— a filer who is neither party refused `filer_not_party`, and a filed Agreement
whose JCS SHA-256 is not the signed payment receipt's `deal` refused
`agreement_hash_mismatch`, both before any case is reserved or part extended (62
F1) — the closed-case refusal, either
party appending evidence with only `mandate.to` appending concurrence, the signed
per-agreement record with its sequence and cursors, the respondent listing,
per-part `extend` at the payments double as the authority's own account, the
contract's automatic dismissal of a case whose every part is `not_held` at filing
(`all_parts_definitively_not_held_at_filing`, closed with `dismissal_reason:
nothing_held`), and executing a ruling's effect list as payment events with stable
effect keys and the case reference, resuming after a payments failure without
applying an effect twice, then lifting only that case's extensions.

**Extension results (15 F3).** The contract's `NotHeldPart.reason` is one of
`paid_out`, `reversed` and `nothing_held`, and its `MediationFailure` carries
`protection_incomplete`, mediation's own error, retried under the original key. So
only payments' nothing-held refusal, `hold_not_extendable`, reports a part
`not_held`. Every other
refusal (`caller_not_authorized`, `transaction_not_found`, `invalid_event`,
`ledger_unavailable` and the rest) and every transport failure answers the filing
`error` with `protection_incomplete`, which SCM's adapter reads as pending; a retry
under the same key completes it. A payments outage or a misconfigured authority
account therefore never tells a filer its money is not held.

**A not-held part's reason (26 F1).** The payments snapshot states no reason: a
part's `status` is `held`, `released`, `reversed` or `settled`, and the engine reports
`settled` alike for a refunded part, a part both released and reversed, and a part
where nothing moved. So the double, reading the part's signed snapshot as the
authority's account, classifies its amounts: `paid_out` when any money was released
to the payee; otherwise `reversed` when any was reversed or refunded to the payer;
otherwise `nothing_held`. Paid-out money comes first because it is what mediation
cannot recover, which a filer most needs to know. The double's suite covers each
case: released only, reversed only, released and reversed, refunded only, and
nothing moved.

**Programmed:** whether a case is ruled, the ruling's basis, delivery end and
per-part effects with their amounts, filing-answer overrides (`pending`, `error`, a
refusal), and a gate holding a ruling before its effects. An operator ruling on an
open case takes the same shape, matched by case.

The double verifies no concurrence signature or mechanical guard: SCM's verification
is proven in the kits against the producer's vectors, and a guard is the authority's
decision logic. The Agreement's binding to its payment is different (62 F1): it is
the authority's admission rule, not SCM's verification or a decision, the receipt
the double already reads carries the `deal` it is checked against, and the payments
double makes the same comparison when an Agreement is attached. An honest filing
always passes it, since SCM's buyer side checks the receipt's `deal` against the
Agreement it negotiated, so in a lane it catches only SCM filing a different or
re-serialised Agreement. With no
matching rule, mechanics proceed (a filing is accepted, each part's extension is
attempted, appends are recorded, a case with nothing held is dismissed) and nothing
is ever ruled, consistent with silence never ruling. A payee-filed or concurred case therefore rules only when a rule says
so; the double's README and specification state that deviation.

A lane result proves SCM's filing, answering, observation, end service and display of
a ruling, not a remedy's arithmetic, which stays producer-qualified.

**Rejected:**

- **A rules engine in the tool, held to the producer's traces.** It duplicates the
  authority's decision logic, which drifts whenever the producer revises its rules.
- **Trace playback over HTTP.** It serves only Agreements identical to the traces',
  and lanes negotiate their own.
- **No mediation double.** The case stages keep skipping, and no public lane exercises
  disputes.

### D2. The doubles' perceived clocks move under scenario control

Each double reads a perceived clock, wall time plus an offset that a control moves
forward only; one harness helper advances both together, so mediation's record
times and payments' holds agree, and status reports each double's perceived now.
Due authority state — a notice stop taking effect, funding exhaustion at
funded-through, a payout after the dispute window — becomes visible at the next read,
with no background work and no barrier.

**The clock's lifetime (15 F2).** A lane keeps its doubles for every module it runs,
so an advance would otherwise outlive the module that made it, and later modules
would approve deals whose records are dated ahead of their storefronts. The clock
helper is therefore a fixture whose finaliser resets both doubles to wall time,
whatever the module's outcome, through a reset control. Reset is the one backward
move, and only to a zero offset; advances stay forward-only. Records the module left
dated ahead stay readable, because the payments engine evaluates a transaction at the
later of its clock and the transaction's own instant, and only that module's deals
carry them. The scenario that advances the clock is a module of its own (D21), so
the reset bounds its advance whatever order the lane runs modules in, and within it
no storefront step follows the advance (D18).

**Independent clocks.** A lane's perceived clock lives only in its own doubles'
processes, never in a shared service or on the host. Each pipeline lane runs its own
doubles in its own Compose project, and each Helm validation namespace its own
release of them (D11), so lanes running side by side never share an offset.

Decisions a storefront or site makes from an authority record and its own clock — the
funding timer, ending or truncating at a stop's effective time, the lease end — are
not driven in lanes by this change. A lane-wide perceived clock covering storefronts,
sites and the buyer half is a new change, opened after this one.

**Rejected:**

- **Wall time, short windows and an internal scheduler with barriers.** A pipeline
  stage would wait out windows, against the end-to-end discipline.
- **A lane-wide perceived clock here.** Large production seams in every service, and
  this change's own scenarios need none.
- **Back-dating payment records.** Signed receipts keep the original approval instant,
  and a shifted `start` can precede the Agreement start that SCM checks.
- **No lane clock.** Authority timing would be proven only below end-to-end.
- **Ordering clock-advancing modules after every other module of the lane run**
  (15 F2). It leaves the advance in place for the rest of the run and makes a lane's
  result depend on module order; a reset bounds the advance to its module.
- **Restarting the doubles after a clock-advancing module** (15 F2). The runner has
  no Compose access, and a restart drops the payments state earlier modules' deals
  still refer to.

### D3. One contract per double and two evidence classes

Each double serves its kit's vendored publication only. There is no mode selector,
candidate resource, proposed declaration or hash-comparing readiness: the doubles and
their consumers are built from one wheelhouse and lock, so their contract bytes are
identical by construction. A run is labelled *lane doubles*, with each double's
installed contract hashes read from its status for information, or *live evidence*,
which only a hosted target yields and which `activate-per-period-compute-servicing`
owns. A change that must build against an unpublished producer revision adds a mode
then, against that revision's real shape.

**Rejected:**

- **Three classes with no selector.** The proposed class would be a definition nothing
  can produce.
- **The selector built now.** Machinery for a candidate that does not exist.

### D4. Controls: one rule mechanism, shared middleware, a typed client

**The controls**, each with its callers:

| Control | Double | Callers |
|---|---|---|
| Clock advance (D2) | both, one helper | convergence rows 0, 6, 7, 13; D6 |
| Clock reset to wall time (D2) | both, one helper | the clock fixture's finaliser |
| Refuse a matching call with a published status and code | both | convergence rows 1, 3; the doubles' suites |
| Drop the response after commit | both | convergence rows 1, 3; D6 |
| Unavailable: every API request's response abandoned while installed | both | convergence row 1; D6 |
| Fund an account | payments | convergence row 6 |
| Rotate the receipt signer to a second fixture key | payments | convergence row 11 |
| Filing-answer override | mediation | convergence rows 1, 3, 13 |
| Ruling `{basis, delivery_end, effects, close}`, optional `pause_before_effects` and resume | mediation | D6; convergence rows 3, 5, 8, 10, 12 |
| Decide an open case; close without ruling | mediation | D6; convergence rows 3, 12 |
| List cases by transaction | mediation | D6 |
| List rules with matched and waiting counts | both | every scenario's verification and cleanup |

A rule's `match` accepts the transaction, so a rule can be scoped to one deal.

```json
POST /test/rules        (payments double)
{"rule_id": "buyer-stop-lost",
 "match": {"route": "events", "account": "00000000-0000-4000-8000-0000000000b1", "event": "stop"},
 "drop_response_after_commit": true}

POST /test/rules        (mediation double)
{"rule_id": "vm-operator-end",
 "match": {"operation": "file", "filer": "payee", "kind": "delivery_end", "cause": "payee"},
 "ruling": {"basis": "payee_filed", "delivery_end": true, "close": true, "effects": []}}
```

**Transport faults live in the doubles.** One ASGI middleware abandons every API
request's response while *unavailable* is installed, and lets a matching request
commit before abandoning its response for *drop after commit*. SCM's clients see each
as a transport error, as they would an unreachable host or a lost response. The
mediation double's calls to payments meet the payments double's middleware too.

**How a response is abandoned (15 F1).** The doubles run under uvicorn, which answers
`500` when an application raises before starting a response, and closes the
connection only when the response has started. So the middleware starts the response
and then abandons it; the server closes the connection, and httpx raises a
`RemoteProtocolError`, which both kit clients count as a transport error. A plain
refusal would not do: SCM's mediation adapter reads a 5xx as pending and a transport
error as unknown, so a 500 would prove the wrong branch.

**Control routes are never faulted (15 F1).** The middleware applies only to the
contract's API routes. The authenticated control routes keep answering while a fault
is installed, so a finaliser can always remove the rule that caused it, and removing
*unavailable* restores the API. SCM never calls a control route, so the exemption
changes nothing SCM sees.

**Control semantics (15 F4).** Every control error has one body, `{"code",
"message"}`, in the controls package's models, and the client raises one typed error
carrying the code.

| Case | Answer |
|---|---|
| A rule without `match` | `422 invalid_request`; nothing is installed. A rule states its scope |
| `match: {}` | accepted: every call of its double, stated explicitly |
| *Unavailable* (26 F2) | a rule like any other, with `match: {}`: it covers every contract API route. Any other `match` is `422 invalid_request` and installs nothing: a scoped outage has no caller, and would only drop some requests before commit |
| Installing an existing `rule_id` | `409 rule_exists`; a silent replace would hide a leaked rule |
| Deleting or resuming an unknown `rule_id` | `404 rule_not_found` |
| Deleting a rule that has matched or completed | `204`, removed: deleting is cleanup, whatever the rule's state |
| Resuming a rule not waiting at its gate | `409 rule_not_waiting` |
| A malformed ruling or effect | `422 invalid_request`, validated by the typed model and against the vendored contract's ruling and effect shapes; nothing is installed |
| An empty effect list | valid: a ruling that moves no money |
| Deciding or closing an unknown case; funding an unknown account | `404 case_not_found`; `404 account_not_found` |
| Deciding or closing a closed case | `409 case_closed`, the refusal the API gives an append |
| Closing a case applying a ruling (40 F1) | `409 case_applying`; nothing is lifted. The contract's closed entry follows every effect's application and the case's lift, and has no state for an abandoned effect, so the double never shows SCM a final record whose money did not move |
| Listing cases for a transaction with none | `200`, an empty list: a listing, not a lookup |

**Where the contract lives.** `tools/lane-double-controls` (import
`lane_double_controls`) holds the rule, fault, clock, funding, rotation and ruling
models, the route declarations, a typed client and the transport-fault middleware.
Both doubles and `e2e-tests` depend on it; the doubles themselves stay unimported.
This is the mock-provisioning split of contracts, client and service.

**Control shapes (settled in section 1).** A rule's `match` is a string map over
its double's properties: payments matches `route` (`transactions`, `snapshot`,
`mandate`, `attachments`, `events`, `balances`), `account`, `event` and
`transaction`; mediation matches `operation`, `filer`, `kind`, `cause` and
`transaction`. Any other property, or an action its double does not take
(payments takes no filing answer or ruling), is `422 invalid_request`. A ruling's
`basis` is validated against the contract's `RulingBasis`, and its `effects` against
`Effect`. `delivery_end` is a boolean, recording the contract's `end_delivery` at the
ruling's time, and an `end_delivery` entry in `effects` is refused, so a delivery end
has one spelling. A filing-answer override is `{status: pending}`, `{status: error,
code}` with a `MediationFailure` code, or `{status: rejected, reason}` with a
`FilingRefusalCode`. Neither the health route nor a control route is ever faulted
or shown to a double's classifier: an orchestrator's liveness probe must not
restart a double during an outage. The middleware decides nothing itself: each
double's classifier matches a request against its rules and counts the match in
the listing, since only the double knows its accounts and rules. The middleware
runs the classifier on a worker thread (40 F3): the mediation classifier may read
a transaction's parties from payments, and the control and health routes keep
answering while it waits. A control call
without the double's control token is `401 authentication_required`. The client
raises an error status whose body is not a control error with the client-side
code `unexpected_response`, which no double sends.

**Mediation shapes (settled in section 4).** A mediation rule's `operation` is
`file`, `append`, `case`, `record` or `respondent`; a filing answer applies to a
filing alone and is not remembered under its key, so a retry once the rule is
gone files for real, a `pending` answer's case reference being the one that
filing then takes. A refusal rule's code is one of the contract's
`MediationFailure` codes. A ruling's effects are applied only when each is a
per-part `reverse` (40 F2). A `stop` and a `penalty` act on rate parts — a stop
schedules or applies a part's stop under its partial-period rule against payments'
clock, a penalty reverses earned amounts still held across parts in mandate order —
and no lane in this change runs a rate part, so neither is applied untested; an
`award` is unexecutable on `arkhai.payments.v1`, as the contract states. Each is
refused at install, `422 invalid_request`, as is a match value no call can have.
Executing `stop` and `penalty` is convergence's, before its rate rows rule with
them ("Effects on other changes"). A ruling with `close`
lifts the case's own extensions and records the closed entry; without it, a
second ruled entry attests the effects applied and the case stays open. A case
waits on its rule while held at the gate or stopped part-way by payments, and
resuming the rule continues it; repeating the ruling a case is applying, as an
operator's decision, continues it too, whether or not its rule is still installed,
and another ruling there is `422 invalid_request`; closing a case applying a ruling
is refused, `409 case_applying` (40 F1): no caller needs a way out of a ruling
payments keeps refusing, which is a scenario's error, and the case holds only its
own deal's money. The gate holds a ruling's delivery end with its other effects in
the double's record, where the ruled entry records it `prepared`; SCM's watch records
an end from a delivery-end effect whatever its state, so a scenario steps no
storefront servicing while a ruling waits at its gate (D15). A rule whose action a
call's operation cannot take is passed over for that call, neither counted nor
hiding a later rule. A rule that could never act is refused at install, `422 invalid_request`:
a filing answer on any operation but `file`, a ruling on any but `file` or
`append`, and a `record` or `respondent` read matched on anything but its
operation. Effect ids are `<case_ref>:<ruling>:<n>`, case references carry a
prefix unique to the process, and each effect's payment event is fixed when it is
first sent, so every resend is the same request.
Closing without a ruling answers `502 payments_unavailable` when payments does not
lift the case's extensions, a code outside the table above, since no table case
covers payments failing under a control; `ControlCode` lists it. The API refuses an
unauthenticated call `401 authentication_required`, a malformed one `400
invalid_request`, and an unknown case, an unknown Agreement, and a reader who is
no party alike `404 invalid_request`; an Agreement is known from its first filing
whose transaction payments answers. The double checks a filer is a party
(`filer_not_party`) and the filed Agreement's binding to the receipt's `deal`
(`agreement_hash_mismatch`), both answered as the contract's `rejected` filing,
and, as D1 says, verifies no authority listing.

**Scope and access.** There are no run scopes: a lane is its own stack, a module holds
its services, a rule's `match` is its scope, and the scenario's finaliser deletes its
rules, so a leftover rule shows in the listing. Control routes sit on each double's
lane-private port behind a fixture control token, with no host port.

Each control is a deterministic step: nothing delays, races or runs in the
background. Snapshot and livemode corruption faults are not offered: the kits'
verifier tests prove those refusals at the lowest level that can.

**Rejected:**

- **Toxiproxy in front of the doubles.** A container per lane for faults SCM cannot
  tell from the doubles' own.
- **A control client owned by the harness.** Route models duplicated between doubles
  and harness, free to drift.
- **The harness importing the double distributions.** The runner would gain FastAPI
  and both doubles' internals.
- **WireMock or MockServer as fault proxies.** TLS terminated in the stub, and no
  proven way to forward a request and then drop its response.
- **Run identifiers and explicit target sets.** Lanes are already isolated stacks.
- **Controls on a second, private listener** (15 F1). It models an outage at the TCP
  level, which no SCM client can tell from an abandoned response, at the cost of a
  second port in every lane.
- **Deferring the operations whose semantics were open** (15 F4). Each has a caller in
  this change, D6's module or its finalisers.
- **_Unavailable_ as a control of its own, outside the rules** (26 F2). A second
  install and cleanup contract, and a second thing for a finaliser to remove, for no
  behaviour a rule with `match: {}` lacks.

### D5. No production guard on fixture identities

The mediation double's identity is inert outside development topologies by
construction: an origin that is only a lane-private service name, `mediation-double`,
answered in a Compose lane or in a validation namespace whose own local values enable
the subchart (D11), while a release rendered from release values runs no double
(26 F4); a deterministic fixture account whose only token is at the payments double;
and a record key derived from a committed seed labelled a public development value,
never for a public network. Registries recommend it only in lane profiles and the
local release. A live deal naming it could only come from a
buyer accepting it from its own list or a registry it opted into, which the buyer's
acceptance list already governs; the marketplace does not protect a party from an
authority it chose.

**Rejected:**

- **A loader guard refusing fixture identities outside a lane profile.** Production
  kits would embed test values, and a copied lane configuration copies its marker.
- **A guard in live mode.** Still embeds test values, and registries have no mode.

### D6. This change's scenarios

- The VM payment scenario's operator-end case and refund stages run against the
  mediation double. With no rule, the seller's filing is accepted, its parts are held
  by real extensions, nothing rules, and the seller's refund reverses the held money.
- The bare-metal buyer's teardown filing reaches the mediation double; the scenario
  asserts a filed case held per part, not a ruling.
- Six VM-lane controls scenarios, each a module of its own on its own once-only deal
  (D17, D21), prove the lane's dispute wiring — the CA, the storefront's dispute
  adapter and the control client together:
  1. a programmed ruling with a delivery end and a reverse, its effect visible at the
     payments double and the storefront ending delivery after observing it (D15);
  2. an operator decision with a partial reverse and no delivery end, the deal
     running on;
  3. a lost filing response, the dispute adapter adopting the one case (D18);
  4. mediation unavailable, servicing reporting the authority unreachable while the
     deal runs (D18);
  5. payments losing its answer to the first of two programmed effects and then
     unavailable while the ruling is repeated, the ruling incompletely applied and
     then completed with no duplicate effect (D16);
  6. a clock advance past a once part's hold, the payout visible and a later case
     reporting `not_held` and dismissed with nothing held (D1, D18); no storefront
     step follows the advance, and the clock fixture resets both doubles when the
     module ends (D2).
- The doubles' own suites drive the kits' real clients over HTTP, and prove through
  the typed client every control the scenarios do not exercise: funding, signer
  rotation, refusal with a published code, the filing-answer override, close without
  ruling and the rule listing (15 F5). Those controls' first lane use is
  convergence's (rows 6, 11, 1, 3 and 13), over the client path the six scenarios
  already prove.

The six scenarios are the change's boundary: changing them amends the delta (D19).
Convergence keeps every rate row.

**Rejected:**

- **Only the existing scenarios.** The controls' first lane use would be convergence's,
  which would debug this change's wiring.
- **Every new scenario left to convergence.** The same defect.
- **A VM stage for every control** (15 F5). Funding, rotation and the override
  exercise the doubles' own behaviour, which their suites prove at a lower level, at
  a much greater scenario cost.

### D7. Project, fixtures and TLS

- `tools/mediation-lane-double`, import `mediation_lane_double`, image
  `arkhai:mediation-lane-double`, Compose service `mediation-double`, a lane
  collaborator like the payments double: it may import internal kits and nothing
  imports it.
- Its fixtures: the authority identity (origin `https://mediation-double:8443`,
  account `00000000-0000-4000-8000-0000000000d1`, a record key from a committed seed),
  bearer tokens for the buyer and seller payment accounts, and a control token. The
  payments double's account fixture gives `…00d1` a token. The `.invalid` authority is
  retired. Every value is labelled a public development value.
- One lane CA. Its generator also issues a `mediation-double` leaf, so callers keep one
  CA bundle; the generator and certificates move from `tools/payments-lane-double/tls/`
  to `tools/lane-double-controls/tls/`, from which both images build their keys.

**Rejected:**

- **A second CA.** Doubles every caller's trust configuration.
- **The mediation build reading the payments project's directory.** A cross-project
  file dependency.

### D8. Mediation trust through configuration

`[[DisputeCredential]]` gains an optional `ca_bundle_path`, and `MediationClient` a CA
argument used as its verification context. The storefronts' and buyers' lifecycle
compositions pass it. Absent means the default trust store; no process trust store
changes.

```toml
[[DisputeCredential]]
interface      = "arkhai.mediation.v1"
origin         = "https://mediation-double:8443"
account        = "00000000-0000-4000-8000-0000000000d1"
record_key     = "ed25519:…"
api_key        = "mediation-lane-double-seller-public-development-token"
ca_bundle_path = "/run/lane-doubles/lane-ca.pem"
```

The credential carries it because it is identity-bound and present in every role that
talks to an authority; lanes take the authority from the registry and have no
`[[Dispute]]` entry.

**Rejected:**

- **`SSL_CERT_FILE`.** Displaces public trust for the whole process.
- **Trust on `[[Dispute]]`.** Absent in lanes.

### D9. Lane wiring

- `compose.payments-double.yml` also runs the mediation double, in all three lanes.
- The lane registries recommend the mediation double's identity.
- The runner's `config-payments-lane.yml` gains a `MEDIATION` section: target, lane
  ownership, CA bundle path, the buyer's token and the control token. The mediation
  helper fails setup by name on an unready lane-owned target and keeps a blocked skip
  for an external one, as the payments helper does. The harness writes the buyer's
  mediation token into each `market` process under `api_key_env` and writes the
  buyer's `[[DisputeCredential]]`. Tests hold every restated value to its fixture.
- Bob's storefront dispute credential carries the mediation double's seller token and
  `ca_bundle_path`.
- In the Compose lanes, the controls scenarios and the VM case stages prove the
  storefront's mediation access; the lanes run no `check-mediation`. Its caller is the
  local release's Helm test (D11).

**Rejected:**

- **The mediation double in the VM and bare-metal lanes only.** Overlays that differ
  to save one container.

### D10. The payments double's claimed surface

Its library-integration suite drives the payments kit's real client over HTTP, with
clock control, and claims rate parts, payee-only `start`, `stop` with notice and the
earliest pending stop, per-part `end`, funding exhaustion at funded-through,
`afterStop` holds, partial `reverse` before and after a stop, and `extend` and `lift`
with their published refusals. No lane rate scenario is added.

### D11. The local Helm release (15 F2, 15 F6, 26 F3)

The umbrella chart's subchart pattern is extended: a `mediation-lane-double` subchart
runs beside `payments-lane-double`, enabled only by `local-values.yaml`, with its
Service named `mediation-double`, the name its lane-CA leaf is issued for, so a
validation namespace runs one, as it runs one payments double. The release's registry
recommends its identity. The `payments-ca-bundle` ConfigMap already holds the lane
CA, which now also issues the mediation leaf, so no second mount is added; the
ConfigMap keeps its name.

Bob's dispute credential is copied from his Compose secret overlay, whose
`ca_bundle_path` names the Compose mount, a file that does not exist in the cluster;
the storefront would fail building its mediation client at the first servicing of a
payment deal. The chart cannot derive it as it derives
`[Settlement.arkhai_payments].ca_bundle_path`, because the credential lives in a
runtime Secret the chart never renders. So `topology-secrets.sh`, which writes that
Secret, rewrites the copied credential's `ca_bundle_path` to the chart's CA file, and
a test holds the rewritten value to `storefront.caBundleFile`. The `deployment-state`
delta modifies "Payment credentials stay with their owning process" and "The local
release rehearses a deployment's payments interface" accordingly.

**The storefront checks its mediation configuration from its own container (26 F3).**
The rewrite, the Service name, the leaf's name and the token are a seam this change
creates, and the storefront builds its mediation client lazily, so a defect in any of
them would first show at a payment deal's dispute servicing. As `check-payments` does
for payments, the VM storefront offers `market-storefront check-mediation --origin
<authority>`, its logic in the mediation kit: it loads the storefront's configuration
as `serve` does, selects the `[[DisputeCredential]]` for that origin, builds the
mediation client with the credential's `ca_bundle_path`, makes one authenticated
`respondent` read, prints one JSON outcome carrying no credential, and exits nonzero
naming the failing step — configuration, an unresolvable token (credential),
transport, or the authority's refusal with its code. The storefront chart renders a `<agent>-mediation-check` Helm test pod
beside `-payments-check`, from the same helpers as the Deployment, for an agent with a
dispute credential and a `tests.mediationOrigin` — in the local release, Bob, at
`https://mediation-double:8443` — and `scripts/validate_slice.py` runs it as it runs
the payments checks. It is a configuration and connectivity sanity check, as the
chart's smoke tests are: it asserts nothing about the read's answer, an empty listing
and a full one alike, and files, rules and changes nothing, so it covers nothing the
lanes prove.

No scenario runs against the release's doubles in this change: payment scenarios in
Helm validation belong to `helm-e2e-pipeline-parity`. Moving the lane collaborators —
Anvil, the address book, Mailpit and both doubles — out of the operator's umbrella
chart into a lane-infrastructure chart of their own is the better end state and
belongs to `separate-lane-infrastructure-chart`, which takes this subchart with the
rest.

**Rejected:**

- **No mediation subchart, the identity unanswered in the cluster.** The copied
  credential still breaks client construction, and the release keeps one lane
  collaborator fewer than the lanes run.
- **Keeping the `.invalid` authority in the release** (the review's suggestion under
  15 F6). It contradicts D7's retirement of that identity and the subchart above.
- **A separate lane-infrastructure chart in this change** (15 F2). The better end
  state, but its move touches every target and tool that treats a namespace as one
  release (`helm/Makefile`, `scripts/validate_slice.py`, the capacity figure, the
  render tests), work unrelated to mediation.
- **Mounting the lane CA at the chart's path in every Compose stack** (15 F6), so one
  path is right verbatim in both. It changes every lane's mounts and TOML paths for
  one copied key.
- **Claiming only the rendered topology, leaving access to `helm-e2e-pipeline-parity`**
  (26 F3). It ships a connection nobody has made; one read is not a payment scenario.
- **Running `check-mediation` in the Compose lanes too** (26 F3). The lanes already
  prove the storefront's mediation access through their scenarios.
- **A smoke test asserting the authority's answer.** The chart's smoke tests are
  sanity checks of configuration and liveness; behaviour belongs to the lanes.

### D12. Scope removed from the earlier design

The earlier design's contract modes and difference manifests, the proposed evidence
class, the production guard, the bare-metal scenario port (already in the current
specification), revision netting (no SCM caller files a revision), the shared
`tools/authority-lane-doubles` project, the `SSL_CERT_FILE` trust bundle, wall-time
barriers, race and delay controls, and corruption faults are not built. The delta
specification is rebuilt against the current `test-compatibility` specification, and
`tasks.md` is rewritten at planning.

### D13. Implementation cadence

Two rounds:

1. **The doubles and their contract, two sessions.**
   - `tools/lane-double-controls` (models, routes, typed client, transport-fault
     middleware, the moved lane CA generator) and the payments double's controls
     (clock, funding, signer rotation, refusals, faults), with its suite claiming the
     rate and hold surface.
   - `tools/mediation-lane-double` (mechanics, rules and rulings, effect application,
     gate, clock, case listing) with its suite, and D8's `ca_bundle_path` across the
     deal-lifecycle and mediation kits and the four lifecycle compositions.
2. **Lane wiring, the controls scenarios and the local release, three sessions.**
   - The overlay, fixtures, registries, the runner's `MEDIATION` section and helper,
     buyer configuration, the VM case and refund stages and the bare-metal filing.
   - The six controls scenarios and their helpers (D6, D14–D19, D21).
   - D11's subchart, release values, `topology-secrets.sh` rewrite, `check-mediation`
     with its Helm test and its step in `validate_slice.py`, and D20's release
     wheelhouse split.

   One review covers the round.

The doubles are reviewed before any lane uses them, so a wiring defect cannot hide a
double's. The scenarios and the local release are independent slices of about equal
weight, each a session of its own, under the round's one review.

### D14. The buyer files through SCM's dispute adapter

SCM files only `delivery_end` claims, and both of its ways of filing end delivery as
they file: the storefront's operator end records the end and tears delivery down with
the filing, and the buyer's `market end` files after a surrender the storefront
acknowledges. No SCM command files a case on a running deal, and the storefront's part
in a case another party files is to answer it as respondent and observe its ruling.

So where a scenario needs a case on a delivering deal, the harness files as the buyer:
a delivery-end claim (`{kind: delivery_end, ended_at, delivered: true, cause: payer}`,
the shape the buyer's `market end` sends) through the mediation kit's
`MediationAdapter` over its typed `MediationClient`, with the buyer's token and the
lane CA from the runner's `mediation` section and an operation store for the adapter's
single-writer check, as `BuyerLifecycle.submit` supplies one. The storefront meets
what a real buyer's filing gives it: no matching surrender, so it answers with a
contest. `e2e-tests` declares `arkhai-kit-mediation`, which it then imports.

Each stage acts through the services' typed clients, the doubles' control client, or
the dispute adapter, never a raw HTTP call. No buyer command files a case on a running
deal; the roadmap records that as an unowned gap, which these scenarios would then
use.

**Rejected:**

- **An `effects` request through `effects_request`.** It would let several cases
  share a deal, but no SCM product files one, so the scenarios would prove a kit path
  only the harness uses.
- **The raw `MediationClient` with a hand-built filing.** It skips SCM's request
  validation, adoption and filed-record read, proving less of SCM.
- **A new buyer filing command in this change.** A buyer feature with its own design,
  whose only caller would be this test.
- **SCM's existing filers alone.** Delivery would end before any ruling, so a ruled
  end could never be what ends delivery, and a discount on a running deal could not
  be shown.

### D15. A programmed ruling is staged by its gate

A ruling rule acts inside the request it matches (D4), so the ruled-end scenario
installs its ruling rule on the buyer's filing with `pause_before_effects`, and orders
its stages: file (the case filed, its part held, the ruled entry recording the
delivery end and the reverse `prepared`), resume (the reverse at payments, the lift,
the closed entry), then a storefront servicing step (the end recorded with cause
`ruling`, teardown begun). Every side effect has its own stage, and the rule, its
match on the deal and the gate are used in a lane before convergence relies on them.

The storefront's watch records an end from a delivery-end effect without reading its
`applied` state, and one servicing cycle runs respondent discovery, then the watch,
then the physical end. So the gate holds the delivery end only in the double's
record: no stage steps the storefront's servicing while a ruling waits at its gate.
Neither the double nor SCM changes. What a `prepared` delivery end means is the
producer's to say; the roadmap records it as an unowned question.

The storefront does not answer this scenario's case, which is closed before its
servicing step; the discount and mediation-unavailable scenarios, where no rule acts,
prove the respondent's answer.

**Rejected:**

- **A ruling rule on the storefront's answer.** One servicing step would answer,
  trigger the gated ruling and record the end from its prepared entry in the same
  cycle.
- **An operator decision instead of a rule.** The rule and its gate would first run
  in a lane in convergence.
- **A second gate before the ruling is recorded.** A new rule field whose only caller
  is this scenario; the existing gate's ruled-but-unapplied state is what convergence
  plans to observe.
- **The double recording the delivery end applied under the gate.** It guesses at the
  producer's semantics.
- **SCM's watch waiting for `applied`.** A behaviour change on an unsettled question,
  which would be a change of its own.

### D16. Payments holds a ruling twice before it completes

The payments double's rules cannot tell a ruling's two reverses on one part apart,
and *unavailable* cannot be scoped (D4, 26 F2), so no control stops a ruling exactly
between its effects; the double's suite proves that case in-process. The lane
scenario proves what only the lane can: the storefront observing an incompletely
applied ruling, and an effect resent across the two doubles' processes without a
duplicate. Its stages, after a delivering deal, the buyer's filing with no rule and the
storefront's answer:

1. a payments drop-after-commit rule on the authority's `reverse` for the deal;
2. an operator decision with two reverses on part 0 and `close`: payments commits the
   first, its answer is lost, the second is never sent, the case is `applying`;
3. a servicing step, the storefront showing the ruling unapplied and the case open;
4. the rule deleted, then payments *unavailable* installed;
5. the decision repeated, failing at the first effect's resend, the case still
   `applying`, and a servicing step;
6. the outage removed;
7. the decision repeated: the first effect's resend answered from payments' stored
   event, the second applied, the extension lifted, the case closed; and a servicing
   step showing it closed.

The payments snapshot shows the first amount reversed after step 2 and both after
step 7, exactly once each.

**Rejected:**

- **Stopping at the lost answer, without the outage.** It omits a payments outage
  holding a ruling in the lane.
- **A payments match property on the event's amount or request id.** It amends the
  controls contract and the payments classifier, still cannot scope an outage, and
  never resends the first effect.
- **A mediation gate after the nth effect.** A new ruling field whose only caller is
  this scenario, and the first effect is never resent.
- **Leaving the case to the double's suite.** The storefront's display of an
  incomplete ruling would first run in convergence.

### D17. One deal per scenario

Each of the six controls scenarios commits its own once-only deal. The operator
decision of the discount scenario closes its case. A deal that a buyer filed on
cannot take a second, different delivery-end filing, so a deal still delivering when
its scenario ends is ended by a stage that files nothing, which the plan establishes.

**Rejected:**

- **Sharing deals among scenarios.** Four deals would serve six scenarios only by
  leaving the discount scenario's case open for a later ruling, coupling the
  scenarios' state.

### D18. The lost-filing, mediation-unavailable and hold-passed scenarios

- **Lost filing.** The filer is the storefront's operator end. Stages: a delivering
  deal; a mediation drop-after-commit rule on the deal's filing; the operator end,
  which records the end, starts teardown and files, its answer lost; the rule deleted;
  the operator end repeated, the adapter reading the record and adopting the one case,
  or the storefront's own servicing retry where SCM retries the filing itself; a
  servicing step, the lifecycle read and the case listing each showing one case.
- **Mediation unavailable.** A delivering deal; the buyer's filing with no rule; a
  servicing step answering it; mediation *unavailable*; a servicing step reporting the
  authority unreachable with delivery active; the outage removed; a servicing step
  reading the authority again. The case comes first because the storefront's read of
  a record the authority does not yet know is refused even when nothing is wrong.
- **Hold passed.** A delivering deal; both doubles' clocks advanced past the once
  part's release instant; the payments snapshot showing the payout; the buyer's
  filing answered with the part `not_held`, reason `paid_out`, and the case dismissed
  with nothing held. No storefront step follows the advance, so only the harness
  files.

**Rejected:**

- **The lost-filing scenario through the buyer's `market end`.** Its retry is the
  buyer's same-key replay, not the storefront adapter's adoption.

### D19. The delta states the six scenarios

The six scenarios are the change's boundary, so the `test-compatibility` delta's
requirement "Controls scenarios prove the lane's dispute wiring in the VM lane" names
them, each on its own deal, how its stages act, and the rule that no stage steps the
storefront's servicing while a ruling waits at its gate, with a WHEN/THEN scenario for
the ruled end, the discount, the lost filing, mediation unavailable and payments
holding a ruling; the hold passed stays in the clock requirement.

### D20. The release wheelhouse carries no distribution only tests depend on

`lane-double-controls` serves only `e2e-tests` and the lane doubles. `dist` keeps
building it, since the e2e runner image and both doubles' images install from `.dist`,
but `dist-release`, which the release workflow tars as `marketplace-wheelhouse`,
builds the release set without it: the root `Makefile` gains a target for the release
set, which both `dist` and `dist-release` build, and only `dist` adds the controls
wheel. A release-tooling test holds that `dist-release` excludes it and `dist`
includes it.

The same holds for `arkhai-apicredits-sample-app`, the demo API the end-to-end
harness drives, which `RELEASING.md` already leaves unpublished (77 F1, settled with
the owner at the pre-closeout triage): `domains/Makefile`'s release aggregate omits
it, `dist` and `dist-ci` add it beside the controls wheel, since the API-credit
lane's sample-app image installs it from `.dist`, and the release-tooling test holds
that the two are exactly what `dist` builds beyond the release set. The principle is
stated, with the release set's composition, in `RELEASING.md`, the owner's choice;
`BUILD_AND_PACKAGING.md`, "The wheelhouse", says in one sentence that `make dist`
builds the lanes' superset of the release set `make dist-release` builds.

**Rejected:**

- **Leaving the wheel in the release.** An official release would ship a wheel no
  operator installs.
- **Deriving the release set from the architecture declaration.** Durable for every
  future test-only package, but it changes how every wheel is assembled, packaging
  work unrelated to mediation.
- **Deferring with a roadmap gap.** The change that added the wheel to the release
  can take it out in a few lines.

### D21. Each controls scenario is a module of its own

The six are scenarios in both of the repository's senses: an end-to-end scenario's
deterministic run of stages, which by precedent is a module (`test_vm_payment_deal.py`,
`test_vm_payment_purchase.py`), and a WHEN/THEN scenario of the delta. So each is a
module of its own under one package of the VM scenarios, sharing helpers for
committing a deal, the buyer's filing and a servicing step. The clock fixture resets
both doubles at each module's end (D2), so the clock scenario's advance is bounded by
construction and no order among the six is needed. The plan names the modules'
markers and their `E2E_MODULE` entries.

**Rejected:**

- **One module of six test sequences.** It keeps the clock advance's ordering
  constraint, and "scenario" would name both the module and its parts.

## Settled during implementation

Choices made inside the decisions above while implementing them, kept here so the
task notes can stay short:

- **An abandoned response (D4).** It is started with `content-length: 1` and never
  finished, so the closed connection cannot read as a complete empty answer
  whatever framing uvicorn picks. A fault is observable only through a real
  server — httpx's `ASGITransport` asserts on an unfinished response rather than
  raising a transport error — so every fault test serves its app under uvicorn on
  loopback.
- **Where matching and counting live (D4).** The middleware hands each request to
  the double's classifier, which matches and counts it, since only the double
  knows its accounts and rules; each API handler counts a refusal itself, so a
  call meets one rule and is counted once. The mediation classifier reads an
  unseen transaction's parties from payments, outside the service's lock and only
  while a rule matches on `filer`. With payments unreadable at classification the
  middleware sees no `filer` while the service later reads it, so the two layers
  can take different first rules for that one call; left as it is, since no
  scenario installs a filer-scoped fault while payments is down.
- **One perceived clock implementation (D2).** `PerceivedClock` lives in
  `lane_double_controls.clock`, which both doubles import, rather than a copy per
  double.
- **An unusable dispute credential (D8).** A CA bundle the client cannot load
  raises at client construction. Each storefront's `credential_available` builds
  and caches the client, so an unloadable bundle, an unresolvable token or an
  origin the client refuses reads the deal `repair required`, rather than failing
  the VM storefront's whole servicing cycle, whose respondent poller builds its
  adapter outside the per-deal `try`; it logs a warning naming the authority, the
  exception's type and the configured path, never the exception's message (77
  F3). The repair reason stays `deal-servicing`'s fixed "Agreement authority
  credential is missing". Each buyer's mediation port answers the construction
  failure as a `MediationTransportError`, as it answers an unresolvable
  credential.
- **`check-mediation`'s extra `configuration` cases (D11).** More than one
  mediation credential at the origin, an identity the contract refuses, and plain
  HTTP off loopback are each `configuration`, since building the client would
  otherwise raise out of the check. The authority is built with empty `params`,
  which the contract admits; the respondent read sends none.
- **The mediation-check pod renders on `tests.mediationOrigin` alone (D11).** The
  chart never reads the runtime Secret's overlay, so naming the origin is what
  states the agent holds a credential; a missing one fails at `configuration`.
- **The buyer's filing (D14).** `file_as_buyer` submits through the
  deal-lifecycle kit's `submit_dispute`, the path `BuyerLifecycle.submit` takes,
  without its courtesy hint to the storefront, which would be a second side
  effect; the storefront learns of the case by respondent discovery at its next
  servicing step.
- **The ruled end's two servicing steps (D15).** A servicing step reads the
  site's lease before its authority watch records the ruled end and begins
  teardown, so the site's signed end report is read only on the next step; the
  ruled-end scenario's stage `05` stores the end and stage `05b` runs that second
  step and reads the report. Validation 71 found the scenario relying on a report
  pushed within the first step, which did not arrive in that run.
- **The deal's ending (D17).** The storefront dispatches a journaled filing only
  at a servicing step or an operator end, and a lease-ended site report can
  journal one, so `DisputeStageZ_NoFurtherCase` steps servicing once before
  reading the case listing, and also reads the lifecycle read's `filings`, since
  the adapter refuses a second delivery-end filing without sending it.
- **The hold passed in two advances (D18).** The hosted part's hold is
  `afterStop`, and a once part stops only at its terms end, which the lease's
  ending does not move, so its snapshot states no `releaseAt` until then. The
  scenario advances both doubles past the terms end, then past `releaseAt`.
- **The lost filing's retry (D18).** Every servicing watch dispatches the deal's
  pending filings first, so the storefront retries the filing itself and the
  adoption is read at a servicing step, the design's second branch.

## Effects on other changes

- **`converge-ongoing-compute-leases`:** its lane-time paragraph (real UTC, bounded
  waits, due-work barriers, clock-skew bounds) is rewritten to D2 and D4; row 10's
  cap amounts and rows 5 and 8's remedies are programmed outcomes, proving SCM's
  handling rather than arithmetic; row 4's races and measured windows move to
  integration level; row 11's refused anchors and livemode changes are proven at kit
  and application level; rows 6 and 7's storefront-side timing waits on the lane-wide
  clock change; the "proposed" class goes (D3). The mediation double executes only
  `reverse` effects (D4, "Mediation shapes"; 40 F2), so the rows whose programmed
  rulings carry a `stop` or a `penalty` first add that effect's execution to the
  double, with its suite's proof. A row using the gate steps no storefront servicing
  while its ruling waits there, since the storefront ends delivery on a `prepared`
  delivery end (D15).
- **`spot-deals-through-arkhai-payments`:** D8 cites the typed control contract of D4
  and the two classes of D3.
- **`activate-per-period-compute-servicing`:** rule-programming stages are lane-only
  gate stages its hosted runs omit, and shared measurement stages compare SCM's state
  with the authority's signed record; its D2 detects payments and mediation-API
  divergence in lanes, mediation-ruling divergence only live; its D4's real-UTC
  doubles and its proposed-provenance recommendation follow D2 and D3.
- **`separate-lane-infrastructure-chart`:** opened by this change's design review
  (15 F2); moves the mediation subchart D11 adds, with the payments double and
  `dev-env`, into a lane-infrastructure chart.
- **`helm-e2e-pipeline-parity`:** owns running the payment scenarios, and so the
  doubles' controls, in Helm validation.
- **The lane-wide perceived clock:** a new change after this one; until it exists,
  this change's closeout records it as an unowned Goal 8 gap naming convergence rows 6
  and 7.
- **Roadmap:** Goal 8's row for this change drops the published/proposed classes;
  convergence's drops revised-case netting; the hosted dispute-authority row records
  D5; two unowned entries are added: a buyer command filing a dispute case on a
  running deal (D14), and what a `prepared` delivery end means to SCM (D15).

## Principles stated for promotion

1. A double reproduces its producer's API mechanics and takes the producer's
   decisions as scenario-programmed answers, as mock provisioning does; it never
   duplicates the producer's decision logic: `docs/development/ARCHITECTURE.md`,
   "Testing strategy", and `docs/development/TESTING.md`, "Private Service
   Dependencies".
2. A decision derived from a record and a timestamp is driven in an end-to-end run by
   moving the deciding service's perceived clock through a control; today only the
   lane doubles have one: `docs/development/TESTING.md`, "The discipline every
   scenario follows", replacing its statement that no control moves the clock, and
   `docs/development/ARCHITECTURE.md`, "Testing strategy".
3. The release wheelhouse carries no distribution only tests depend on:
   `docs/development/RELEASING.md` (D20).

## Open Questions

None.
