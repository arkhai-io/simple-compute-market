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
  (`tools/payments-lane-double/fixtures/dispute-authority.toml`). The VM payment
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
  the mediation double, and one VM-lane module proving each control kind once.

**Non-goals:** a rules engine reproducing the dispute authority's or the payments
service's decisions; contract modes; a production guard on fixture identities;
storefront- or site-side clock control; rate scenarios in lanes (convergence owns
them once spot derives rate parts); a mediation double in the local Helm release;
live, hosted-ledger or adjudication evidence.

## Decisions

### D1. The mediation double answers from programmed rules

The mediation double reproduces the dispute authority's API mechanics and takes
every decision the authority would make as a scenario-programmed answer, the way
mock provisioning takes a job's outcome. It never re-implements the authority's
decision logic.

**Real mechanics:** routes, bearer authentication, schema validation against the
vendored contract, idempotency and conflict answers, the closed-case refusal, either
party appending evidence with only `mandate.to` appending concurrence, the signed
per-agreement record with its sequence and cursors, the respondent listing,
per-part `extend` at the payments double as the authority's own account (a part
payments refuses to extend reports `not_held` from that refusal), and executing a
ruling's effect list as payment events with stable effect keys and the case
reference, resuming after a payments failure without applying an effect twice, then
lifting only that case's extensions.

**Programmed:** whether a case is ruled, the ruling's basis, delivery end and
per-part effects with their amounts, filing-answer overrides (`pending`, `error`, a
refusal), and a gate holding a ruling before its effects. An operator ruling on an
open case takes the same shape, matched by case.

The double verifies no concurrence signature, Agreement digest or mechanical guard:
SCM's verification is proven in the kits against the producer's vectors. With no
matching rule, mechanics proceed (a filing is accepted, each part's extension is
attempted, appends are recorded) and nothing is ever ruled, consistent with silence
never ruling. A payee-filed or concurred case therefore rules only when a rule says
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
| Refuse a matching call with a published status and code | both | convergence rows 1, 3; the doubles' suites |
| Drop the response after commit | both | convergence rows 1, 3; D6 |
| Unavailable: every connection closed unanswered while installed | both | convergence row 1; D6 |
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

**Transport faults live in the doubles.** One ASGI middleware closes connections
unanswered while *unavailable* is installed, and lets a matching request commit before
abandoning its response for *drop after commit*. SCM's clients see each as a transport
error, as they would an unreachable host or a lost response. The mediation double's
calls to payments meet the payments double's middleware too.

**Where the contract lives.** `tools/lane-double-controls` (import
`lane_double_controls`) holds the rule, fault, clock, funding, rotation and ruling
models, the route declarations, a typed client and the transport-fault middleware.
Both doubles and `e2e-tests` depend on it; the doubles themselves stay unimported.
This is the mock-provisioning split of contracts, client and service.

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

### D5. No production guard on fixture identities

The mediation double's identity is inert outside lanes by construction: an origin
that is only a Compose service name, a deterministic fixture account whose only token
is at the payments double, and a record key derived from a committed seed labelled a
public development value, never for a public network. Registries recommend it only
in lane profiles and the local release. A live deal naming it could only come from a
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
- One VM-lane controls module, on once-only deals, proves each control kind once:
  1. a programmed ruling with a delivery end and a reverse, its effect visible at the
     payments double and the storefront ending delivery after observing it;
  2. an operator decision with a partial reverse and no delivery end, the deal
     running on;
  3. a lost filing response, the dispute adapter adopting the one case;
  4. mediation unavailable, servicing reporting the authority unreachable while the
     deal runs;
  5. payments unavailable between two programmed effects, the ruling incompletely
     applied and then completed with no duplicate effect;
  6. a clock advance past a once part's hold, the payout visible and a later case
     reporting `not_held`. It runs last, so no stage runs storefront work against
     records dated ahead of the storefront.
- The doubles' own suites drive the kits' real clients over HTTP.

Planning may trim the module's stages. Convergence keeps every rate row.

**Rejected:**

- **Only the existing scenarios.** The controls' first lane use would be convergence's,
  which would debug this change's wiring.
- **Every new scenario left to convergence.** The same defect.

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
- No storefront `check-mediation` command: the controls module proves the storefront's
  mediation access.

**Rejected:**

- **The mediation double in the VM and bare-metal lanes only.** Overlays that differ
  to save one container.
- **A `check-mediation` command.** A diagnostic with no caller.

### D10. The payments double's claimed surface

Its library-integration suite drives the payments kit's real client over HTTP, with
clock control, and claims rate parts, payee-only `start`, `stop` with notice and the
earliest pending stop, per-part `end`, funding exhaustion at funded-through,
`afterStop` holds, partial `reverse` before and after a stop, and `extend` and `lift`
with their published refusals. No lane rate scenario is added.

### D11. The local Helm release

No mediation double or control surface is added: the release serves no payment
scenario. Its registry recommends the lane's mediation identity, which nothing answers
in the cluster, so servicing keeps reporting deals running. Bob's copied dispute
credential carries `ca_bundle_path`, harmless there.

**Rejected:** a mediation subchart, with no scenario to use it.

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
2. **Lane wiring, one session.** The overlay, fixtures, registries, the runner's
   `MEDIATION` section and helper, buyer configuration, the VM case and refund stages,
   the bare-metal filing and the controls module.

The doubles are reviewed before any lane uses them, so a wiring defect cannot hide a
double's.

## Effects on other changes

- **`converge-ongoing-compute-leases`:** its lane-time paragraph (real UTC, bounded
  waits, due-work barriers, clock-skew bounds) is rewritten to D2 and D4; row 10's
  cap amounts and rows 5 and 8's remedies are programmed outcomes, proving SCM's
  handling rather than arithmetic; row 4's races and measured windows move to
  integration level; row 11's refused anchors and livemode changes are proven at kit
  and application level; rows 6 and 7's storefront-side timing waits on the lane-wide
  clock change; the "proposed" class goes (D3).
- **`spot-deals-through-arkhai-payments`:** D8 cites the typed control contract of D4
  and the two classes of D3.
- **`activate-per-period-compute-servicing`:** rule-programming stages are lane-only
  gate stages its hosted runs omit, and shared measurement stages compare SCM's state
  with the authority's signed record; its D2 detects payments and mediation-API
  divergence in lanes, mediation-ruling divergence only live; its D4's real-UTC
  doubles and its proposed-provenance recommendation follow D2 and D3.
- **The lane-wide perceived clock:** a new change after this one; until it exists,
  this change's closeout records it as an unowned Goal 8 gap naming convergence rows 6
  and 7.
- **Roadmap:** Goal 8's row for this change drops the published/proposed classes;
  convergence's drops revised-case netting; the hosted dispute-authority row records
  D5.

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

## Open Questions

None.
