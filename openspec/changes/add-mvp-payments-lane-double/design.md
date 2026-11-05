# Design

## Context

No end-to-end lane can run a purchase settled in `arkhai.payments.v1`. With no payments
target configured, every payment scenario is a blocked skip
(`e2e-tests/tests/e2e/roles/helpers/payments.py`), so the payment path is verified only
against an external deployment. The kit's `FakePaymentsClient` is in-process and cannot
serve a `market` subprocess or a storefront container.

Facts the decisions rest on:

- **The engine exists.** `PaymentsAuthority`
  (`kit/arkhai-payments/src/market_arkhai_payments/fixtures/authority.py`) is a
  clock-injected, atomic, idempotent per-part authority that already replays the
  producer's vectors, and `FakePaymentsClient` uses it. It has no balance view.
- **The client is plain HTTPS with fixed paths.** `PaymentsClient`
  (`kit/arkhai-payments/src/market_arkhai_payments/client.py`) refuses plain HTTP outside
  loopback and builds non-loopback connections with `trust_env`, so `SSL_CERT_FILE`
  reaches it. It has no balance call.
- **Lane authentication is bearer tokens.** `ArkhaiPaymentsConfig` refuses
  `development_auth` unless `service_url` is loopback
  (`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`), and a Compose
  or cluster service name is not loopback.
- **The payments service serves `GET /balances/{account}`**, answering only for the
  caller's own account and refusing another with 403 `caller_not_authorized`. Its
  response is the vendored `Balance` model; the vendored schema carries the model but no
  routes, and the kit hard-codes every path it calls.
- **Mediation is a separate service with a separate client.** It has its own published
  contract (`kit/arkhai-mediation/schema/SOURCE.md`), its own client
  (`kit/arkhai-mediation/src/market_arkhai_mediation/client.py`) at the Agreement-pinned
  authority origin, and it reaches the payments service over HTTP to extend holds.
- **The existing payment scenarios.** `e2e_bare_metal_payment_deal` and
  `e2e_credits_payment_deal` use only the once-only surface. `e2e_vm_payment_deal`'s
  stages 1–2 are once-only; its stage 3 needs a mediation authority that accepts a filed
  case, and stage 4 depends on stage 3.
- **`PAYMENTS` is one settings section across lanes.** Every lane runs with the `docker`
  profile (`e2e-tests/Makefile`), while the values differ per lane: the seller credential
  is the bare-metal storefront's eip191 key in one lane and an Ed25519 seed in the
  API-credit lane.
- **Readiness is configuration-only.** `arkhai_payments_preflight` never contacts the
  service, so no current check proves a storefront can reach its payments service.
- **The local Helm release serves no payment scenario** (`scripts/validate_slice.py`),
  and the storefront charts render agent configuration from structured values whose keys
  they can read (`openspec/specs/deployment-state/spec.md`, "A storefront chart passes
  service configuration through").

## Goals / Non-Goals

**Goals:**

- A once-only `arkhai.payments.v1` HTTP double, mirroring the payments service's API,
  that runs in the VM, bare-metal and API-credit lanes and in the local Helm release.
- Every once-only payment stage the lanes hold runs against it rather than skipping.
- The payer's own balance read in the payments kit.
- The storefront charts' payments interface — CA trust and key injection — rehearsed in
  the local release through the values a deployment supplies, with a check a deployment
  can rerun.

**Non-Goals:**

- A mediation double, controls, contract modes, fault injection or evidence classes:
  `add-arkhai-payments-lane-double`'s.
- Qualifying rate parts, stops or holds at the HTTP boundary, though the double serves
  what its engine serves.
- A production guard refusing fixture identities.
- Serving payment scenarios on the local Helm release.
- Any hosted-ledger, funding or live evidence.

## Decisions

### D1. The double is its own tooling project, named for payments

`tools/payments-lane-double`, import package `payments_lane_double`, image
`arkhai:payments-lane-double`, Compose and cluster service `payments-double`. It wraps the
kit's `PaymentsAuthority`, so there is no second ledger, and imports only public kit
models and fixtures. No package depends on it. It is a third kind of tool beside
`tools/README.md`'s two: a lane collaborator that may import internal kits and that
nothing imports. Its image is built from the repository wheelhouse and its committed
lock, in each lane's build target and for the local release.

Package, module and image names avoid "authority", which the repository uses for several
different things.

The mediation double, when built, is a sibling project, `tools/mediation-lane-double`,
that reaches this double over HTTP with its own account, as the dispute authority acts
at the payments service only through its own authorities
(`openspec/specs/market-composition/spec.md`, "The payments service and dispute authority
keep their authority").

**Rejected:**

- **A shared `tools/authority-lane-doubles` project with payments and mediation entry
  points.** Mediation is a separate service with a separate client at the producer and in
  SCM, so nothing calls for bundling, and the name uses an overloaded word.
- **A module in the e2e harness served from `arkhai:e2e-tests`.** Cheapest, but the
  harness would become driver and counterparty at once.
- **An ASGI app in the payments kit.** The production wheel would gain a web framework,
  and the mediation double could not live in a single-mechanism kit.

### D2. All three lanes run the double; the VM scenario's case stages wait for mediation

| Scenario | After this change |
|---|---|
| `e2e_bare_metal_payment_deal` | runs on the double |
| `e2e_credits_payment_deal` | runs on the double |
| `e2e_vm_payment_deal` stages 1–2 | run on the double, proving the VM wiring |
| `e2e_vm_payment_deal` stages 3–4 | blocked skip naming the missing mediation target |

Stages 3–4 gain a mediation prerequisite, a separate setting from `PAYMENTS`
(`MEDIATION.SERVICE_URL`, blank by default, which blocks them by name), until a
mediation double supplies one. The VM module's existing resource release frees capacity;
its unrefunded hold lives only in the double's memory and ends with the lane.

Stage 2 runs, and asserts the authority view is `running` while the pinned authority
cannot be reached. A transport failure at the pinned origin becomes a
`MediationTransportError`, which the mediation adapter turns into a non-`Accepted` view;
the seller takes `state` from the payments observation whatever the dispute outcome.
The seller reports `repair_required` instead whenever it holds no usable credential for
the deal's dispute authority, so the VM lane's storefront carries an identity-bound
`[[DisputeCredential]]` for the pinned authority, its `api_key_env` naming a variable that
holds a labelled public development value. A focused storefront-level test proves the
case: with a resolvable credential and an unresolvable pinned origin, servicing reads
`state == "running"` with a non-`Accepted` dispute outcome, and the respondent poll
neither raises nor marks the deal for repair. If it shows otherwise, this decision and
the test-compatibility delta are revised together before implementation goes on.

The bare-metal and API-credit lanes' storefronts carry no such credential: no domain
code branches on `repair_required`, and only the VM scenario asserts the authority state.

**Rejected:**

- **Leaving the API-credit lane out.** Its scenario needs only the once-only surface, and
  the acceptance boundary would carry an exception.
- **Gating the whole VM module.** No scenario would exercise the VM wiring before
  `qualify-real-provisioning-by-scenario`.
- **Removing the VM scenario from the lane's markers.** It hides the scenario.

### D3. A committed development CA and leaf, with deployment injection

`tools/payments-lane-double/tls/` holds a generator and its output: the lane CA
certificate and the double's leaf certificate and key. The generator derives both keys
from fixed seeds and uses fixed validity, and Ed25519 signatures are deterministic, so a
check regenerates the files and requires them unchanged. The CA's private key is never
written. The leaf's SANs are `payments-double`, `localhost` and `127.0.0.1`; the service
is named `payments-double` in Compose and in the local release, so the certificate
matches both. Every value is a labelled public development value, never for a public
network, following the repository's Anvil-key precedent.

Lane callers trust the lane CA alone through `SSL_CERT_FILE`: no lane container reaches a
public HTTPS endpoint.

In Helm:

- Both storefront charts gain a CA option whose main source is a ConfigMap key — infra
  supplies `payments-ca-bundle` / `ca-bundle.pem` — mounted and named by
  `SSL_CERT_FILE`. A Secret key is a secondary source. The chart has no default.
- The local deploy target creates that ConfigMap from the committed lane CA by default.
- The double's subchart takes its server certificate and key from an existing Secret
  when one is named, and otherwise from the committed files.

A fixed service name means two local releases in one namespace collide; validation uses
one release per namespace. In the local two-release topology the double runs in the first
release only: the bare-metal release's values disable its subchart, and its storefront
reaches the first release's `payments-double` in the same namespace.

The committed fixtures — TLS files, accounts, tokens and the buyer's seed balance — are
built into the double's image at a fixed path, so Compose runs it without mounts and the
subchart's "committed files" are the image's own. The charts follow the repository's rule
that a chart accepts only names of existing Secrets and never reads credential files into
values (`helm/Makefile`): the local key Secret and CA ConfigMap are created from the
committed fixtures by the local out-of-band step that creates every other local Secret,
`make -C helm topology-secrets` (`helm/scripts/topology-secrets.sh`), and the local deploy
target checks for them before installing.

**Rejected:**

- **Generating the CA per run.** Two mechanisms, Compose and Helm; Helm regenerates on
  every upgrade unless pinned with `lookup`; and the files must reach the test runner.
- **The double making its CA at startup.** Sharing it with other pods needs cluster API
  access.

### D4. No production guard; the pinned dispute authority is unusable by construction

- Fixture accounts, tokens and keys are labelled public development values in lane-only
  files.
- The double always signs `livemode: false`, so a live-configured role refuses every
  receipt it signs (`openspec/specs/market-composition/spec.md`, "Arkhai payment request
  and receipt authentication").
- The pinned dispute authority's origin is `https://dispute.invalid`, under a top-level
  domain reserved never to resolve, so nothing can ever answer there.
- Its record key has no usable private half: a nothing-up-my-sleeve point, or a key
  generated with its private half discarded. It is not derived from a seed.
- Its account has no bearer token at the double.
- The VM storefront's `[[DisputeCredential]]` for it (D2) is the seller's token toward
  the mediation authority, not the authority's token at the double; nothing at
  `.invalid` ever reads it.

So a copied fixture is either refused by mode, unknown to a real service, or obviously
inert. A guard in role configuration loaders is `add-arkhai-payments-lane-double`'s
decision, because its mediation double needs a usable public signing key.

**Rejected:**

- **A guard refusing known fixture identities unless a lane flag allows them.** Production
  kits would embed test values, a copied lane configuration copies the flag, and no loader
  distinguishes production from a lane today.

### D5. The balance read mirrors the payments service

- `PaymentsClient.get_balance(account) -> Balance` calls `GET /balances/{account}`, with
  the account validated as an `AccountId`. The client needs no knowledge of its own
  account; the service decides who may read.
- `PaymentsAuthority.balance(account)` first advances every transaction the account is a
  party to, to the injected clock, as a snapshot does (`advance(transaction,
  refill=False)`), so matured lots are released into the payee's `available` and rate
  trims are refunded to the payer's before anything is read. It then returns `available`
  from the engine's balances, released payee earnings included, and `held` as one entry
  per part and distinct maturity among that part's held lots, where the account is the
  payee:
  - a timed entry's `address` is `hold:<transaction>:<part>:<releaseAt in Unix seconds>`,
    its `balance` the sum of the part's held lots maturing then, and its `releaseAt` that
    maturity;
  - the part's lots with no maturity yet form one entry, `hold:<transaction>:<part>:until`,
    whose `until` is `lift` when extensions are open, unless an until-stop hold is still
    awaiting its stop, and `stop` in every other case.

  A once part has one lot, so it has one entry; a rate part's periods each mature on
  their own, and a single entry would report later money as releasing at the earliest
  date. The vendored `Balance` keys entries by `address`, so several may share a part.
- An account the engine has never seen returns `{"available": {}, "held": []}`.
- The engine's suite reads a payee's balance just before a once hold matures, finding it
  held, and just after, finding nothing held and the earnings net of fee in `available`.
- `FakePaymentsClient.get_balance` delegates to the same view.
- The double answers only the caller's own account, refusing any other with 403
  `caller_not_authorized`.

**Rejected:**

- **`get_balance()` with no argument.** The client would need to learn its owner account,
  changing every caller's construction.
- **An always-empty `held`.** Valid against the schema but false for a payee with held
  money.

### D6. A lane-owned target fails rather than skips

- The double has a `/health` healthcheck, and the lanes' storefronts depend on it being
  healthy.
- Each lane target runs the storefront payments check (D12) after the stack is up, so a
  storefront that cannot reach the double fails setup by name.
- The lane settings mark the target `PAYMENTS.LANE_OWNED=true`. The helper then fails on
  an unready target, naming its URL; an external target keeps its blocked skip.
- The helper's readiness probe builds an SSL context from `SSL_CERT_FILE` when it is set,
  keeping environment proxies disabled.

**Rejected:** keeping the skip and relying on Compose alone. An outage partway through a
run would still look like a skip.

### D7. The pinned dispute authority reaches both roles through the registry

Each lane registry, and the local release's registry, recommends the `.invalid` authority
through its recommended-dispute-authorities setting. Sellers use registry
recommendations by default, and the shared buyer profile writer opts in, so neither role
carries a `[[Dispute]]` entry. In the VM lane, Bob publishes to two registries, and
publication offers only authorities common to every destination, so both VM registries
carry the same recommendation.

**Rejected:** a local `[[Dispute]]` entry in every storefront and buyer configuration —
more places to keep identical, and not how a deployment pins one.

### D8. The double mirrors the payments service's API

A double mirrors its producer's API unless there is a compelling reason to deviate.

- `GET /health` returns `{"status": "ok"}`.
- `Authorization: Bearer <token>` maps to an account through the fixture account file; a
  missing or unknown token gets 401 `authentication_required`. A malformed body gets 400
  `invalid_request`.
- `POST /transactions` approves a mandate, with optional attachments, checking in order:
  1. bearer authentication;
  2. the caller is `mandate.from`, otherwise 403 `caller_not_authorized`;
  3. an exact repeat of an approved mandate returns its original receipt, whatever the
     clock or the payer's balance now says, so a lost response can be retried;
  4. for a new approval only, admission refuses, in order: `mandate_expired`;
     `unsupported_asset` for anything but `USD/6`; `fee_mismatch` against the double's
     fee policy of 250 bps; `account_not_found` when `from` or `to` is outside its account
     directory; then the engine's `insufficient_funds` and `deal_mismatch`.

  The engine's own `approve` already looks up the transaction before checking expiry; the
  double's admission must not run ahead of that lookup. Its suite includes a retry after
  the mandate's `expires` that receives the original receipt.
- `GET /transactions/{id}` and `GET /transactions/{id}/mandate` answer the parties and any
  account named in any part's authorities; anyone else gets 403.
- `POST /transactions/{id}/attachments` stores an Agreement the engine checks against the
  deal hash.
- `POST /transactions/{id}/events` submits an event, with `Idempotency-Key` as the
  engine's `requestId`.
- `GET /balances/{account}` is D5's.

The double serves whatever its engine serves, rate parts and `start`, `stop`, `extend` and
`lift` included. Its own suite, the specification and the documentation claim only the
once-only surface; rate and hold qualification stays `add-arkhai-payments-lane-double`'s.

Admission policy — fee, assets, account directory — lives in the double, not the engine,
since the in-process fake seeds approvals through `load` and has no admission.

State is in memory in one process, one lock serialising requests, and is lost on restart;
a run lives with its lane. The clock is wall time injected into the engine. The
receipt-signing key is a labelled fixture seed distinct from `FakePaymentsClient`'s. The
buyer is funded at startup from the fixture file; there is no funding route, since
funding is topology.

**Rejected:** refusing rate mandates and events other than `reverse`. It adds code to
remove behaviour the service has, where limiting the claim keeps the boundary.

### D9. `PAYMENTS` settings are injected per lane through the environment

Each lane target passes `ARKHAI_PAYMENTS__…` overrides to the test runner: the service URL
and identity, the accounts, that lane's seller credential, `API_KEY_ENV`, `LANE_OWNED`,
and the bare-metal fixture's `SELLER_ACCOUNT`, `COMPUTE_HOURLY_GROSS` and
`DISPUTE_WINDOW`. It also passes the buyer token variable `API_KEY_ENV` names,
`SSL_CERT_FILE` and the CA mount. The VM lane's storefront also receives its
`[[DisputeCredential]]` for the pinned authority and the variable it names (D2). The
values come from committed fixture files under
`tools/payments-lane-double/`, generated into each lane's environment the way the
`e2e-*-dev-env` targets already are. The local release's e2e-tests chart values carry the
same keys.

**Rejected:** a `PAYMENTS` section in `config-docker.yml`, which would configure the same
values in every lane and in any run selecting the profile.

**Reversed at the implementation round's triage (31 O1).** The owner chose alternative B,
against the triage's recommendation of A. Lane configuration follows
`DEPLOYMENT_AND_CONFIG.md`'s "Profile-based configuration", where `<PREFIX>_*` variables
are a last-resort escape hatch, never the normal way to supply configuration:
- The test runner reads each lane's `PAYMENTS` settings from a committed profile,
  `e2e-tests/config/config-<lane>-lane.yml`, selected by that lane's `ACTIVE_PROFILES`.
  This answers the rejection above, because only the lane that selects a profile gets its
  values.
- Each lane's Compose overlay states its values literally.
- The pre-existing `e2e-*-dev-env` targets move the same way in this change. That
  includes the values their services read as `REGISTRY_*` and `PROVISIONING_*`
  environment variables, which move into those services' profile files.
- The only environment values left are the buyer's bearer token, which `api_key_env`
  reads from the process by design, and `SSL_CERT_FILE`, process trust read by the TLS
  library.
- Tests hold every restated value to the fixture files it restates.

The shape is open, and it returned the change to design: which values become which
service's profile, what remains a real per-run choice beyond `PROVISIONING_MODE`, what
replaces `e2e-dev-identities`, and the proposal's scope and impact.

### D10. Implementation cadence

One round of four sessions, then its review:

1. **Kit:** the engine's balance view, `PaymentsClient.get_balance`,
   `FakePaymentsClient.get_balance`, and the payments check function D12's commands call.
2. **The double:** the project, its app, the TLS fixtures and generator, the account and
   funding fixtures, its image, and its suite driving the real `PaymentsClient` against
   the app.
3. **Compose wiring:** the double in the VM, bare-metal and API-credit stacks, storefront
   payments configuration and registry recommendations, per-lane settings, the helper's
   `LANE_OWNED` rule and CA-trusting probe, the VM scenario's mediation prerequisite, the
   VM storefront's dispute credential and its unreachable-mediation test (D2), and both
   storefront CLIs' `check-payments`, run by each lane target.
4. **Helm:** the `payments-lane-double` subchart, both storefront charts' CA and
   payments-key options, the local release's payments values and deploy-target defaults,
   the `helm test` payments check, and the render cases.

### D11. The local Helm release rehearses a deployment's payments interface

The local release is where the external round's deployment shape is rehearsed:

- **Key injection.** Both storefront charts gain a payments-key option: a Secret name and
  key, exposed under the variable the agent configuration's `api_key_env` names, read
  from the structured configuration the chart already renders. Infra supplies
  `seller-payments-key` / `api-key`.
- **Deployment values only.** The local release configures payments through the same
  values a deployment uses — `[Settlement.arkhai_payments]` in agent configuration, the
  key Secret, the CA ConfigMap — never `development_auth`. The local out-of-band step
  creates the key Secret and the CA ConfigMap from the committed fixtures, and the deploy
  target checks for them (D3).
- **The double.** The `payments-lane-double` subchart is enabled by the local deploy
  target, never in release values, as `dev-env` is.
- **A rerunnable check.** A `helm test` pod runs D12's `check-payments`, reading the
  seller's own balance, with everything that decides the storefront's payments access
  and nothing else (D12).
- **Render cases.** The subchart, both options, a payments-only storefront with Wallet,
  Chains and Alkahest null and RPC off, and the test pod mounting no data volume.

Payment scenarios are not served on the local release. That is a roadmap gap, to be
revisited when an external run fails in a way the charts shape.

### D12. Storefronts check their payments access from their own container

Readiness never contacts the payments service, so an authenticated read from the
storefront's own process environment is what proves its CA mount, `SSL_CERT_FILE`, key
variable and `service_url` together.

Both storefront CLIs gain `check-payments --account <id>` (`market-storefront
check-payments`, `bare-metal-storefront check-payments`), beside the existing operator
command `bare-metal-storefront redeliver-introduction`. The API-credit storefront's CLI,
`apicredits-storefront`, gains the same subcommand over the same kit function, since D6
has every lane's setup run the check and D2 brings the API-credit lane in; it has no
chart, so it has no Helm test. Each loads the storefront's
configuration exactly as `serve` does and calls one function in `kit/arkhai-payments`,
which builds the client through `payments_client_for_owner`, calls `get_balance`, and
returns the outcome or the failing step: `configuration`, `credential`, `transport`, or
`refused <code>`. The command prints one JSON line with no credential and exits nonzero on
failure.

```console
$ bare-metal-storefront check-payments --account 00000000-0000-4000-8000-0000000000b2
{"check": "payments", "outcome": "ok", "service_url": "https://payments-double:8443",
 "account": "00000000-0000-4000-8000-0000000000b2", "assets": ["USD/6"], "held": 0}
```

It is run by Compose lane setup through `docker compose exec`; by the local release's
`helm test` pod; by a deployment through `helm test`, or through `kubectl exec` into the
running pod when its exact conditions matter; and by
`qualify-real-provisioning-by-scenario`'s external round as its first check of the
topology's payments interface. The account is explicit because the storefront's payments
configuration does not name the seller's payee account.

The chart's test pod runs the storefront CLI's `check-payments` directly, not through the
entrypoint, with what decides payments access identical to the Deployment's — the image,
the configuration and secrets mounts, the identity credential variable, the CA bundle
mount with `SSL_CERT_FILE`, and the payments-key variable — rendered from the same chart
helpers as the Deployment so the two cannot drift. It omits the data volume, whose
ReadWriteOnce claim a pod on another node cannot attach; the `/health` probes, which
target a server the command never starts; and the ZeroTier capabilities and device. A
local release without persistence uses an `emptyDir` and would not reveal the volume
problem, so a render case asserts the test pod mounts no data volume.

**Rejected:**

- **A test pod from the e2e-tests image with copied configuration.** It can pass while
  the storefront's own mount or variable is wrong.
- **A storefront admin route performing the read.** New authenticated production surface
  for a diagnostic.

**Settled at the implementation round's triage (29 F2): validation's Helm part runs the
check pods.** `scripts/validate_slice.py` runs every `-payments-check` test pod the
release's hooks render, each as its own step, after the scenario pod. As with the scenario
pod, a pass counts only with the pod's own exit status of 0, because `helm test` passes
when its filter matches nothing. The validator keeps each pod's log as evidence, and warns
when the release renders no check pod. Validation deploys only the first release, so this
covers Bob's storefront; the bare-metal storefront's check stays under `topology-check`.
**Rejected:** closeout recording an owner-run `make -C helm test`. It is evidence once,
and nothing re-proves the check on the next change to the charts.

## Effects on other changes

- **`qualify-real-provisioning-by-scenario`:** the storefront charts' CA option, its D11,
  is delivered here; its D11 keeps the kit's cluster-service HTTPS test. Its D14's list
  grows by the API-credit lane, Helm and the check. Archive cleanup returns it to design,
  where this is reverified.
- **`add-arkhai-payments-lane-double`:** its D1 becomes a sibling
  `tools/mediation-lane-double` reaching this double over HTTP, with controls added to
  this double; its D7 becomes "this change owns the payments double; that one extends it
  and adds mediation". The production guard on fixture identities is its decision. The VM
  payment scenario's stages 3–4 wait on its mediation double.

## Principles stated for promotion

1. A double mirrors its producer's API unless there is a compelling reason to deviate:
   `docs/development/TESTING.md`, with the rule in `docs/development/ARCHITECTURE.md`'s
   testing philosophy.
2. A local release configures a service through the same values a deployment uses, as the
   deployment's rehearsal, never through development-only modes:
   `docs/development/DEPLOYMENT_AND_CONFIG.md`.

## Open Questions

- **31 O1, the shape of D9's reversal.** It is open, and returned the change to design;
  D9 lists the questions.
- **29 documentation, the guidance the MODIFIED `deployment-state` requirement follows.**
  The delta permits a value read from the process environment by something other than
  the loader (`SSL_CERT_FILE`) and a credential the configuration names by variable
  (the `api_key_env` key). `DEPLOYMENT_AND_CONFIG.md`'s "Profile-based configuration"
  names only the profile resolver variables and a variable an external subprocess
  reads. The owner's rule is that code follows the guidance and a disagreeing spec or
  guidance changes. So either that section gains the two kinds, or the CA bundle and
  key travel another way.

Serving payment scenarios on the local Helm release is recorded as a roadmap gap with its
trigger (D11), and a production guard on fixture identities is
`add-arkhai-payments-lane-double`'s decision (D4).
