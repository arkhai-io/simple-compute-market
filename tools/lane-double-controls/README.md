# lane-double-controls

The control contract of the end-to-end lanes' doubles, the payments double
(`tools/payments-lane-double`) and the mediation double
(`tools/mediation-lane-double`), and of the API-credits lane's sample app
(`domains/apicredits/sample-app`), which serves its time control alone: the
contract a party serves and a scenario calls. The inference lane's gateway
(`domains/inference/gateway-service`), a published package, serves the time
route and the status on this wire without importing this package; the typed
client here drives it. It holds the wire models, the
control route declarations, a typed client, the transport-fault middleware, the
time control over a party's time source (`lane_double_controls.time_control`), and
the lane CA the doubles serve under. It imports no double, so a caller of the controls
installs neither FastAPI nor a double's internals, and nothing here is part of
the market runtime.

## The controls

Every control is a deterministic step a scenario takes: nothing here delays,
races or runs in the background. Control routes sit under `/test/` on each
party's own API port, and each is authenticated by the party's control token as
a bearer token: a double's fixture token, the sample app's and the inference
gateway's from their environment. No lane publishes a double's port to its host;
the sample app's control and the gateway's sit on their published API ports,
behind their tokens and outside their metering gates.

| Route | Parties | Control |
|---|---|---|
| `POST /test/rules` | both doubles | install a when→then rule |
| `GET /test/rules` | both doubles | list rules with their matched and waiting counts |
| `DELETE /test/rules/{rule_id}` | both doubles | remove a rule, whatever its state |
| `POST /test/rules/{rule_id}/resume` | mediation | release a ruling held before its effects |
| `POST /test/time` | every party, under injected time | set the party's injected time forward |
| `GET /test/status` | every party | the party's time and the installed contract hashes |
| `POST /test/funding` | payments | credit an account |
| `POST /test/signer/rotate` | payments | sign with the second fixture receipt key |
| `POST /test/transactions/{transaction}/reserve` | payments | reserve a transaction's running rate parts further |
| `GET /test/cases?transaction=…` | mediation | list a transaction's cases |
| `POST /test/cases/{case_ref}/decide` | mediation | an operator's ruling on an open case |
| `POST /test/cases/{case_ref}/close` | mediation | close an open case without ruling |

Each party reads the time of the world from one source, the time component's
([`tools/injected-time`](../injected-time/README.md)), installed from its own
time-source setting: wall time by default, or injected time, an instant that
holds until the time control sets it forward. `TimeControl` wraps the
component's route service for a party's handlers. `POST /test/time` takes
`{"now": <Unix seconds>}`, read by the component's one rule, and answers
`{"source": "injected", "now": …}` (`TimeView`); a party evaluates its due state
lazily at each read, so a notice, a funding boundary or a hold's release set
past shows at the next read. Status carries the time as `{"source": "injected",
"now": …}` or `{"source": "wall"}`, and the sample app's names no contract. A
wall-time party serves no time route, as no wall-time instance offers a way to
change its time.

The payments service's scheduler reserves a started rate part's further periods
as time passes; the payments double reserves them only when the scenario calls
the reservation control, since a double takes its producer's scheduled decisions
as answers a scenario programs. `POST /test/transactions/{transaction}/reserve`
takes `{"through": <Unix seconds>}` (`Reservation`) and reserves each of the
transaction's running rate parts — started and not stopped — through that
instant, as far as the part's end and the payer's balance allow, answering
`{"transaction", "parts": [{"part", "reserved_through", "periods_added"}]}`
(`Reserved`), each part's `reserved_through` the funded boundary its signed
snapshot then reports. The double reserves as the payments engine reserves at a
rate part's `start`, covering 60 seconds past `through`, so a `through` on a
period boundary short of the part's end reserves the period after it too, and
`reserved_through` may lie up to a period past `through`. The answer always lists
at least one part: a transaction
with no running rate part is refused, so a reservation stage run too early or
against the wrong deal fails where it runs.

A rule (`Rule`) names a `rule_id`, a `match`, and exactly one action:

- `refusal` `{status, code}` answers a matching call with that published error;
- `drop_response_after_commit` lets a matching call commit, then abandons its
  response;
- `unavailable` abandons every API response while it is installed;
- `filing_answer` answers a matching mediation filing `pending`, `error` with a
  contract failure code, or `rejected` with a contract refusal reason;
- `ruling` `{basis, delivery_end, effects, close}` rules a matching mediation
  case, optionally held at `pause_before_effects` until resumed. The gate holds
  the delivery end with the other effects, recorded `prepared`; since the
  marketplace's watch records an end from a delivery-end effect whatever its
  applied state, a scenario steps no storefront servicing while a ruling waits
  at its gate.

A call matches when every `match` entry equals the call's property of that name.
`match` is always stated: `{}` is every call of the double, and a rule without
one is refused. An `unavailable` rule's `match` is `{}`. The payments double
matches on `route`, `account`, `event` and `transaction`; the mediation double on
`operation`, `filer`, `kind`, `cause` and `transaction`. A ruling's basis and
effects are validated against the vendored mediation contract, through
`market_arkhai_mediation.contract`; its delivery end is the `delivery_end` flag,
never an effect, and an empty effect list is a ruling that moves no money.

Every refusal has one body, `{"code", "message"}`, raised on both sides of the
wire as `ControlError`:

| Case | Answer |
|---|---|
| a rule without `match`, an `unavailable` rule with a non-empty one, a malformed ruling or effect, a property or action the double does not have | `422 invalid_request`; nothing is installed |
| a missing or wrong control token | `401 authentication_required` |
| installing an existing `rule_id` | `409 rule_exists` |
| deleting or resuming an unknown `rule_id` | `404 rule_not_found` |
| resuming a rule not waiting at its gate | `409 rule_not_waiting` |
| deciding or closing an unknown case; funding an unknown account | `404 case_not_found`; `404 account_not_found` |
| deciding or closing a closed case | `409 case_closed` |
| deciding a case that is applying another ruling | `422 invalid_request` |
| closing a case applying a ruling, before every effect is applied | `409 case_applying`; nothing is lifted |
| closing a case whose extensions payments does not lift | `502 payments_unavailable` |
| setting time earlier than the party's instant | `409 time_moves_forward`; nothing changes |
| a time setting whose body is not exactly `{"now": <instant>}` | `422 invalid_time`; nothing changes |
| reserving a transaction the payments double does not hold | `404 transaction_not_found`; nothing changes |
| reserving a transaction with no started, unstopped rate part | `409 no_running_rate_part`; nothing changes |
| a reservation whose transaction or body is malformed | `422 invalid_request`; nothing changes |
| setting the time of a wall-time double | `404 invalid_request`, no such control route |

Deleting a rule that has matched is cleanup and answers `204`; listing a
transaction with no cases answers an empty list.

`ControlClient` is the typed client: it builds each request from the route
declarations, trusts the CA bundle it is given alone, and raises a refusal as
`ControlError` carrying the code. An error status whose body is not a control
error, such as a proxy's page, is raised with the code `unexpected_response`,
which no double sends. A transport failure stays httpx's own error.

## Transport faults

`TransportFaultMiddleware` wraps a double's ASGI app and asks the double's
classifier, for each API request, whether an installed rule faults it; the
classifier counts the match in that rule's listing. A fault starts the response
and abandons it, so uvicorn closes the connection and the caller's httpx raises
`RemoteProtocolError`, which both kit clients count as a transport error: an
`unavailable` request never runs, and a `drop_response_after_commit` request runs
to completion first. Control routes are never faulted, so a finaliser can always
remove the rule that caused a fault, and neither is `/health`, so an
orchestrator's liveness probe never restarts a double during an outage; neither
reaches the classifier. The classifier runs on a worker thread, so those routes
keep answering while it waits on a collaborator; it may be called from several
threads at once and guards its own state.

## TLS

`tls/generate.py` derives the lane CA's key and each double's leaf key from fixed
seeds and writes the CA certificate (`lane-ca.pem`), and for each double its leaf
certificate and key: `payments-double.pem` and `mediation-double.pem`, each for
its service name, `localhost` and `127.0.0.1`, with `.key.pem` keys. Serials and
validity, ending 9999-12-31, are fixed and Ed25519 signatures are deterministic,
so the output is the same bytes on every run. One CA issues both leaves, so a
caller trusts both doubles through one CA bundle.

Every seed, the CA and the leaves are public development values, for lanes and
local releases: the CA's private key is never written to a file, but its seed is
in the generator, so anyone can issue a certificate under the lane CA. Never trust
it, or serve with these keys, on a public network. The certificates are
committed; the leaf keys are not, since the repository's secret gate refuses a
private key block, so each double's image build runs the generator and takes its
own key. Callers trust the lane CA through their configured CA bundle path, never
by replacing a process trust store.

## Running it

- `make test` (here) checks the committed certificates (`check-tls`
  regenerates them into a temporary directory and fails unless they are
  identical), type-checks the package, and runs the unit and integration
  suite. The fault cases, and the client's case trusting the lane CA, serve a
  small app under uvicorn on loopback, because an abandoned response is a
  server's behaviour, which an in-process transport does not have; the
  generator's cases complete their handshakes in memory.
- `make tls` rewrites the certificates and writes the leaf keys beside them,
  ignored by Git, for running a double outside its image.
- From the repository root, `make test-lane-double-controls` runs `make test`,
  as part of `make test` and the Tests workflow's matrix, and `make dist` and
  `make dist-ci` build the wheel into the repository wheelhouse, from which a
  project declaring it installs it through its lock. The release wheelhouse,
  `make dist-release`, does not carry it, since only tests depend on it.
