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
  loopback and builds non-loopback connections with `trust_env`, so today only
  `SSL_CERT_FILE`, which replaces the whole process's trust store, can make it trust a
  private CA. It has no balance call.
- **One builder, three readers of the key.** `payments_client_for_owner`
  (`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`) builds every
  buyer and seller client, but `arkhai_payments_preflight` and the payments check each
  read the variable `api_key_env` names themselves.
- **Lane authentication is bearer tokens.** `ArkhaiPaymentsConfig` refuses
  `development_auth` unless `service_url` is loopback, and a Compose or cluster service
  name is not loopback.
- **The payments service serves `GET /balances/{account}`**, answering only for the
  caller's own account and refusing another with 403 `caller_not_authorized`. Its
  response is the vendored `Balance` model; the vendored schema carries the model but no
  routes, and the kit hard-codes every path it calls.
- **Mediation is a separate service with a separate client.** It has its own published
  contract (`kit/arkhai-mediation/schema/SOURCE.md`) and its own client
  (`kit/arkhai-mediation/src/market_arkhai_mediation/client.py`) at the Agreement-pinned
  authority origin, and it reaches the payments service over HTTP to extend holds. The
  client receives a `MediationCredential` naming an environment variable and reads the
  token itself; four callers build one from `[[DisputeCredential]].api_key_env`, bypassing
  `DisputeCredential.resolve()` (`kit/deal-lifecycle`).
- **The existing payment scenarios.** `e2e_bare_metal_payment_deal` and
  `e2e_credits_payment_deal` use only the once-only surface. `e2e_vm_payment_deal`'s
  stages 1–2 are once-only; its stage 3 needs a mediation authority that accepts a filed
  case, and stage 4 depends on stage 3.
- **Lane configuration travels through Make today.** The root `Makefile`'s
  `e2e-<lane>-dev-env`, `e2e-*-stack-env` and `e2e-dev-identities(-env)` targets print
  `VAR=value` lines into generated environment files: mostly absolute host paths to
  committed files, which `${VAR:?…}` guards in the base and domain Compose files demand,
  plus the bare-metal registry's and site's identities and the provisioning mode.
  Compose resolves each file's variables before merging, so an overlay cannot satisfy a
  base file's guard, and a relative path in an included or extended file resolves against
  that file's own directory. `DEPLOYMENT_AND_CONFIG.md` makes `<PREFIX>_*` variables a
  last-resort escape hatch.
- **The registry is configured by its environment.** `core/registry`'s `Settings` is a
  `pydantic_settings` class reading the environment and three fixed dotenv files
  (`.env.local`, `.env`, `/app/shared-env/.env`, later winning, the environment above
  all). `REGISTRY_FILTER_SPEC_PATH` bypasses it (`api/filter_spec.py`). Its chart sets
  every value as pod `env`, five of which (`ENABLE_HEALTH_CHECKS`,
  `HEALTH_CHECK_INTERVAL`, `ENDPOINT_CHECK_TIMEOUT`, `HEARTBEAT_TTL_SECS`, `CHAIN_ID`)
  nothing reads.
- **Provisioning reads one profile directory.** Its loader layers `config.yml` and
  `config-<profile>.yml` from a single `CONFIG_DIRECTORY`, defaulting to the package's
  own; mock delivery is selected by the profile name `mock`. The provisioning chart sets
  `CONFIG_DIRECTORY=/app/config` and mounts its rendered profiles there as single files.
- **The runner's profiles.** The test runner layers `config-<profile>.yml` under
  `ACTIVE_PROFILES`; `config-docker.yml` already carries per-lane sections every lane
  loads (`bare_metal_lane`, `api_credits`). `PAYMENTS` is one section the shared helper
  reads, whose seller credential and bare-metal price differ by lane.
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
- The storefront charts' payments interface — a configured CA bundle and a payments key
  in the secret overlay — rehearsed in the local release through the values a deployment
  supplies, with a check a deployment can rerun.
- Every lane's and the full local stack's configuration in committed profile, overlay
  and secret-overlay files, none generated by Make.
- Secrets reaching a service through a secret profile or overlay file, never through an
  environment variable its configuration names.

**Non-Goals:**

- A mediation double, controls, contract modes, fault injection or evidence classes:
  `add-arkhai-payments-lane-double`'s.
- Qualifying rate parts, stops or holds at the HTTP boundary, though the double serves
  what its engine serves.
- A production guard refusing fixture identities.
- Serving payment scenarios on the local Helm release.
- Any hosted-ledger, funding or live evidence.
- Moving the registry onto the Dynaconf loader the provisioning service uses.
- Bringing the signing credential `ARKHAI_IDENTITY_CREDENTIAL` under the secret-profile
  rule.

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
its unrefunded hold lives only in the double's memory and ends with the lane. The VM
payment deal lists its own seeded resource, since a listing's binding to a resource
outlives the listing and the canonical deal binds `test_full_deal`'s earlier on the same
stack.

Stage 2 runs, and asserts the authority view is `running` while the pinned authority
cannot be reached. A transport failure at the pinned origin becomes a
`MediationTransportError`, which the mediation adapter turns into a non-`Accepted` view;
the seller takes `state` from the payments observation whatever the dispute outcome.
The seller reports `repair_required` instead whenever it holds no usable credential for
the deal's dispute authority, so the VM lane's storefront carries an identity-bound
`[[DisputeCredential]]` for the pinned authority, its `api_key` a labelled public
development value in Bob's secrets overlay (D19). A focused storefront-level test proves
the case: with a resolvable credential and an unresolvable pinned origin, servicing reads
`state == "running"` with a non-`Accepted` dispute outcome. The respondent poll's
transport error reaches the servicing cycle, which logs it and completes; the deal is not
marked for repair.

The bare-metal and API-credit lanes' storefronts carry no such credential: no domain
code branches on `repair_required`, and only the VM scenario asserts the authority state.

**Rejected:**

- **Leaving the API-credit lane out.** Its scenario needs only the once-only surface, and
  the acceptance boundary would carry an exception.
- **Gating the whole VM module.** No scenario would exercise the VM wiring before
  `qualify-real-provisioning-by-scenario`.
- **Removing the VM scenario from the lane's markers.** It hides the scenario.

### D3. A committed development CA and leaf, with deployment injection

`tools/payments-lane-double/tls/` holds a generator and the two certificates it writes:
the lane CA certificate and the double's leaf certificate. The generator derives both keys
from fixed seeds and uses fixed validity, and Ed25519 signatures are deterministic, so a
check regenerates the certificates and requires them unchanged. The CA's private key is
never written. The leaf key is written but never committed: the repository's secret gate
refuses a committed private key block and admits no fixture by path, so the double's
image build runs the generator and takes the key from it, the same bytes every build, and
a unit test holds that key to the committed leaf certificate (merge of the branch the
change lands on; the owner chose this over an allowlist entry). The leaf's SANs are `payments-double`, `localhost` and `127.0.0.1`; the service
is named `payments-double` in Compose and in the local release, so the certificate
matches both. Every value is a labelled public development value, never for a public
network, following the repository's Anvil-key precedent.

Lane callers trust the lane CA through their payments configuration's `ca_bundle_path`
(D19): the storefronts' lane configurations, the runner's `PAYMENTS.CA_BUNDLE_PATH`, and
the buyer configuration the harness writes.

In Helm:

- Both storefront charts' CA option takes a ConfigMap key as its main source — infra
  supplies `payments-ca-bundle` / `ca-bundle.pem` — and a Secret key as a secondary one,
  mounts it, and derives `[Settlement.arkhai_payments].ca_bundle_path` in the agent's
  rendered configuration from the option's presence, refusing a configuration stating a
  different path. The chart has no default. The option is refused, naming the section,
  when the configuration has no `[Settlement.arkhai_payments]` section or an empty one:
  only the payments client reads the bundle, and a section the chart created for it
  would put payments configuration into a storefront that stated none (61, CA bundle).
- The local out-of-band step creates that ConfigMap from the committed lane CA by
  default, and the local deploy target checks that it exists.
- The double's subchart takes its server certificate and key from an existing Secret
  when one is named, and otherwise from the committed files.

A fixed service name means two local releases in one namespace collide; validation uses
one release per namespace. In the local two-release topology the double runs in the first
release only: the bare-metal release's values disable its subchart, and its storefront
reaches the first release's `payments-double` in the same namespace.

The committed fixtures — certificates, accounts, tokens and the buyer's seed balance —
and the leaf key generated at build are built into the double's image at a fixed path, so Compose runs it without mounts and the
subchart's "committed files" are the image's own. The charts follow the repository's rule
that a chart accepts only names of existing Secrets and never reads credential files into
values (`helm/Makefile`): the CA ConfigMap and the seller token, written into each
storefront's runtime Secret's `storefront.secrets.toml`, come from the committed fixtures
through the local out-of-band step that creates every other local Secret,
`make -C helm topology-secrets` (`helm/scripts/topology-secrets.sh`). The local deploy
and topology targets check that the CA ConfigMap and the runtime Secrets their releases
read exist before installing, not what a Secret's overlay holds: a missing token is the service's to
report, and it does, the storefront's payments readiness blocked by
`arkhai_payments.api_key_missing` and its payments check failing at the configuration
step (61, token check).

**Rejected:**

- **Allowlisting the committed leaf key in the secret gate's configuration.** The gate's
  own design rejects a path allowlist, since it would admit a real key in a test.
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
- Its record key has no usable private half: a key generated with its private half
  discarded unrecorded, not derived from a seed.
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
- The lane's runner profile marks the target `PAYMENTS.LANE_OWNED=true` (D14). The helper
  then fails on an unready target, naming its URL; an external target keeps its blocked
  skip.
- The helper's readiness probe trusts `PAYMENTS.CA_BUNDLE_PATH` when it is set, keeping
  environment proxies disabled.

**Rejected:** keeping the skip and relying on Compose alone. An outage partway through a
run would still look like a skip.

### D7. The pinned dispute authority reaches both roles through the registry

Each lane registry, and the local release's registry, recommends the `.invalid` authority
through its recommended-dispute-authorities setting. Sellers use registry
recommendations by default, and the shared buyer profile writer opts in, so neither role
carries a `[[Dispute]]` entry. In the VM lane, Bob publishes to two registries, and
publication offers only authorities common to every destination, so both VM registries
carry the same recommendation. In the lanes it is the shared `payments-lane` registry
profile (D16).

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

### D9. Lane configuration lives in committed files, never generated by Make

A stack's configuration lives in committed profile, overlay, values and secret-overlay
files. A Makefile chooses which configuration loads — a profile, a mode — and never
generates or carries it. A value the base topology fixes stays in the base file; a
deployment's own values are in its overlay. D13–D18, D20, D21 and D23 apply this to the
lanes, the full local stack, the registry, the provisioning services and the runner.

**Rejected:** each lane target passing `ARKHAI_PAYMENTS__…` overrides to the runner, and
Compose values, from environment files the root `Makefile` generates from the fixtures
(`e2e-<lane>-payments-env`, `lane_env.py compose|runner`), as round 1 implemented. The
values could not be read in any file, the seller key was extracted from an identity file
with `sed`, a buyer seed lived in the Makefile, and `DEPLOYMENT_AND_CONFIG.md` makes
prefixed variables a last-resort escape hatch. No review caught it because no check covers
the Makefile.

### D10. Round 1's implementation cadence

Round 1 implemented one round of four sessions: the kit (balance view, `get_balance`,
the payments check function); the double (project, app, TLS and account fixtures, image,
suite); Compose wiring (the double in three lanes, storefront payments configuration and
registry recommendations, lane settings, the helper's `LANE_OWNED` rule, the VM
scenario's mediation prerequisite and dispute credential, the storefront CLIs'
`check-payments`); and Helm (the subchart, both storefront charts' options, the local
release's payments values, the `helm test` check, render cases). D22 gives the cadence of
the work this design adds.

### D11. The local Helm release rehearses a deployment's payments interface

The local release is where the external round's deployment shape is rehearsed:

- **Secrets in the secret overlay.** Each storefront's payments key is
  `[Settlement.arkhai_payments].api_key` in its runtime Secret's `storefront.secrets.toml`,
  which the Deployment and the payments-check pod already mount (D19). No chart option or
  variable carries it.
- **Deployment values only.** The local release configures payments through the same
  values a deployment uses — `[Settlement.arkhai_payments]` in agent configuration, the
  runtime secret overlay, the CA option — never `development_auth`. The local out-of-band
  step writes the token and creates the CA ConfigMap from the committed fixtures, and the
  deploy target checks that the ConfigMap and the runtime Secret exist (D3).
- **The dispute credential.** The local release's registry recommends the pinned dispute
  authority, so Bob's runtime overlay also states his `[[DisputeCredential]]` for it, as
  the VM lane's Compose overlay does (D2). The out-of-band step copies it from that
  committed overlay, `dev-env/identities/bob.storefront.secrets.toml`, so both stacks
  hold one value; the bare-metal release's storefront carries none, as its lane does
  (63 O1).
- **The double.** The `payments-lane-double` subchart is enabled by the local deploy
  target, never in release values, as `dev-env` is.
- **A rerunnable check.** A `helm test` pod runs D12's `check-payments`, reading the
  seller's own balance, with everything that decides the storefront's payments access
  and nothing else (D12).
- **Render cases.** The subchart, the CA option and its derived `ca_bundle_path`, a
  payments-only storefront with Wallet, Chains and Alkahest null and RPC off, a public
  `config` stating `api_key` refused by the values schema, and the test pod mounting no
  data volume.

Payment scenarios are not served on the local release. That is a roadmap gap, to be
revisited when an external run fails in a way the charts shape.

### D12. Storefronts check their payments access from their own container

Readiness never contacts the payments service, so an authenticated read from the
storefront's own process is what proves its CA mount, `ca_bundle_path`, the secret
overlay's key and `service_url` together.

All three storefront CLIs gain `check-payments --account <id>` (`market-storefront
check-payments`, `bare-metal-storefront check-payments`, `apicredits-storefront
check-payments`), beside the existing operator command `bare-metal-storefront
redeliver-introduction`. The API-credit storefront has no chart, so it has no Helm test.
Each loads the storefront's configuration exactly as `serve` does and calls one function
in `kit/arkhai-payments`, which builds the client through `payments_client_for_owner`,
calls `get_balance`, and returns the outcome or the failing step: `configuration`
(including a `ca_bundle_path` that cannot be loaded), `credential`, `transport`, or
`refused`, the service's error code in a separate `code` field. Every `detail` is fixed
text plus public configuration, never an exception message. The command prints one JSON
line with no credential and exits 0 on `ok`, 1 on a failed step, and 2 on a malformed
`--account`.

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
the configuration and secrets mounts, the identity credential variable, and the CA bundle
mount — rendered from the same chart helpers as the Deployment so the two cannot drift.
It omits the data volume, whose ReadWriteOnce claim a pod on another node cannot attach;
the `/health` probes, which target a server the command never starts; and the ZeroTier
capabilities and device. A local release without persistence uses an `emptyDir` and would
not reveal the volume problem, so a render case asserts the test pod mounts no data
volume.

Validation's Helm part runs every `-payments-check` test pod the release's hooks render,
each as its own step, after the scenario pod. As with the scenario pod, a pass counts only
with the pod's own exit status of 0, because `helm test` passes when its filter matches
nothing. The validator keeps each pod's log as evidence, and warns when the release
renders no check pod. Validation deploys only the first release, so this covers Bob's
storefront; the bare-metal storefront's check stays under `topology-check`.

**Rejected:**

- **A test pod from the e2e-tests image with copied configuration.** It can pass while
  the storefront's own mount or overlay is wrong.
- **A storefront admin route performing the read.** New authenticated production surface
  for a diagnostic.
- **Closeout recording an owner-run `make -C helm test`.** It is evidence once, and
  nothing re-proves the check on the next change to the charts.

### D13. The lane configuration cleanup is in this change

The pre-existing environment targets move to committed files here, with this change's
own payments wiring, rather than in a separate change, so the Makefile never shows two
patterns. The registry takes a minimal step (D16); moving it onto the provisioning
service's Dynaconf loader is a later change.

**Rejected:**

- **Splitting the pre-existing cleanup into its own change.** This change's own additions
  can move without touching a base file, and the cleanup is a second acceptance boundary.
  But a split leaves the Makefile carrying identities beside payments values in files
  until it lands.
- **Recording the cleanup as unowned work.** Nothing would own the guard question.

### D14. The runner reads a shared payments profile and a small profile per lane

Each lane target runs the runner with `ACTIVE_PROFILES=docker,payments-lane,<lane>-lane`,
through `test-buyer-machine`'s `RUNNER_PROFILES`; unset, the runner gets `docker` alone, as
a run against no payments target does. Dynaconf merges the `payments` section key by key.

```yaml
# e2e-tests/config/config-payments-lane.yml
payments:
  service_url: "https://payments-double:8443"
  service_identity: "kaKKC3Q4FZOk2UaVeSCJJq_IrYLIg5t2RDWbnrqaSzo"
  fee_bps: 250
  livemode: false
  lane_owned: true
  ca_bundle_path: "/run/payments-lane-double/lane-ca.pem"
  api_key_env: "PAYMENTS_BUYER_API_KEY"
  buyer_api_key: "payments-lane-double-buyer-public-development-token"
  buyer_account: "00000000-0000-4000-8000-0000000000b1"
  seller_account: "00000000-0000-4000-8000-0000000000b2"
  buyer_marketplace_credential: "sbGxsbGxsbGxsbGxsbGxsbGxsbGxsbGxsbGxsbGxsbE"

# e2e-tests/config/config-bare-metal-lane.yml
payments:
  seller_marketplace_credential: "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
  compute_hourly_gross: 1000000
  dispute_window: "P7D"
```

`config-vms-lane.yml` states Bob's key, `config-apicredits-lane.yml` the API-credit
storefront's. Quoted YAML strings stay strings, so no `@str` marker is needed.

The buyer's token is a runner setting: the helper writes `PAYMENTS.BUYER_API_KEY` into the
`market` subprocess's environment under the variable `PAYMENTS.API_KEY_ENV` names, the
buyer's own provider, as the provisioning service writes `ANSIBLE_CONFIG` from its
settings. An external run supplies its real token in a secret profile (D19), as the Helm
runner's `arkhai-e2e-credentials` `e2e-secret` profile carries the buyer's marketplace
credential. The shared buyer-config writer passes `PAYMENTS.CA_BUNDLE_PATH` on as the
buyer's `ca_bundle_path`. The runner's environment carries no payments value; the lane CA
reaches it as one literal mount in `test-buyer-machine`.

**Rejected:**

- **One full profile per lane.** Nine shared values three times.
- **Lane-named sections in `config-docker.yml`.** The helper would need a selector, itself
  a setting, and every run selecting `docker` would carry all three.
- **The token and `SSL_CERT_FILE` from a committed runner env file.** Superseded by D19:
  the token is a secret delivered as a profile, and trust is configured.

### D15. Development binds move to the root-level overlays; base files keep topology

Every development bind leaves `domains/{vms,apicredits,bare_metal}/compose.yml` and the
`compose.bare-metal.yml` wrapper for the `-local` or `-lane` overlay, stated literally and
relative to the repository root, the project directory of every `-f` file. The base files
keep their topology and lose their `${VAR:?…}` guards for those binds. They keep no
default, so there is still no committed fallback: a missing credential or document stops
the service at its startup rather than Compose at parse time. Planning confirms each
service refuses to start without its binds; a service that does not keeps its guard.

```yaml
# compose.bare-metal-local.yml — public development values, never for a public network
  bare-metal-storefront:
    env_file:
      - ./dev-env/identities/bob.identity.env
    volumes:
      - ./domains/bare_metal/storefront/storefront.dev.toml:/etc/arkhai/storefront.toml:ro
      - ./dev-env/identities/bare-metal.storefront.secrets.toml:/etc/arkhai/storefront.secrets.toml:ro
      - ./tools/payments-lane-double/tls/lane-ca.pem:/run/payments-lane-double/lane-ca.pem:ro
```

Every lane target, its `-down` and its `-logs` name only their Compose files and the run's
mode (D20); no environment file is generated.

**Rejected:**

- **Keeping the guards with the Makefile printing paths only.** The Makefile stays a
  conduit, of paths.
- **Committed per-lane interpolation files.** A relative value resolves against whichever
  included or extended file uses it.
- **Splitting the bare-metal wrapper so its operator-facing guards stay.** The lane would
  duplicate the wrapper's service definitions.

### D16. The registry takes profile-shaped env files

`core/registry` adopts the resolver variables the provisioning service uses: after its
current dotenv defaults, it loads `<CONFIG_DIRECTORY>/config-<profile>.env` for each entry
of `ACTIVE_PROFILES`, in order, a later file winning, the process environment above all.
`REGISTRY_FILTER_SPEC_PATH` becomes a `Settings` field, `registry_filter_spec_path`, so a
file carries it: its alias is the same variable, so the process environment still
overrides it, and unset means the packaged `filter-spec.yaml`. `api/filter_spec.py`
resolves its default path from a `Settings` it is given, defaulting to the module's
`settings`, rather than from `os.environ`. The tests that select a spec through
`monkeypatch.setenv("REGISTRY_FILTER_SPEC_PATH", …)` (`test_filter_spec.py`,
`test_settled_envelope_across_specs.py`) move to that injected seam, as `AGENTS.md`'s
test guidance prefers to patching the process environment, and a test proves a profile
naming another specification, with no process variable set, loads it. Correction
of the misleading `.env.local` comment and removal of the five unread variables from the
chart, `core/registry/Dockerfile` and `core/registry/.env.docker-compose` go with it. The
later move onto Dynaconf changes only the files' format.

All five lane registries (`registry`, `registry-b`, `api-credits-registry`,
`compute-registry`, `bare-metal-registry`) take their `REGISTRY_*` values from committed
profiles, and a lane layers the shared recommendation on top:

```
# dev-env/registry/config-bare-metal-registry.env
REGISTRY_AUTHORITY_ID=bare-metal-registry
REGISTRY_AUTHORITY_SCHEME=eip191
REGISTRY_AUTHORITY_IDENTIFIER=0x90f79bf6eb2c4f870365e785982e1f101e93b906
REGISTRY_AUTHORITY_CREDENTIAL_FILE=/run/secrets/arkhai/registry-identity/credential
REGISTRY_DESCRIPTOR_BASE_URL=http://bare-metal-registry:8080
REGISTRY_DESCRIPTOR_DISPLAY_NAME=Local Bare Metal Compute Registry
REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY=Arkhai local development

# dev-env/registry/config-payments-lane.env
REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES='[{"account":"00000000-0000-4000-8000-0000000000d1",...}]'
```

```yaml
  bare-metal-registry:
    environment:
      - CONFIG_DIRECTORY=/etc/arkhai/registry
      - ACTIVE_PROFILES=bare-metal-registry,payments-lane
    volumes:
      - ./dev-env/registry:/etc/arkhai/registry:ro
```

The registry chart renders its existing values — identity, descriptor, `config.*`,
`service.port`, the constant credential path, the filter specification path — into a
ConfigMap key `config-production.env`, mounted under `CONFIG_DIRECTORY=/app/config` with
`ACTIVE_PROFILES=production`, as the provisioning chart renders `config-production.yml`.
Its values keep their shape and its posture checks stay. Secret-held settings arrive as
`secretProfile: {secretName, profile}`, a pre-existing Secret holding
`config-<profile>.env`, mounted beside the rendered profile and appended to
`ACTIVE_PROFILES`, which is what External Secrets produces; `auth.bootstrapKeySecret` and
`auth.adminKeySecret` are retired with a render refusal naming `secretProfile`. The
Deployment's `env` holds only the two resolver variables.

**Rejected:**

- **The fixed dotenv slots, with no code change.** Their order contradicts their comment,
  and they layer at most one lane file.
- **A registry-specific `REGISTRY_ENV_FILES` list.** Explicit, but its name would change
  again at the Dynaconf move.
- **Compose's own `env_file:` key.** The values would still arrive through the process
  environment, with no Kubernetes counterpart but `envFrom`.
- **Leaving the chart until the Dynaconf change.** It keeps a long pod `env` list.
- **An operator map of verbatim env-file profiles.** No caller needs one.

### D17. Provisioning services take site profiles in the chart's mount shape

Each lane provisioning service (`provisioning`, `alice-provisioning`,
`bare-metal-provisioning`) sets `CONFIG_DIRECTORY=/app/config` and binds single files into
it: the packaged `config.yml` and `config-docker.yml` from their source in the repository,
and a committed site profile holding the identities and the site id its overlay set as
`PROVISIONING_*` variables.

```yaml
# dev-env/provisioning/config-bare-metal-site.yml
identity:
  scheme: "eip191"
  identifier: "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
storefront_identity:
  scheme: "eip191"
  identifier: "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"
storefront_site_id: "bare-metal-e2e"
admin_identity:
  scheme: "eip191"
  identifier: "0x9965507d1a55bcc2695c58ba16fb37d819b0a4dc"
```

VM's `config-vms-bob-site.yml` and `config-vms-alice-site.yml` bind through
`compose.vms-local.yml`, so the full local stack shares them. The base files' topology
values — the database path, `REDIS_URL`, the callback URL naming a service, the
definition documents' container paths — stay in their `environment:`.

**Rejected:**

- **Two-directory resolution in `arkhai-kit-config`.** It changes the shared kit and
  would make Helm load packaged profiles it never loaded.
- **The image copying its profiles to `/app/config`.** The same Helm behaviour change.
- **Literal `PROVISIONING_*` overlay variables.** Lane settings in the override layer.

### D18. Every environment target is retired

`e2e-vms-dev-env`, `e2e-apicredits-dev-env`, `e2e-bare-metal-dev-env`, both
`e2e-*-stack-env` helpers, `e2e-dev-identities`, `e2e-dev-identities-env` and the three
`e2e-<lane>-payments-env` go, with `e2e-tests/Makefile`'s `e2e_env_if_missing` and its
environment files. The full stack is
`docker compose -f docker-compose.yml -f compose.vms-local.yml -f compose.apicredits-local.yml up -d`,
so written in `docker-compose.yml`'s header and `VALIDATION_RUNBOOK.md`. The buyer runtime
directories become literal Git-ignored binds (`./.e2e-buyer/profile:…`); the runbook step
that runs a buyer service by hand creates them first, since Docker would create a missing
bind source owned by root. Dated records under `docs/attachments/` keep their wording.

**Rejected:**

- **A full-stack convenience target.** A target that only knows file names adds a place
  to look and no information.
- **Keeping `e2e-dev-identities-env` for what is left.** A conduit for the mode alone.

### D19. Secrets through secret overlays; trust through configuration

A service takes its secrets from a secret profile or overlay file layered by its
configuration system, never from an environment variable its configuration names. On a
cluster, External Secrets writes that file.

- **Payments key.** `ArkhaiPaymentsConfig` gains `api_key: SecretStr`, marked secret so
  the storefronts' generated values schema refuses it in a chart's public `config`, and
  exclusive with `api_key_env` and `development_auth`. Storefronts state it in their
  secret overlay (`storefront.secrets.toml`, or the API-credit storefront's secret
  layer). The buyer role keeps `api_key_env`, its public TOML's exact named-variable
  provider.
- **One resolution.** The kit exposes one key resolution — `api_key`, otherwise the
  variable `api_key_env` names — called by `payments_client_for_owner`,
  `arkhai_payments_preflight` and the payments check.
- **CA bundle.** `ArkhaiPaymentsConfig` gains `ca_bundle_path`; `PaymentsClient` gains a
  `ca_bundle` argument the builder passes, used as the client's verification context, so
  a private CA is trusted for the payments client alone rather than replacing the
  process's trust store. No `SSL_CERT_FILE` is set anywhere.
- **Dispute credentials.** `DisputeCredential` gains `api_key: SecretStr` beside
  `api_key_env`, and `resolve()` returns either. `MediationCredential` carries the
  resolved token, and every caller — both storefronts' and both buyers' lifecycle
  composition — obtains it through `resolve()`. Its contract:
  - `MediationCredential(identity, *, token: SecretStr)`: the field is renamed and
    keyword-only. `__post_init__` refuses a token that is not a `SecretStr` with
    `TypeError`, and an empty token, one with surrounding whitespace, or one containing
    CR or LF with `ValueError` — the checks `MediationClient` makes today, moved to
    where the token arrives. An unmigrated positional call such as
    `MediationCredential(identity, "DEMO_PAYEE")` therefore fails at construction
    rather than authenticating with a variable name as its bearer token.
  - `MediationClient` loses its `environ=` parameter; it has no environment to read.
  - `DisputeCredential.api_key` must be non-empty, refused at configuration validation
    as a malformed `api_key_env` is. `resolve()` still raises `ValueError` for an unset
    or empty variable, which the storefronts' `credential_available` reads as no usable
    credential, so the deal reports `repair_required` (D2).
  - Every direct constructor migrates: the four lifecycle compositions, the
    `kit/arkhai-mediation` and `kit/deal-servicing` examples, the kit and domain tests,
    and `kit/arkhai-mediation/README.md`. Examples and tests pass
    `token=SecretStr(...)` instead of an `environ` mapping. Scripts under
    `docs/attachments/` are dated records and keep their wording (D18).
- **Charts.** Both storefront charts' `paymentsKey` option, its `seller-payments-key`
  Secret and the chart's `api_key_env` check are removed; the CA option derives
  `ca_bundle_path` (D3).
- **Values schemas.** Both storefronts' generated schemas refuse in `config` the payments
  `api_key` (marked secret in the model), the payments `api_key_env`, and every
  `[[DisputeCredential]]` entry, whole. No variable the chart sets holds a key a public
  `api_key_env` could name, and a dispute credential entry is incomplete without its token. The refusal
  of `api_key_env` is the storefront generators', not a role marker on the shared
  payments model: the settlement runtime enforces a field's roles when it loads the
  configuration, and conformance here is a check of the charts, not a runtime refusal.
  (74 F1)
- **The signing credential** stays `ARKHAI_IDENTITY_CREDENTIAL` from a Secret, kept from
  the loader by the identity specification, until a change decides its delivery (Open
  Questions).

`DEPLOYMENT_AND_CONFIG.md` states the rule beside "Profile-based configuration", and the
`deployment-state` requirement on a storefront's configuration names its two exceptions:
the resolver variables and the signing credential.

**Rejected:**

- **The guidance gaining a named-variable credential and a library-read variable
  (`SSL_CERT_FILE`) as allowed kinds.** A variable named by configuration is a second,
  weaker secret channel beside the secret profile a cluster already writes, and
  `SSL_CERT_FILE` displaces public trust for the whole process.
- **Leaving the delta and the guidance disagreeing.**

### D20. The provisioning mode is the one value a run supplies

Each overlay states the provisioning `ACTIVE_PROFILES` with the mode last:
`docker,<site>,${PROVISIONING_MODE:-mock}`. The Make targets keep their `mock`/`real`
check and export `PROVISIONING_MODE` to Compose. No `real` profile file exists, and the
loader skips a missing include; mock delivery is selected by the name `mock`, so under
`real` the service is not mocked and reports `real` among its profiles. The base files
keep `ACTIVE_PROFILES=docker`. The runner's `RUNNER_PROFILES`, the image suffix, the
network and the marker lists stay run parameters.

**Rejected:** a mode overlay per stack, restating every service's profile list.

### D21. Tests hold every restated value to its source

Tests in `scripts/tests` and `tools/payments-lane-double/tests` hold: the registry
profiles' principals to their credential files; the provisioning site profiles to the
runner's pins; the runner's payments profiles and the secret overlays' tokens to
`tools/payments-lane-double/fixtures/accounts.toml`; the seller keys to the identity files;
the lane registry recommendation to `fixtures/dispute-authority.toml`; each
`ca_bundle_path` to its overlay's mount; and each overlay bind's source to an existing
file. `lane_env.py` keeps only `seller-account`, the account the lane targets pass to
`check-payments`, and `seller-token`, which `topology-secrets.sh` writes into the runtime
secret overlay.

**Rejected:** the account restated literally in the e2e Makefile, which brings a value
back into the Makefile.

### D22. Implementation cadence

The work this design adds is one round of three sessions, then its review and one
validation that also covers round 1's triage fixes:

1. **Interfaces:** the kit's `api_key`, `ca_bundle_path`, key resolution and
   `PaymentsClient` CA argument; `check-payments`' configuration step for an unreadable
   bundle; `DisputeCredential.api_key`, `MediationCredential` carrying the token with its
   validation (D19) and every direct constructor migrated — the four lifecycle
   compositions, the kit examples, the kit and domain tests, the mediation README; the
   registry's profile env-file loader, the `registry_filter_spec_path` setting read by
   `api/filter_spec.py` through an injected `Settings`, its tests moved off
   `monkeypatch.setenv`, and unread variables removed.
2. **Compose and Make:** guards out of the base files and literal binds in the overlays
   for the three lanes and the full stack; the registry and provisioning profiles; the
   runner's payments profiles and the helper's token and CA handling; the storefronts'
   secret overlays, payments keys and wallet keys; the environment targets retired; the
   mode selector; the tests of D21; the documents that named the targets.
3. **Helm:** the registry chart's env-file profile and `secretProfile`, with the retired
   keys refused; both storefront charts' CA option deriving `ca_bundle_path`,
   `paymentsKey` removed, the payments-check pods and render cases updated;
   `local-values.yaml` and `topology-secrets.sh`.

Each session carries its own delta-spec and guidance obligations into the plan's closeout.

### D23. Storefront wallet keys move into the secret overlays

Bob's and Alice's `[Wallet] private_key` move from `STOREFRONT_WALLET__PRIVATE_KEY` in
`compose.vms-local.yml` into their secret overlays; Alice gains
`alice.storefront.secrets.toml`. The API-credit storefront's key moves from
`APICREDITS_STOREFRONT_WALLET__PRIVATE_KEY` into its secret layer. The wallet env files
those services load (`.env.bob.docker`, `.env.alice.docker`, `api-credits.wallet.env`),
whose `AGENT_PRIV_KEY` the storefronts never read, are deleted. This follows D19 and the
bare-metal lane, whose secret overlay already holds its wallet key.

## Effects on other changes

- **`qualify-real-provisioning-by-scenario`:** the storefront charts' CA option, its D11,
  is delivered here as a mounted bundle from which the chart derives `ca_bundle_path`,
  and the storefront's payments key is `api_key` in its secret overlay, not a variable
  named by `api_key_env` or a `paymentsKey` option; its D11 keeps the kit's
  cluster-service HTTPS test. Its D14's list grows by the API-credit lane, Helm and the
  check. Its planning must not cite `SSL_CERT_FILE` or `paymentsKey`. Archive cleanup
  returns it to design, where this is reverified.
- **`add-arkhai-payments-lane-double`:** its D1 becomes a sibling
  `tools/mediation-lane-double` reaching this double over HTTP, with controls added to
  this double; its D7 becomes "this change owns the payments double; that one extends it
  and adds mediation". The production guard on fixture identities is its decision. The VM
  payment scenario's stages 3–4 wait on its mediation double. It inherits
  `MediationCredential` carrying a resolved token and `DisputeCredential.api_key`.
- **A later registry change** moves the registry onto the Dynaconf loader the
  provisioning service uses, from the profile env files and `secretProfile` here.

## Principles stated for promotion

1. A double mirrors its producer's API unless there is a compelling reason to deviate:
   `docs/development/TESTING.md`, with the rule in `docs/development/ARCHITECTURE.md`'s
   testing philosophy.
2. A local release configures a service through the same values a deployment uses, as the
   deployment's rehearsal, never through development-only modes:
   `docs/development/DEPLOYMENT_AND_CONFIG.md`.
3. A service takes its secrets from a secret profile or overlay file layered by its
   configuration system, never from an environment variable its configuration names:
   `docs/development/DEPLOYMENT_AND_CONFIG.md`, with the rule in
   `docs/development/ARCHITECTURE.md`.
4. A stack's configuration lives in committed profile, overlay and values files; a
   Makefile chooses which configuration loads and never generates or carries it; a value
   the base topology fixes stays in the base file, and a deployment's own values in its
   overlay: `docs/development/DEPLOYMENT_AND_CONFIG.md` ("Per-domain stack composition"),
   with the rule in `docs/development/ARCHITECTURE.md`.

## Implementation record

What the build settled beyond the decisions above, and the review findings declined with
their reasons. `tasks.md` keeps each task's final behaviour and evidence; this keeps the
rationale.

### The payments kit (D5, D12, D19)

- The balance view and `snapshot()` share one `_release_at` helper, so the two cannot
  format a maturity differently; the snapshot's bytes are unchanged (vector replay).
- `check_payments_access` takes a section, a raw mapping or `None`: a missing or invalid
  section is a `configuration` outcome, so no CLI handles one itself. An invalid
  section's detail lists only each error's location and pydantic type code, since a key
  pasted under the wrong name would otherwise be echoed. A `PaymentsProtocolError` (a
  non-payments server at the URL) is a `transport` step: the kit's transport error
  already means "could not be reached or its response could not be read", and D12 has
  four steps. A key variable holding CR or LF is a `credential` failure, checked before
  the client is built. A malformed `account` raises `ValueError`, the caller's argument
  rather than the role's access; each CLI turns it into a usage error (exit 2). A trust
  bundle the client cannot load when it is built (`OSError`) is reported as `transport`
  with fixed text rather than escaping as a traceback (review 29 F1).
- The three CLIs share one kit call, `check_configured_payments_access(read_section,
  account)`: a `ValueError` from the section reader is a `configuration` outcome, so one
  escaping the call is always a malformed account. Each CLI module has two seams under
  `TESTING.md`'s command-module convention, `payments_section()` and
  `payments_transport()`; the VM and API-credit readers import their config module inside
  the function because their settings resolve on first import, after the root `--config`
  option.
- A disabled payments section fails the check at `configuration`, although
  `payments_client_for_owner` still serves accepted deals while payments is disabled for
  new ones: a storefront servicing old payment deals with payments disabled reports the
  check failed.
- The key-form conflicts (`api_key` with `api_key_env`, either with `development_auth`)
  are refused whether or not the section is enabled, since a disabled section still builds
  clients for accepted deals and the one resolution must find one form. A multi-line key
  is refused because it travels as a header value. An empty `ca_bundle_path` is refused
  because `ssl.create_default_context(cafile="")` silently loads the default store.
  `ArkhaiPaymentsConfig`, `DisputeCredential` and `DisputeConfig` set
  `hide_input_in_errors`: pydantic shows a short input, a three-character key included,
  whole in a validation error. The preflight's no-key blocker is
  `arkhai_payments.api_key_missing`.
- The TLS cases issue a CA and leaf carrying key usage, key identifiers and EKU, which
  Python 3.13's strict X.509 verification requires. No test shows the process trust store
  untouched off loopback; that rests on the client setting no process state and httpx
  consulting `SSL_CERT_FILE` only for `verify=True`.
- Versioning: a package bumps once per change against the branch it merges into, and an
  exact pin moves with the bump. Reverting a bump needs `make dist-clean` before
  `make lock`, since `make lock` resolves a lower bound to the highest wheel in `.dist`.
- Declined: moving the kit's TLS test into an `integration/` directory (the kit's suite
  is flat and imports a sibling module); removing the check's second key resolution (it
  resolves once to classify a failure, and the builder resolves again through the same
  function); showing the bare-metal loader's refusal message in the outcome (every detail
  is fixed text, and other loaders' messages may quote input).

### The payments double (D1, D3, D8)

- `PaymentsDouble` is a framework-free service over the engine; `create_app` binds thin
  FastAPI routes to it. It keeps its own map of approved mandates, since the engine keeps
  them private and both the repeat check and read authorization need them; an unknown
  transaction is 404 `transaction_not_found`.
- Statuses the repository does not record for the service are inferred and documented as
  such: 422 for `unsupported_asset` and `fee_mismatch` (following the engine's
  `invalid_mandate`) and 404 for `account_not_found`. Several attachments on one approval:
  the engine takes one Agreement, so the double passes the first that does not hash to the
  deal, keeping `deal_mismatch` after the funds check. The `Bearer` scheme matches
  case-insensitively; success statuses are 200.
- The suite drives the kit's real `PaymentsClient`, with commented exceptions for the
  mandate route (the client has no call for it; a `get_mandate` was left out because no
  consumer reads the route) and three rejection paths the client cannot build.
- The image installs the project editable two levels deep, since its wheel is not in the
  wheelhouse; `docs/development/BUILD_AND_PACKAGING.md` documents the one-level case.
- The leaf key reaches Git history in this branch's earlier commits, so the change lands
  from a branch cut from `dev`'s tip carrying this branch's tree in one commit (review 83
  F1, the owner's choice over rewriting history or merging with the public-content check
  failing).
- Declined: moving the suite's helpers out of `tests/conftest.py`, which pytest's default
  import mode serves.

### Storefronts and the VM servicing proof (D2, D12)

- `RespondentPoller.poll` lets the `MediationTransportError` escape, and
  `VmDealLifecycle.cycle` catches it and logs "VM respondent discovery awaits recovery" at
  ERROR every cycle, retrying the next; so the VM lane's storefront logs that line while it
  holds the `.invalid` authority's credential, as expected. Nothing is marked for repair,
  because the poll fails before it reads a case. `VmDealLifecycle(...,
  mediation_transport=None)` is the seam the proof injects the DNS failure through.
- A padded or multi-line `DisputeCredential.api_key` is refused at validation by the rules
  `MediationCredential` applies, so a credential `credential_available` calls usable is
  one a client can send. The buyers resolve the credential inside their existing `try`, so
  an unresolvable one is still a `MediationTransportError` at I/O. The bare-metal
  settings' `settlement` and `disputecredential` fields are `repr=False`.

### Lanes and stacks (D2, D6, D9, D14–D21, D23)

- Lane storefront configurations are full copies (`storefront.bob.lane.toml`,
  `storefront.credits.lane.toml`) rather than overlays: the storefronts' Dynaconf loaders
  merge with `merge_enabled`, which concatenates lists, so an overlay restating `priority`
  would duplicate entries the settlement registry refuses. A test holds each copy equal to
  its stack profile less the payments additions.
- Enabling payments publishes no API-credit payment option by itself: the option builder
  publishes one only from a publication clause, so the lane copy states a
  `[pricing].settlements` clause. The API-credit scenario's refund signs with the lane
  storefront's eip191 key, not an Ed25519 seed.
- An Ed25519 marketplace credential is unpadded base64url; the first lane run failed on a
  hex seed.
- `LANE_OWNED` with no `SERVICE_URL` fails, naming both. `MEDIATION.SERVICE_URL` is a gate
  only: stages 3–4 file with the authority their Agreement pins and never contact it.
- The runner hands the buyer key to both the `market` subprocess and the in-process
  payments clients as a mapping, writing it into no process environment, unlike the
  `ANSIBLE_CONFIG` precedent, since the requirement forbids the token in the runner's
  environment.
- The base files' bring-up without binds was not run directly; the refusal rests on each
  service's startup code (registries, signers, credits service, sample app, bare-metal
  definition documents). The bare-metal site starts without its SSH key, which only
  Ansible reads per job, and its guard went with the others, so a real-mode deployment
  binding its documents and not its key fails at its first job. The bare-metal buyer
  service moved whole into the overlay, because Compose interpolates each file before
  merging and a later file cannot satisfy a guarded `image:`.
- The lanes run provisioning as `docker,<site>,mock`: mock delivery is selected by the
  profile name, and `config-mock.yml` is not bound.
- The full stack mounts the same secret overlays, inert there; `storefront.credits.toml`
  states no key form, since the payments section refuses two forms even when disabled.
- `.gitignore` keeps `.e2e-*.env`, since an environment file an earlier run wrote holds a
  contributor's local paths.
- Declined: keeping the bare-metal SSH key's guard; returning `REGISTRY_FILTER_SPEC_PATH`
  and registry-b's gates to the domain files; replacing the VM base file's
  `${HOME}/.ssh/id_ed25519` bind (an operator's real key, predating the change); pinning
  `pyyaml` in `test-release-tooling`; dropping the static overlay checks beside the render
  cases (the render cases skip without Docker Compose); moving the runner-profile cases out
  of the double's `tests/integration/`; replacing `test_payments_helper.py`'s patch of the
  default probe (the case shows what that probe receives); hardening the mode check
  against a multi-word value. `tools/issue-discovery`'s default compose arguments still
  name `docker-compose.yml` alone, as before.

### The registry (D16)

- The registry parses `ACTIVE_PROFILES` as `arkhai-kit-config`'s `parse_active_profiles`
  does, restated because it does not depend on that kit, until it moves onto Dynaconf.
- The served filter specification stays one cached load; `reset_cache(settings=None)` is
  the seam that makes the next load resolve from a given `Settings`.
- The chart's profile lines are single-quoted: the dotenv reader decodes only `\\` and
  `\'` there, so the chart refuses a value ending in a backslash (it would run into the
  next line) or holding `${` (python-dotenv interpolates every value). A `checksum/config`
  annotation keeps a values change rolling the registry. `secretProfile` refuses a
  `secretName` without a profile, and the profile `production`. `core/registry/Dockerfile`
  lost `ENV PORT`, which as a process variable would override the profile; its `CMD`
  still hard-codes port 8080, a pre-existing mismatch with a non-default `service.port`.
- `domains/vms/provisioning/iac/README.md` still shows the four removed registry variables
  in an example deployment command; it is corrected where that document is next
  maintained.

### Helm (D3, D11, D12)

- The subchart's Deployment is release-scoped; only its Service name is fixed. Its probes
  use unverified HTTPS, so they hold whatever certificate is served, while the image's
  healthcheck trusts only the lane CA. `TOPOLOGY_ROLLOUT_ORDER` leaves the double out, as
  it leaves dev-env out: a restart loses every payment it holds.
- `tests.paymentsAccount` is per agent in the storefront chart, one check pod per agent
  that sets it; the check pod also mounts the Alkahest address book when the agent names
  one, since the check loads settings as `serve` does.
- The local release's e2e-tests chart profile carries only the public payments keys:
  charts accept no credential in values, and the release serves no payment scenario.
- Validation's Helm part runs every `-payments-check` pod from the release's hooks
  (review 29 F2), recorded under D12.
- `topology-secrets.sh` copies Bob's `[[DisputeCredential]]` from the Compose overlay,
  rewriting each setting as a TOML basic string and refusing a rewrite that does not read
  back (a character outside the Basic Multilingual Plane becomes a surrogate pair TOML
  refuses).

## Open Questions

- **How the signing credential is delivered.** `ARKHAI_IDENTITY_CREDENTIAL` stays a
  Secret-sourced variable kept from the loader by the identity specification, the one
  secret principle 3 does not yet govern. Revisit when a change decides identity
  credential delivery for the roles.

Serving payment scenarios on the local Helm release is recorded as a roadmap gap with its
trigger (D11), a production guard on fixture identities is
`add-arkhai-payments-lane-double`'s decision (D4), and the registry's move onto Dynaconf is
a later change (Effects on other changes).
